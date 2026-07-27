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

import threading
from datetime import datetime, timedelta

from api.premiacao import calculo, coleta, gobrax, params
from api.premiacao.coleta import SNAP_DIR  # reexport: monkeypatch nos testes

TTL = timedelta(hours=1)

_LOCK = threading.Lock()

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


def _preco_diesel(mes: str) -> float | None:
    """Preço médio do diesel interno no mês (AVA). ERP fora não derruba a
    tela: qualquer falha (conexão, túnel, coluna ausente) volta `None`."""
    from api import db  # lazy: testes do serviço não precisam de Postgres

    ano, m = map(int, mes.split("-"))
    de = f"{ano:04d}-{m:02d}-01"
    ate = f"{ano + 1:04d}-01-01" if m == 12 else f"{ano:04d}-{m + 1:02d}-01"
    try:
        linhas = db.query(_PRECO_DIESEL_SQL, {"de": de, "ate": ate})
        preco = linhas[0]["preco"] if linhas else None
        return float(preco) if preco is not None else None
    except Exception:  # noqa: BLE001 -- ERP fora não pode derrubar a tela
        return None


def _coletado_ha_mais_de_1h(snap: dict, agora: datetime) -> bool:
    coletado_em = datetime.strptime(snap["coletado_em"], "%Y-%m-%d %H:%M")
    return (agora - coletado_em) > TTL


def _precisa_recoletar(mes: str, mes_corrente: str, snap: dict | None,
                        force: bool, agora: datetime) -> bool:
    if force or snap is None:
        return True
    return mes == mes_corrente and _coletado_ha_mais_de_1h(snap, agora)


def obter(mes: str | None = None, force: bool = False, agora=None) -> dict:
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
        with _LOCK:
            # relê depois de tomar o lock: quem chegou 2º pode achar já pronto
            snap_relido = coleta.ler_snapshot(mes, SNAP_DIR)
            if _precisa_recoletar(mes, mes_corrente, snap_relido, force, agora):
                try:
                    cliente = _novo_cliente()
                    novo = coleta.coletar_mes(cliente, mes, agora=agora)
                    coleta.gravar_snapshot(novo, SNAP_DIR)
                    snap = novo
                except (gobrax.GobraxIndisponivel, gobrax.GobraxNaoConfigurado, ValueError):
                    if snap_relido is None:
                        raise
                    snap = snap_relido
                    aviso = (f"coletado em {snap['coletado_em']} — "
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
