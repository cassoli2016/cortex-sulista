"""Testes da agregacao por cliente, formulas e ranking."""
from __future__ import annotations

from api.dre_cliente.agregacao import agregar


def _cenario_um_cliente():
    linhas = {
        "RECEITA BRUTA": {1: 1000.0},
        "IMPOSTOS FEDERAIS": {1: -100.0},
        "CUSTO VARIAVEL": {1: -400.0, 2: -50.0},   # viagem 2 = combustivel do vazio
        "CREDITOS TRIBUTARIOS": {1: 50.0},
    }
    viagem_cliente = {1: "A", 2: "A"}
    viagem_meta = {
        1: {"km": 800.0, "tipo": 1, "is_proprio": True, "tipo_operacao": "FROTA", "dias": 2},
        2: {"km": 200.0, "tipo": 3, "is_proprio": True, "tipo_operacao": "FROTA", "dias": 0},
    }
    return linhas, viagem_cliente, viagem_meta


def test_agrega_linhas_e_formulas():
    r = agregar(*_cenario_um_cliente())
    a = next(c for c in r["clientes"] if c["cliente"] == "A")
    L = a["linhas"]
    assert abs(L["RECEITA BRUTA"] - 1000.0) < 1e-6
    assert abs(L["CUSTO VARIAVEL"] - (-450.0)) < 1e-6
    assert abs(L["DEDUCOES DA RECEITA"] - (-100.0)) < 1e-6
    assert abs(L["RECEITA LIQUIDA"] - 900.0) < 1e-6
    assert abs(L["MARGEM DE CONTRIBUICAO"] - 500.0) < 1e-6


def test_indicadores():
    r = agregar(*_cenario_um_cliente())
    a = next(c for c in r["clientes"] if c["cliente"] == "A")
    ind = a["indicadores"]
    assert abs(ind["km_carregado"] - 800.0) < 1e-6
    assert abs(ind["km_vazio"] - 200.0) < 1e-6
    assert abs(ind["pct_km_vazio"] - 0.2) < 1e-6
    assert ind["viagens"] == 1
    assert abs(ind["mc"] - 500.0) < 1e-6
    assert abs(ind["mc_pct"] - (500.0 / 900.0)) < 1e-6
    assert ind["dias_veiculo"] == 2
    assert abs(ind["mix"]["proprio"] - 1000.0) < 1e-6


def test_ranking_por_mc_pct_desc():
    linhas = {
        "RECEITA BRUTA": {1: 1000.0, 2: 1000.0},
        "CUSTO VARIAVEL": {1: -100.0, 2: -900.0},
    }
    viagem_cliente = {1: "Bom", 2: "Ruim"}
    meta = {
        1: {"km": 100.0, "tipo": 1, "is_proprio": True, "tipo_operacao": "FROTA", "dias": 1},
        2: {"km": 100.0, "tipo": 1, "is_proprio": True, "tipo_operacao": "FROTA", "dias": 1},
    }
    r = agregar(linhas, viagem_cliente, meta)
    nomes = [c["cliente"] for c in r["clientes"]]
    assert nomes.index("Bom") < nomes.index("Ruim")


def test_consolidado_leaf_inclui_sem_cliente():
    linhas = {"RECEITA BRUTA": {1: 1000.0, 2: 500.0}, "CUSTO VARIAVEL": {1: -100.0, 2: -50.0}}
    viagem_cliente = {1: "A", 2: None}
    meta = {
        1: {"km": 100.0, "tipo": 1, "is_proprio": True, "tipo_operacao": "FROTA", "dias": 1},
        2: {"km": 50.0, "tipo": 1, "is_proprio": True, "tipo_operacao": "FROTA", "dias": 1},
    }
    r = agregar(linhas, viagem_cliente, meta)
    assert abs(r["consolidado_leaf"]["RECEITA BRUTA"] - 1500.0) < 1e-6
    assert abs(r["consolidado_leaf"]["CUSTO VARIAVEL"] - (-150.0)) < 1e-6
    nomes = {c["cliente"] for c in r["clientes"]}
    assert "(sem cliente)" in nomes
