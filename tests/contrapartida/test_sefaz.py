# tests/contrapartida/test_sefaz.py
"""Camada de compatibilidade com a biblioteca de e-documentos.

Quatro correcoes foram necessarias so para o "ola mundo" da integracao com a
SEFAZ. Estes testes garantem que elas continuem la, que sejam IDEMPOTENTES e
que sumam sozinhas quando a biblioteca corrigir o defeito - remendo que se
empilha e remendo que um dia quebra em producao.

Nenhum destes testes vai a rede.
"""
from __future__ import annotations

import pytest

from api.contrapartida import sefaz


def test_ambiente_de_producao_nao_tem_atalho():
    """Trocar de ambiente tem de ser decisao explicita de quem chama. Uma
    constante PRODUCAO aqui seria sobrescrita sem ninguem perceber."""
    assert sefaz.HOMOLOGACAO == "2"
    assert not hasattr(sefaz, "PRODUCAO")


def test_status_servico_usa_homologacao_por_padrao():
    import inspect
    p = inspect.signature(sefaz.status_servico).parameters
    assert p["ambiente"].default == sefaz.HOMOLOGACAO


class _Mod:
    """Modulo falso com a mesma forma da biblioteca."""
    SVSP_STATES = ("SP",)
    SVRS_STATES = ("RS",)
    AMBIENTE_PRODUCAO = "producao"
    AMBIENTE_HOMOLOGACAO = "homologacao"
    PR = {"homologacao": {"servidor": "hom.pr", "STATUS": "cte4/x"}}

    @staticmethod
    def get_service_url(sigla, service, ambiente):
        return f"ORIGINAL:{sigla}"


def test_endereco_resolve_estado_com_sefaz_propria():
    """PR, MG, MS e MT tem SEFAZ propria e caem no `else` da biblioteca, que
    devolve a STRING da sigla no lugar do dicionario."""
    m = _Mod()
    sefaz._endereco(m)
    assert m.get_service_url("PR", "STATUS", 2) == "https://hom.pr/cte4/x"


def test_endereco_nao_mexe_nos_grupos_que_a_biblioteca_ja_resolve():
    m = _Mod()
    sefaz._endereco(m)
    assert m.get_service_url("SP", "STATUS", 2) == "ORIGINAL:SP"
    assert m.get_service_url("RS", "STATUS", 2) == "ORIGINAL:RS"


def test_remendos_sao_IDEMPOTENTES():
    """Aplicar duas vezes nao pode empilhar camadas: cada chamada envolveria a
    anterior e o comportamento mudaria a cada import."""
    m = _Mod()
    sefaz._endereco(m)
    primeiro = m.get_service_url
    sefaz._endereco(m)
    assert m.get_service_url is primeiro


def test_leitura_erra_com_MENSAGEM_UTIL_quando_falta_o_elemento():
    """Sem isto o erro e "Unknown property ... Header", que nao diz nada sobre
    o que a SEFAZ respondeu."""
    import erpbrasil.edoc.edoc as base
    sefaz._leitura(base)
    from erpbrasil.edoc import resposta as resp

    class Falsa:            # sem parseString -> caminho xsdata
        pass

    class Retorno:
        text = "<env><Body>sem o que procuramos</Body></env>"

    with pytest.raises(ValueError) as e:
        resp.analisar_retorno_raw("op", None, "", Retorno(), Falsa)
    assert "sem o elemento" in str(e.value)


def test_a_compatibilizacao_nao_toca_no_caminho_generateDS():
    """A NF-e da biblioteca usa generateDS e funciona. Os remendos so agem
    quando o objeto NAO tem a API antiga - senao quebrariam o que anda."""
    fonte = sefaz.__file__.replace(".pyc", ".py")
    with open(fonte, encoding="utf-8") as f:
        src = f.read()
    assert 'hasattr(ds, "export")' in src
    assert 'hasattr(classe, "parseString")' in src
