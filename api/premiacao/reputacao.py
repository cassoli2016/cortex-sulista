# -*- coding: utf-8 -*-
"""Reputação de seis ciclos, categoria e a medida disciplinar sugerida.

A DIFERENÇA ENTRE O RANKING E A REPUTAÇÃO, que é o coração do modelo: o
ranking do ciclo mede O CICLO — quem foi bem no mês. A reputação mede a
HISTÓRIA — seis ciclos de conduta, com os méritos somando e cada ciclo limpo
valendo um bônus. Uma pessoa pode estar em ATENÇÃO no mês e continuar OURO na
categoria; é assim de propósito, porque categoria que oscila todo mês não
é categoria, é outro ranking.

A CONTA DA REPUTAÇÃO DE CONDUTA (a do modelo):

    100 − pontos dos desvios da janela + pontos dos méritos + ciclos limpos × bônus

Ela PASSA DE 100 de propósito — é o que faz a faixa ELITE (105) existir. Quem
nunca teve desvio e acumulou mérito fica acima do teto do ranking, e isso é o
sinal que separa "não errou" de "fez além".

O QUE É CICLO LIMPO: ciclo sem NENHUM desvio, contado a partir do primeiro
ciclo em que a pessoa aparece na base — não desde sempre. Sem isso, quem foi
admitido há dois meses ganharia bônus por quatro ciclos em que não existia.
"""
from __future__ import annotations

import logging

from . import ciclo as ciclo_mod, pilares

log = logging.getLogger("cortex.premiacao.reputacao")

#: As medidas do rito CLT. O texto diz QUEM aplica, porque medida disciplinar
#: aplicada por quem não pode aplicar é nula — e a tela é lida por gente da
#: operação, não do RH.
MEDIDAS = {
    "N1": "Orientação registrada (gestão da frota)",
    "N2": "Advertência verbal formalizada (gestão + gestor da área)",
    "N3": "Advertência escrita (gestor + RH)",
    "N4": "Suspensão (RH)",
}

ORDEM_MEDIDA = ("N1", "N2", "N3", "N4")


def sugerir_medida(desvios_ciclo: list[dict], desvios_3: list[dict],
                   desvios_6: list[dict]) -> dict | None:
    """A medida SUGERIDA para quem teve desvio no ciclo — ou None.

    É SUGESTÃO, e a tela diz isso em letras: motorista próprio é CLT, o rito é
    trabalhista e quem aplica é o RH. O sistema propõe o nível pela reincidência
    (é o que ninguém consegue acompanhar à mão); a validação é de gente.

    A escada é a do modelo: 4 desvios em 6 ciclos → N4; 3 em 6 → N3; 2 em 3 →
    N2; senão N1. E um desvio GRAVÍSSIMO no ciclo nunca fica abaixo de N3 —
    quebra de PGR não se resolve com orientação verbal.
    """
    if not desvios_ciclo:
        return None
    n3, n6 = len(desvios_3), len(desvios_6)
    if n6 >= 4:
        nivel = "N4"
    elif n6 >= 3:
        nivel = "N3"
    elif n3 >= 2:
        nivel = "N2"
    else:
        nivel = "N1"
    gravissimo = any(d.get("grav") == "GRAVISSIMA" for d in desvios_ciclo)
    if gravissimo and ORDEM_MEDIDA.index(nivel) < ORDEM_MEDIDA.index("N3"):
        nivel = "N3"
    return {"nivel": nivel, "medida": MEDIDAS[nivel],
            "porque": _porque(nivel, n3, n6, gravissimo),
            "reincidencia_3": n3, "reincidencia_6": n6,
            "sugerida": True}


def _porque(nivel: str, n3: int, n6: int, gravissimo: bool) -> str:
    if gravissimo and nivel == "N3":
        return "desvio gravíssimo no ciclo"
    if nivel == "N4":
        return f"{n6} desvios em 6 ciclos"
    if nivel == "N3":
        return f"{n6} desvios em 6 ciclos"
    if nivel == "N2":
        return f"{n3} desvios em 3 ciclos"
    return "primeiro desvio da janela"


def janela_de_conduta(ciclo: str, comportamento_por_ciclo: dict, cpf: str,
                      n: int = 3) -> list[dict]:
    """Os desvios de `cpf` nos últimos `n` ciclos (o mais recente incluído)."""
    saida = []
    for c in ciclo_mod.janela(ciclo, n):
        ficha = (comportamento_por_ciclo.get(c) or {}).get(cpf) or {}
        saida.extend(ficha.get("desvios") or [])
    return saida


def _media(valores: list[float]) -> float | None:
    limpos = [v for v in valores if v is not None]
    return round(sum(limpos) / len(limpos), 1) if limpos else None


def calcular(ciclo: str, cpf: str, comportamento_por_ciclo: dict,
             gobrax_por_ciclo: dict, gr_por_ciclo: dict, valores: dict,
             primeiro_ciclo: str | None = None) -> dict:
    """A reputação composta de seis ciclos e a categoria dela.

    `*_por_ciclo` são mapas {ciclo: {cpf: ficha}} já lidos uma vez por quem
    chama — seis ciclos × três fontes por motorista seriam centenas de idas ao
    banco para montar uma tela.
    """
    janela = ciclo_mod.janela(ciclo, ciclo_mod.JANELA_REPUTACAO)
    desvios, meritos, limpos = [], [], 0
    notas_g, notas_r = [], []
    for c in janela:
        ficha = (comportamento_por_ciclo.get(c) or {}).get(cpf) or {}
        d = ficha.get("desvios") or []
        desvios.extend(d)
        meritos.extend(ficha.get("meritos") or [])
        # CICLO LIMPO só conta a partir de quando a pessoa existe na base.
        if (primeiro_ciclo is None or c >= primeiro_ciclo) and c <= ciclo and not d:
            limpos += 1
        g = (gobrax_por_ciclo.get(c) or {}).get(cpf) or {}
        if g.get("nota") is not None:
            notas_g.append(float(g["nota"]))
        r = (gr_por_ciclo.get(c) or {}).get(cpf) or {}
        if r.get("nota") is not None:
            notas_r.append(float(r["nota"]))

    pontos_desvio = sum(float(d["pts"]) for d in desvios)
    pontos_merito = sum(float(m["pts"]) for m in meritos)
    bonus = float(valores.get("bonus_ciclo_limpo", 0)) * limpos
    rep_conduta = 100.0 - pontos_desvio + pontos_merito + bonus

    media_g, media_r = _media(notas_g), _media(notas_r)
    comp = pilares.composta(media_g, rep_conduta, media_r, valores)
    return {
        "ciclos": janela,
        "desvios": len(desvios), "meritos": len(meritos),
        "ciclos_limpos": limpos,
        "pontos_desvio": pontos_desvio, "pontos_merito": pontos_merito,
        "rep_conduta": round(rep_conduta, 1),
        "gobrax_media": media_g, "gr_media": media_r,
        "reputacao": comp["nota"],
        "pilares": comp["pilares"], "ausentes": comp["ausentes"],
        "categoria": pilares.categoria(comp["nota"], valores),
    }
