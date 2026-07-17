"""Testes da alocacao de custo fixo por dia-veiculo (v2)."""
from __future__ import annotations

from api.dre_cliente.custeio import alocar_fixo


def test_aloca_ativo_por_dias_proporcional():
    cf = {"proprio": 0.0, "locado": 0.0, "ativo": -1000.0}
    dias = {"A": {"proprio": 0, "locado": 0, "ativo": 30},
            "B": {"proprio": 0, "locado": 0, "ativo": 10}}
    r = alocar_fixo(cf, dias)
    assert abs(r["A"] - (-750.0)) < 1e-6
    assert abs(r["B"] - (-250.0)) < 1e-6


def test_deprec_so_proprio_locacao_so_locado():
    cf = {"proprio": -500.0, "locado": -800.0, "ativo": 0.0}
    dias = {"A": {"proprio": 10, "locado": 0, "ativo": 10},
            "B": {"proprio": 0, "locado": 20, "ativo": 20}}
    r = alocar_fixo(cf, dias)
    assert abs(r["A"] - (-500.0)) < 1e-6   # todo o proprio (deprec) -> A
    assert abs(r["B"] - (-800.0)) < 1e-6   # toda a locacao -> B


def test_soma_alocada_igual_ao_total_quando_ha_dias():
    cf = {"proprio": -100.0, "locado": -200.0, "ativo": -300.0}
    dias = {"A": {"proprio": 5, "locado": 5, "ativo": 10},
            "B": {"proprio": 5, "locado": 15, "ativo": 20}}
    r = alocar_fixo(cf, dias)
    assert abs(sum(r.values()) - (-600.0)) < 1e-6


def test_base_sem_dias_nao_divide_por_zero():
    cf = {"proprio": -500.0, "locado": 0.0, "ativo": 0.0}
    dias = {"A": {"proprio": 0, "locado": 0, "ativo": 0}}
    r = alocar_fixo(cf, dias)
    assert r["A"] == 0.0
