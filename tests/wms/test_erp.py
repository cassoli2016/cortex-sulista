# -*- coding: utf-8 -*-
"""A porta do Avacorp. O dublê é o CORPO REAL copiado da réplica em
12/09/2026 (nota 374.282 da Schulz, três racks) — nunca derivado do código
que o lê: dublê montado a partir da constante testada não testa a constante."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from api.validacao import DadoInvalido
from api.wms import erp

CAB_REAL = {
    "grupo": 1, "empresa": 1, "filial": 19, "unidade": 1, "diferenciadornumero": 1,
    "serie": 124, "numero": 16216, "sequencianotafiscal": 1,
    "chave": "42260984693183000168550010003742821000374282", "nf_numero": 374282,
    "nf_serie": "1", "nf_emissao": datetime.date(2026, 9, 12),
    "remetente": "84693183000168", "destinatario": "17635277003109",
    "valor_mercadoria": Decimal("17000.00"), "peso_kg": Decimal("17.000"),
    "volumes": Decimal("17.00"), "especie": "PALLET",
    "natureza": "PEÇAS E PARTES AUTOMOTIVAS", "coletas": 2,
}
ITENS_REAIS = [
    {"sequencia": 1, "codigo": "961.0301-0", "descricao": "RACK METALICO  ZF-BRASIL - AA01298655",
     "unidade": "PC", "especie": "PALLET", "qtd": Decimal("6.00"), "peso_kg": Decimal("6.000"),
     "valor": Decimal("6000.00")},
    {"sequencia": 2, "codigo": "961.0067-0",
     "descricao": "RACK ESPECIAL - ZF (9T02.500.163)_Aplic.17.06 a 17.11_14/15",
     "unidade": "PC", "especie": "PALLET", "qtd": Decimal("6.00"), "peso_kg": Decimal("6.000"),
     "valor": Decimal("6000.00")},
    {"sequencia": 3, "codigo": "961.0294-0",
     "descricao": "RACK METALICO  ZF-BRASIL - 9T02 500 154 -  17.36/17.37/17.40",
     "unidade": "PC", "especie": "VOLUMES", "qtd": Decimal("5.00"), "peso_kg": Decimal("5.000"),
     "valor": Decimal("5000.00")},
]
CADASTRO_REAL = [
    {"cnpj": "84693183000168", "razao_social": "SCHULZ S/A",
     "nome_fantasia": "SCHULZ - JOINVILLE/SC", "cidade": "JOINVILLE", "uf": "SC"},
    {"cnpj": "17635277003109", "razao_social": "METALSIDER LTDA",
     "nome_fantasia": "METALSIDER LTDA", "cidade": "BETIM", "uf": "MG"},
]


@pytest.fixture
def dublê(monkeypatch):
    chamadas = []

    def query(sql, params=None):
        chamadas.append((sql, params))
        if sql is erp.NF_SQL:
            return [CAB_REAL]
        if sql is erp.ITENS_SQL:
            return ITENS_REAIS
        if sql is erp.CADASTRO_POR_CODIGO_SQL:
            return [c for c in CADASTRO_REAL if c["cnpj"] in params[0]]
        return []

    monkeypatch.setattr(erp.db, "query", query)
    return chamadas


def test_a_nota_vem_com_os_itens_e_os_nomes_das_partes(dublê):
    nf = erp.buscar_nf(CAB_REAL["chave"])
    assert nf["nf_numero"] == 374282 and nf["nf_emissao"] == "2026-09-12"
    assert nf["remetente"]["razao_social"] == "SCHULZ S/A"
    assert nf["destinatario"]["nome_fantasia"] == "METALSIDER LTDA"
    assert [i["codigo"] for i in nf["itens"]] == ["961.0301-0", "961.0067-0", "961.0294-0"]
    assert sum(i["qtd"] for i in nf["itens"]) == 17.0
    assert nf["coletas"] == 2, "a tela precisa dizer que a chave está em mais de uma coleta"


def test_os_itens_se_casam_pela_PK_da_nota_na_coleta_as_8_colunas(dublê):
    """Casar pelas 7 colunas da COLETA traria os itens de todas as notas dela —
    e o total inflado sairia plausível."""
    erp.buscar_nf(CAB_REAL["chave"])
    sql, params = next(c for c in dublê if c[0] is erp.ITENS_SQL)
    assert "sequencianotafiscal" in sql
    assert params == (1, 1, 19, 1, 1, 124, 16216, 1)


def test_chave_em_varias_coletas_escolhe_por_desempate_escrito_por_inteiro():
    """Empate em ORDER BY é sorteio. O desempate cobre a PK inteira."""
    ordem = erp.NF_SQL.split("ORDER BY", 1)[1]
    for col in ("dtinc", "filial", "serie", "numero", "sequencianotafiscal", "diferenciadornumero"):
        assert col in ordem, col


def test_chave_que_nao_esta_em_coleta_devolve_None(monkeypatch):
    monkeypatch.setattr(erp.db, "query", lambda sql, params=None: [])
    assert erp.buscar_nf("0" * 44) is None


def test_ERP_fora_do_ar_vira_recusa_legivel_e_nao_500(monkeypatch):
    def cai(sql, params=None):
        raise OSError("connection refused")
    monkeypatch.setattr(erp.db, "query", cai)
    with pytest.raises(erp.ErpIndisponivel, match="recebimento manual"):
        erp.buscar_nf("1" * 44)


def test_busca_de_cadastro_por_raiz_e_por_nome_sem_byte_nulo(monkeypatch):
    vistos = []
    monkeypatch.setattr(erp.db, "query", lambda sql, params=None: vistos.append((sql, params)) or [])
    erp.buscar_cadastro("84.693.183")
    erp.buscar_cadastro("schulz_%")
    (s1, p1), (s2, p2) = vistos
    assert s1 is erp.CADASTRO_POR_PREFIXO_SQL and p1[0] == "84693183%"
    assert s2 is erp.CADASTRO_POR_NOME_SQL and p2[0] == r"%schulz\_\%%"
    assert not any("\x00" in str(p) for _s, p in vistos)
    with pytest.raises(DadoInvalido, match="8 dígitos"):
        erp.buscar_cadastro("8469")


def test_nenhuma_constante_sql_do_erp_escreve_curinga_literal():
    """`%` dentro da constante vira placeholder do psycopg."""
    for nome in dir(erp):
        if nome.endswith("_SQL"):
            sql = getattr(erp, nome)
            assert "%%" not in sql and "'%" not in sql and "%'" not in sql, nome
