# -*- coding: utf-8 -*-
"""A condição da estrada pela VELOCIDADE DOS PRÓPRIOS CAMINHÕES — a reserva da TomTom.

POR QUE EXISTE
==============
Em 11/09/2026 o produto de trânsito da TomTom esgotou o crédito
(`InsufficientFunds`), e a Torre ficou sem a condição da estrada de nenhum
caminhão. Quem opera decidiu: a TomTom continua sendo a fonte principal, e a
velocidade da própria frota entra como RESERVA quando ela não responder — sem
crédito, sem chave, ou recusando todos os pontos.

O QUE FOI MEDIDO ANTES DE ESCREVER (11/09/2026, ~11h, 56 caminhões em viagem)
============================================================================
- **O rastreador do ERP é a base.** 55 dos 56 tinham ponto na última hora, com
  12 a 21 pontos por hora (um a cada ~5 min), último ponto com mediana de 3,3
  min e NENHUM ponto sem velocidade. A Gobrax conhecia só 13 dos 56 — usada
  sozinha, a Torre enxergaria um caminhão em cada quatro.
- **As duas concordam onde se encontram**: diferença mediana de 1 km/h (p90 de
  15) nos pares a menos de 5 min um do outro. A Gobrax manda um ponto a cada 30
  s com o caminhão andando; por isso o ÚLTIMO ponto dela entra quando é mais
  novo que o do ERP — a mesma regra de `api/posicoes.py`: vence o mais recente.
- **NÃO HÁ IGNIÇÃO** em nenhuma das duas (a Gobrax manda só data, coordenada e
  velocidade), e a jornada em tempo real (RasterJOR), que diria "em repouso",
  estava sem coletar desde as 06h20 e cobre ~5 dos caminhões em viagem.

A CONSEQUÊNCIA, E ELA É A DECISÃO DESTE MÓDULO
==============================================
Naquele instante 22 dos 55 estavam PARADOS — 40% da frota em viagem, 15 deles
há mais de 15 minutos. Isso é descanso, cliente e posto, não congestionamento.
Então a reserva só afirma o que a velocidade sustenta:

- **andando** — última leitura a 40 km/h ou mais;
- **lento há N min** — DUAS ou mais leituras seguidas entre 8 e 40 km/h. É o
  sinal de trânsito: caminhão não roda a 25 km/h por dez minutos numa BR à toa.
  Uma leitura só pode ser pedágio, rotatória ou saída de posto;
- **parado há N min, motivo não informado** — e é assim que a tela diz, nunca
  "congestionado". Afirmar a causa seria dizer o que a fonte não disse.

A consulta ao ERP é uma só para a frota em viagem, por `veiculo = ANY(...)` e
`dt >= ...`, e usa o índice `(veiculo, dt)` — medido com EXPLAIN antes: Index
Scan, custo ~230, contra uma tabela de 4,2 milhões de linhas (3,6 GB). O ERP é
PostgreSQL 9.3: nada de `make_interval` (só existe do 9.4 em diante).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from api.tomtom import transito

log = logging.getLogger(__name__)

#: Quanto de série se lê do ERP. 45 min dão ~9 pontos a 5 min de passo — o
#: bastante para "lento há 20 min" sem ler a tabela à toa.
JANELA_MIN = 45
#: Último ponto mais velho que isto não é "agora": vira "sem posição recente".
FRESCO_MIN = 30
#: As mesmas fronteiras da leitura da TomTom, para as duas falarem a mesma
#: língua na mesma tabela: abaixo de 8 km/h é parado.
PARADO_KMH = transito.PARADO_KMH
LENTO_KMH = 40.0
#: Lento só com duas leituras seguidas — ver o cabeçalho.
MIN_LEITURAS_LENTO = 2

SERIE_SQL = """
SELECT upper(trim(veiculo))                            AS placa,
       dt,
       greatest(coalesce(velocidade, 0), 0)::float8    AS velocidade
  FROM veiculo_posicao
 WHERE veiculo = ANY(%s)
   AND dt >= %s
 ORDER BY veiculo, dt
