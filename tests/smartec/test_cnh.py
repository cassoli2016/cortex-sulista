# -*- coding: utf-8 -*-
"""CNH e exame toxicológico — a coleta que não existia, e o que ela encontra.

Os corpos abaixo são LITERAIS de `/api/Cnh` (Tipo CONSULTAR), medidos em
08/09/2026. Entrada de teste que representa formato EXTERNO nunca se deriva do
código que vai lê-la.

O CPF dos exemplos é INVENTADO (não passa no dígito verificador de propósito):
dado de pessoa real não entra em teste de repositório público.
"""
from __future__ import annotations

import pytest

from api.smartec import armazenamento as arm

# ─────────────────────────────────────────────────────────── corpos REAIS
#
# O QUE A CONTA DEVOLVE HOJE: a Smartec conhece o condutor (CNH e NOME em 24
# de 24) e NAO devolve nada do que decide — vencimento, pontuação,
# impedimento e toxicológico vieram nulos em 24 de 24.
COMO_VEM_HOJE = {
    "CPF": "00000000191",
    "CNH": "02722406498",
    "NOME": "FULANO DE TAL",
    "PONTUACAO": None,
    "PORTARIA": None,
    "IMPEDIMENTO": None,
    "VENCIMENTO": None,
    "DATA_PESQUISA": "13/08/2026",
    "VENCIMENTO_EXAME_TOXICOLOGICO": None,
    "OBSERVACAO_TOXICOLOGICO": None,
    "PESQUISA_TOXICOLOGICO": None,
    "CATEGORIA_VERIFICADO": None,
    "VENCIMENTO_VERIFICADO": "00/00/0000",
    "EMISSAO_VERIFICADO": "00/00/0000",
    # O BLOCO DE BLOQUEIOS VEM SEMPRE, com as chaves presentes e NULAS — é a
    # mesma armadilha do bloco SENATRAN nas restrições de veículo, onde ela
    # classificou 292 de 292 veículos como impeditivos.
    "BLOQUEIOS": [{"DESCRICAO": None, "DATA": None, "INICIO": None,
                   "FIM": None, "DIAS": None, "DATA_PESQUISA": None}],
}

#: Como VIRIA se o módulo estivesse habilitado — a forma que o código precisa
#: saber ler antes de o fornecedor ligar, senão o dia em que ligar não
#: acontece nada e ninguém entende por quê.
COMO_VIRIA_COMPLETO = {
    "CPF": "00000000191",
    "CNH": "02722406498",
    "NOME": "FULANO DE TAL",
    "PONTUACAO": 7,
    "IMPEDIMENTO": None,
    "VENCIMENTO": "31/03/2027",
    "DATA_PESQUISA": "08/09/2026",
    "VENCIMENTO_EXAME_TOXICOLOGICO": "15/11/2026",
    "OBSERVACAO_TOXICOLOGICO": "EXAME VALIDO",
    "CATEGORIA_VERIFICADO": "E",
    "BLOQUEIOS": [{"DESCRICAO": "SUSPENSAO DO DIREITO DE DIRIGIR",
                   "DATA": "01/02/2026", "DIAS": 30}],
}


@pytest.fixture()
def esq(esquema_pg):
    arm.ESQUEMA = esquema_pg
    yield esquema_pg
    arm.ESQUEMA = None


# ────────────────────────────────────────── o estado de hoje, gravado honesto

def test_o_que_chega_hoje_e_gravado_SEM_inventar_valor(esq):
    """Campo que não veio fica NULO. "Coleta vazia nunca vira snapshot cheio".

    Preencher com um valor de conveniência (data de hoje, zero pontos) faria a
    tela dizer que a CNH está conferida quando ninguém conferiu nada.
    """
    from api import pglocal
    assert arm.gravar_cnh(COMO_VEM_HOJE, esq) == 1
    r = pglocal.query("SELECT * FROM smt_cnh", esquema=esq)[0]
    assert r["registro"] == "02722406498"
    assert r["nome"] == "FULANO DE TAL"
    assert r["validade"] is None
    assert r["toxicologico_validade"] is None
    assert r["pontos"] is None


def test_bloqueio_com_DESCRICAO_nula_NAO_vira_situacao(esq):
    """A lista de bloqueios vem sempre, com as chaves presentes e nulas.

    Contar a PRESENÇA da lista como bloqueio marcaria todo condutor como
    suspenso — é o mesmo defeito que o bloco SENATRAN produziu nos veículos,
    onde classificou 292 de 292 como impeditivos.
    """
    from api import pglocal
    arm.gravar_cnh(COMO_VEM_HOJE, esq)
    r = pglocal.query("SELECT situacao, detalhe FROM smt_cnh", esquema=esq)[0]
    assert r["situacao"] == ""
    # E O QUE DE FATO PRENDE A REGRA: o bloqueio fantasma nem entra no
    # detalhe. A primeira versao deste teste olhava so `situacao`, e era
    # VERDE-PARA-SEMPRE -- com o defeito reintroduzido ela continuava vazia,
    # porque juntar uma descricao nula da string vazia de qualquer jeito.
    # Sabotei, vi verde, e foi assim que descobri que o guard nao guardava.
    assert r["detalhe"]["bloqueios"] == [], (
        "bloqueio de DESCRICAO nula entrou no detalhe: a PRESENCA da lista "
        "esta sendo contada como bloqueio")


