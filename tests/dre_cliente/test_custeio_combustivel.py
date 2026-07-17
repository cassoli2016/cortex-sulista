"""Testes do custeio de combustivel proprio (rateio por km)."""
from __future__ import annotations

from api.dre_cliente.custeio import custear_combustivel


def _kmv(id, placa, km, proprio):
    return {"id": id, "placa": placa, "km": km, "is_proprio": proprio}


def test_rateio_proporcional_ao_km():
    abastec = {"AAA": 400.0}
    km = [_kmv(1, "AAA", 100.0, True), _kmv(2, "AAA", 300.0, True)]
    r = custear_combustivel(abastec, km)
    # convencao DRE: custo entra negativo
    assert r == {1: -100.0, 2: -300.0}


def test_soma_dos_rateios_igual_ao_custo_do_veiculo():
    abastec = {"AAA": 999.0}
    km = [_kmv(1, "AAA", 33.0, True), _kmv(2, "AAA", 67.0, True)]
    r = custear_combustivel(abastec, km)
    assert abs(sum(r.values()) - (-999.0)) < 1e-6


def test_agregado_terceiro_nao_recebe_combustivel():
    abastec = {"AAA": 400.0}
    km = [_kmv(1, "AAA", 100.0, False)]
    assert custear_combustivel(abastec, km) == {1: 0.0}


def test_veiculo_sem_km_nao_divide_por_zero():
    abastec = {"AAA": 400.0}
    km = [_kmv(1, "AAA", 0.0, True)]
    assert custear_combustivel(abastec, km) == {1: 0.0}
