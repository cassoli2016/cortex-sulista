# -*- coding: utf-8 -*-
"""A rota que o veículo DEVE fazer, e onde ele está ao longo dela.

POR QUE A LINHA RETA NÃO SERVIA. A primeira versão media a distância que falta
em linha reta entre o veículo e o ponto de entrega. Reta subestima sempre, e em
trecho de serra subestima muito: "faltam 56 km" quando faltam 80 de asfalto é
uma promessa que a operação não cumpre, e quem está esperando na doca organiza
a equipe em cima dela.

DE ONDE VEM A ROTA, e a lição repetida. Fui procurar o KML no webservice do
gerenciador de risco e a rota já estava no ERP — pela terceira vez hoje, a
fonte estava no banco:

- `programacaoembarque.trajeto` aponta o trajeto da viagem, e está preenchido
  em 9.456 de 9.458 viagens dos últimos 60 dias (100%);
- `trajeto.extensao` é a distância RODOVIÁRIA da rota, preenchida em 4.597 de
  4.945 rotas ativas (93%);
- `trajeto_percurso` traz os pontos por onde ela passa, com coordenada em
  33.260 de 33.260 (100%) e a rodovia de cada trecho.

O QUE NÃO SE USA, e por quê. `trajeto_percurso.distanciakminiciotrajeto` tem o
nome exato do que eu precisava — o km desde o início — e está preenchido com
valor ÚTIL em 7 dos 33.260 pontos. Zero em todo o resto. Um campo assim é pior
que ausente: quem confia nele calcula progresso zero para a frota inteira e não
descobre, porque zero é um número plausível.

COMO O PROGRESSO É CALCULADO. A poligonal dá a FORMA (por onde a estrada vai) e
a `extensao` dá o TAMANHO (quanto de asfalto). Projeta-se o veículo sobre a
poligonal, mede-se a fração percorrida dela, e essa fração multiplica a
extensão real. Metade das rotas tem só dois pontos — nelas a forma é uma reta,
mas o km continua sendo o rodoviário, que já é o ganho principal.
"""
from __future__ import annotations

import logging
import math

from .. import db

log = logging.getLogger("cortex.rastreio.rota")

#: A rota vem da COLETA, nao da viagem. Tentei pela viagem primeiro
#: (`programacaoembarque.trajeto`, preenchido em 100% delas) e nao serve para
#: esta tela: a placa do CT-e 268146 nao tem viagem em curso — as ultimas sao
#: de dezembro de 2024 —, porque o veiculo do documento e o que LEVOU a carga,
#: e a viagem dele ja fechou. A coleta, essa, e a da carga.
#:
#: UM CT-e PODE COBRIR VARIAS COLETAS (carga consolidada), e cada uma tem o seu
#: trajeto. Desempata o DESTINO: fica o trajeto cujo destino bate com o do
#: conhecimento. Sem empate resolvido, a coleta mais recente — e nunca a
#: "primeira que aparecer", que muda conforme o plano de execucao do banco.
ROTA_SQL = """
SELECT t.codigo, t.descricao, t.extensao::float8 AS extensao,
       -- `quantidadehorasprevistas` NAO entra: no ERP ela e `interval`, e
       -- `::float8` sobre interval estoura a consulta inteira. O campo nao e
       -- usado aqui, e um cast desnecessario derrubou a rota em silencio.
       upper(trim(coalesce(t.cidadedestino,''))) AS destino_rota,
       co.numero AS coleta
FROM conhecimento c
JOIN conhecimento_composicao cc
  ON cc.grupo=c.grupo AND cc.empresa=c.empresa AND cc.filial=c.filial
 AND cc.unidade=c.unidade AND cc.diferenciadornumero=c.diferenciadornumero
 AND cc.serie=c.serie AND cc.numero=c.numero
JOIN coleta co
  ON co.grupo=cc.grupo AND co.empresa=cc.empresa
 AND co.filial=cc.filialdocumento AND co.unidade=cc.unidadedocumento
 AND co.diferenciadornumero=cc.diferenciadornumerodocumento
 AND co.serie=cc.seriedocumento AND co.numero=cc.numerodocumento
JOIN trajeto t
  ON t.codigo = co.trajeto AND t.grupo = co.grupo AND t.empresa = co.empresa
WHERE c.grupo=%(g)s AND c.empresa=%(e)s AND c.filial=%(f)s
  AND c.numero=%(n)s AND c.serie=%(s)s
  AND coalesce(t.extensao,0) > 0
ORDER BY co.numero DESC
"""