# ─────────────────────────── o espelho: quando o fornecedor ligar, tem de ler

def test_quando_o_modulo_for_habilitado_o_codigo_JA_le(esq):
    """Guard que só sabe ler o vazio aprova o vazio para sempre.

    Sem este caso, a leitura dos campos que importam nunca teria sido
    exercitada — e o dia em que a Smartec habilitar o módulo seria o dia de
    descobrir que o de-para estava errado.
    """
    from datetime import date

    from api import pglocal
    assert arm.gravar_cnh(COMO_VIRIA_COMPLETO, esq) == 1
    r = pglocal.query("SELECT * FROM smt_cnh", esquema=esq)[0]
    assert r["validade"] == date(2027, 3, 31)
    assert r["toxicologico_validade"] == date(2026, 11, 15)
    assert r["pontos"] == 7
    assert "SUSPENSAO" in r["situacao"]
    assert r["categoria"] == "E"


def test_reconsultar_o_mesmo_CPF_atualiza_e_nao_duplica(esq):
    """Chave natural é o CPF. Coleta que duplica dobra a tabela na 2ª passada."""
    from api import pglocal
    arm.gravar_cnh(COMO_VEM_HOJE, esq)
    arm.gravar_cnh(COMO_VIRIA_COMPLETO, esq)
    linhas = pglocal.query("SELECT validade FROM smt_cnh", esquema=esq)
    assert len(linhas) == 1
    assert linhas[0]["validade"] is not None, "o update nao aplicou"


# ────────────────────────────────────────────── o veredito que a Saude mostra

def test_o_veredito_separa_NAO_PERGUNTEI_de_PERGUNTEI_E_NAO_VEIO(esq):
    """São problemas de donos diferentes, e a tela precisa dizer qual é.

    Sem coleta, o conserto é nosso. Com coleta e sem dado, o conserto é uma
    conversa com o fornecedor. Uma tela vazia não distingue os dois, e é por
    isso que a ausência ficou invisível por tanto tempo.
    """
    from api.smartec import leitura

    leitura_esq = esq
    assert leitura.estado_cnh(leitura_esq)["veredito"] == "nunca coletado"

    arm.gravar_cnh(COMO_VEM_HOJE, esq)
    e = leitura.estado_cnh(leitura_esq)
    assert e["consultados"] == 1 and e["com_validade"] == 0
    assert "nao esta habilitado" in e["veredito"]

    arm.gravar_cnh(COMO_VIRIA_COMPLETO, esq)
    assert leitura.estado_cnh(leitura_esq)["veredito"] == "recebendo dado"


def test_UM_condutor_com_dado_NAO_apaga_o_alarme_dos_outros(esq):
    """O defeito que a coleta real de producao expos, em 08/09/2026.

    A primeira versao dizia "recebendo dado" se QUALQUER condutor tivesse
    vencimento. Na coleta real, UM de 81 tinha -- e o cartao da Saude ficou
    VERDE com 80 motoristas cuja habilitacao ninguem estava conferindo.

    Um caso solto nao pode desligar o alarme dos outros oitenta.
    """
    from api.smartec import leitura

    arm.gravar_cnh(COMO_VIRIA_COMPLETO, esq)                    # tem tudo
    # CPFs DISTINTOS do completo: a primeira versao usava um prefixo que
    # colidia com ele, e o registro bom era SOBRESCRITO -- o teste media 3
    # condutores onde deviam ser 4.
    for i in range(3):                                          # nao tem nada
        arm.gravar_cnh({**COMO_VEM_HOJE, "CPF": f"9990000019{i}"}, esq)

    e = leitura.estado_cnh(esq)
    assert e["consultados"] == 4 and e["com_validade"] == 1
    assert e["faltam_validade"] == 3 and e["faltam_toxicologico"] == 3
    assert e["veredito"].startswith("entrega PARCIAL"), e["veredito"]
    # E A CONTAGEM VAI JUNTO: "falta 1" e "faltam 80" nao podem se ler igual.
    assert "3 de 4" in e["veredito"]


# ──────────────────────────────────────────────────────────────────── PII

def test_o_CPF_nunca_sai_na_mensagem_de_erro():
    """Erro vira log, log vira arquivo, e o repositorio desta casa e PUBLICO.

    `coletar_cnh` guarda só o TIPO da exceção — nunca o texto, que em cliente
    HTTP costuma ecoar o corpo da requisição, e o corpo aqui É o CPF.
    """
    import inspect

    from api.smartec import coleta
    fonte = inspect.getsource(coleta.coletar_cnh)
    assert "type(exc).__name__" in fonte
    assert "{cpf}" not in fonte and "+ cpf" not in fonte
