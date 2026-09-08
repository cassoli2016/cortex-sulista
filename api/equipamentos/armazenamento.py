# -*- coding: utf-8 -*-
"""As quatro tabelas do cadastro no banco da casa.

Módulo PURO sobre o banco: nada aqui fala com o ERP nem com a Smartec. É a
separação que permite testar a consolidação — que é a regra difícil — sem rede
nenhuma e sem o AVA no ar.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal

from .. import pglocal

log = logging.getLogger("cortex.equipamentos")

# Redirecionado pelos testes para o schema descartável (fixture `esquema_pg`).
# Um ponto só para esquecer — e esquecer aqui escreve em PRODUÇÃO. Foi assim
# que uma sabotagem de guard apagou 219 registros reais de `rntrc_transportador`.
ESQUEMA: str | None = None


def _esq() -> str | None:
    return ESQUEMA


def _json_pronto(valor):
    """Decimal e date não sobrevivem ao `json.dumps` — convertem AQUI.

    Serialização converte no LIMITE do módulo. Deixar para o `JSONResponse` faz
    o estouro acontecer no `render()`, DEPOIS do try/except da rota: 500 em
    text/plain, sem pista de qual campo.
    """
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json_pronto(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json_pronto(v) for v in valor]
    return valor


# ────────────────────────────────────────────────────────────────── as fontes

def gravar_fonte(placa: str, fonte: str, campos: dict,
                 payload: dict | None = None) -> None:
    """O que uma fonte disse sobre uma placa. Idempotente por (placa, fonte).

    `ON CONFLICT DO UPDATE` sobre a chave natural: reconsultar a mesma placa
    ATUALIZA, nunca duplica. Coleta que duplica faz a segunda passada dobrar a
    tabela, e o total inflado é plausível — que é o pior tipo de erro.
    """
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO eqp_fonte (placa, fonte, campos, payload, visto_em)"
            " VALUES (%s, %s, %s, %s, now())"
            " ON CONFLICT (placa, fonte) DO UPDATE"
            "    SET campos = EXCLUDED.campos,"
            "        payload = EXCLUDED.payload,"
            "        visto_em = EXCLUDED.visto_em",
            (placa, fonte, json.dumps(_json_pronto(campos), ensure_ascii=False),
             json.dumps(_json_pronto(payload), ensure_ascii=False)
             if payload is not None else None))


def gravar_fontes(fonte: str, linhas: list[dict]) -> int:
    """Grava uma fonte inteira de uma vez (é como o ERP entra: ~2.000 placas).

    Uma transação só. Meia carga gravada seria pior que nenhuma: a
    consolidação seguinte misturaria placas de duas leituras diferentes do
    ERP, e nada apontaria para isso.
    """
    if not linhas:
        return 0
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO eqp_fonte (placa, fonte, campos, payload, visto_em)"
            " VALUES (%s, %s, %s, %s, now())"
            " ON CONFLICT (placa, fonte) DO UPDATE"
            "    SET campos = EXCLUDED.campos,"
            "        payload = EXCLUDED.payload,"
            "        visto_em = EXCLUDED.visto_em",
            [(l["placa"], fonte,
              json.dumps(_json_pronto(l.get("campos") or {}), ensure_ascii=False),
              json.dumps(_json_pronto(l.get("payload")), ensure_ascii=False)
              if l.get("payload") is not None else None)
             for l in linhas])
    return len(linhas)


def fontes_da_placa(placa: str) -> dict[str, dict]:
    """`{fonte: {campos, payload, visto_em}}` de uma placa."""
    linhas = pglocal.query(
        "SELECT fonte, campos, payload, visto_em FROM eqp_fonte"
        " WHERE placa = %s", (placa,), esquema=_esq())
    return {r["fonte"]: {"campos": r["campos"] or {},
                         "payload": r["payload"],
                         "visto_em": r["visto_em"]} for r in linhas}


def todas_as_fontes() -> dict[str, dict[str, dict]]:
    """Tudo, agrupado por placa. É o que a consolidação em massa lê.

    Carrega a tabela inteira de propósito: ~2.000 placas × até 6 fontes é
    pequeno, e a alternativa (uma consulta por placa) faria 12.000 idas ao
    banco para reconstruir um cadastro que cabe folgado na memória.
    """
    fora: dict[str, dict[str, dict]] = {}
    for r in pglocal.query(
            "SELECT placa, fonte, campos, visto_em FROM eqp_fonte",
            esquema=_esq()):
        fora.setdefault(r["placa"], {})[r["fonte"]] = {
            "campos": r["campos"] or {}, "visto_em": r["visto_em"]}
    return fora


# ────────────────────────────────────────────────────────────────── a edição

def gravar_edicao(placa: str, campo: str, valor: str | None,
                  autor: str, motivo: str | None = None) -> None:
    """Correção à mão. Vence toda fonte automática na consolidação."""
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO eqp_edicao (placa, campo, valor, motivo, autor)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (placa, campo) DO UPDATE"
            "    SET valor = EXCLUDED.valor, motivo = EXCLUDED.motivo,"
            "        autor = EXCLUDED.autor, criado_em = now()",
            (placa, campo, valor, motivo, autor))


def apagar_edicao(placa: str, campo: str) -> None:
    """Desfaz a correção — o campo volta a seguir as fontes automáticas.

    Existe porque correção errada precisa de volta atrás, e a volta atrás não
    é "escrever o valor antigo à mão": isso deixaria o campo preso à mão para
    sempre, e a próxima coleta boa não o alcançaria mais.
    """
    with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM eqp_edicao WHERE placa = %s AND campo = %s",
                    (placa, campo))


def edicoes() -> dict[str, dict[str, str]]:
    fora: dict[str, dict[str, str]] = {}
    for r in pglocal.query("SELECT placa, campo, valor FROM eqp_edicao",
                           esquema=_esq()):
        fora.setdefault(r["placa"], {})[r["campo"]] = r["valor"]
    return fora


def edicoes_da_placa(placa: str) -> list[dict]:
    return pglocal.query(
        "SELECT campo, valor, motivo, autor, criado_em FROM eqp_edicao"
        " WHERE placa = %s ORDER BY campo", (placa,), esquema=_esq())


def auditar(usuario: str | None, acao: str, alvo: str = "",
            detalhe: str = "") -> None:
    """Toda escrita entra no `audit_log` — a trilha da casa, append-only.

    Falha de auditoria NÃO derruba a ação que já aconteceu: a coleta gastou a
    consulta, o cadastro mudou, e um erro aqui transformaria um trabalho feito
    em erro 500 para quem pediu. Mas ela é REGISTRADA no log do processo, para
    que "a trilha está incompleta" tenha sintoma em algum lugar.
    """
    from .. import auth
    try:
        with pglocal.get_conn(_esq()) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip)"
                " VALUES(%s, %s, %s, %s, %s, %s)",
                (auth._agora(), usuario or "", acao, alvo, detalhe, ""))
    except Exception as exc:  # noqa: BLE001
        log.warning("auditoria de %s nao gravada: %s", acao,
                    type(exc).__name__)