#: Os pontos por onde a rota passa, na ordem. Coordenada zerada fica de fora:
#: (0,0) e no golfo da Guine, e um ponto ali entortaria a poligonal inteira.
PONTOS_SQL = """
SELECT tp.sequencia, tp.latitude::float8 AS lat, tp.longitude::float8 AS lng,
       tp.cidadepassa, tp.ufpassa, tp.rodovia
FROM trajeto_percurso tp
WHERE tp.trajeto = %(cod)s
  AND tp.latitude IS NOT NULL AND tp.longitude IS NOT NULL
  AND tp.latitude <> 0 AND tp.longitude <> 0
ORDER BY tp.sequencia
"""


def _km(a_lat, a_lng, b_lat, b_lng) -> float:
    """Haversine entre dois pontos. Aqui ela é legítima: mede o COMPRIMENTO de
    um segmento da poligonal, não a distância que falta de estrada."""
    la1, lo1, la2, lo2 = (math.radians(v) for v in (a_lat, a_lng, b_lat, b_lng))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def obter(chaves: dict, cidade_destino: str = "") -> dict | None:
    """A rota da carga, com os pontos. `None` quando nao ha.

    `chaves` sao as do conhecimento (g, e, f, n, s). `cidade_destino` desempata
    quando o CT-e cobre mais de uma coleta.
    """
    try:
        cands = [dict(r) for r in db.query(ROTA_SQL, chaves)]
    except Exception as exc:  # noqa: BLE001
        log.warning("rastreio: rota falhou: %s", type(exc).__name__)
        return None
    if not cands:
        return None

    alvo = (cidade_destino or "").strip().upper()
    escolhida = next((c for c in cands if alvo and c["destino_rota"] == alvo),
                     cands[0])
    try:
        pts = [dict(x) for x in db.query(PONTOS_SQL,
                                         {"cod": escolhida["codigo"]})]
    except Exception:  # noqa: BLE001
        return None
    if len(pts) < 2:
        # UM PONTO SO nao e rota: e um endereco. Devolver isso faria a tela
        # desenhar uma linha de tamanho zero e um progresso sem denominador.
        return None
    return {"codigo": escolhida["codigo"],
            "descricao": escolhida.get("descricao"),
            "extensao_km": escolhida.get("extensao"),
            "pontos": pts,
            "candidatas": len(cands)}


def _projetar(px, py, ax, ay, bx, by) -> tuple[float, float, float]:
    """Ponto mais próximo de P no segmento AB. Devolve (x, y, t) com t em 0..1.

    Trabalha em graus como se fossem plano cartesiano. Numa escala de dezenas
    de quilômetros o erro disso é pequeno perto da imprecisão da própria
    poligonal — que tem, em metade das rotas, dois pontos para trezentos km.
    """
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ax, ay, 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ax + t * dx, ay + t * dy, t


def progresso(rota: dict, lat: float, lng: float) -> dict | None:
    """Onde o veículo está ao longo da rota.

    Devolve a fração percorrida, o km rodoviário já feito e o que falta — os
    dois em cima da `extensao` real, nunca da reta.
    """
    pts = rota.get("pontos") or []
    if len(pts) < 2:
        return None

    # comprimento de cada segmento e o total da poligonal
    segs = []
    total_poli = 0.0
    for i in range(len(pts) - 1):
        d = _km(pts[i]["lat"], pts[i]["lng"], pts[i+1]["lat"], pts[i+1]["lng"])
        segs.append(d)
        total_poli += d
    if total_poli <= 0:
        return None

    # o segmento mais próximo do veículo, e o quanto da poligonal ficou para trás
    melhor = None
    acumulado = 0.0
    for i, d in enumerate(segs):
        a, b = pts[i], pts[i+1]
        x, y, t = _projetar(lat, lng, a["lat"], a["lng"], b["lat"], b["lng"])
        dist = _km(lat, lng, x, y)
        if melhor is None or dist < melhor["afastado_km"]:
            melhor = {"i": i, "t": t, "afastado_km": dist,
                      "ate_aqui": acumulado + d * t}
        acumulado += d

    fracao = max(0.0, min(1.0, melhor["ate_aqui"] / total_poli))
    ext = rota.get("extensao_km") or 0.0
    fora = {
        "fracao": fracao,
        "progresso_pct": int(round(fracao * 100)),
        # AFASTAMENTO DA ROTA: o quanto o veículo está longe da linha. É o que
        # distingue "está na rota, no meio dela" de "está em outra viagem" —
        # e é uma medida melhor que a comparação de distâncias que ela
        # substitui, porque não depende de o destino estar à frente.
        "afastado_km": round(melhor["afastado_km"], 1),
        "rodovia": (pts[melhor["i"]].get("rodovia") or "").strip() or None,
    }
    if ext > 0:
        fora["rota_km"] = round(ext, 0)
        fora["percorrido_km"] = round(ext * fracao, 0)
        fora["falta_km"] = round(ext * (1 - fracao), 0)
    return fora
