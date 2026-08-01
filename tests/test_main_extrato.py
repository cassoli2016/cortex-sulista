"""Testa o helper de limite de tamanho do upload de extrato (api/main.py).

O projeto ainda nao tem harness de TestClient/autenticacao para testar
endpoints ponta a ponta (extrato/importar e o primeiro endpoint de upload por
corpo bruto). A checagem de tamanho foi extraida numa funcao pura pequena
(`_tamanho_excede`) exatamente para poder ser testada isolada, sem subir a
app nem simular sessao.
"""
from __future__ import annotations

from api.main import _tamanho_excede

_LIMITE = 8 * 1024 * 1024


def test_tamanho_excede_quando_content_length_maior_que_limite():
    assert _tamanho_excede(str(_LIMITE + 1), _LIMITE) is True


def test_tamanho_nao_excede_quando_content_length_menor_ou_igual_ao_limite():
    assert _tamanho_excede(str(_LIMITE), _LIMITE) is False
    assert _tamanho_excede("100", _LIMITE) is False


def test_tamanho_nao_excede_quando_header_ausente():
    assert _tamanho_excede(None, _LIMITE) is False
    assert _tamanho_excede("", _LIMITE) is False


def test_tamanho_nao_excede_quando_header_malformado_nao_estoura_excecao():
    # Content-Length invalido/nao-numerico nunca pode virar 500 - so cai para
    # a segunda linha de defesa (checagem pos-leitura do corpo).
    assert _tamanho_excede("abc", _LIMITE) is False
    assert _tamanho_excede("12.5", _LIMITE) is False
