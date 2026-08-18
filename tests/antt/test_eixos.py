"""Tradução do tipo de carga do AVA para as classes da ANTT.

Eixos não são testados aqui: vêm somados do SQL (tipoveiculo.quantidadeeixos
da tração mais das carretas), com cobertura de 100% do cadastro.
"""
from __future__ import annotations

from api.antt.eixos import normalizar, resolver_carga


def test_normalizar_tira_acento_e_caixa():
    assert normalizar(" Semi-Reboque Frigorífico ") == "SEMI-REBOQUE FRIGORIFICO"
    assert normalizar(None) == ""


def test_codigo_diversas_vira_carga_geral():
    """DIV cobre 1.352 dos 1.377 veículos de agregados e terceiros."""
    assert resolver_carga("DIV") == "carga_geral"


def test_codigos_de_assoalho_tambem_sao_carga_geral():
    assert resolver_carga("AFR") == "carga_geral"
    assert resolver_carga("AMD") == "carga_geral"


def test_campo_vazio_cai_no_padrao_conservador():
    """18 veículos não têm o código preenchido. Carga geral é a classe de menor
    coeficiente entre as não perigosas — nunca infla o piso."""
    assert resolver_carga(None) == "carga_geral"
    assert resolver_carga("  ") == "carga_geral"


def test_codigo_desconhecido_devolve_none_para_virar_pendencia():
    """Código novo no cadastro tem de aparecer na tela para ser mapeado, não
    virar carga geral silenciosamente."""
    assert resolver_carga("XYZ") is None


def test_todo_valor_do_mapa_e_um_tipo_valido_da_antt():
    from api.antt.coeficientes import TIPOS_CARGA
    from api.antt.eixos import _mapa

    carga = _mapa()["carga"]
    for chave, valor in carga["por_codigo"].items():
        assert valor in TIPOS_CARGA, f"{chave} aponta para {valor}"
    assert carga["padrao"] in TIPOS_CARGA
