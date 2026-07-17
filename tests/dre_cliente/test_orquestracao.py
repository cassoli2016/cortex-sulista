"""Teste de wiring da orquestracao _calcular (fetch mockado, sem banco)."""
from __future__ import annotations

from datetime import date

import api.dre_cliente as dc
from api.dre_cliente import sql
from api.dre_cliente.params import carregar_params


def _mock_fetch(monkeypatch):
    viagens = [
        {"id": "v1", "placa": "AAA", "dtsaida": date(2026, 1, 2),
         "dtchegada": date(2026, 1, 3), "tipo": 1, "km": 1000.0,
         "valorfrete": 10000.0, "valorfretecompra": 0.0, "is_proprio": True,
         "tipo_operacao": "TRA", "cliente_codigo": "AG1", "cliente_nome": "ACME"},
        {"id": "v2", "placa": "AAA", "dtsaida": date(2026, 1, 4),
         "dtchegada": date(2026, 1, 4), "tipo": 3, "km": 200.0,
         "valorfrete": 0.0, "valorfretecompra": 0.0, "is_proprio": True,
         "tipo_operacao": "TRA", "cliente_codigo": None, "cliente_nome": None},
        {"id": "v3", "placa": "BBB", "dtsaida": date(2026, 1, 5),
         "dtchegada": date(2026, 1, 6), "tipo": 1, "km": 500.0,
         "valorfrete": 4000.0, "valorfretecompra": 2500.0, "is_proprio": False,
         "tipo_operacao": "AGR", "cliente_codigo": "AG2", "cliente_nome": "BETA"},
    ]
    monkeypatch.setattr(sql, "fetch_viagens", lambda *a, **k: viagens)
    monkeypatch.setattr(sql, "fetch_heuristica_cliente", lambda *a, **k: {})
    monkeypatch.setattr(sql, "fetch_abastecimentos", lambda *a, **k: {"AAA": 3000.0})
    monkeypatch.setattr(sql, "fetch_taxa_km", lambda *a, **k: {"AAA": 0.5})
    monkeypatch.setattr(sql, "fetch_dre_oficial", lambda *a, **k: {
        "RECEITA BRUTA": 14000.0, "IMPOSTOS FEDERAIS": -511.0,
        "IMPOSTOS ESTADUAIS": -1680.0, "IMPOSTOS MUNICIPAIS": 0.0,
        "CONTRIBUICAO PREVIDENCIARIA": -210.0, "ANULACOES": 0.0, "DESCONTOS": 0.0,
        "CUSTO VARIAVEL": -6500.0, "CREDITOS TRIBUTARIOS": 700.0, "CUSTO FIXO": -4000.0,
    })
    monkeypatch.setattr(sql, "fetch_cv_detalhe", lambda *a, **k: [
        {"agrupador": "CV - MANUTENCAO", "total": -600.0},
        {"agrupador": "CV - COMBUSTIVEL", "total": -3000.0},
    ])
    monkeypatch.setattr(sql, "fetch_cf_detalhe", lambda *a, **k: [
        {"agrupador": "CF - FOLHA MOT", "total": -1500.0},
        {"agrupador": "CF - DEPRECIACAO OPERACIONAL", "total": -500.0},
        {"agrupador": "CF - PESSOAL OPERACIONAL", "total": -2000.0},  # nao desce
    ])


def test_calcular_reconcilia_e_lista_clientes(monkeypatch):
    _mock_fetch(monkeypatch)
    params = carregar_params()
    # _calcular nao levanta AssertionError => balanco da reconciliacao fecha
    r = dc._calcular(cur=None, comp_de="2026-01", comp_ate="2026-01",
                     filial=None, params=params)

    nomes = {c["cliente"] for c in r["clientes"]}
    assert "ACME" in nomes and "BETA" in nomes

    acme = next(c for c in r["clientes"] if c["cliente"] == "ACME")
    assert abs(acme["linhas"]["RECEITA BRUTA"] - 10000.0) < 1e-6
    # km vazio (v2) foi atribuido a ACME
    assert abs(acme["indicadores"]["km_vazio"] - 200.0) < 1e-6

    # balanco explicito por linha: descido + nao_alocado + variacao = oficial
    for linha, rec in r["reconciliacao"].items():
        assert abs(rec["descido"] + rec["nao_alocado"] + rec["variacao_absorcao"]
                   - rec["oficial"]) < 1e-6

    # v2: CF alocado e Margem Direta presentes; CF do ACME <= MC (custo reduz)
    assert "CUSTO FIXO" in acme["linhas"]
    assert "MARGEM DIRETA DO CLIENTE" in acme["linhas"]
    assert acme["linhas"]["CUSTO FIXO"] <= 0.0
    assert abs(acme["linhas"]["MARGEM DIRETA DO CLIENTE"]
               - (acme["linhas"]["MARGEM DE CONTRIBUICAO"] + acme["linhas"]["CUSTO FIXO"])) < 1e-6
    # CF descido reconciliado: so o alocavel (folha+deprec=-2000) desce; pessoal (-2000) nao
    assert abs(r["reconciliacao"]["CUSTO FIXO"]["descido"] - (-2000.0)) < 1e-6


def test_repasse_agregado_desce_em_custo_variavel(monkeypatch):
    _mock_fetch(monkeypatch)
    params = carregar_params()
    r = dc._calcular(cur=None, comp_de="2026-01", comp_ate="2026-01",
                     filial=None, params=params)
    beta = next(c for c in r["clientes"] if c["cliente"] == "BETA")
    # repasse de 2500 do agregado entra negativo no custo variavel do BETA
    assert beta["linhas"]["CUSTO VARIAVEL"] <= -2500.0
