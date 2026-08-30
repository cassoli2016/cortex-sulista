"""Condição da estrada onde cada caminhão EM VIAGEM está agora.

O RECORTE É "EM VIAGEM", E ELE É QUEM PAGA A CONTA
==================================================
Medido em 30/08/2026: a frota tem 275 placas com posição, e **69 viagens em
trânsito** — todas as 69 com posição, porque a união do rastreamento do ERP com
a Gobrax cobre 100% delas (`api/posicoes.py`).

Consultar as 275 seria 4x o custo para responder sobre caminhão parado no
pátio, que não tem estrada nenhuma para estar congestionada. O recorte não é
economia: é a pergunta certa.

O LIMITE DELES NÃO É OBSERVÁVEL — ENTÃO MEÇA O NOSSO GASTO
==========================================================
Nenhuma resposta da TomTom traz cabeçalho de cota (medido nas três famílias de
endpoint). O teto do plano só existe no painel deles. Sem poder ver o limite, o
mínimo honesto é ver o consumo: cada chamada é contada em `tt_chamadas`, por
dia e por recurso, e o número aparece na Saúde.

Daí também a cadência ser **sob demanda com TTL**, e não uma tarefa agendada.
Agendada, o custo é constante mesmo num domingo em que ninguém abre a tela; sob
demanda, o gasto acompanha o uso. Com TTL de 10 minutos, um dia inteiro de
alguém olhando a Torre dá ~70 chamadas por ciclo e no máximo ~6 ciclos por
hora — e o contador diz o resto.

PARALELO, MAS POUCO
===================
69 chamadas em série a 0,54 s dariam ~37 s, tempo demais para uma tela. Oito
trabalhadores resolvem em ~5 s. Oito, e não trinta: bater numa API de terceiro
com dezenas de conexões simultâneas é o tipo de coisa que faz o terceiro
começar a recusar — e a recusa dele viria como o 403 que já é difícil de
diagnosticar aqui.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from api import pglocal
from api.tomtom import cliente, transito

log = logging.getLogger(__name__)

ESQUEMA: str | None = None       # os testes redirecionam
TTL_S = 600                      # 10 min: trânsito não muda em segundos
TRABALHADORES = 8

_cache: tuple[float, dict] | None = None
_lock = threading.Lock()


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


def registrar(recurso: str, n: int = 1, erros: int = 0,
              esquema: str | None = None) -> None:
    """Soma ao consumo do dia. NÃO levanta: contabilidade que derruba a
    funcionalidade que ela mede é pior que contabilidade nenhuma."""
    try:
        pglocal.executar(
            """INSERT INTO tt_chamadas (dia, recurso, chamadas, erros, ultima_em)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (dia, recurso) DO UPDATE
                  SET chamadas = tt_chamadas.chamadas + EXCLUDED.chamadas,
                      erros    = tt_chamadas.erros    + EXCLUDED.erros,
                      ultima_em = EXCLUDED.ultima_em""",
            (date.today(), recurso, n, erros, datetime.now()),
            esquema=_esq(esquema))
    except Exception as exc:  # noqa: BLE001
        log.warning("não consegui registrar consumo da TomTom: %s",
                    type(exc).__name__)


def consumo(dias: int = 7, esquema: str | None = None) -> dict:
    """O gasto recente. É o que responde "estamos perto do teto?" quando o
    teto não é visível na resposta."""
    try:
        linhas = [dict(r) for r in pglocal.query(
            """SELECT dia::text AS dia, recurso, chamadas, erros,
                      to_char(ultima_em,'YYYY-MM-DD HH24:MI') AS ultima_em
                 FROM tt_chamadas
                WHERE dia >= current_date - %s
                ORDER BY dia DESC, recurso""", (dias,), esquema=_esq(esquema))]
    except Exception as exc:  # noqa: BLE001
        log.warning("consumo da TomTom indisponível: %s", type(exc).__name__)
        return {"hoje": None, "linhas": [], "erro": type(exc).__name__}
    hoje = str(date.today())
    return {"hoje": sum(l["chamadas"] for l in linhas if l["dia"] == hoje),
            "erros_hoje": sum(l["erros"] for l in linhas if l["dia"] == hoje),
            "linhas": linhas}


def _um_ponto(item: tuple[str, dict]) -> dict:
    placa, p = item
    try:
        bruto = cliente.fluxo(p["lat"], p["lon"])
        return {"placa": placa, "ok": True, **transito.do_payload(bruto)}
    except cliente.TomTomIndisponivel as exc:
        # A MENSAGEM JÁ VEM SANITIZADA do cliente. Repassá-la é seguro, e é o
        # que permite a tela dizer "403 com a chave do mapa" em vez de "erro".
        return {"placa": placa, "ok": False, "estado": "nd",
                "rotulo": "Não foi possível consultar", "erro": str(exc)}


def condicao_da_frota(*, forcar: bool = False, limite: int | None = None,
                      viagens=None, posicoes_atuais=None,
                      so_cache: bool = False) -> dict:
    """A leitura de trânsito das viagens em curso.

    `so_cache=True` NUNCA sai para a rede: devolve o que houver em cache, ou
    diz que não há. Existe para o snapshot do Copiloto, e a razão é uma lição
    já paga: a premiação tinha um `force` que ia buscar na Gobrax, e incluí-la
    no snapshot sem cuidado teria transformado "abrir o chat" em chamada de
    API externa a cada dez minutos. Aqui seriam ~70 chamadas por abertura.

    `viagens` e `posicoes_atuais` existem para o teste injetar — sem eles, lê
    da Torre e de `api/posicoes.py`.
    """
    global _cache
    agora = time.monotonic()
    if not forcar and _cache and (agora - _cache[0]) < TTL_S:
        return {**_cache[1], "do_cache": True}
    if so_cache:
        return {"configurado": cliente.configurado(), "sem_cache": True,
                "trechos": [], "resumo": transito.resumo([]),
                "mensagem": "sem leitura recente — abra a Torre de Controle"}

    with _lock:
        if not forcar and _cache and (time.monotonic() - _cache[0]) < TTL_S:
            return {**_cache[1], "do_cache": True}

        if not cliente.configurado():
            return {"configurado": False,
                    "mensagem": "Chave da TomTom não configurada "
                                "(Gestão › Integrações).",
                    "trechos": [], "resumo": transito.resumo([])}

        if viagens is None:
            from api import queries
            viagens = (queries.get_torre() or {}).get("transito") or []
        placas = []
        vistas = set()
        for v in viagens:
            pl = (v.get("placa") or "").strip().upper()
            if pl and pl not in vistas:
                vistas.add(pl)
                placas.append(pl)

        if posicoes_atuais is None:
            from api import posicoes as _pos
            posicoes_atuais = _pos.atuais()
        mapa = posicoes_atuais.get("posicoes") or {}

        alvos = [(pl, mapa[pl]) for pl in placas if pl in mapa]
        # SEM POSIÇÃO NÃO É "SEM TRÂNSITO": some do numerador E do
        # denominador, e é contado à parte. Tratar como livre diria que está
        # tudo bem por falta de dado.
        sem_posicao = [pl for pl in placas if pl not in mapa]
        if limite:
            alvos = alvos[:limite]

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=TRABALHADORES) as pool:
            trechos = list(pool.map(_um_ponto, alvos))
        gastou = time.time() - t0
        erros = sum(1 for t in trechos if not t.get("ok"))
        registrar("fluxo", n=len(trechos), erros=erros)

        for t in trechos:
            p = mapa.get(t["placa"]) or {}
            t["lat"], t["lon"] = p.get("lat"), p.get("lon")
            t["fonte_posicao"] = p.get("fonte")
            t["posicao_idade_min"] = p.get("idade_min")

        fora = {
            "configurado": True,
            "trechos": sorted(trechos, key=lambda t: _ordem(t["estado"])),
            "resumo": transito.resumo(trechos),
            "viagens": len(placas),
            "consultados": len(alvos),
            "sem_posicao": sem_posicao,
            "erros": erros,
            "segundos": round(gastou, 1),
            # De onde veio a posição de cada um: com a Gobrax fora, o total não
            # muda (o ERP cobre 274 das 275) e é só esta linha que denuncia.
            "posicao_por_fonte": posicoes_atuais.get("por_fonte"),
            "fontes_fora": posicoes_atuais.get("fontes_fora") or [],
            "colhido_em": datetime.now().isoformat(timespec="seconds"),
            "do_cache": False,
        }
        _cache = (time.monotonic(), fora)
        return fora


_PESO = {"bloqueado": 0, "parado": 1, "congestionado": 2, "lento": 3,
         "livre": 4, "nd": 5}


def _ordem(estado: str) -> int:
    """Pior primeiro. Numa lista que existe para agir, o que exige ação vai em
    cima — a lição da ignição ligada sem comunicar, que estava afogada no meio
    de quinze linhas ordenadas por dias."""
    return _PESO.get(estado, 9)
