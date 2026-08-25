"""Regra do saldo bancário: quais contas entram e de quando é a posição.

Dois defeitos com a mesma causa, medidos em 25/08/2026:

  Visão Geral / Fluxo de Caixa : 17 contas, -R$ 2.669.441
  Fluxo Consolidado / Antecip. :  7 contas, -R$ 1.755.051
  diferença                    :      R$ 914.390

O que entrava a mais eram contas de gestão de PEDÁGIO (REPOM parada há 86
dias, e-Frete PEDÁGIO, PAMCARD) e uma conta órfã do BB com posição de
2014-07-15 que nem existe em `banco_conta`. E a data exibida era o MÁXIMO de
todas: dizia "posição de 25/08" sobre uma soma que carregava saldo de 2014.
"""
from __future__ import annotations

import re

from api import queries as q

SQL = q.SALDO_SQL


def _sem_espaco(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_soma_apenas_conta_ativa_e_do_fluxo():
    """É a marca do PRÓPRIO ERP: `considerarfluxocaixa=1` é o que a
    controladoria já classificou como caixa disponível."""
    sql = _sem_espaco(SQL)
    assert "bc.ativoinativo = 1" in sql
    assert "bc.considerarfluxocaixa = 1" in sql


def test_usa_a_mesma_regra_do_fluxo_consolidado():
    """As duas telas mostravam números diferentes do MESMO saldo. Se as regras
    divergirem de novo, este teste cai."""
    a = _sem_espaco(q.SALDO_SQL)
    b = _sem_espaco(q.FLUXCON_SALDO_CONTA_SQL)
    for cond in ("bc.ativoinativo = 1", "bc.considerarfluxocaixa = 1"):
        assert cond in a and cond in b, f"{cond} sumiu de uma das duas"


def test_devolve_a_posicao_mais_antiga_e_nao_so_a_mais_recente():
    """Cada conta é lançada num dia diferente: só o máximo faz um saldo com
    uma semana de atraso parecer de ontem."""
    sql = _sem_espaco(SQL)
    assert "AS bancos_data_min" in sql
    assert "min(s.dtmovimento)" in sql


def test_declara_o_que_ficou_de_fora():
    """R$ 914 mil não podem sumir em silêncio só porque não são caixa."""
    sql = _sem_espaco(SQL)
    assert "AS bancos_fora" in sql
    assert "AS bancos_fora_contas" in sql


def test_conta_orfa_nao_entra_no_saldo():
    """A conta do BB com posição de 2014 não existe em `banco_conta`; o JOIN
    interno a exclui, e o LEFT JOIN do bloco 'fora' a captura."""
    sql = _sem_espaco(SQL)
    # o saldo usa JOIN (exclui quem não está cadastrado)
    assert "JOIN banco_conta bc ON bc.banco=s.banco" in sql
    # o bloco de fora usa LEFT JOIN + IS DISTINCT FROM (inclui os não cadastrados)
    assert "LEFT JOIN banco_conta bc" in sql
    assert "bc.ativoinativo IS DISTINCT FROM 1" in sql


def test_caixa_continua_somando_todos_os_caixas():
    """`caixa_saldo` não tem a marca de fluxo — o filtro vale só para bancos."""
    sql = _sem_espaco(SQL)
    assert "FROM caixa_saldo" in sql
    caixa = sql[sql.index("FROM caixa_saldo"):]
    assert "considerarfluxocaixa" not in caixa
