# -*- coding: utf-8 -*-
"""O relógio da coleta do Radar, dentro da API — o mesmo desenho do aviso de
carga (`api/rastreio/agendador.py`): thread daemon, laço que nunca levanta,
arranque idempotente, só no processo LÍDER e NUNCA sob pytest.

Aqui não há mensagem saindo para ninguém, mas a regra vale igual: uma rodada
de testes com esta thread viva baixaria quatro sites de terceiro a cada dez
minutos e ESCREVERIA no schema de produção — a mesma porta pela qual a suíte
já gravou onde não devia três vezes nesta casa.

POR QUE NÃO UMA TAREFA DO WINDOWS: tarefa agendada nova exige alguém instalar
elevado nesta máquina, e o censo delas é enganoso (`Get-ScheduledTask` sem
elevação esconde as que rodam como SISTEMA). A API é uma das tarefas que
EXISTEM de verdade e sobe no boot.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from ..sob_teste import sob_teste  # noqa: E402

log = logging.getLogger("cortex.radar.agendador")

#: De quanto em quanto tempo o laço acorda. Quem decide se uma fonte é
#: buscada é a CADÊNCIA dela (`coleta.CADENCIA_S`), lida do banco — acordar
#: sem nada vencido custa uma consulta ao banco local.
CICLO_S = 600

#: Folga antes do primeiro ciclo: a API acabou de subir (muitas vezes por um
#: deploy) e não precisa disputar o arranque com um download de 1,8 MB.
ATRASO_INICIAL_S = 60

_iniciado = False


def _dorme(seg: float) -> None:
    time.sleep(seg)


def _um_ciclo() -> dict | None:
    """Uma passada. NUNCA levanta — thread que morre por exceção some do radar,
    e o sintoma dela é idêntico ao de "não havia nada a coletar"."""
    from . import coleta
    try:
        return coleta.coletar()
    except Exception as exc:  # noqa: BLE001
        log.warning("radar: ciclo falhou: %s", type(exc).__name__)
        return None


def _laco() -> None:
    _dorme(ATRASO_INICIAL_S)
    while True:
        try:
            r = _um_ciclo()
            if r and any(v != "no_prazo" for v in r.values()):
                log.info("radar: %s", ", ".join(f"{k}={v}" for k, v in r.items()
                                                 if v != "no_prazo"))
        except Exception as exc:  # noqa: BLE001
            log.warning("radar: %s", type(exc).__name__)
        _dorme(CICLO_S)


def desligado() -> bool:
    """`RADAR_COLETA=0` no `.env` desliga a coleta (máquina sem internet,
    bancada de desenvolvimento). Sem a variável, liga — as fontes são públicas
    e não pedem credencial, então não há "instalação incompleta" a esperar."""
    return os.environ.get("RADAR_COLETA", "").strip().lower() in ("0", "nao", "não", "off", "false")


def iniciar() -> None:
    """Sobe a thread da coleta do Radar. Idempotente."""
    global _iniciado
    if _iniciado:
        return
    if sob_teste():
        log.info("radar: rodada de teste — coleta nao iniciada")
        return
    if desligado():
        log.info("radar: RADAR_COLETA desligada no .env — coleta nao iniciada")
        return
    _iniciado = True
    threading.Thread(target=_laco, daemon=True, name="radar-coleta").start()
    log.info("coleta do radar iniciada (ciclo de %ds)", CICLO_S)
