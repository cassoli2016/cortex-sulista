"""Testes da reconciliacao por plug contra a DRE oficial."""
from __future__ import annotations

from api.dre_cliente.reconciliacao import reconciliar


def test_balanco_por_construcao():
    descido = {"RECEITA BRUTA": 900.0}
    oficial = {"RECEITA BRUTA": 1000.0}
    r = reconciliar(descido, oficial, {})
    linha = r["RECEITA BRUTA"]
    assert abs(linha["nao_alocado"] - 100.0) < 1e-6
    assert abs(linha["cobertura_pct"] - 0.9) < 1e-6
    # balanco: descido + nao_alocado + variacao = oficial
    assert abs(linha["descido"] + linha["nao_alocado"] + linha["variacao_absorcao"]
               - oficial["RECEITA BRUTA"]) < 1e-6


def test_linha_direta_cobertura_total():
    r = reconciliar({"CV AGR": -600.0}, {"CV AGR": -600.0}, {})
    assert abs(r["CV AGR"]["nao_alocado"]) < 1e-6
    assert abs(r["CV AGR"]["cobertura_pct"] - 1.0) < 1e-6


def test_variacao_entra_no_balanco():
    descido = {"CUSTO VARIAVEL": -400.0}
    oficial = {"CUSTO VARIAVEL": -450.0}
    variacao = {"CUSTO VARIAVEL": -50.0}
    r = reconciliar(descido, oficial, variacao)
    assert abs(r["CUSTO VARIAVEL"]["nao_alocado"]) < 1e-6
    assert abs(r["CUSTO VARIAVEL"]["cobertura_pct"] - 1.0) < 1e-6


def test_oficial_zero_sem_div_zero():
    r = reconciliar({"X": 0.0}, {"X": 0.0}, {})
    assert r["X"]["cobertura_pct"] == 1.0
    r2 = reconciliar({"X": 5.0}, {"X": 0.0}, {})
    assert r2["X"]["cobertura_pct"] == 0.0


def test_descido_extra_nao_e_silenciosamente_descartado():
    r = reconciliar({"EXTRA": 10.0}, {}, {})
    assert "EXTRA" in r
    assert abs(r["EXTRA"]["nao_alocado"] - (-10.0)) < 1e-6
