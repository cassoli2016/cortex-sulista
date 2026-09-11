# -*- coding: utf-8 -*-
"""A lentidão nos corredores pela VELOCIDADE DA NOSSA FROTA — medida, e de graça.

POR QUE EXISTE (11/09/2026)
===========================
A franquia grátis de trânsito da TomTom é MENSAL — 20 mil consultas de fluxo e
2.500 de ocorrências (docs.tomtom.com/pricing) — e a varredura da Torre gastou
a de setembro na primeira semana. O cartão "Rodovias agora" da página inicial
ficou sem nada ao vivo, e quem opera respondeu: "não quero que desligue, quero
que apareça e esteja certo". A fonte escolhida até a TomTom renovar foi esta:
o rastreador dos próprios caminhões, que a Torre já usa
(`api/frota_movimento.py`).

O QUE ELA AFIRMA, E O QUE NÃO
=============================
- Conta, por corredor, os caminhões EM VIAGEM (os da Torre) cuja posição de
  AGORA (até `frota_movimento.FRESCO_MIN`) cai dentro da caixa do corredor —
  as MESMAS caixas das ocorrências da TomTom (`rodovias.CORREDORES`), para as
  duas falarem do mesmo lugar.
- LENTO é o de `frota_movimento`: duas leituras seguidas entre 8 e 40 km/h —
  o sinal de trânsito. É o número que o cartão destaca.
- PARADO é contado e dito "motivo não informado": descanso, cliente e posto
  não são congestionamento, e 40% da frota em viagem estava parada no dia em
  que isso foi medido.
- Só enxerga onde há caminhão nosso. Corredor sem caminhão diz "nenhum
  caminhão nosso agora" — nunca "livre", que seria afirmar a estrada pela
  ausência de dado.

SEM PLACA. A página inicial é de TODO usuário logado; o que sai daqui é
contagem por corredor, e a tabela `rad_frota` não tem coluna de placa, de
motorista nem de coordenada (guard estrutural em `tests/radar/test_frota.py`).
"""
from __future__ import annotations

import logging
from datetime import datetime
from statistics import median

from . import rodovias

log = logging.getLogger("cortex.radar.frota")


def corredor_de(lat: float, lon: float) -> str | None:
    """A chave do corredor cuja caixa contém o ponto, ou None."""
    for chave, _rotulo, oeste, sul, leste, norte in rodovias.CORREDORES:
        if oeste <= lon <= leste and sul <= lat <= norte:
            return chave
    return None


def _entradas() -> tuple[list, dict]:
    """As viagens em trânsito da Torre e as posições de agora (ERP + Gobrax)."""
    from api import posicoes, queries
    viagens = (queries.get_torre() or {}).get("transito") or []
    return viagens, posicoes.atuais()


def _serie(placas, agora):
    from api import frota_movimento
    return frota_movimento.serie(placas, agora)


def ler(viagens=None, posicoes_atuais=None, ler_serie=None,
        agora: datetime | None = None) -> list[dict]:
    """Uma linha por corredor, sempre os quatro — zero é resposta.

    `viagens`, `posicoes_atuais` e `ler_serie` existem para o teste: nenhum
    teste consulta o ERP de verdade.
    """
    from api import frota_movimento
    if viagens is None or posicoes_atuais is None:
        v, p = _entradas()
        viagens = v if viagens is None else viagens
        posicoes_atuais = p if posicoes_atuais is None else posicoes_atuais
    mapa = (posicoes_atuais or {}).get("posicoes") or {}
    onde: dict[str, str] = {}
    for v in viagens:
        pl = (v.get("placa") or "").strip().upper()
        p = mapa.get(pl) or {}
        idade = p.get("idade_min")
        # POSIÇÃO VELHA NÃO DIZ ONDE O CAMINHÃO ESTÁ AGORA: ele pode ter saído
        # do corredor há horas.
        if (not pl or pl in onde or p.get("lat") is None or p.get("lon") is None
                or idade is None or idade > frota_movimento.FRESCO_MIN):
            continue
        c = corredor_de(float(p["lat"]), float(p["lon"]))
        if c:
            onde[pl] = c
    trechos = (frota_movimento.condicao(list(onde), posicoes_atuais, agora=agora,
                                        ler=ler_serie or _serie) if onde else [])
    linhas = {c[0]: {"regiao": c[0], "caminhoes": 0, "andando": 0, "lentos": 0,
                     "parados": 0, "indefinidos": 0, "lento_max_min": None,
                     "vel_lentos": None, "_vel": []} for c in rodovias.CORREDORES}
    for t in trechos:
        l = linhas[onde[t["placa"]]]
        l["caminhoes"] += 1
        estado = t.get("estado")
        if estado == "livre":
            l["andando"] += 1
        elif estado == "lento":
            l["lentos"] += 1
            l["lento_max_min"] = max(l["lento_max_min"] or 0, int(t.get("minutos") or 0))
            if t.get("velocidade") is not None:
                l["_vel"].append(t["velocidade"])
        elif estado == "parado":
            l["parados"] += 1
        else:
            l["indefinidos"] += 1
    saida = []
    for l in linhas.values():
        vel = l.pop("_vel")
        l["vel_lentos"] = int(round(median(vel))) if vel else None
        saida.append(l)
    return saida
