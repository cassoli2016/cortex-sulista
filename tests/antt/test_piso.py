"""Piso mínimo: fórmula, vazio a 92%, e os estados de não-cálculo."""
from __future__ import annotations

from datetime import date

from api.antt.piso import avaliar, calcular_piso

QUANDO = date(2026, 8, 1)  # vigência da Res. 6.084/2026


def test_formula_basica_km_vezes_ccd_mais_cc():
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2, quando=QUANDO)
    assert r["estado"] == "calculado"
    assert abs(r["piso"] - (500.0 * 3.9826 + 451.84)) < 1e-9
    assert r["resolucao"] == "6.084/2026"


def test_confere_com_a_calculadora_oficial_da_antt():
    """Oráculo: calculadorafrete.antt.gov.br, carga geral 5 eixos, 500 km,
    consultado em 18/08/2026 -> R$ 3.993,46."""
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=5, quando=QUANDO)
    assert abs(r["piso"] - 3993.46) < 0.01


def test_vazio_obrigatorio_paga_92_por_cento_do_ccd_sem_cc():
    r = calcular_piso(km=300.0, tipo_carga="conteinerizada", eixos=5,
                      quando=QUANDO, vazio=True, vazio_obrigatorio=True)
    assert r["estado"] == "calculado"
    assert abs(r["piso"] - (0.92 * r["ccd"] * 300.0)) < 1e-9
    assert r["cc"] is None  # carga e descarga não incide em deslocamento vazio


def test_vazio_confere_com_a_calculadora_oficial():
    """Oráculo: a própria calculadora imprime a fórmula do retorno vazio como
    '0,92 x Distância x CCD'. Conteinerizada 5 eixos, 400 km -> R$ 2.441,50."""
    r = calcular_piso(km=400.0, tipo_carga="conteinerizada", eixos=5,
                      quando=QUANDO, vazio=True, vazio_obrigatorio=True)
    assert abs(r["piso"] - 2441.50) < 0.01


def test_vazio_sem_obrigacao_e_isento_nao_abaixo_do_piso():
    r = calcular_piso(km=300.0, tipo_carga="carga_geral", eixos=5,
                      quando=QUANDO, vazio=True, vazio_obrigatorio=False)
    assert r["estado"] == "isento"
    assert r["piso"] is None


def test_sem_eixos_nao_inventa_numero():
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=None, quando=QUANDO)
    assert r["estado"] == "sem_eixos"
    assert r["piso"] is None


def test_sem_tipo_de_carga_nao_inventa_numero():
    r = calcular_piso(km=500.0, tipo_carga=None, eixos=5, quando=QUANDO)
    assert r["estado"] == "sem_carga"
    assert r["piso"] is None


def test_km_zero_e_estado_proprio():
    r = calcular_piso(km=0.0, tipo_carga="carga_geral", eixos=5, quando=QUANDO)
    assert r["estado"] == "sem_km"
    assert r["piso"] is None


def test_tipo_de_carga_desconhecido_vira_sem_tabela():
    r = calcular_piso(km=100.0, tipo_carga="carga_imaginaria", eixos=5, quando=QUANDO)
    assert r["estado"] == "sem_tabela"
    assert r["piso"] is None


def test_viagem_antiga_usa_a_tabela_da_epoca():
    r = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2,
                      quando=date(2026, 3, 15))
    assert r["resolucao"] == "6.076/2026"
    assert abs(r["piso"] - (500.0 * 3.6815 + 436.39)) < 1e-9


def test_avaliar_marca_abaixo_do_piso():
    calc = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2, quando=QUANDO)
    a = avaliar(pago=1000.00, piso_calc=calc)
    assert a["abaixo"] is True
    assert abs(a["gap"] - (1000.00 - calc["piso"])) < 1e-9


def test_avaliar_nao_julga_o_que_nao_foi_calculado():
    calc = calcular_piso(km=500.0, tipo_carga=None, eixos=None, quando=QUANDO)
    a = avaliar(pago=1000.00, piso_calc=calc)
    assert a["abaixo"] is False
    assert a["gap"] is None


def test_pago_exatamente_no_piso_nao_e_abaixo():
    calc = calcular_piso(km=500.0, tipo_carga="carga_geral", eixos=2, quando=QUANDO)
    a = avaliar(pago=calc["piso"], piso_calc=calc)
    assert a["abaixo"] is False
