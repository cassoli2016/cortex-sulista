"""Testes de deducoes e creditos por percentual parametrico."""
from __future__ import annotations

from api.dre_cliente.custeio import custear_creditos, custear_deducoes


def test_deducoes_por_imposto_negativas():
    receita = {1: 1000.0, 2: 2000.0}
    pct = {"federais": 0.0365, "estaduais": 0.12}
    r = custear_deducoes(receita, pct)
    assert abs(r["federais"][1] - (-36.5)) < 1e-6
    assert abs(r["federais"][2] - (-73.0)) < 1e-6
    assert abs(r["estaduais"][1] - (-120.0)) < 1e-6


def test_creditos_soma_naturezas_positivo():
    custos = {"combustivel": {1: 100.0}, "pneus": {1: 50.0}}
    pct = {"combustivel": 0.12, "pneus": 0.12}
    r = custear_creditos(custos, pct)
    assert abs(r[1] - 18.0) < 1e-6


def test_creditos_ignora_natureza_sem_pct():
    custos = {"combustivel": {1: 100.0}, "manutencao": {1: 999.0}}
    pct = {"combustivel": 0.10}  # sem manutencao
    r = custear_creditos(custos, pct)
    assert abs(r[1] - 10.0) < 1e-6


def test_creditos_usa_magnitude_do_custo():
    # custo gerador vem negativo (convencao DRE) -> credito continua positivo
    custos = {"combustivel": {1: -100.0}}
    pct = {"combustivel": 0.12}
    r = custear_creditos(custos, pct)
    assert abs(r[1] - 12.0) < 1e-6
