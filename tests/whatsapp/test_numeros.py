"""Normalização de telefone brasileiro.

Isto parece formatação e é controle: o limite que impede o número da Sulista de
ser banido conta DESTINATÁRIOS DISTINTOS na trilha. Se `(47) 99999-8888` e
`5547999998888` virassem duas linhas, o contador mediria formato de digitação,
não pessoas — e o freio protegeria contra nada.
"""
from __future__ import annotations

import pytest

from api.whatsapp import numeros as n


@pytest.mark.parametrize("bruto", [
    "(47) 99999-8888",
    "47 99999-8888",
    "47999998888",
    "+55 47 99999-8888",
    "5547999998888",
    "0055 47 99999 8888",     # prefixo de discagem internacional
    " 55 (47) 9.9999-8888 ",
])
def test_todo_jeito_de_escrever_vira_o_mesmo_numero(bruto):
    """O teste que sustenta o freio: sete grafias, um destinatário."""
    assert n.normalizar(bruto) == "5547999998888"


def test_separar_nao_conta_o_mesmo_numero_duas_vezes():
    """Colar uma lista com o mesmo cliente em dois formatos não pode gastar
    duas mensagens — nem duas fatias do limite diário."""
    lista = n.separar("47 99999-8888, (47)99999-8888; 5547999998888\n11988887777")
    assert len(lista) == 2
    assert {n.normalizar(x) for x in lista} == {"5547999998888", "5511988887777"}


def test_fixo_de_oito_digitos_passa():
    assert n.normalizar("(47) 3333-4444") == "554733334444"


def test_celular_antigo_sem_o_nono_digito_passa():
    """NÃO acrescentamos o 9: quem resolve essa equivalência é o WhatsApp, e a
    Z-API valida a existência do número a cada envio. Inventar o dígito aqui
    mandaria a mensagem para outro assinante."""
    assert n.normalizar("(47) 99998888") == "554799998888"


@pytest.mark.parametrize("bruto,pedaco", [
    ("(20) 99999-8888", "DDD 20"),          # 20 não é DDD no Brasil
    ("(04) 99999-8888", "DDD 04"),
    ("47 09999-8888", "começar com 9"),     # 9 dígitos que não começa com 9
    ("47 89999-8888", "começar com 9"),
    ("999", "formato brasileiro"),
    ("", "Informe o telefone"),
])
def test_recusa_com_o_motivo_na_mensagem(bruto, pedaco):
    """A mensagem vai direto para a tela: quem está com o cadastro aberto
    precisa saber O QUE corrigir, não que 'o telefone é inválido'."""
    with pytest.raises(n.TelefoneInvalido) as exc:
        n.normalizar(bruto)
    assert pedaco in str(exc.value)


def test_ddd_inexistente_e_recusado_mesmo_com_ddi():
    with pytest.raises(n.TelefoneInvalido):
        n.normalizar("5520999998888")


def test_formatar_desfaz_para_leitura_humana():
    assert n.formatar("5547999998888") == "(47) 99999-8888"
    assert n.formatar("554733334444") == "(47) 3333-4444"


def test_formatar_nao_estraga_o_que_nao_reconhece():
    """Linha antiga da trilha, ou número estrangeiro: mostrar o cru é melhor
    que mostrar um parêntese em lugar errado."""
    assert n.formatar("123") == "123"
