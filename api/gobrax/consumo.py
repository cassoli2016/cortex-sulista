"""Telemetria × abastecimento — duas medidas independentes do mesmo consumo.

A telemetria mede o que o motor gastou; o abastecimento mede o que saiu da
bomba. Onde os dois divergem muito há desvio, bomba descalibrada ou
abastecimento não lançado — e é essa diferença, não cada número isolado, que
justifica a tela.

Faixa física: km/l fora de 0,5 a 15 é leitura implausível de telemetria, não
desempenho. Medido em julho/2026, a frota real trouxe 0,1 e 17,88 — os dois
impossíveis para caminhão. Linha assim fica VISÍVEL e marcada, mas fora da
média da frota, mesmo tratamento que a premiação dava.

COBERTURA: a telemetria pode reportar só uma fração do período. Medido em
julho/2026, a placa BBF5G20 tem odômetro de 995 mil km e a API devolveu 32,95 km
no mês, enquanto o AVA registra 6.644 km em 12 abastecimentos — o rastreador
ficou praticamente mudo. Comparar km/l nesse caso não mede consumo, mede
silêncio de rastreador. Por isso o cruzamento só vale onde a telemetria cobre a
maior parte do km do abastecimento; abaixo disso a linha é marcada como
telemetria incompleta e fica fora da contagem de divergentes.
"""
from __future__ import annotations

import re

from api.gobrax import armazenamento, estatisticas

_SO_ALNUM = re.compile(r"[^A-Za-z0-9]")

LIMITE_DIVERGENCIA_PCT = 15.0
KM_L_MIN, KM_L_MAX = 0.5, 15.0
# abaixo disso a telemetria cobriu pouco do período e a comparação não mede consumo
COBERTURA_MINIMA = 0.70


def normalizar_placa(placa: str | None) -> str:
    """A Gobrax devolve ABC-1234; o AVA guarda ABC1234."""
    return _SO_ALNUM.sub("", (placa or "")).upper()


def plausivel(km_l) -> bool:
    return km_l is not None and KM_L_MIN <= km_l <= KM_L_MAX


def cruzar(telemetria: list[dict], ava: list[dict]) -> list[dict]:
    por_placa: dict[str, dict] = {}
    for t in telemetria:
        chave = normalizar_placa(t.get("placa"))
        if chave:
            por_placa[chave] = {**t, "km_l_ava": None, "delta_pct": None,
                                "suspeito": not plausivel(t.get("km_l"))
                                            and t.get("km_l") is not None}
    for a in ava:
        chave = normalizar_placa(a.get("placa"))
        if not chave:
            continue
        linha = por_placa.setdefault(chave, {
            "placa": a.get("placa"), "km": None, "litros": None, "km_l": None,
            "vel_media": None, "odometro": None, "freadas": 0, "freadas_alta": 0,
            "km_l_ava": None, "delta_pct": None, "suspeito": False})
        litros = float(a.get("litros_ava") or 0)
        km_ava = float(a.get("km_ava") or 0)
        linha["litros_ava"] = litros or None
        linha["km_ava"] = km_ava or None
        linha["abastecimentos"] = a.get("abastecimentos")
        # cada lado usa o SEU próprio km: misturar o km da telemetria com os
        # litros do abastecimento produziu km/l de 0,01 e delta de +50.000%
        if litros > 0 and km_ava > 0:
            linha["km_l_ava"] = km_ava / litros
        km_tel = float(linha.get("km") or 0)
        if km_ava > 0 and km_tel > 0:
            linha["cobertura_tel"] = km_tel / km_ava
        linha["telemetria_incompleta"] = (
            linha.get("cobertura_tel") is not None
            and linha["cobertura_tel"] < COBERTURA_MINIMA)
        # a faixa física vale para os DOIS lados: o km declarado no
        # abastecimento também falha, e um km/l de 0,14 do AVA produzia delta de
        # +1.765% que não é divergência de consumo, é distância mal lançada
        linha["ava_implausivel"] = (linha.get("km_l_ava") is not None
                                    and not plausivel(linha["km_l_ava"]))
        if (linha.get("km_l") and linha.get("km_l_ava")
                and not linha["telemetria_incompleta"]
                and not linha.get("suspeito")
                and not linha["ava_implausivel"]):
            linha["delta_pct"] = (linha["km_l"] / linha["km_l_ava"] - 1) * 100
    return sorted(por_placa.values(), key=lambda l: -abs(l.get("delta_pct") or 0))


def resumir(linhas: list[dict], limite_pct: float = LIMITE_DIVERGENCIA_PCT) -> dict:
    com_duas = [l for l in linhas if l.get("km_l") and l.get("km_l_ava")]
    # a média da frota só usa leitura plausível: um km/l de 0,1 puxa a média
    # inteira para baixo sem que ninguém tenha rodado mal
    bons = [l for l in linhas if plausivel(l.get("km_l"))]
    km = sum(float(l.get("km") or 0) for l in bons)
    litros = sum(float(l.get("litros") or 0) for l in bons)
    comparaveis = [l for l in linhas if l.get("delta_pct") is not None]
    return {
        "veiculos": len(linhas),
        "com_telemetria": sum(1 for l in linhas if l.get("km_l")),
        "com_as_duas_medidas": len(com_duas),
        "comparaveis": len(comparaveis),
        "telemetria_incompleta": sum(1 for l in linhas
                                     if l.get("telemetria_incompleta")),
        "ava_implausivel": sum(1 for l in linhas if l.get("ava_implausivel")),
        "suspeitos": sum(1 for l in linhas if l.get("suspeito")),
        "km_total": km,
        "litros_total": litros,
        "km_l_frota": (km / litros) if litros > 0 else None,
        "freadas": sum(int(l.get("freadas") or 0) for l in linhas),
        "freadas_alta": sum(int(l.get("freadas_alta") or 0) for l in linhas),
        "divergentes": sum(1 for l in comparaveis
                           if abs(l["delta_pct"]) > limite_pct),
        "limite_pct": limite_pct,
        "cobertura_minima": COBERTURA_MINIMA,
    }


def get_consumo(competencia: str) -> dict:
    import calendar
    from datetime import date, timedelta

    from api import db
    from api.gobrax.sql import ABASTECIMENTO_MES_SQL

    tel = armazenamento.ler(estatisticas.COLECAO, competencia)
    ano, mes = (int(x) for x in competencia.split("-"))
    ultimo = calendar.monthrange(ano, mes)[1]
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(ABASTECIMENTO_MES_SQL,
                    {"de": date(ano, mes, 1).isoformat(),
                     "ate": (date(ano, mes, ultimo) + timedelta(days=1)).isoformat()})
        ava = [dict(r) for r in cur.fetchall()]
    linhas = cruzar(tel, ava)
    return {
        "competencia": competencia,
        "kpis": resumir(linhas),
        "linhas": linhas,
        "sync": armazenamento.ultima(estatisticas.COLECAO),
        "fonte": ("Gobrax vehicle-statistics (cache local) × "
                  "sulista.ctaplus_abastecimentos do AVA, casados por placa"),
    }
