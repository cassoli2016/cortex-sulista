# -*- coding: utf-8 -*-
"""O relógio dos avisos do app do motorista — o mesmo desenho do Radar e do
aviso de carga: thread daemon, laço que nunca levanta, arranque idempotente, só
no processo LÍDER e NUNCA sob pytest.

DUAS CADÊNCIAS NUM LAÇO SÓ:
- a ENTREGA (`avisos.despachar`) a cada minuto: o recado do RH e o do mural
  nascem na hora, e o push tem de sair logo — mas pela thread, e não pela
  rota do RH, que não pode ficar esperando oitenta pushes para responder;
- a VARREDURA (`avisos.varrer`) a cada dez minutos: multa, registro e viagem
  não passam por código nosso, e a consulta ao ERP é da frota inteira.

Sob pytest ela NUNCA sobe: a varredura lê o ERP de produção e ESCREVE no
banco, e a entrega manda notificação REAL para o celular de motorista — a mesma
porta pela qual a suíte já quase mandou WhatsApp para cliente.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from ..sob_teste import sob_teste

log = logging.getLogger("cortex.motorista.agendador")

CICLO_S = 60
VARREDURA_S = 600
#: A API acabou de subir (muitas vezes por um deploy): não disputa o arranque.
ATRASO_INICIAL_S = 90

_iniciado = False


def _dorme(seg: float) -> None:
    time.sleep(seg)


def _laco() -> None:
    from . import avisos
    _dorme(ATRASO_INICIAL_S)
    ultima = 0.0
    while True:
        try:
            if time.monotonic() - ultima >= VARREDURA_S:
                ultima = time.monotonic()
                r = avisos.varrer()
                novos = sum(v.get("novos", 0) for v in r.values())
                if novos:
                    log.info("avisos do motorista: %d novo(s) na varredura", novos)
            d = avisos.despachar()
            if d.get("enviados"):
                log.info("avisos do motorista: %d push(es) entregue(s)", d["enviados"])
        except Exception as exc:  # noqa: BLE001
            log.warning("avisos do motorista: ciclo falhou: %s", type(exc).__name__)
        _dorme(CICLO_S)


def desligado() -> bool:
    """`MOTORISTA_AVISOS=0` no `.env` desliga o relógio (bancada sem ERP)."""
    return os.environ.get("MOTORISTA_AVISOS", "").strip().lower() in (
        "0", "nao", "não", "off", "false")


def iniciar() -> None:
    """Sobe a thread dos avisos. Idempotente."""
    global _iniciado
    if _iniciado:
        return
    if sob_teste():
        log.info("avisos do motorista: rodada de teste — relogio nao iniciado")
        return
    if desligado():
        log.info("avisos do motorista: MOTORISTA_AVISOS desligado no .env")
        return
    _iniciado = True
    threading.Thread(target=_laco, daemon=True, name="motorista-avisos").start()
    log.info("relogio dos avisos do motorista iniciado")
