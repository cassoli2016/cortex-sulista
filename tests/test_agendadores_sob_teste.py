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
from pathlib import Path

import pytest

from api import push, sob_teste as st

# Os agendadores que o startup sobe. `auth.init_db` tambem roda no startup, mas
# e outro assunto (migration em producao) e tem lugar proprio.
#
# OS NOMES SAO OS REAIS, e isso precisou de conserto em 06/09/2026: a lista
# dizia "aviso-carga" e a thread se chama "rastreio-aviso"
# (`api/rastreio/agendador.py`). A varredura passava por VACUIDADE — procurava
# um nome que nao existe, entao passaria igual com a thread viva. Guard que
# nomeia errado o alvo e guard que nunca ficaria vermelho.
#
# `saude-em-fundo` (07/09/2026) NAO e agendador -- nao tem relogio e nao fala
# com fornecedor nenhum: e a thread que tira a medicao cara da Saude do
# caminho do pedido. Entra aqui pela MESMA razao mesmo assim: ela le o ERP de
# producao e abre PowerShell, e sem gate uma rodada de testes deixaria threads
# vivas medindo a casa depois de o teste acabar. O gate esta em
# `_EmFundo.em_fundo`, e `tests/test_saude_em_fundo.py` prova que as quatro
# instancias de PRODUCAO nascem gateadas.
#
# `radar-coleta` (11/09/2026) e a coleta da pagina inicial: nao manda mensagem
# para ninguem, mas baixa quatro sites de terceiro, gasta cota da TomTom e
# ESCREVE no banco — dentro de uma suite, no schema de producao.
AGENDADORES = ("push-digest", "rastreio-aviso", "saude-em-fundo", "radar-coleta")


def _threads_vivas() -> set[str]:
    return {t.name for t in threading.enumerate()}


def _threads_criadas_em_api() -> dict:
    """`{nome: arquivo}` de toda `threading.Thread(...)` sob `api/`.

    Le o FONTE porque a alternativa — importar tudo e observar — so acharia a
    thread que alguem lembrou de subir no teste, que e exatamente o esquecimento
    que este guard existe para pegar.
    """
    import re
    raiz = Path(__file__).resolve().parent.parent / "api"
    achadas, sem_nome = {}, []
    for f in raiz.rglob("*.py"):
        texto = f.read_text(encoding="utf-8")
        for m in re.finditer(r"threading\.Thread\((?P<args>[^)]*)\)", texto, re.S):
            args = m.group("args")
            nome = re.search(r'name\s*=\s*"([^"]+)"', args)
            rel = f.relative_to(raiz.parent).as_posix()
            if nome:
                achadas[nome.group(1)] = rel
            else:
                sem_nome.append(rel)
    return {"nomes": achadas, "sem_nome": sem_nome}


def test_TODA_thread_de_api_tem_nome():
    """Thread sem `name=` nao aparece em varredura nenhuma — nem nesta, nem na
    de threads vivas. Ela e invisivel por construcao, e invisivel e o estado em
    que o defeito de ontem viveu."""
    sem_nome = _threads_criadas_em_api()["sem_nome"]
    assert not sem_nome, (
        "thread sem `name=` em %s — sem nome ela nao entra na varredura, e "
        "uma thread que fala com cliente fora do radar e o defeito da "
        "v0.258.3" % sem_nome)


def test_AGENDADOR_NOVO_e_DESCOBERTO_e_nao_esperado():
    """O GUARD QUE FECHA A CLASSE, e a razao dele e do dia em que foi escrito.

    Com os gates postos nos dois agendadores, o alarme que denunciou o defeito
    original — linha de teste aparecendo no log da API de producao — deixou de
    existir. Se um agendador novo nascer sem gate, nada mais grita sozinho.

    A varredura por nome de thread virou a unica cobertura, e ela lia uma LISTA
    ESCRITA A MAO: um agendador que ninguem acrescentasse ficaria invisivel de
    novo, que e a forma antiga do mesmo defeito.

    Aqui a direcao se inverte: o CODIGO e quem descobre, e a lista tem de
    acompanhar. Com o guard vizinho (`os nomes da lista existem no codigo`) os
    dois lados ficam amarrados — nenhum pode andar sozinho.
    """
    achadas = _threads_criadas_em_api()["nomes"]
    faltando = {n: f for n, f in achadas.items() if n not in AGENDADORES}
    assert not faltando, (
        "thread nova em api/ que a varredura nao cobre: %s.\n"
        "Acrescente o nome a AGENDADORES — e antes disso confira se ela tem "
        "gate de `sob_teste()`: sem ele, uma rodada de testes a sobe dentro do "
        "processo, com as credenciais de producao desta bancada."
        % faltando)


