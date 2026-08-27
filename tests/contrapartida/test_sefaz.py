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
    QR_CODE_URL = "QRCode"
    PR = {"homologacao": {"servidor": "hom.pr", "STATUS": "cte4/x",
                          "QRCode": "http://portal.pr/cte/qrcode"}}

    @staticmethod
    def get_service_url(sigla, service, ambiente):
        return f"ORIGINAL:{sigla}"


def test_endereco_resolve_estado_com_sefaz_propria():
    """PR, MG, MS e MT tem SEFAZ propria e caem no `else` da biblioteca, que
    devolve a STRING da sigla no lugar do dicionario."""
    m = _Mod()
    sefaz._endereco(m)
    assert m.get_service_url("PR", "STATUS", 2) == "https://hom.pr/cte4/x"


def test_qrcode_NAO_e_concatenado_com_o_servidor():
    """O QR Code nao e caminho dentro do servidor da SEFAZ: e uma URL completa,
    de OUTRO dominio (o portal de consulta publica). Concatenar produzia
    "https://hom.pr/http://portal.pr/..." dentro do documento assinado, e a
    SEFAZ recusava com 851 - que acusa o campo certo sem dizer que ele veio
    concatenado. So aparecia em estado de SEFAZ propria; SP e SVSP e nunca
    passou por aqui."""
    m = _Mod()
    sefaz._endereco(m)
    url = m.get_service_url("PR", "QRCode", 2)
    assert url == "http://portal.pr/cte/qrcode"
    assert "hom.pr" not in url
    assert url.count("http") == 1


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


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("erpbrasil")
    is None,
    reason="grupo `fiscal` ausente (uv sync --group fiscal)")
def test_leitura_erra_com_MENSAGEM_UTIL_quando_falta_o_elemento():
    """Sem isto o erro e "Unknown property ... Header", que nao diz nada sobre
    o que a SEFAZ respondeu.

    Pula sem o grupo `fiscal`: producao roda `uv sync` sem grupo nenhum, de
    proposito, e falhar la por dependencia ausente e alarme falso.
    """
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
