"""Varredura do CSV aberto: filtro, layout e normalização."""
from __future__ import annotations

import io

import pytest

from api.antt import rntrc

CABECALHO = ("nome_transportador;numero_rntrc;data_primeiro_cadastro;"
             "situacao_rntrc;cpfcnpjtransportador;categoria_transportador;"
             "cep;municipio;uf;equiparado;data_situacao_rntrc")

LINHAS = [
    '"TRANSPORTES ALFA";"007600540";"23/05/2017";"ATIVO";"11.193.322/0001-10";'
    '"ETC";"14095-290";"RIBEIRAO PRETO";"SP";"Sim";"23/10/2024"',
    '"JOAO DA SILVA";"006242260";"24/05/2005";"PENDENTE";"820.***.***-00";'
    '"TAC";"97000-000";"SAO SEPE";"RS";"Nao";"28/08/2025"',
    '"NAO INTERESSA LTDA";"000999999";"01/01/2020";"ATIVO";"00.000.000/0001-00";'
    '"ETC";"00000-000";"OUTRA";"MG";"Nao";"01/01/2020"',
]


def _fonte(linhas=None):
    return io.StringIO("\n".join([CABECALHO] + (linhas or LINHAS)))


def test_varre_e_devolve_so_os_interessantes():
    achadas = rntrc.varrer(_fonte(), {"7600540", "6242260"})
    assert {l["rntrc"] for l in achadas} == {"7600540", "6242260"}


def test_zero_a_esquerda_do_csv_casa_com_a_chave_normalizada():
    achadas = rntrc.varrer(_fonte(), {"7600540"})
    assert achadas and achadas[0]["rntrc"] == "7600540"


def test_traz_situacao_categoria_e_uf():
    l = rntrc.varrer(_fonte(), {"6242260"})[0]
    assert l["situacao"] == "PENDENTE"
    assert l["categoria"] == "TAC"
    assert l["uf"] == "RS"
    assert l["nome"] == "JOAO DA SILVA"


def test_nunca_guarda_documento_de_pessoa():
    """CPF vem mascarado na origem e não tem uso aqui: o casamento é por
    registro. Documento não entra no banco local em hipótese nenhuma."""
    l = rntrc.varrer(_fonte(), {"6242260"})[0]
    assert not any("cpf" in k.lower() or "cnpj" in k.lower() for k in l)
    assert "820" not in repr(l)


def test_layout_diferente_do_esperado_aborta_com_mensagem():
    """Se a ANTT mudar as colunas, parar é melhor que gravar lixo por cima."""
    with pytest.raises(rntrc.LayoutInesperado):
        rntrc.varrer(io.StringIO("coluna_a;coluna_b\n1;2"), {"7600540"})


def test_conjunto_vazio_de_interessantes_nao_varre_nada():
    assert rntrc.varrer(_fonte(), set()) == []


def test_sincronizar_grava_e_relata(tmp_path):
    from api.antt import armazenamento as arm
    base = tmp_path / "antt.db"
    arm.init_db(base)
    r = rntrc.sincronizar({"7600540", "6242260"},
                          baixar=lambda: (_fonte(), "2026-07"), path=base)
    assert r["gravadas"] == 2
    assert r["competencia"] == "2026-07"
    assert arm.situacao("7600540", base)["situacao"] == "ATIVO"


def test_competencia_sai_do_nome_do_arquivo_e_ordena():
    """O rótulo do recurso ('Jul26 - RNTRC') não ordena; a competência da URL
    sim, e é por ela que o mês mais recente é escolhido."""
    assert rntrc.competencia_da_url(
        "https://x/download/transportadores_rntrc_07_2026.csv") == "2026-07"
    assert rntrc.competencia_da_url(
        "https://x/download/transportadores_rntrc_12_2025.csv") == "2025-12"
    assert "2026-07" > "2025-12"


def test_url_fora_do_padrao_nao_vira_competencia():
    assert rntrc.competencia_da_url("https://x/outra_coisa.csv") is None
    assert rntrc.competencia_da_url("") is None
