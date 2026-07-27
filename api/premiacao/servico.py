"""Serviço da premiação (Task 5): orquestra params (Task 2) + gobrax/coleta
(Tasks 3/4) + cálculo (Task 1) no shape consumido pelos endpoints de
`api/main.py` e pela tela.

TTL/lock/fallback:
  - Recoleta quando `force`, OU não existe snapshot do mês, OU (mês corrente
    E o snapshot foi coletado há mais de 1h).
  - A coleta+gravação é protegida por um `threading.Lock` de MÓDULO — só a
    escrita fica atrás do lock, a leitura de snapshot/index é sempre livre.
    Quem chega e espera o lock relê o snapshot antes de decidir se ainda
    precisa coletar (o primeiro pode já ter deixado um snapshot fresco).
  - Se a recoleta falha (`GobraxIndisponivel`/`GobraxNaoConfigurado`, ou
    `ValueError` de resposta malformada da API — mesmo tratamento) e existe
    snapshot antigo, ele é servido com `aviso`; sem snapshot antigo, a falha
    propaga (o endpoint decide o HTTP).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from api.premiacao import calculo, coleta, gobrax, params
from api.premiacao.coleta import SNAP_DIR  # reexport: monkeypatch nos testes

log = logging.getLogger(__name__)

TTL = timedelta(hours=1)

_LOCK = threading.Lock()

# Cache de módulo do preço do diesel (M5): {mes: (timestamp_monotonic, valor)}.
# Com o túnel AVA fora, cada GET pagava connect_timeout(8s)+pool(15s) por um
# número informativo — TTL de 10 min corta isso sem esconder a falha (loga 1x).
_PRECO_TTL_S = 600
_PRECO_CACHE: dict[str, tuple[float, float | None]] = {}

_PRECO_DIESEL_SQL = """
SELECT (CASE WHEN sum(a.volume) > 0 THEN sum(a.custo)/sum(a.volume) END)::float8 AS preco
FROM sulista.ctaplus_abastecimentos a
WHERE a.data_inicio_abastecimento >= %(de)s::date
  AND a.data_inicio_abastecimento <  %(ate)s::date
  AND a.posto_comercial IS NOT TRUE
  AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%arla%%'
