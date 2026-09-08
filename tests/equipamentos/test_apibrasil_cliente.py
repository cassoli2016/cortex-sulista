# -*- coding: utf-8 -*-
"""O cliente da APIBrasil — o que ela responde, e o que isso significa.

Os corpos abaixo são LITERAIS copiados da resposta real, nunca derivados do
código que vai lê-los: entrada de teste que representa formato EXTERNO
montada a partir da própria constante testada sabota o teste junto com o alvo,
e ele segue verde. Foi como o cartão de janelas do ERP passou a não testar
nada.
"""
from __future__ import annotations

import pytest

from api.apibrasil import cliente as apib

# ─────────────────────────────────────────────────────────── corpos REAIS
#
# MEDIDO em 08/09/2026 contra gateway.apibrasil.io, com o Bearer da conta no
# cofre e sem produto de veículo contratado.
SEM_PLANO = {"error": True, "message": "Plano ativo não encontrado."}


def test_plano_ativo_nao_encontrado_NAO_e_placa_desconhecida():
    """O defeito que esta medição pegou, e que não teria sintoma nenhum.

    "Plano ativo não encontrado" CONTÉM "não encontrado". Sem a checagem de
    erro de conta vindo primeiro, uma carga de 1.446 placas gravaria todas
    como desconhecidas do Detran — e desconhecida no Detran é justamente o
    sinal de cadastro furado que se foi buscar. O painel mostraria 1.446
    problemas graves onde há uma assinatura a resolver.
    """
    assert apib._erro_de_conta(SEM_PLANO) is True
    assert apib._vazio(SEM_PLANO) is False


def test_placa_realmente_desconhecida_continua_sendo_ausencia():
    """O espelho: a correção acima não pode ter matado o caso legítimo.

    Guard que só sabe proibir aprova o vazio — se `_vazio` passasse a devolver
    False para tudo, o teste acima ficaria verde e a integração perderia a
    capacidade de distinguir placa inexistente de falha.
    """
    assert apib._vazio({"message": "Veículo não encontrado"}) is True
    assert apib._vazio({"message": "Nenhum registro para a placa"}) is True


@pytest.mark.parametrize("corpo", [
    {"message": "Token inválido"},
    {"message": "Crédito insuficiente"},
    {"message": "Limite excedido"},
    {"message": "Não autorizado"},
])
def test_toda_recusa_de_conta_e_recusa_e_nao_ausencia(corpo):
    """Cada parâmetro é um guard: nenhum deles pode virar 'placa não existe'."""
    assert apib._vazio(corpo) is False


def test_a_mensagem_sai_do_corpo_sem_chutar_uma_chave_unica():
    """A APIBrasil não publica envelope de erro único.

    Fixar uma chave devolveria vazio no dia em que ela mudar — e mensagem
    vazia numa recusa é pior que corpo truncado, porque quem lê não tem o que
    investigar.
    """
    assert apib._mensagem(SEM_PLANO) == "Plano ativo não encontrado."
    assert apib._mensagem({"erro": "falhou"}) == "falhou"
    assert apib._mensagem({"response": {"detail": "aninhado"}}) == "aninhado"
    # Formato desconhecido: devolve o corpo truncado. Feio de ler, mas nunca
    # mentira — ao contrário de uma chave escolhida a dedo que volta vazia.
    assert "inesperado" in apib._mensagem({"coisa": "inesperado"})


# ───────────────────────────────────────────────── o freio do caminho inferido

def test_produto_nao_confirmado_recusa_carga_em_massa():
    """Três dos quatro caminhos foram inferidos, e inferir custa dinheiro.

    Sem este freio, 1.446 placas contra um caminho errado gastam a cota
    inteira em 404 — e o erro só apareceria na fatura.
    """
    naoconf = [p for p, op in apib.CATALOGO.items() if not op["confirmado"]]
    assert naoconf, "o teste perdeu o alvo: nenhum produto esta marcado como inferido"
    for produto in naoconf:
        with pytest.raises(apib.ApiBrasilRecusa, match="nao foi confirmado|não foi confirmado"):
            apib.chamar(produto, "ABC1D23")


def test_a_sonda_alcanca_o_produto_inferido():
    """O espelho do freio: a sonda EXISTE para furá-lo de propósito.

    Se ela também recusasse, o caminho inferido nunca poderia ser medido e o
    freio viraria uma parede permanente.
    """
    import inspect
    fonte = inspect.getsource(apib.sondar)
    assert "exigir_confirmado=False" in fonte


def test_produto_fora_do_catalogo_nao_vira_URL():
    """A tela manda a CHAVE; o servidor monta o caminho.

    Regra da casa para playground de fornecedor: nunca URL livre vinda do
    navegador.
    """
    with pytest.raises(apib.ApiBrasilErro, match="desconhecido"):
        apib.chamar("../admin", "ABC1D23")


# ────────────────────────────────────────────────────────────── sanitização

def test_o_token_nunca_sai_em_texto(monkeypatch):
    """Cabeçalho ecoado em log é credencial publicada — e o repo é PÚBLICO."""
    monkeypatch.setattr(apib.credenciais, "ler",
                        lambda nome: "SEGREDO-DO-COFRE-123456" if nome == "APIBRASIL_TOKEN" else "")
    sujo = "falhou com Authorization: Bearer SEGREDO-DO-COFRE-123456 no header"
    limpo = apib._sanitizar(sujo)
    assert "SEGREDO-DO-COFRE-123456" not in limpo
    assert "***" in limpo


def test_sem_credencial_e_recusa_nomeada_e_nao_falha_generica():
    """Instalação incompleta não é erro de sistema: é conserto que a pessoa faz."""
    assert issubclass(apib.ApiBrasilNaoConfigurado, apib.ApiBrasilErro)
