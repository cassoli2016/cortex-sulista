"""Testes do custeio de linhas diretas por viagem."""
from __future__ import annotations

from api.dre_cliente.custeio import custear_diretos


def test_receita_direta_por_viagem():
    viagens = [{"id": 1, "valorfrete": 1000.0, "valorfretecompra": 0.0, "is_proprio": True}]
    r = custear_diretos(viagens)
    assert r["RECEITA BRUTA"][1] == 1000.0


def test_repasse_so_agregado_terceiro_negativo():
    viagens = [{"id": 1, "valorfrete": 1000.0, "valorfretecompra": 600.0, "is_proprio": False}]
    r = custear_diretos(viagens)
    assert r["CUSTO VARIAVEL"][1] == -600.0


def test_repasse_proprio_e_zero():
    viagens = [{"id": 1, "valorfrete": 1000.0, "valorfretecompra": 600.0, "is_proprio": True}]
    r = custear_diretos(viagens)
    assert r["CUSTO VARIAVEL"][1] == 0.0


def test_campos_opcionais_ausentes_nao_quebram():
    viagens = [{"id": 1, "valorfrete": 500.0, "valorfretecompra": 0.0, "is_proprio": True}]
    r = custear_diretos(viagens)
    assert r["CUSTO VARIAVEL"][1] == 0.0
    assert r["RECEITA BRUTA"][1] == 500.0


def test_campos_opcionais_presentes():
    viagens = [{"id": 1, "valorfrete": 1000.0, "valorfretecompra": 0.0, "is_proprio": True,
                "pedagio": 50.0, "descontos": 20.0}]
    r = custear_diretos(viagens)
    assert r["CUSTO VARIAVEL"][1] == -50.0
    assert r["DESCONTOS"][1] == -20.0
