# -*- coding: utf-8 -*-
"""Coleta das batidas — idempotente, por cursor, e SEM guardar o trajeto.

A DECISÃO CENTRAL DESTE MÓDULO
==============================
O cliente recebe a coordenada de cada batida. Esta camada a USA e a DESCARTA:
calcula a distância até a cerca mais próxima, grava o escalar, e joga fora
latitude e longitude.

A cerca precisa responder "caiu na unidade?" — e para isso o veredito mais a
distância bastam. A coordenada crua responderia muito mais: por onde a pessoa
andou, a que horas, em que dias. Isso é histórico de deslocamento de
trabalhador, que a empresa não precisa manter para operar a cerca.

E o que se perde? Nada do que originou esta frente: com a distância ainda se
recalibra raio — que é o achado, os raios cadastrados estão apertados
(PIRAQUARA com 40 m onde o p95 real é 87 m) — sem reconstruir trajeto nenhum.

AS TRÊS REGRAS DO CURSOR, MEDIDAS CONTRA O SERVIÇO REAL
=======================================================
1. **Não parte de zero.** `ultIdImportado=0` devolve lista VAZIA, não o
   histórico. `semear()` faz a primeira carga por PERÍODO e grava o maior id
   visto; só a partir daí o cursor anda.
2. **A página tem teto de 1.000.** Quem parar na primeira perde o resto em
   silêncio, e o cursor avança mesmo assim — o buraco não volta.
3. **O cursor só anda com marcação NA MÃO.** Se a página vier vazia ou a
   gravação falhar, ele fica onde está: coleta que avança o ponteiro sem ter
   consumido nada perde o intervalo para sempre.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from api import pglocal

from . import cliente

log = logging.getLogger(__name__)

#: Esquema alvo. O teste troca por um descartável; produção usa o padrão.
ESQUEMA: str | None = None

#: A coleta tem uma fila só — o cursor é global, não por filial: o `id` do
#: fornecedor é único em toda a conta.
CHAVE = "marcacoes"

#: Teto de páginas por execução. 1.000 marcações por página, e a casa toda faz
#: ~900 batidas por semana: 20 páginas cobrem meses de atraso sem prender a
#: tarefa por horas se algo tiver ficado para trás.
MAX_PAGINAS = 20


def _esq() -> str | None:
    return ESQUEMA


def _agora() -> datetime:
    return datetime.now(timezone.utc)


# ── geometria ───────────────────────────────────────────────────────────────
def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Metros."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def cerca_mais_proxima(lat: float, lon: float,
                       cercas: list[dict]) -> tuple[str | None, float | None]:
    """Nome e distância da cerca mais próxima.

    POLÍGONO É MEDIDO PELO VÉRTICE, e isso é uma aproximação declarada: a
    distância real seria até a ARESTA, e para um ponto dentro da área ela é
    zero. Aqui o número serve para ORDENAR e para calibrar raio, não para
    decidir dentro/fora — quem decide isso é o fornecedor, que conhece a forma
    inteira. Medir a aresta daria precisão que ninguém usa.
    """
    melhor, dist = None, None
    for c in cercas:
        d = distancia_m(lat, lon, float(c["lat"]), float(c["lon"]))
        if dist is None or d < dist:
            melhor, dist = c["nome"], d
    return melhor, dist


# ── cercas ──────────────────────────────────────────────────────────────────
def sincronizar_cercas() -> dict:
    """Espelha as cercas do fornecedor. Idempotente pela chave natural."""
    cercas = cliente.cercas()
    if not cercas:
        # Coleta vazia NUNCA vira snapshot completo: apagar o espelho porque o
        # fornecedor respondeu vazio deixaria a casa sem cerca nenhuma.
        log.warning("ponto certificado: ListarCercas devolveu vazio; espelho intacto")
        return {"lidas": 0, "gravadas": 0}
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        for c in cercas:
            cur.execute(
                """INSERT INTO pc_cerca (id_local, id_cerca, nome, descricao, endereco,
                                         forma, raio_m, lat, lon, ativa, local_ativo,
                                         atualizada_em)
                        VALUES (%(id_local)s, %(id_cerca)s, %(nome)s, %(descricao)s,
                                %(endereco)s, %(forma)s, %(raio_m)s, %(lat)s, %(lon)s,
                                %(ativa)s, %(local_ativo)s, now())
                   ON CONFLICT (id_local) DO UPDATE SET
                        id_cerca = EXCLUDED.id_cerca, nome = EXCLUDED.nome,
                        descricao = EXCLUDED.descricao, endereco = EXCLUDED.endereco,
                        forma = EXCLUDED.forma, raio_m = EXCLUDED.raio_m,
                        lat = EXCLUDED.lat, lon = EXCLUDED.lon,
                        ativa = EXCLUDED.ativa, local_ativo = EXCLUDED.local_ativo,
                        atualizada_em = now()""", c)
    return {"lidas": len(cercas), "gravadas": len(cercas)}


def cercas_do_espelho() -> list[dict]:
    try:
        return pglocal.query(
            "SELECT nome, lat, lon, forma, raio_m, ativa FROM pc_cerca",
            esquema=_esq())
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return []
        raise


# ── marcações ───────────────────────────────────────────────────────────────
def _gravar(marcacoes: list[dict], cercas: list[dict]) -> int:
    """Grava as marcações SEM a coordenada. Devolve quantas entraram."""
    if not marcacoes:
        return 0
    linhas = []
    for m in marcacoes:
        perto, dist = (None, None)
        if m.get("lat") is not None and m.get("lon") is not None and cercas:
            perto, dist = cerca_mais_proxima(m["lat"], m["lon"], cercas)
        linhas.append({
            "id": m["id"], "nsr": m["nsr"], "matricula": m["matricula"] or "?",
            "marcada_em": m["marcada_em"], "inserida_em": m["inserida_em"],
            "latencia_s": m["latencia_s"], "atividade": m["atividade"],
            "relogio": m["relogio"], "situacao": m["situacao"],
            "local": m["local"] or m["local_descricao"], "id_local": m["id_local"],
            # AQUI a coordenada morre: vira um escalar e não é gravada.
            "distancia_m": int(round(dist)) if dist is not None else None,
            "cerca_proxima": perto,
        })
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO pc_marcacao (id, nsr, matricula, marcada_em, inserida_em,
                                        latencia_s, atividade, relogio, situacao,
                                        local, id_local, distancia_m, cerca_proxima)
                    VALUES (%(id)s, %(nsr)s, %(matricula)s, %(marcada_em)s,
                            %(inserida_em)s, %(latencia_s)s, %(atividade)s, %(relogio)s,
                            %(situacao)s, %(local)s, %(id_local)s, %(distancia_m)s,
                            %(cerca_proxima)s)
               ON CONFLICT (id) DO UPDATE SET
                    situacao = EXCLUDED.situacao, local = EXCLUDED.local,
                    distancia_m = EXCLUDED.distancia_m,
                    cerca_proxima = EXCLUDED.cerca_proxima""", linhas)
    return len(linhas)


