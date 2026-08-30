"""Coordenada de um destino que o ERP não tem.

O PROBLEMA MEDIDO
=================
13 das 70 viagens em trânsito não têm `coleta.latitudedestino` preenchido, e
sem coordenada não há rota — elas ficavam sem ETA nenhum. São **10 cidades
distintas**: JOINVILLE/SC (3 viagens), PIRAQUARA/PR (2) e mais oito com uma
cada.

Geocodificar dez cidades custa dez chamadas UMA VEZ. As mesmas cidades se
repetem viagem após viagem, então o custo recorrente é zero — por isso o cache
é PERMANENTE, sem TTL: cidade não se move. O que envelhece numa geocodificação
é a precisão de um ENDEREÇO, e aqui a consulta é "CIDADE/UF".

O QUE ISTO NÃO É
================
**Não é o ponto de entrega.** É o centro da cidade, e num município grande a
diferença até a doca chega a vinte minutos. Por isso quem usa recebe
`aproximado=True` e a tela DIZ — um ETA aproximado apresentado como exato é
pior que ETA nenhum, porque quem lê decide em cima dele.

E não substitui o cadastro: a coordenada de verdade continua sendo a do ERP,
que é o que o campo `latitudedestino` existe para guardar. Isto é a ponte
enquanto ela falta.
"""
from __future__ import annotations

import logging
import re

from api import pglocal
from api.tomtom import cliente, coleta

log = logging.getLogger(__name__)

ESQUEMA: str | None = None       # os testes redirecionam


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


def normalizar(lugar: str) -> str:
    """MAIÚSCULA e sem espaço duplo.

    O ERP devolve rótulo com espaço duplo ("1 - FIL  MTZ" é o caso conhecido),
    e sem normalizar a mesma cidade viraria duas linhas de cache — medindo
    formato de digitação em vez de lugar.
    """
    return " ".join((lugar or "").upper().split())


def _guardado(chave: str, esquema=None) -> dict | None:
    r = pglocal.um("SELECT lat, lon, achou, rotulo FROM tt_geocode "
                   "WHERE consulta = %s", (chave,), esquema=_esq(esquema))
    return dict(r) if r else None


def coordenada(lugar: str, *, esquema=None) -> dict | None:
    """`{"lat","lon","rotulo","aproximado":True}` ou `None`.

    NUNCA levanta: um destino que não resolve não pode derrubar a varredura
    das outras 56 viagens.
    """
    chave = normalizar(lugar)
    if not chave or "/" not in chave:
        return None
    try:
        g = _guardado(chave, esquema)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache de geocode indisponível: %s", type(exc).__name__)
        g = None
    if g is not None:
        # `achou = False` guardado é resposta: não consulta de novo para
        # receber o mesmo "não sei" e gastar a mesma cota.
        if not g["achou"]:
            return None
        return {"lat": g["lat"], "lon": g["lon"], "rotulo": g["rotulo"],
                "aproximado": True}

    cidade, _, uf = chave.partition("/")
    try:
        d = cliente.geocodificar(cidade.strip(), uf.strip())
    except cliente.TomTomNaoConfigurado:
        return None
    except cliente.TomTomIndisponivel as exc:
        log.warning("geocode de %s falhou: %s", chave, exc)
        return None
    finally:
        coleta.registrar("geocode", n=1)

    achou = bool(d)
    try:
        pglocal.executar(
            "INSERT INTO tt_geocode (consulta, lat, lon, achou, rotulo) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (consulta) DO UPDATE "
            "SET lat=EXCLUDED.lat, lon=EXCLUDED.lon, achou=EXCLUDED.achou, "
            "    rotulo=EXCLUDED.rotulo, obtido_em=now()",
            (chave, d["lat"] if achou else None, d["lon"] if achou else None,
             achou, d["rotulo"] if achou else None), esquema=_esq(esquema))
    except Exception as exc:  # noqa: BLE001
        log.warning("não consegui gravar o geocode de %s: %s",
                    chave, type(exc).__name__)
    return {**d, "aproximado": True} if achou else None


def cacheadas(esquema=None) -> list[dict]:
    """O que já está resolvido — para a tela poder dizer quantos destinos
    dependem de aproximação, e quais o fornecedor não resolveu."""
    try:
        return [dict(r) for r in pglocal.query(
            "SELECT consulta, lat, lon, achou, rotulo, "
            "       to_char(obtido_em,'YYYY-MM-DD HH24:MI') AS obtido_em "
            "  FROM tt_geocode ORDER BY consulta", esquema=_esq(esquema))]
    except Exception:  # noqa: BLE001
        return []
