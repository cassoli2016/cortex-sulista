# -*- coding: utf-8 -*-
"""Coleta do RasterIntegra — o consolidado de risco por viagem e o km diário.

POR QUE A COLETA É POR PLACA (medido em 01/09/2026, ao vivo)
============================================================
O único filtro que o servidor respeita de verdade é ``Placa`` — com ele as
datas também passam a morder (recortam o FIM REAL das finalizadas; as
abertas da placa vêm junto e são descartadas aqui). O resto do manual não
sobrevive ao contato com o servidor:

- ``StatusViagem`` é ignorado em toda combinação;
- datas SEM placa devolvem um lote antigo de viagens nunca finalizadas;
- o modo cursor (sem filtro nenhum) está TRAVADO num backlog de mar/2025 —
  devolveu o mesmo lote duas vezes seguidas, sem avançar.

Quem escolhe as placas é o ERP: as que têm viagem com vínculo de GR
encerrada nos últimos dias. ~80 placas/dia a 15 s por chamada ≈ 20 min de
madrugada — e 15 s respeita o rate-limit (o CodErro 102 do fornecedor pede
30 s no getPosicoes; aqui 20 s passou limpo na bateria de testes).

COLETA VAZIA NUNCA VIRA SNAPSHOT COMPLETO: cada rodada registra em
``gr_carga`` o que consultou e o que gravou; a falha interrompe e fica
escrita com o erro — a Saúde mede o frescor DALI.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from . import armazenamento as arm
from . import cliente

log = logging.getLogger(__name__)

PAUSA_ENTRE_CHAMADAS = 15.0   # segundos; 20 s passou sem CodErro 102
JANELA_VIAGENS_DIAS = 8       # fim real que a chamada por placa recorta
ERP_CHEGADA_DIAS = 2          # placas com viagem GR encerrada há até N dias


def _agora() -> datetime:
    return datetime.now()


def placas_alvo(dias: int = ERP_CHEGADA_DIAS) -> list[str]:
    """Placas com viagem GR-vinculada encerrada recente, segundo o ERP."""
    from api import db
    sql = """
      SELECT DISTINCT p.veiculo AS placa
      FROM programacaoembarque p
      WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
        AND p.dtchegada >= current_date - %(dias)s
        AND p.veiculo IS NOT NULL AND trim(p.veiculo) <> ''
        AND EXISTS (SELECT 1 FROM programacaoembarque_gerenciadorarisco gr
                    WHERE gr.grupo = p.grupo AND gr.empresa = p.empresa
                      AND gr.diferenciadornumero = p.diferenciadornumero
                      AND gr.numero = p.numero)
      ORDER BY 1"""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, {"dias": dias})
        return [arm.placa_norm(r["placa"]) for r in cur.fetchall()]


def placas_backfill(meses: int = 12) -> list[str]:
    """Todas as placas com vínculo de GR na janela longa (para o backfill)."""
    from api import db
    sql = """
      SELECT DISTINCT p.veiculo AS placa
      FROM programacaoembarque p
      WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
        AND p.dtsaida >= current_date - %(dias)s
        AND p.veiculo IS NOT NULL AND trim(p.veiculo) <> ''
        AND EXISTS (SELECT 1 FROM programacaoembarque_gerenciadorarisco gr
                    WHERE gr.grupo = p.grupo AND gr.empresa = p.empresa
                      AND gr.diferenciadornumero = p.diferenciadornumero
                      AND gr.numero = p.numero)
      ORDER BY 1"""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, {"dias": meses * 31})
        return [arm.placa_norm(r["placa"]) for r in cur.fetchall()]


def _chamar_com_paciencia(metodo: str, corpo: dict) -> dict:
    """Uma chamada; se o fornecedor pedir calma (rate-limit), espera e repete
    UMA vez. Qualquer outra falha sobe — melhor coleta interrompida e dita
    do que meia coleta silenciosa."""
    try:
        return cliente.chamar(metodo, corpo)
    except cliente.RasterIntegraIndisponivel as exc:
        if "102" not in str(exc):
            raise
        log.warning("rasterintegra pediu calma (102); esperando 31s")
        time.sleep(31)
        return cliente.chamar(metodo, corpo)


def coletar_viagens(placas: list[str] | None = None,
                    janela_dias: int = JANELA_VIAGENS_DIAS,
                    pausa: float = PAUSA_ENTRE_CHAMADAS,
                    esquema: str | None = None) -> dict:
    """Consolidado de risco (getEventoFimViagem) por placa. Só grava as F."""
    inicio = _agora()
    if placas is None:
        placas = placas_alvo()
    hoje = date.today()
    corpo_base = {
        "DataInicial": (hoje - timedelta(days=janela_dias)).strftime("%Y-%m-%d"),
        "DataFinal": hoje.strftime("%Y-%m-%d"),
    }
    janela = f"{corpo_base['DataInicial']}..{corpo_base['DataFinal']}"
    consultas = gravadas = 0
    try:
        for i, placa in enumerate(placas):
            if i and pausa:
                time.sleep(pausa)
            d = _chamar_com_paciencia(
                "getEventoFimViagem", {"Placa": placa, **corpo_base})
            consultas += 1
            gravadas += arm.upsert_viagens(d.get("Viagens") or [], esquema)
    except Exception as exc:  # noqa: BLE001 — a trilha guarda o tipo, sem URL
        arm.registrar_carga("viagens", inicio, janela, consultas, gravadas,
                            f"{type(exc).__name__}: {str(exc)[:300]}", esquema)
        raise
    arm.registrar_carga("viagens", inicio, janela, consultas, gravadas,
                        None, esquema)
    log.info("gr viagens: %s placas, %s finalizadas gravadas", consultas, gravadas)
    return {"placas": consultas, "gravadas": gravadas, "janela": janela}


def coletar_km(dias: tuple[int, ...] = (1, 2), pausa: float = PAUSA_ENTRE_CHAMADAS,
               esquema: str | None = None) -> dict:
    """km com/sem viagem por veículo (getKMRodado): D-1 e D-2 — o D-2 cura
    o que chegou atrasado na Raster."""
    inicio = _agora()
    hoje = date.today()
    consultas = gravadas = 0
    janela = ",".join(f"D-{n}" for n in dias)
    try:
        for i, n in enumerate(dias):
            if i and pausa:
                time.sleep(pausa)
            dia = hoje - timedelta(days=n)
            d = _chamar_com_paciencia(
                "getKMRodado", {"Data": dia.strftime("%Y-%m-%d")})
            consultas += 1
            gravadas += arm.upsert_km(dia, d.get("KMRodado") or [], esquema)
    except Exception as exc:  # noqa: BLE001
        arm.registrar_carga("km", inicio, janela, consultas, gravadas,
                            f"{type(exc).__name__}: {str(exc)[:300]}", esquema)
        raise
    arm.registrar_carga("km", inicio, janela, consultas, gravadas, None, esquema)
    log.info("gr km: %s dias, %s linhas", consultas, gravadas)
    return {"dias": consultas, "gravadas": gravadas, "janela": janela}


def backfill_viagens(meses: int = 12, pausa: float = PAUSA_ENTRE_CHAMADAS,
                     esquema: str | None = None) -> dict:
    """Histórico: uma chamada POR PLACA sem janela traz até 12 meses (teto de
    500 por chamada — placa muito rodada perde o rabo mais antigo, e tudo
    bem: o objetivo é tendência, não arqueologia)."""
    inicio = _agora()
    placas = placas_backfill(meses)
    consultas = gravadas = 0
    try:
        for i, placa in enumerate(placas):
            if i and pausa:
                time.sleep(pausa)
            d = _chamar_com_paciencia("getEventoFimViagem", {"Placa": placa})
            consultas += 1
            gravadas += arm.upsert_viagens(d.get("Viagens") or [], esquema)
    except Exception as exc:  # noqa: BLE001
        arm.registrar_carga("viagens", inicio, f"backfill {meses}m",
                            consultas, gravadas,
                            f"{type(exc).__name__}: {str(exc)[:300]}", esquema)
        raise
    arm.registrar_carga("viagens", inicio, f"backfill {meses}m",
                        consultas, gravadas, None, esquema)
    log.info("gr backfill: %s placas, %s finalizadas", consultas, gravadas)
    return {"placas": consultas, "gravadas": gravadas}
