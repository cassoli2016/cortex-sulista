# -*- coding: utf-8 -*-
"""O relógio do aviso de carga, dentro da própria API.

POR QUE ELE MUDOU DE CASA
=========================
O aviso era disparado de hora em hora por uma tarefa do Windows
(`instalar_tarefa_avisocargas.ps1`). Duas coisas quebravam nesse arranjo:

1. **A hora cheia não é o relógio de quem pediu.** Quem se inscrevia às 12h38
   era atendido às 13h00 — vinte e dois minutos depois — e depois de hora em
   hora a partir do servidor, não a partir dela. O pedido era o contrário:
   contar do momento em que a pessoa pediu.
2. **A tarefa não estava registrada nesta máquina.** Em 05/09/2026 só existiam
   quatro tarefas do CÓRTEX no agendador (API, AutoDeploy, Ngrok, Tunnel), e
   nenhuma delas roda `avisar_cargas.py` — ainda assim os avisos saíam em
   HH:00. Ou seja: o que dispara o aviso hoje não está escrito em lugar nenhum
   deste repositório, e um recurso que fala com cliente não pode depender de
   uma peça que ninguém sabe onde está.

Aqui ele passa a viver junto da API, que é uma das tarefas que EXISTEM de
verdade e sobe no boot. É o mesmo padrão do digest diário (`api/push.py`):
thread daemon, laço que nunca levanta, arranque idempotente.

POR QUE ISTO NÃO DUPLICA MENSAGEM
=================================
Esta é a pergunta certa, porque o outro gatilho — o que não achamos — pode
continuar rodando. **Não duplica, e não por sorte:** quem decide se manda é
`assinatura.INTERVALO_MIN` contra a âncora do TELEFONE, lida do banco a cada
ciclo. Dois gatilhos disparando ao mesmo tempo leem a mesma âncora e chegam à
mesma conclusão; o segundo encontra o `ultimo_envio` que o primeiro acabou de
gravar. O envio é idempotente por construção, e é isso que torna seguro somar
um relógio novo sem desligar o antigo.

O CICLO É CURTO DE PROPÓSITO
============================
Dez minutos. Não é para mandar de dez em dez — quem manda é o intervalo de 60
— é para o atraso máximo entre "venceu" e "saiu" ser de dez minutos. Com ciclo
de uma hora, a âncora de 12h38 voltaria a ser atendida às 14h00, que é
exatamente o defeito que isto existe para corrigir.
"""
from __future__ import annotations

import logging
import threading
import time

#: A DETECÇÃO MORA NUM LUGAR SÓ (`api/sob_teste.py`), e isto aqui é só o
#: apontador. A regra é de segurança — "não subir thread que fala com cliente
#: dentro de uma rodada de teste" — e regra de segurança com duas cópias é a
#: que se conserta no arquivo errado no dia em que precisar mudar.
#:
#: O nome fica no espaço deste módulo de propósito: é por `agendador.sob_teste`
#: que os testes daqui o substituem, e `iniciar()` o resolve pelo global.
from ..sob_teste import sob_teste  # noqa: E402

log = logging.getLogger("cortex.rastreio.agendador")

#: De quanto em quanto tempo o laço acorda. Ver o cabeçalho: isto é a PRECISÃO
#: da entrega, não a frequência do envio.
CICLO_S = 600

#: Espera antes do primeiro ciclo. O AutoDeploy reinicia a API várias vezes por
#: dia; sem esta folga, cada reinício dispararia uma varredura de envio no
#: primeiro segundo — e um dia de deploys agitado viraria uma rajada.
ATRASO_INICIAL_S = 120

_iniciado = False


def _dorme(seg: float) -> None:
    time.sleep(seg)


def _um_ciclo() -> dict | None:
    """Uma passada. NUNCA levanta — thread que morre por exceção some do
    radar, e o sintoma dela é idêntico ao de "não havia nada para avisar"."""
    from . import aviso
    try:
        return aviso.rodar()
    except Exception as exc:  # noqa: BLE001
        log.warning("agendador do aviso: ciclo falhou: %s", type(exc).__name__)
        return None


def _fora_da_janela() -> bool:
    """De madrugada nem vale acordar o banco.

    A JANELA JÁ É APLICADA NO ENVIO (`whatsapp.envio` recusa e explica), então
    isto não é a trava — é economia de ruído: sem esta checagem o laço faria
    seis varreduras por hora a noite inteira, cada uma terminando em recusa, e
    encheria o log de aviso que não é problema nenhum.
    """
    try:
        from ..whatsapp import config
        return not config.dentro_da_janela()
    except Exception:  # noqa: BLE001
        # Sem conseguir ler a configuração, seguir em frente: quem recusa de
        # verdade é o envio, e errar para o lado de tentar é o lado seguro.
        return False


def _laco() -> None:
    _dorme(ATRASO_INICIAL_S)
    while True:
        try:
            if not _fora_da_janela():
                r = _um_ciclo()
                if r and (r["enviados"] or r["falhas"]):
                    log.info("aviso de carga: %s enviado(s), %s no prazo, "
                             "%s igual(is), %s falha(s)",
                             r["enviados"], r.get("cedo", 0), r["iguais"],
                             r["falhas"])
        except Exception as exc:  # noqa: BLE001
            log.warning("agendador do aviso: %s", type(exc).__name__)
        _dorme(CICLO_S)


def iniciar() -> None:
    """Sobe a thread do aviso de carga. Idempotente.

    SÓ COM O WHATSAPP CONFIGURADO. Sem credencial não é falha, é instalação
    incompleta — e uma thread acordando de dez em dez minutos para descobrir
    isso de novo não ajuda ninguém.

    E NUNCA SOB PYTEST — ver `sob_teste()`.
    """
    global _iniciado
    if _iniciado:
        return
    if sob_teste():
        log.info("aviso de carga: rodada de teste — agendador nao iniciado")
        return
    try:
        from ..whatsapp import cliente
        if not cliente.configurado():
            log.info("aviso de carga: WhatsApp nao configurado — "
                     "agendador nao iniciado")
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("aviso de carga: nao deu para conferir o WhatsApp (%s) — "
                    "agendador nao iniciado", type(exc).__name__)
        return
    _iniciado = True
    threading.Thread(target=_laco, daemon=True,
                     name="rastreio-aviso").start()
    log.info("agendador do aviso de carga iniciado (ciclo de %ds, "
             "intervalo por telefone de %d min)", CICLO_S, _intervalo())


def _intervalo() -> int:
    from . import assinatura
    return assinatura.INTERVALO_MIN
