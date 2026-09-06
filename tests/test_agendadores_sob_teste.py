# -*- coding: utf-8 -*-
"""NENHUM AGENDADOR SOBE NUMA RODADA DE TESTES.

O QUE ISTO IMPEDE, e por pouco não custou de verdade em 06/09/2026:
`TestClient` dispara o `@app.on_event("startup")` — a mesma porta por onde a
suíte já aplicava migration no banco de produção — e o startup sobe as threads
de agendador. Nesta bancada o WhatsApp e o push estão configurados DE VERDADE,
porque aqui É a máquina de produção: o gate de credencial (`habilitado()`,
`cliente.configurado()`) não segura nada.

O resultado seria uma suíte mandando WhatsApp real para quem espera carga e
notificação real no celular das pessoas, sem ninguém ter pedido. Nenhuma
mensagem indevida chegou a sair — a folga de arranque cobriu as rodadas curtas
e as longas caíram fora da janela de envio. Foi sorte de calendário, não
desenho.

O rastro que denunciou: um `RuntimeError` no log da API de PRODUÇÃO cuja causa
era o `monkeypatch` de um teste. A thread de um processo de teste, viva,
escrevendo no log da casa.

CUIDADO AO LER ESTES TESTES: o gate faz `iniciar_*()` sair na primeira linha,
então um teste de arranque escrito sem atenção passa POR VACUIDADE — ele não
prova que a thread subiu, prova que a função retornou. Por isso o teste que
exercita o caminho POSITIVO desliga o gate explicitamente e confere a thread
pelo NOME, e o que exercita o gate usa a função REAL, nunca um dublê (um
`lambda: True` provaria o dublê).
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

from api import push, sob_teste as st

# Os agendadores que o startup sobe. `auth.init_db` tambem roda no startup, mas
# e outro assunto (migration em producao) e tem lugar proprio.
AGENDADORES = ("push-digest", "aviso-carga")


def _threads_vivas() -> set[str]:
    return {t.name for t in threading.enumerate()}


# --------------------------------------------------------------------------
# a pergunta
# --------------------------------------------------------------------------
def test_sob_teste_responde_SIM_aqui_dentro():
    """Se isto falhar, todo o resto deste arquivo é decorativo."""
    assert st.sob_teste() is True


def test_a_ORDEM_importa_sys_modules_ANTES_da_variavel(monkeypatch):
    """O caso que a variável de ambiente sozinha NÃO cobre.

    `PYTEST_CURRENT_TEST` só existe DURANTE um teste. Na coleta, ou numa
    fixture de escopo de módulo que monta o `TestClient` uma vez para o arquivo
    inteiro, ela não está definida — e é justamente aí que o startup costuma
    rodar. Um gate que dependesse só dela deixaria passar exatamente o caso que
    ele existe para barrar.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert not os.environ.get("PYTEST_CURRENT_TEST")
    assert st.sob_teste() is True, "o gate depende da variável de ambiente"


def test_a_variavel_sozinha_TAMBEM_serve(monkeypatch):
    """O segundo caminho continua valendo: processo que não importou pytest mas
    foi lançado por ele (um subprocesso) também é rodada de teste."""
    monkeypatch.setitem(sys.modules, "pytest", None)
    monkeypatch.delitem(sys.modules, "pytest")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "algum_teste")
    assert st.sob_teste() is True


# --------------------------------------------------------------------------
# o gate, exercitado com a funcao REAL
# --------------------------------------------------------------------------
def test_o_scheduler_de_push_NAO_sobe_numa_rodada_de_teste():
    """Sem dublê nenhum: estamos sob pytest de verdade, e é essa a condição.

    A exposição do push é menor que a do aviso de carga — um digest por DIA, em
    hora fixa, com marcador no banco — mas a porta é idêntica: basta a rodada
    cruzar a hora marcada.
    """
    antes = _threads_vivas()
    push.iniciar_scheduler()
    assert "push-digest" not in (_threads_vivas() - antes)


def test_o_agendador_do_aviso_de_carga_TAMBEM_nao_sobe():
    from api.rastreio import agendador
    antes = _threads_vivas()
    agendador.iniciar()
    assert "aviso-carga" not in (_threads_vivas() - antes)


@pytest.mark.parametrize("nome", AGENDADORES)
def test_nenhuma_thread_de_agendador_esta_viva_nesta_rodada(nome):
    """A varredura, e é ela que pega o agendador NOVO.

    Os dois testes acima cobrem quem já existe. Este cobre o próximo: qualquer
    thread de agendador que apareça viva numa rodada de testes é a mesma porta
    reaberta com outro nome.
    """
    assert nome not in _threads_vivas()


# --------------------------------------------------------------------------
# e o caminho POSITIVO, para o gate nao virar "nunca sobe"
# --------------------------------------------------------------------------
def test_com_o_gate_desligado_e_VAPID_configurado_a_thread_SOBE(monkeypatch):
    """O contrapeso, e sem ele os testes acima passariam com
    `iniciar_scheduler` vazia.

    Aqui o dublê é legítimo e está no lugar certo: substitui a PERGUNTA ("é
    rodada de teste?"), não a resposta do gate. O que se afirma é que, fora de
    uma rodada de testes e com credencial, a thread realmente sobe.
    """
    monkeypatch.setattr(push, "sob_teste", lambda: False)
    monkeypatch.setattr(push, "habilitado", lambda: True)
    monkeypatch.setattr(push, "_started", False)
    subidas = []
    monkeypatch.setattr(push.threading, "Thread",
                        lambda **kw: type("T", (), {
                            "start": lambda s: subidas.append(kw.get("name"))})())
    push.iniciar_scheduler()
    assert subidas == ["push-digest"]


def test_sem_VAPID_nao_sobe_nem_fora_de_teste(monkeypatch):
    """Sem credencial não é falha, é instalação incompleta — e uma thread
    acordando de cinco em cinco minutos para redescobrir isso não ajuda."""
    monkeypatch.setattr(push, "sob_teste", lambda: False)
    monkeypatch.setattr(push, "habilitado", lambda: False)
    monkeypatch.setattr(push, "_started", False)
    subidas = []
    monkeypatch.setattr(push.threading, "Thread",
                        lambda **kw: type("T", (), {
                            "start": lambda s: subidas.append(1)})())
    push.iniciar_scheduler()
    assert subidas == []


def test_o_gate_vem_ANTES_do_gate_de_credencial(monkeypatch):
    """Ordem que importa numa instalação SEM VAPID: ali `habilitado()` já
    barraria, e o gate de teste pareceria desnecessário. Nesta bancada o VAPID
    existe — é por isso que a ordem tem de ser esta, e não a inversa por
    acaso. O teste prova que a saída sob pytest não depende de `habilitado()`.
    """
    def explode():
        raise AssertionError("habilitado() foi consultado antes do gate")
    monkeypatch.setattr(push, "habilitado", explode)
    monkeypatch.setattr(push, "_started", False)
    push.iniciar_scheduler()      # sob pytest: sai antes de perguntar