"""


def serie(placas: list[str], agora: datetime | None = None,
          janela_min: int = JANELA_MIN) -> dict[str, list[tuple[datetime, float]]]:
    """A série de velocidade de cada placa na janela, do rastreador do ERP."""
    if not placas:
        return {}
    from api import db
    agora = agora or datetime.now()
    saida: dict[str, list[tuple[datetime, float]]] = {}
    for l in db.query(SERIE_SQL, (list(placas), agora - timedelta(minutes=janela_min))):
        saida.setdefault(l["placa"], []).append((l["dt"], float(l["velocidade"])))
    return saida


def _min(a: datetime, b: datetime) -> int:
    return int(round((b - a).total_seconds() / 60))


def classificar(pontos: list[tuple[datetime, float]], agora: datetime) -> dict:
    """De uma série de (quando, km/h) para o estado que a Torre mostra."""
    if not pontos:
        return {"estado": "nd", "rotulo": "Sem posição na última hora",
                "velocidade": None, "minutos": None}
    pontos = sorted(pontos)
    ult_dt, ult_v = pontos[-1]
    idade = _min(ult_dt, agora)
    if idade > FRESCO_MIN:
        return {"estado": "nd", "rotulo": f"Sem posição recente (há {idade} min)",
                "velocidade": int(ult_v), "minutos": None, "idade_min": idade}
    base = {"velocidade": int(round(ult_v)), "idade_min": idade}

    if ult_v < PARADO_KMH:
        ini, todo = ult_dt, True
        for d, v in reversed(pontos):
            if v >= PARADO_KMH:
                todo = False
                break
            ini = d
        m = _min(ini, ult_dt)
        # PARADO A JANELA INTEIRA é "há MAIS de N min": a série começa no meio
        # da parada, e dizer "há N" afirmaria quando ela começou.
        rot = (f"Parado há mais de {m} min" if todo and m else f"Parado há {m} min")
        return {**base, "estado": "parado", "rotulo": rot, "minutos": m,
                "motivo": "não informado"}

    if ult_v < LENTO_KMH:
        ini, n = ult_dt, 0
        for d, v in reversed(pontos):
            if not (PARADO_KMH <= v < LENTO_KMH):
                break
            ini, n = d, n + 1
        if n >= MIN_LEITURAS_LENTO:
            m = _min(ini, ult_dt)
            return {**base, "estado": "lento", "rotulo": f"Lento há {m} min",
                    "minutos": m}
        # UMA LEITURA LENTA SÓ NÃO É NEM TRÂNSITO NEM ESTRADA LIVRE. Com o
        # dado real de 11/09/2026 ela saía "Andando" em verde a 10 km/h — e
        # verde afirma uma estrada que a série não mostra. Fica neutra, dizendo
        # a velocidade, até a leitura seguinte decidir.
        return {**base, "estado": "nd", "minutos": None,
                "rotulo": f"Devagar numa leitura só ({int(round(ult_v))} km/h)"}
    return {**base, "estado": "livre", "rotulo": "Andando", "minutos": None}


def condicao(placas: list[str], posicoes_atuais: dict | None = None,
             agora: datetime | None = None, ler=None) -> list[dict]:
    """Um trecho por placa, no MESMO formato dos trechos da TomTom.

    `ler` existe para o teste: nenhum teste consulta o ERP de verdade.
    `posicoes_atuais` é o que `api/posicoes.py` já leu — o último ponto da
    Gobrax entra dali, sem uma segunda chamada à Gobrax.
    """
    agora = agora or datetime.now()
    series = (ler or serie)(placas, agora)
    mapa = (posicoes_atuais or {}).get("posicoes") or {}
    saida = []
    for pl in placas:
        pts = list(series.get(pl) or [])
        fonte = "erp" if pts else None
        p = mapa.get(pl) or {}
        q = p.get("quando")
        if p.get("fonte") == "gobrax" and isinstance(q, datetime) and \
                (not pts or q > max(d for d, _ in pts)):
            pts.append((q, float(p.get("velocidade") or 0)))
            fonte = "gobrax"
        c = classificar(pts, agora)
        saida.append({"placa": pl, "ok": c["estado"] != "nd", "fonte": "frota",
                      "fonte_velocidade": fonte, "velocidade_livre": None,
                      "atraso_s": None, "leituras": len(pts), **c})
    return saida
