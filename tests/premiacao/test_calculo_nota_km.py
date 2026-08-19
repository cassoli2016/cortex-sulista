"""Regra nova: premio = km × valor_por_km × (nota/100), com cortes.

Os números de conferência são reais, medidos na API em 19/08/2026 (abril/2026).
"""
from __future__ import annotations

from api.premiacao import calculo

PARAMS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}


def _m(nome="FULANO", km=5200.0, nota=99.0, **kw):
    return {"driverId": 1, "driverName": nome, "km": km, "nota": nota, **kw}


def test_formula_confere_com_o_exemplo_aprovado():
    """JEAN LAURO, abril/2026: 5.200 km, nota 99, a R$ 0,10/km = R$ 514,80."""
    r = calculo.calcular([_m(km=5200.0, nota=99.0)], PARAMS)
    assert r["linhas"][0]["premio"] == 514.80


def test_outros_dois_exemplos_aprovados():
    r = calculo.calcular([_m(nome="AGNALDO", km=2840.0, nota=81.0),
                          _m(nome="ANGELA", km=2595.0, nota=73.0)], PARAMS)
    premios = {l["driverName"]: l["premio"] for l in r["linhas"]}
    assert premios["AGNALDO"] == 230.04
    assert premios["ANGELA"] == 189.44


def test_nota_abaixo_da_minima_nao_premia_mas_continua_visivel():
    r = calculo.calcular([_m(nota=69.0)], PARAMS)
    linha = r["linhas"][0]
    assert linha["premio"] == 0
    assert linha["elegivel"] is False
    assert linha["motivo"] == "nota abaixo da mínima"


def test_km_abaixo_do_minimo_nao_premia():
    r = calculo.calcular([_m(km=1499.0)], PARAMS)
    assert r["linhas"][0]["premio"] == 0
    assert r["linhas"][0]["motivo"] == "km abaixo do mínimo"


def test_totais_contam_so_os_elegiveis():
    r = calculo.calcular([_m(nome="OK", km=5200.0, nota=99.0),
                          _m(nome="NOTA BAIXA", km=5200.0, nota=50.0),
                          _m(nome="POUCO KM", km=100.0, nota=99.0)], PARAMS)
    assert r["premiados"] == 1
    assert r["premio_total"] == 514.80
    assert r["motoristas"] == 3


def test_km_ou_nota_negativos_nao_geram_premio():
    """Leitura implausível de telemetria não pode virar dinheiro."""
    for ruim in (_m(km=-100.0), _m(nota=-5.0)):
        r = calculo.calcular([ruim], PARAMS)
        assert r["linhas"][0]["premio"] == 0


def test_nota_acima_de_cem_e_tratada_como_cem():
    """Score é uma nota de 0 a 100; acima disso é defeito da origem e não pode
    inflar o prêmio. Km acima do mínimo de propósito: o corte de km vem antes e
    mascararia o teto da nota."""
    r = calculo.calcular([_m(km=2000.0, nota=150.0)], PARAMS)
    assert r["linhas"][0]["premio"] == 200.00


def test_o_corte_de_nota_vem_antes_do_corte_de_km():
    """Quem falha nos dois critérios recebe o motivo da nota — é o que o
    gestor precisa ver primeiro para conversar com o motorista."""
    r = calculo.calcular([_m(km=10.0, nota=10.0)], PARAMS)
    assert r["linhas"][0]["motivo"] == "nota abaixo da mínima"


def test_lista_vazia_nao_quebra():
    r = calculo.calcular([], PARAMS)
    assert r["premio_total"] == 0 and r["premiados"] == 0


def test_a_regra_e_identificada_no_resultado():
    """O snapshot grava qual regra gerou o valor: mês antigo continua exibindo
    o valor com que foi pago."""
    r = calculo.calcular([_m()], PARAMS)
    assert r["regra"] == "nota_km"
