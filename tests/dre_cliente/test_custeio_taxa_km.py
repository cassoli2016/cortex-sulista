"""Testes do custeio por taxa R$/km (manutencao/pneus) + variacao de absorcao."""
from __future__ import annotations

from api.dre_cliente.custeio import custear_taxa_km


def _kmv(id, placa, km, proprio):
    return {"id": id, "placa": placa, "km": km, "is_proprio": proprio}


def test_absorvido_taxa_vezes_km_negativo():
    taxa = {"AAA": 2.0}
    km = [_kmv(1, "AAA", 100.0, True)]
    absorvido, _ = custear_taxa_km(taxa, km, real_do_razao=-250.0)
    assert absorvido == {1: -200.0}


def test_variacao_sub_absorcao():
    taxa = {"AAA": 2.0}
    km = [_kmv(1, "AAA", 100.0, True)]
    _, variacao = custear_taxa_km(taxa, km, real_do_razao=-250.0)
    # real -250, absorvido -200 -> falta -50 (sub-absorcao)
    assert abs(variacao - (-50.0)) < 1e-6


def test_variacao_super_absorcao_positiva():
    taxa = {"AAA": 2.0}
    km = [_kmv(1, "AAA", 100.0, True)]
    _, variacao = custear_taxa_km(taxa, km, real_do_razao=-150.0)
    assert abs(variacao - 50.0) < 1e-6


def test_agregado_terceiro_nao_recebe_taxa():
    taxa = {"AAA": 2.0}
    km = [_kmv(1, "AAA", 100.0, False)]
    absorvido, variacao = custear_taxa_km(taxa, km, real_do_razao=-200.0)
    assert absorvido == {1: 0.0}
    assert abs(variacao - (-200.0)) < 1e-6
