"""A leitura do ERP é PostgreSQL 9.3 e a do Monitoramento SAC."""
from __future__ import annotations

import re

from api.horas_paradas import fonte

CONSULTAS = {"cargas": fonte.CARGAS_SQL, "contrato": fonte.CONTRATO_SQL,
             "clientes": fonte.CLIENTES_SQL, "catalogo": fonte.CATALOGO_SQL}


def test_nada_que_o_93_nao_tenha():
    """`FILTER (WHERE …)` e `json_build_object` são do 9.4; o erro que o ERP
    devolve aponta para o meio do agregado, não para a versão."""
    for nome, sql in CONSULTAS.items():
        assert not re.search(r"FILTER\s*\(", sql, re.I), nome
        assert "json_build_object" not in sql, nome


def test_nenhum_sinal_de_porcentagem_solto():
    """`%` dentro de constante SQL vira placeholder do psycopg."""
    for nome, sql in CONSULTAS.items():
        assert not re.search(r"%(?!\(\w+\)s)", sql), nome


def test_as_quatro_ocorrencias_do_SAC_e_o_cliente_pelo_PAGADOR():
    sql = fonte.CARGAS_SQL
    assert "IN (394, 395, 396, 397)" in sql
    for oc in (394, 395, 396, 397):
        assert "ocorrencia = %d AND rn = 1" % oc in sql
    assert "cnpjcpfcodigopagadorfrete" in sql and "vinculo = 1" in sql
    # a janela de ENTREGA é a que a operação combina (ver portal_cliente)
    assert "dtprevisaochegadaviagem" in sql and "dtprevisaoentrega " not in sql


def test_a_contagem_de_repeticoes_nao_e_a_acumulada():
    """`count(*)` sobre janela COM `ORDER BY` é contagem corrente, não o total
    da partição — e o aviso de "mais de um apontamento" nunca acenderia na
    primeira linha."""
    sql = fonte.CARGAS_SQL
    assert re.search(r"count\(\*\)\s+OVER w\b", sql)
    assert re.search(r"w\s+AS \(PARTITION BY[^)]*\)", sql)
    assert "wo AS (w ORDER BY" in sql


def test_chave_tem_as_sete_colunas():
    r = {c: i for i, c in enumerate(fonte.CHAVE)}
    assert fonte.chave(r).count("|") == 6