def cursor() -> dict | None:
    try:
        return pglocal.um("SELECT * FROM pc_cursor WHERE chave = %s", (CHAVE,),
                          esquema=_esq())
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return None
        raise


def _mover_cursor(ultimo_id: int, quantas: int, erro: str | None = None) -> None:
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO pc_cursor (chave, ultimo_id, marcacoes, atualizado_em,
                                      ultima_coleta_em, ultimo_erro)
                    VALUES (%s, %s, %s, now(), now(), %s)
               ON CONFLICT (chave) DO UPDATE SET
                    ultimo_id = GREATEST(pc_cursor.ultimo_id, EXCLUDED.ultimo_id),
                    marcacoes = pc_cursor.marcacoes + EXCLUDED.marcacoes,
                    atualizado_em = now(), ultima_coleta_em = now(),
                    ultimo_erro = EXCLUDED.ultimo_erro""",
            (CHAVE, int(ultimo_id), int(quantas), erro))


def semear(inicio: str, fim: str) -> dict:
    """Primeira carga, POR PERÍODO — o cursor não parte de zero.

    Datas em DD/MM/AAAA, o formato do fornecedor.
    """
    if cursor():
        return {"semeado": False, "motivo": "o cursor já existe"}
    cercas = cliente.cercas()
    if cercas:
        sincronizar_cercas()
    marc = cliente.marcacoes_por_periodo(inicio, fim)
    if not marc:
        return {"semeado": False, "motivo": "o período não devolveu marcação"}
    n = _gravar(marc, cercas)
    maior = max(m["id"] for m in marc)
    _mover_cursor(maior, n)
    return {"semeado": True, "marcacoes": n, "ultimo_id": maior,
            "de": inicio, "ate": fim}


def coletar(max_paginas: int = MAX_PAGINAS) -> dict:
    """Do cursor para a frente, página a página.

    O PONTEIRO SÓ ANDA COM MARCAÇÃO NA MÃO — e só depois de gravar. Avançar
    antes de gravar perde o intervalo para sempre, porque não há como pedir a
    mesma faixa de volta (o cursor é de mão única).
    """
    c = cursor()
    if not c:
        return {"ok": False, "motivo": "sem cursor: rode semear() primeiro",
                "marcacoes": 0}
    cercas = cercas_do_espelho() or cliente.cercas()
    ultimo, total, paginas = int(c["ultimo_id"]), 0, 0
    try:
        while paginas < max_paginas:
            lote = cliente.marcacoes_desde(ultimo)
            paginas += 1
            if not lote:
                break
            n = _gravar(lote, cercas)
            maior = max(m["id"] for m in lote)
            _mover_cursor(maior, n)
            total += n
            ultimo = maior
            # Página não cheia = chegamos ao fim da fila.
            if len(lote) < cliente.PAGINA:
                break
    except Exception as exc:  # noqa: BLE001
        # O que já entrou, entrou: o cursor está no ponto certo e a próxima
        # execução continua daqui. O erro é registrado, não engolido.
        _mover_cursor(ultimo, 0, cliente._limpar(f"{type(exc).__name__}"))
        log.warning("ponto certificado: coleta parou em %s: %s",
                    ultimo, type(exc).__name__)
        return {"ok": False, "marcacoes": total, "paginas": paginas,
                "ultimo_id": ultimo, "erro": type(exc).__name__}
    return {"ok": True, "marcacoes": total, "paginas": paginas, "ultimo_id": ultimo}


# ── o que a Saúde e a tela perguntam ────────────────────────────────────────
def estado() -> dict:
    """Nunca levanta: alimenta cartão, e cartão que explode leva os outros."""
    d = {"configurado": cliente.configurado(), "cursor": None,
         "ultima_batida": None, "por_situacao": {}, "cercas": 0}
    try:
        c = cursor()
        if c:
            d["cursor"] = {
                "ultimo_id": int(c["ultimo_id"]), "marcacoes": int(c["marcacoes"]),
                "ultima_coleta_em": c["ultima_coleta_em"].isoformat()
                                    if c["ultima_coleta_em"] else None,
                "ultimo_erro": c["ultimo_erro"]}
        r = pglocal.query(
            """SELECT situacao, COUNT(*) n, MAX(marcada_em) ultima
                 FROM pc_marcacao WHERE marcada_em >= now() - INTERVAL '30 days'
                GROUP BY situacao""", esquema=_esq())
        d["por_situacao"] = {x["situacao"]: int(x["n"]) for x in r}
        ultimas = [x["ultima"] for x in r if x["ultima"]]
        d["ultima_batida"] = max(ultimas).isoformat() if ultimas else None
        d["cercas"] = len(cercas_do_espelho())
    except Exception as exc:  # noqa: BLE001
        if not pglocal.sem_tabela(exc):
            log.warning("ponto certificado: estado: %s", type(exc).__name__)
    return d
