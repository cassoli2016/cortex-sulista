# -*- coding: utf-8 -*-
"""A Smartec como fonte do cadastro — e os dois defeitos que o dado real pegou.

Os corpos abaixo são LITERAIS, copiados da resposta real de
`/api/Restricoes` em 08/09/2026. Entrada de teste que representa formato
EXTERNO nunca se deriva do código que vai lê-la: dublê montado a partir da
constante testada sabota o teste junto com o alvo, e ele segue verde.
"""
from __future__ import annotations

import pytest

from api.equipamentos import smartec as sm

# ─────────────────────────────────────────────────────────── corpos REAIS
#
# O bloco `SenatranRestricoes` vem em TODA resposta, com as chaves `Roubo`,
# `Renajud`, `Recall` e `Venda` presentes e NULAS. É esse detalhe que produziu
# o defeito de `_valores` — ver lá.
NADA_CONSTA = {
    "restricao_resumo": "NADA CONSTA",
    "agente_financeiro": "",
    "tem_restricao": False,
    "restricao_detalhe": {
        "DetranRestricoes": None,
        "RenajudRestricoes": None,
        "SenatranRestricoes": [{
            "Restricao1": None, "Restricao2": None, "Restricao3": None,
            "Restricao4": None, "Roubo": None, "Venda": None,
            "Renajud": None, "Recall": None,
            "Data_atualizado": "06/09/2026"}]},
}

FINANCIADO = {
    "restricao_resumo": "ALIENACAO FIDUCIARIA - BANCO SANTANDER BRASIL",
    "agente_financeiro": "BANCO SANTANDER BRASIL",
    "tem_restricao": True,
    "restricao_detalhe": {
        "DetranRestricoes": None,
        "RenajudRestricoes": None,
        "SenatranRestricoes": [{
            "Restricao1": "ALIENACAO FIDUCIARIA", "Restricao2": None,
            "Roubo": None, "Venda": None, "Renajud": None, "Recall": None,
            "Data_atualizado": "05/09/2026"}]},
}

# ABQ3174 da frota — bloqueio judicial de verdade.
JUDICIAL = {
    "restricao_resumo": "BLOQUEIO POR ORDEM JUDICIAL",
    "agente_financeiro": "",
    "tem_restricao": True,
    "restricao_detalhe": {
        "SenatranRestricoes": [{"Restricao1": "RESTRICAO JUDICIAL",
                                "Roubo": None, "Renajud": None,
                                "Data_atualizado": "05/09/2026"}]},
}

# SFL4D83 — furto/roubo.
ROUBO = {
    "restricao_resumo": "VEÍCULO COM OCORRENCIA DE FURTO/ROUBO",
    "agente_financeiro": "",
    "tem_restricao": True,
    "restricao_detalhe": {
        "SenatranRestricoes": [{"Roubo": "SIM", "Renajud": None,
                                "Data_atualizado": "05/09/2026"}]},
}

NAO_CONSULTADO = {"tem_restricao": None}


# ──────────────────────────────── o defeito nº 1: chave contada como valor

def test_NADA_CONSTA_nao_e_restricao_impeditiva():
    """O defeito que classificou 292 de 292 veículos como impeditivos.

    A primeira versão procurava as palavras impeditivas no JSON SERIALIZADO.
    O bloco do SENATRAN tem CHAVES chamadas `Roubo`, `Renajud` e `Recall`, que
    vêm em toda resposta com valor nulo — então o texto casava sempre, até em
    "NADA CONSTA".

    Um painel em que tudo é vermelho não é painel de risco: é ruído, e ensina
    a ignorar o vermelho justamente no dia em que um deles for verdade.
    """
    assert sm._impeditiva(NADA_CONSTA) is False
    assert sm._alienacao(NADA_CONSTA) is None


def test_a_varredura_le_VALOR_e_nunca_nome_de_campo():
    """O mecanismo, isolado: `Roubo: None` não é roubo; `Roubo: 'SIM'` é."""
    assert "ROUBO" not in sm._valores({"Roubo": None, "Recall": None})
    assert "SIM" in sm._valores({"Roubo": "SIM"})


# ──────────────────────── o defeito nº 2: financiado tratado como impeditivo

def test_financiado_NAO_e_alarme_e_o_credor_fica_guardado():
    """173 dos 292 veículos são financiados — é o estado normal da frota.

    Se alienação fiduciária entrasse no mesmo booleano de roubo e Renajud,
    metade do painel ficaria vermelha permanentemente.
    """
    assert sm._impeditiva(FINANCIADO) is False
    assert sm._alienacao(FINANCIADO) == "BANCO SANTANDER BRASIL"


@pytest.mark.parametrize("corpo,rotulo", [(JUDICIAL, "judicial"),
                                          (ROUBO, "roubo")],
                         ids=["bloqueio judicial", "furto/roubo"])
def test_o_que_impede_o_veiculo_de_rodar_ACENDE(corpo, rotulo):
    """O espelho: a separação não pode ter apagado o alarme de verdade.

    Guard que só sabe silenciar aprova a frota inteira. Estes dois casos são
    os dois achados REAIS da primeira coleta (ABQ3174 e SFL4D83).
    """
    assert sm._impeditiva(corpo) is True


def test_nao_consultado_e_NULO_e_nunca_falso():
    """"Não sei" nunca é pintado de verde.

    `False` diz "consultei e não há". `None` diz "ninguém olhou". Colapsar os
    dois faria a frota inteira parecer conferida no dia em que a coleta parar.
    """
    assert sm._impeditiva(NAO_CONSULTADO) is None
    assert sm._alienacao(NAO_CONSULTADO) is None
    assert sm._restricoes(NAO_CONSULTADO) is None


# ──────────────────────────────────────────────── a lista que a tela mostra

def test_a_lista_junta_as_duas_fontes_sem_repetir():
    """Detran e SENATRAN discordam em ~32% dos casos — as duas entram.

    Medido em 19 veículos: 6 tinham restrição numa e não na outra, 3 em cada
    sentido. Escolher a "melhor" fonte perderia um terço dos casos.
    """
    itens = sm._restricoes(JUDICIAL)
    fontes = {i["fonte"] for i in itens}
    assert "Detran" in fontes and "SENATRAN" in fontes
    assert len(itens) == len({i["descricao"] for i in itens}), "repetiu"


def test_data_de_atualizacao_nao_vira_restricao():
    """`Data_atualizado: '05/09/2026'` é carimbo, não restrição."""
    for i in sm._restricoes(FINANCIADO):
        assert "2026" not in i["descricao"]


def test_nada_consta_produz_lista_vazia_e_nao_None():
    """Lista vazia = consultei e não há. `None` = não consultei.

    São a mesma imagem na tela e o oposto em significado.
    """
    assert sm._restricoes(NADA_CONSTA) == []
