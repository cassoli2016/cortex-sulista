# -*- coding: utf-8 -*-
"""Medicao cara nao espera o pedido -- e os TRES estados que isso cria.

O QUE ACONTECEU (07/09/2026). A Saude do Servidor levava 78 s para carregar a
primeira vez, e quem abriu a tela viu ela em branco. Medido bloco a bloco, num
processo NOVO, sem aquecer nada:

    agrupador (mapa contabil)   47,7 s     <- uma consulta ao ERP
    tarefas agendadas            6,9 s     <- sete perguntas ao Windows
    servicos (os 31 cartoes)     0,8 s
    todo o resto                 < 1 s

A consulta foi corrigida (`existe()` no lugar do `left_join()`, 47 s -> 4,5 s)
e a coleta fria caiu para 13,7 s. **Nao bastou.** A casa ja tinha vivido isso
com as tarefas agendadas: com a resposta em 4,8 s contra recarga encadeada de
5 s, quase toda resposta chegava depois de a proxima ter comecado e o guard de
sequencia do front a descartava -- em branco para sempre, sem erro nenhum.

**TTL sozinho nao resolve, e essa e a licao.** Ele poupa a SEGUNDA leitura;
a primeira alguem sempre paga -- e o AutoDeploy reinicia a API a cada push,
entao "a primeira" acontece varias vezes por dia, sempre na cara de quem abriu
a tela. A medicao tem de sair da THREAD do pedido, nao so do relogio.

Este arquivo cobra o contrato do `_EmFundo`, que e onde isso mora.

SOBRE O `em_fundo=True` QUE APARECE ABAIXO: as instancias de PRODUCAO nascem
GATEADAS sob pytest (elas leem o ERP de verdade e abrem PowerShell), entao o
teste que quer afirmar o comportamento da THREAD precisa liga-la
explicitamente. O gate em si tem teste proprio no fim do arquivo, e ele usa as
instancias REAIS e a `sob_teste()` REAL -- um duble ali provaria o duble.
"""
from __future__ import annotations

import threading
import time

import pytest

from api import servidor as sv


def _esperar(cond, limite: float = 5.0) -> bool:
    fim = time.time() + limite
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------- o pedido nao espera a medicao

def test_a_primeira_leitura_NAO_acontece_dentro_da_chamada():
    """O defeito original em uma linha: a primeira chamada media, e quem abriu
    a tela pagou 47 s por isso."""
    portao = threading.Event()

    def lenta():
        portao.wait(5)
        return "pronto"

    c = sv._EmFundo("lenta", 300.0, lenta, em_fundo=True)
    inicio = time.perf_counter()
    valor, estado, idade = c.ler()
    gasto = time.perf_counter() - inicio

    assert gasto < 0.5, "a chamada esperou %.2f s pela medicao" % gasto
    assert (valor, estado, idade) == (None, "medindo", None)
    portao.set()
    assert _esperar(lambda: c.ler()[1] == "fresco")


def test_medindo_NAO_e_erro_e_NAO_e_ausencia():
    """Tres estados, e o cartao diz qual e. `medindo` nao pode virar "nao sei"
    (que acusa) nem sumir da tela (ausencia nao tem sintoma)."""
    c = sv._EmFundo("x", 300.0, lambda: {"ok": True}, em_fundo=True)
    assert c.ler()[1] == "medindo"
    assert _esperar(lambda: c.ler()[1] == "fresco")
    assert c.ler()[0] == {"ok": True}


# ------------------------------------------------------ uma medicao por vez

def test_doze_pinturas_de_cartao_nao_viram_doze_medicoes():
    """A tela repinta de 5 em 5 s. Sem a trava, uma medicao de 5 s viraria doze
    PowerShell simultaneos ou doze varreduras do razao -- PIOR que esperar."""
    portao, contagem = threading.Event(), []

    def lenta():
        contagem.append(1)
        portao.wait(5)
        return 1

    c = sv._EmFundo("x", 300.0, lenta, em_fundo=True)
    fios = [threading.Thread(target=c.ler) for _ in range(12)]
    for f in fios:
        f.start()
    for f in fios:
        f.join(5)
    portao.set()
    assert _esperar(lambda: c.ler()[1] == "fresco")
    assert len(contagem) == 1, "disparou %d medicoes ao mesmo tempo" % len(contagem)


# --------------------------------------------- leitura velha serve, com a idade

def test_passado_o_TTL_serve_a_leitura_VELHA_enquanto_remede():
    """Numero velho servido CALADO e pior que tela vazia, porque ninguem
    desconfia dele -- por isso vem com a idade. Mas apagar o cartao enquanto
    remede seria trocar um numero um pouco velho por nada."""
    vezes = []
    c = sv._EmFundo("x", 1.0, lambda: (vezes.append(1), len(vezes))[1],
                    em_fundo=True)
    c.ler(esperar=True)
    assert c.ler() == (1, "fresco", 0)

    time.sleep(1.1)
    valor, estado, idade = c.ler()
    assert valor == 1, "apagou a leitura boa enquanto remedia"
    assert estado == "velho" and idade >= 1
    assert _esperar(lambda: c.ler()[0] == 2)


def test_falhar_NAO_apaga_o_que_ja_se_sabia():
    """O ERP e replica de producao de TERCEIRO e tem dia ruim. Um tropeco na
    remedicao nao pode zerar o cartao: a leitura anterior continua sendo a
    melhor coisa que a casa sabe, e ela diz a idade."""
    estado_fn = {"quebrar": False}

    def as_vezes():
        if estado_fn["quebrar"]:
            raise RuntimeError("o ERP cancelou")
        return "bom"

    c = sv._EmFundo("x", 0.5, as_vezes, em_fundo=True)
    c.ler(esperar=True)
    assert c.ler()[0] == "bom"

    estado_fn["quebrar"] = True
    time.sleep(0.6)
    c.ler()                                    # dispara a remedicao que falha
    time.sleep(0.3)
    valor, estado, idade = c.ler()
    assert valor == "bom", "a falha APAGOU a ultima leitura boa"
    assert estado == "velho" and idade is not None


