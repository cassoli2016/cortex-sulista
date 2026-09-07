"""A Saúde do Servidor parou de carregar, e o motivo não era um erro.

A resposta levava 4,8 s e a tela recarregava a cada 5 s. Como o `setInterval`
dispara independentemente de a requisição anterior ter voltado, quase toda
resposta chegava DEPOIS de uma mais nova ter começado — e o guard de sequência
do front, que existe para descartar resposta obsoleta ao trocar de filtro, a
descartava. `DATASRV` nunca era preenchido e a tela ficava em branco para
sempre, sem erro nenhum aparecer.

São dois defeitos independentes, e os dois precisam de conserto:

1. **O servidor era lento à toa.** 3,6 s dos 4,8 eram sete consultas ao
   agendador de tarefas do Windows, refeitas a cada 5 s para descobrir uma
   coisa que muda quando alguém roda um instalador.
2. **A tela atropelava a si mesma.** Intervalo fixo com requisição em voo é
   uma bomba-relógio: funciona até o dia em que a resposta encosta no
   intervalo, e aí para de funcionar de um jeito que não parece defeito.
"""
from __future__ import annotations

import re
import time as _time
from pathlib import Path

import pytest

from api import servidor as sv

RAIZ = Path(__file__).resolve().parents[1]
HTML = (RAIZ / "api" / "static" / "index.html").read_text(encoding="utf-8")


def _esperar(cond, limite: float = 5.0) -> None:
    """A medicao corre em outra thread: o teste espera o EFEITO, com prazo.

    Prazo e nao `join()`: o contrato e "o pedido nao espera", entao o teste nao
    pode ter acesso a thread. E sem `sleep` fixo, que ou e lento demais ou
    instavel na maquina carregada."""
    fim = _time.time() + limite
    while _time.time() < fim:
        if cond():
            return
        _time.sleep(0.01)


def test_as_tarefas_agendadas_saem_do_caminho_quente(monkeypatch):
    """Sem cache, o servidor passava 72% do tempo perguntando ao Windows.
    O TTL é o mesmo do estado da Z-API, e pela mesma razão: diagnóstico cujo
    custo é externo não pode ser refeito a cada pintura de cartão.

    Desde 07/09/2026 a medição também sai da THREAD do pedido — o TTL poupava a
    segunda leitura e alguém sempre pagava a primeira (6,9 s, a cada reinício
    do AutoDeploy). Aqui se cobra as duas coisas: uma consulta só, e ela não
    acontece dentro da chamada."""
    chamadas = []

    def _falso():
        chamadas.append(1)
        return [{"nome": "X", "estado": "Ready"}]

    monkeypatch.setattr(sv, "_tarefas_consultar", _falso)
    # `em_fundo=True` EXPLICITO: sob pytest a instancia de producao nao sobe
    # thread (ela le o ERP de verdade), e e a thread que este teste afirma.
    monkeypatch.setattr(sv, "_TAREFAS_EM_FUNDO",
                        sv._EmFundo("t", sv._TAREFAS_TTL,
                                    lambda: sv._tarefas_consultar(),
                                    em_fundo=True))

    v, estado, _ = sv._tarefas()
    assert (v, estado) == (None, "medindo"), "mediu DENTRO da chamada"
    sv._tarefas()
    sv._tarefas()
    # espera o EFEITO (o estado virar), nao a entrada na funcao: `chamadas`
    # ganha a linha ANTES de o valor ser guardado, e esperar por ela e uma
    # corrida que passa nesta maquina e falha na carregada.
    _esperar(lambda: sv._tarefas()[1] == "fresco")
    assert len(chamadas) == 1, "a consulta ao Windows repetiu apesar do cache"

    v, estado, _ = sv._tarefas()
    assert estado == "fresco" and v == [{"nome": "X", "estado": "Ready"}]

    # e `forcar` existe para quem acabou de instalar uma tarefa e quer ver já
    sv._tarefas(forcar=True)
    assert len(chamadas) == 2


def test_o_cache_expira(monkeypatch):
    """Cache que não expira vira mentira: uma tarefa que caiu continuaria
    verde para sempre."""
    chamadas = []
    monkeypatch.setattr(sv, "_tarefas_consultar",
                        lambda: (chamadas.append(1), [{"nome": "X"}])[1])
    monkeypatch.setattr(sv, "_TAREFAS_EM_FUNDO",
                        sv._EmFundo("t", sv._TAREFAS_TTL,
                                    lambda: sv._tarefas_consultar(),
                                    em_fundo=True))
    relogio = {"t": 1000.0}
    monkeypatch.setattr(sv.time, "monotonic", lambda: relogio["t"])

    sv._tarefas(forcar=True)                 # a primeira, para haver o que expirar
    relogio["t"] += sv._TAREFAS_TTL - 1
    sv._tarefas()
    assert len(chamadas) == 1
    relogio["t"] += 2
    v, estado, _ = sv._tarefas()
    _esperar(lambda: len(chamadas) == 2)
    assert len(chamadas) == 2
    # ENQUANTO remede, serve a leitura VELHA com a idade a mostra -- nunca
    # apaga o cartao nem devolve vazio.
    assert v == [{"nome": "X"}] and estado == "velho"


def test_a_saude_NAO_recarrega_por_intervalo_fixo():
    """`setInterval` dispara com a requisição anterior em voo. Foi assim que
    a tela parou de carregar: a resposta perdia a corrida para a próxima e o
    guard de sequência a descartava, sempre.

    O padrão correto é encadear — agendar o próximo ciclo só DEPOIS de o
    anterior terminar. Assim a tela fica mais lenta quando o servidor está
    lento, nunca vazia."""
    assert "function srvAgendar()" in HTML
    # o router chama o encadeador, não um intervalo
    assert "if(v==='srv') srvAgendar();" in HTML
    assert "srvTimer=setInterval" not in HTML
    # e o encadeamento acontece DEPOIS do await
    i = HTML.index("function srvAgendar()")
    corpo = HTML[i:i + 420]
    assert "await loadSrv(true)" in corpo
    assert corpo.index("await loadSrv") < corpo.index("srvAgendar();", 30)


def test_o_timer_da_saude_e_limpo_com_clearTimeout():
    """`clearInterval` num id de `setTimeout` não é erro em JS, mas deixaria o
    código dizendo uma coisa e fazendo outra — e o próximo a ler acreditaria
    no que está escrito."""
    assert "clearTimeout(srvTimer)" in HTML
    assert "clearInterval(srvTimer)" not in HTML