def test_os_nomes_da_lista_EXISTEM_no_codigo():
    """A lista acima ja nomeou uma thread que nao existe, e a varredura passou
    por vacuidade durante uma entrega inteira. Este guard le o nome no FONTE de
    quem sobe a thread: renomea-la la e esquecer a lista aqui volta a acender.

    LE `api/` INTEIRO, e nao uma lista de modulos escrita a mao. Ate 07/09/2026
    ele juntava o fonte de `(push, agendador)` -- os dois agendadores que
    existiam no dia em que foi escrito. A terceira thread nomeada da casa
    (`saude-em-fundo`, em `api/servidor.py`) o deixou vermelho SEM que nada
    estivesse errado, e a saida obvia seria acrescentar mais um modulo a mao --
    reproduzindo, num guard contra vacuidade, o defeito da lista desatualizada
    que ele existe para impedir. A varredura do disco ja estava aqui do lado.
    """
    fontes = _threads_criadas_em_api()["nomes"]
    for nome in AGENDADORES:
        assert nome in fontes, (
            "a lista fala de uma thread chamada %r que nenhum agendador cria — "
            "varredura que nomeia errado o alvo nunca fica vermelha" % nome)


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
def test_o_scheduler_de_push_NAO_sobe_numa_rodada_de_teste(monkeypatch):
    """Sem dublê no GATE: estamos sob pytest de verdade, e é essa a condição.

    A exposição do push é menor que a do aviso de carga — um digest por DIA, em
    hora fixa, com marcador no banco — mas a porta é idêntica: basta a rodada
    cruzar a hora marcada.

    A CREDENCIAL VAI DUBLADA PARA CIMA, e é o que separa este guard de um verde
    ambiental — ver `test_o_agendador_do_aviso_de_carga_TAMBEM_nao_sobe`.
    """
    monkeypatch.setattr(push, "habilitado", lambda: True)
    monkeypatch.setattr(push, "_started", False)
    antes = _threads_vivas()
    push.iniciar_scheduler()
    assert "push-digest" not in (_threads_vivas() - antes)


def test_o_agendador_do_aviso_de_carga_TAMBEM_nao_sobe(monkeypatch):
    """A CREDENCIAL VAI DUBLADA PARA CIMA, e sem isso este guard é ambiental.

    Descoberto em 06/09/2026 sabotando o gate: numa WORKTREE, onde
    `data/whatsapp_config.json` não existe, `iniciar()` para no gate de
    CREDENCIAL antes de chegar ao de pytest. A thread não sobe, o teste passa —
    e passa **pelo motivo errado**, aprovando um agendador sem gate nenhum.

    Na bancada de produção, onde o WhatsApp está configurado, o mesmo teste
    ficava vermelho. Ou seja: o guard mudava de opinião conforme a máquina, e
    era VERDE exatamente onde precisaria ser vermelho — no CI e em toda
    worktree, que é onde a maioria das rodadas acontece.

    Com a credencial dublada, sobra uma coisa só para segurar a thread: o gate
    de `sob_teste()`. É esse que este teste mede.
    """
    from api.rastreio import agendador
    from api.whatsapp import cliente
    monkeypatch.setattr(cliente, "configurado", lambda qual=None: True)
    monkeypatch.setattr(agendador, "_iniciado", False)
    antes = _threads_vivas()
    agendador.iniciar()
    assert "rastreio-aviso" not in (_threads_vivas() - antes)


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