# ----------------------------------------------------------------- a tarja

@pytest.mark.parametrize("estado,idade,esperado", [
    ("fresco", 0, ""),
    ("fresco", 900, ""),
    ("medindo", None, ""),
    ("velho", 30, " · leitura de 30 s atrás"),
    ("velho", 605, " · leitura de 10 min atrás"),
])
def test_a_tarja_so_aparece_quando_a_leitura_passou_do_prazo(estado, idade, esperado):
    assert sv._tarja(estado, idade) == esperado


# ------------------------------------------------- o que os cartoes mostram

def test_o_cartao_do_mapa_contabil_diz_que_esta_medindo():
    """Cartao que SOME por um minuto ensina que a conferencia nao existe."""
    c = sv._servico_agrupador(None, "medindo", None)
    assert c["status"] == "info"
    assert "medindo" in c["detalhe"]


def test_consulta_cancelada_pelo_ERP_nao_acusa_o_cadastro():
    """O portal do ERP e compartilhado com um Power BI sem `statement_timeout`.
    `QueryCanceled` e carga ALHEIA, nao mapa quebrado -- dizer "o mapa nao pode
    ser lido, cinco telas sem dado" manda alguem procurar defeito onde nao ha.
    """
    c = sv._servico_agrupador({"legivel": False, "erro": "QueryCanceled"})
    assert c["status"] == "alerta", "carga externa nao e falha nossa: nao e erro"
    assert "carga externa" in c["detalhe"]
    assert "sem dado" not in c["detalhe"]

    # e o mapa REALMENTE ilegivel continua sendo vermelho, com as cinco telas
    c = sv._servico_agrupador({"legivel": False, "erro": "UndefinedFunction"})
    assert c["status"] == "erro" and "Orçamento" in c["detalhe"]


def test_o_cartao_das_janelas_do_ERP_tambem_diz_que_esta_medindo():
    c = sv._servico_janelas_erp(None, "medindo", None)
    assert c["status"] == "info" and "medindo" in c["detalhe"]


def test_coletar_NOMEIA_o_que_ainda_esta_medindo(monkeypatch):
    """Sem isso a tela diria "nao foi possivel verificar" para uma medicao que
    esta correndo agora -- e isso e acusacao, nao informacao.

    Sem `em_fundo=True` de proposito: gateado, nada mede, e o estado `medindo`
    fica deterministico em vez de depender de a thread ter ganho a corrida."""
    monkeypatch.setattr(sv, "_SEGREDOS", sv._EmFundo("s", 300.0, lambda: {"total": 1}))
    monkeypatch.setattr(sv, "_TAREFAS_EM_FUNDO",
                        sv._EmFundo("t", 60.0, lambda: [{"nome": "X"}]))
    monkeypatch.setattr(sv, "_servicos", lambda: [])
    d = sv.coletar()
    assert set(d["medindo"]) == {"segredos", "tarefas"}
    assert d["segredos"] is None and d["tarefas"] == []
    assert d["deploy"]["status"] == "info", (
        "com o agendador ainda sendo lido, o cartao do AutoDeploy nao pode "
        "dizer que a tarefa nao existe")


# ------------------------------------------------------ o gate, nas REAIS

@pytest.mark.parametrize("atributo", ["_AGRUPADOR", "_JANELAS", "_SEGREDOS",
                                      "_TAREFAS_EM_FUNDO"])
def test_a_instancia_de_PRODUCAO_nao_sobe_thread_sob_pytest(atributo):
    """As quatro medicoes leem o ERP de producao, o agendador do Windows e a
    ACL dos arquivos de segredo -- e nesta bancada as credenciais sao as de
    verdade. Sem gate, uma rodada de testes que encostasse em `coletar()`
    deixaria threads vivas medindo a casa DEPOIS de o teste acabar: a forma
    exata do defeito de 06/09/2026, uma thread de processo de teste escrevendo
    no log da API de producao.

    Usa a instancia REAL e a `sob_teste()` REAL -- um duble aqui provaria o
    duble, nao o gate.

    E e PARAMETRIZADO com as quatro: em guard parametrizado cada parametro e um
    guard, e sabotar um so prova o mecanismo, nao que os outros existam.
    """
    from api.sob_teste import sob_teste
    assert sob_teste(), "este teste so faz sentido rodando sob pytest"
    assert getattr(sv, atributo).em_fundo is False, (
        "%s subiria thread numa rodada de testes" % atributo)


def test_sob_teste_a_leitura_nao_mede_e_nao_deixa_thread():
    """O outro lado do gate: gateado, `ler()` devolve "medindo" e NAO mede --
    em vez de medir na thread do teste, que seria o gate virando bloqueio."""
    chamadas = []
    c = sv._EmFundo("x", 300.0, lambda: chamadas.append(1))
    assert c.em_fundo is False
    antes = {t.name for t in threading.enumerate()}
    assert c.ler() == (None, "medindo", None)
    assert not chamadas, "mediu DENTRO do teste, com as credenciais da casa"
    assert {t.name for t in threading.enumerate()} - antes == set()

    # e `esperar=True` continua medindo: e por ele que o conferidor de linha
    # de comando e o proprio teste pedem o numero de verdade.
    c.ler(esperar=True)
    assert len(chamadas) == 1