"""


def _novo_cliente():
    """Fábrica isolada para os testes stubarem (FakeCliente ou função que
    levanta GobraxIndisponivel/GobraxNaoConfigurado)."""
    return gobrax.ClienteGobrax()


# Cache do histórico de vínculos (exportDriverHistory): são ~98 exports XLSX,
# um por veículo — refazer isso a cada recoleta de TTL seria o item mais caro
# da coleta. O histórico muda devagar (equipe vinculando motoristas), 1h basta.
_BONDS_TTL_S = 3600
_BONDS_CACHE: dict[str, tuple[float, dict]] = {}


def _bonds(cliente) -> dict:
    agora_mono = time.monotonic()
    cacheado = _BONDS_CACHE.get("bonds")
    if cacheado is not None and (agora_mono - cacheado[0]) < _BONDS_TTL_S:
        return cacheado[1]
    resp = cliente.get("/vehicles", {"customers": 1, "operation": "true"})
    veiculos = ((resp or {}).get("customers") or [{}])[0].get("vehicles") or []
    vinfo = {v["id"]: {"plate": v.get("plate", ""),
                       "model": v.get("truckModel") or v.get("model") or v.get("brand") or ""}
             for v in veiculos if v.get("id") is not None}
    bonds = coleta.fetch_bonds(cliente, vinfo)
    _BONDS_CACHE["bonds"] = (agora_mono, bonds)
    return bonds


def _preco_diesel(mes: str) -> float | None:
    """Preço médio do diesel interno no mês (AVA). ERP fora não derruba a
    tela: qualquer falha (conexão, túnel, coluna ausente) volta `None`.

    Cache de módulo com TTL de 10 min (M5): sem ele, todo GET da tela pagava
    o custo cheio de bater no AVA (connect_timeout 8s + pool 15s quando o
    túnel está fora) só para exibir um número informativo. A falha é logada
    (não engolida em silêncio) uma vez por tentativa real — enquanto o cache
    serve, não há nova tentativa nem novo log."""
    agora_mono = time.monotonic()
    cacheado = _PRECO_CACHE.get(mes)
    if cacheado is not None and (agora_mono - cacheado[0]) < _PRECO_TTL_S:
        return cacheado[1]

    from api import db  # lazy: testes do serviço não precisam de Postgres

    ano, m = map(int, mes.split("-"))
    de = f"{ano:04d}-{m:02d}-01"
    ate = f"{ano + 1:04d}-01-01" if m == 12 else f"{ano:04d}-{m + 1:02d}-01"
    try:
        linhas = db.query(_PRECO_DIESEL_SQL, {"de": de, "ate": ate})
        preco = linhas[0]["preco"] if linhas else None
        valor = float(preco) if preco is not None else None
    except Exception as exc:  # noqa: BLE001 -- ERP fora não pode derrubar a tela
        log.warning("preco diesel indisponivel: %s", exc)
        valor = None
    _PRECO_CACHE[mes] = (agora_mono, valor)
    return valor


def _coletado_ha_mais_de_1h(snap: dict, agora: datetime) -> bool:
    coletado_em = snap.get("coletado_em")
    if not coletado_em:
        # M10: snapshot sem coletado_em (nunca deveria acontecer, mas não pode
        # estourar) é tratado como "muito velho" -> recoleta se for o mês
        # corrente; se o mês já fechou, o I1 abaixo decide sozinho.
        return True
    coletado = datetime.strptime(coletado_em, "%Y-%m-%d %H:%M")
    return (agora - coletado) > TTL


def _precisa_recoletar(mes: str, mes_corrente: str, snap: dict | None,
                        force: bool, agora: datetime) -> bool:
    if force or snap is None:
        return True
    if mes == mes_corrente:
        return _coletado_ha_mais_de_1h(snap, agora)
    # I1: o mês FECHOU depois da coleta (snapshot ainda marcado `parcial`) —
    # sem isto, um snapshot parcial de um mês passado nunca era recoletado e
    # o número ficava congelado no dia em que a coleta rodou pela última vez.
    return bool(snap.get("parcial")) and mes < mes_corrente


def obter(mes: str | None = None, force: bool = False, agora=None,
          cliente=None) -> dict:
    """`cliente` opcional: o backfill (`atualizar_tudo`) passa UM cliente para
    todos os meses — um login por mês disparava o rate-limit do Kratos (403)."""
    agora = agora or datetime.now()
    mes_corrente = agora.strftime("%Y-%m")
    mes = mes or mes_corrente

    if not gobrax.configurado():
        # NUNCA incluir valores de ambiente — só os nomes das variáveis que faltam.
        return {
            "configurado": False,
            "variaveis": ["GOBRAX_EMAIL", "GOBRAX_SENHA"],
            "index": coleta.ler_index(SNAP_DIR),
        }

    snap = coleta.ler_snapshot(mes, SNAP_DIR)
    aviso = None

    if _precisa_recoletar(mes, mes_corrente, snap, force, agora):
        # M2: o que ESTA chamada viu ao entrar (antes do lock) — usado depois
        # para saber se outra chamada concorrente já coletou enquanto
        # esperávamos. Sem isso, dois POST /atualizar (force=True) simultâneos
        # coletam 2x: com force o double-check de baixo é sempre verdadeiro
        # (`_precisa_recoletar` short-circuita em `force`) e não filtra nada.
        coletado_em_visto = snap.get("coletado_em") if snap else None
        with _LOCK:
            # relê depois de tomar o lock: quem chegou 2º pode achar já pronto
            snap_relido = coleta.ler_snapshot(mes, SNAP_DIR)
            coletado_em_relido = snap_relido.get("coletado_em") if snap_relido else None
            if snap_relido is not None and coletado_em_relido != coletado_em_visto:
                # outra chamada já coletou/gravou enquanto esperávamos o lock
                # (vale mesmo com force=True) -> usa o snapshot fresco, não
                # recoleta de novo.
                snap = snap_relido
            elif _precisa_recoletar(mes, mes_corrente, snap_relido, force, agora):
                try:
                    cliente = cliente or _novo_cliente()
                    novo = coleta.coletar_mes(cliente, mes, agora=agora,
                                              bonds=_bonds(cliente))
                    if not novo.get("drivers") and snap_relido and snap_relido.get("drivers"):
                        # Coleta VAZIA nunca sobrescreve snapshot com dados: a
                        # frota do customer oscila na plataforma durante
                        # remanejos (aconteceu de verdade — /vehicles foi de 98
                        # a 10 e de volta em minutos, e julho com 3 motoristas
                        # virou 0). Snapshot é dado de pagamento: mantém o
                        # anterior e avisa, em vez de perder o mês.
                        snap = snap_relido
                        aviso = (f"a coleta voltou vazia (plataforma em remanejo?) — "
                                 f"mantido o snapshot de {snap.get('coletado_em') or 'data desconhecida'}")
                    else:
                        coleta.gravar_snapshot(novo, SNAP_DIR)
                        snap = novo
                except (gobrax.GobraxIndisponivel, gobrax.GobraxNaoConfigurado, ValueError):
                    if snap_relido is None:
                        raise
                    snap = snap_relido
                    aviso = (f"coletado em {snap.get('coletado_em') or 'data desconhecida'} — "
                             "não foi possível atualizar")
            else:
                snap = snap_relido

    parametros = params.ler_params()
    calc = calculo.calcular(snap["drivers"], parametros)
    referencias = {
        "preco_diesel_interno": _preco_diesel(mes),
        "media_frota": calc["kpis"].get("media_frota"),
    }

    return {
        "configurado": True,
        "month": mes,
        "parcial": snap.get("parcial", False),
        "coletado_em": snap.get("coletado_em"),
        "aviso": aviso,
        "frota_telemetria": snap.get("frota_telemetria"),
        "index": coleta.ler_index(SNAP_DIR),
        "params": parametros,
        "referencias": referencias,
        "linhas": calc["linhas"],
        "kpis": calc["kpis"],
        "sem_media": calc["sem_media"],
    }


def meses_recentes(n: int, agora: datetime) -> list[str]:
    """Os n meses 'AAAA-MM' até o corrente (inclusive), em ordem cronológica."""
    ano, m = agora.year, agora.month
    saida: list[str] = []
    for _ in range(n):
        saida.append(f"{ano:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, ano = 12, ano - 1
    return list(reversed(saida))


def atualizar_tudo(agora=None, n_meses: int = 6) -> dict:
    """Botão "Atualizar dados": recoleta o mês corrente (force) E preenche os
    meses recentes que ainda não têm snapshot (backfill dos últimos 6 — pedido
    do usuário em produção). Mês antigo que já tem snapshot fechado não é
    tocado; falha em UM mês não derruba os outros (vai para `falhas`)."""
    agora = agora or datetime.now()
    mes_corrente = agora.strftime("%Y-%m")
    existentes = {i["month"] for i in coleta.ler_index(SNAP_DIR)}
    coletados: list[str] = []
    falhas: list[str] = []
    # UM cliente (= um login) para o backfill inteiro: um login por mês disparou
    # o rate-limit do Kratos em produção real (HTTP 403 do flow).
    cliente = _novo_cliente() if gobrax.configurado() else None
    carimbo = agora.strftime("%Y-%m-%d %H:%M")
    for mes in meses_recentes(n_meses, agora):
        if mes != mes_corrente and mes in existentes:
            continue  # fechado e já coletado (o I1 do obter cuida de parcial órfão)
        try:
            obter(mes, force=(mes == mes_corrente), agora=agora, cliente=cliente)
        except (gobrax.GobraxIndisponivel, gobrax.GobraxNaoConfigurado, ValueError) as exc:
            log.warning("backfill %s falhou: %s", mes, exc)
            falhas.append(mes)
            continue
        # coleta DE VERDADE ou fallback silencioso? O carimbo diz: o snapshot
        # recém-coletado leva o coletado_em desta execução.
        snap = coleta.ler_snapshot(mes, SNAP_DIR)
        if snap and snap.get("coletado_em") == carimbo:
            coletados.append(mes)
        else:
            log.warning("backfill %s serviu snapshot antigo (fallback)", mes)
            falhas.append(mes)
    resp = obter(mes_corrente, agora=agora, cliente=cliente)
    resp["meses_coletados"] = coletados
    resp["meses_com_falha"] = falhas
    return resp


def serie() -> dict:
    """Série leve para o card comparativo mensal (Task 6 — fix de revisão):
    só lê snapshots JÁ GRAVADOS em disco (`ler_snapshot`, puro) para cada mês do
    `index` — NUNCA recoleta (não chama `_novo_cliente`/Gobrax) e NUNCA consulta
    o preço do diesel na AVA (`_preco_diesel`), que é o custo que fazia o card
    demorar ~15s por mês quando o túnel está fora. Os params atuais são lidos
    UMA vez (não variam por mês: não há histórico de parâmetro por período).
    Funciona igual com ou sem credenciais Gobrax configuradas — servem os
    snapshots que já existirem; mês sem snapshot sai da lista."""
    parametros = params.ler_params()
    meses = []
    for item in coleta.ler_index(SNAP_DIR):
        snap = coleta.ler_snapshot(item["month"], SNAP_DIR)
        if snap is None:
            continue
        calc = calculo.calcular(snap.get("drivers") or [], parametros)
        meses.append({
            "month": item["month"],
            "label": item["label"],
            "parcial": bool(snap.get("parcial")),
            "media_frota": calc["kpis"].get("media_frota"),
            "meta": parametros["meta"],
            "premio_total": calc["kpis"].get("premio_total"),
        })
    return {"meses": meses}
