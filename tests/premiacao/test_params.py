"""Parâmetros da premiação — regra nota × km, vigente desde 19/08/2026."""
from __future__ import annotations

import json

import pytest

from api.premiacao import params


def test_arquivo_ausente_devolve_defaults(tmp_path):
    assert params.ler_params(tmp_path / "nao-existe.json") == params.DEFAULTS


def test_defaults_sao_os_da_regra_nova():
    assert sorted(params.DEFAULTS) == ["km_minimo", "nota_minima", "valor_por_km"]


def test_round_trip_e_merge_com_defaults(tmp_path):
    p = tmp_path / "params.json"
    salvo = params.salvar_params({"valor_por_km": 0.15}, p)
    assert salvo["valor_por_km"] == 0.15
    assert salvo["nota_minima"] == params.DEFAULTS["nota_minima"]
    assert params.ler_params(p) == salvo


def test_validacao_rejeita_valores_impossiveis(tmp_path):
    p = tmp_path / "params.json"
    for ruim in ({"valor_por_km": 0}, {"valor_por_km": -1},
                 {"nota_minima": -1}, {"nota_minima": 101},
                 {"km_minimo": -10}):
        with pytest.raises(ValueError):
            params.salvar_params(ruim, p)


def test_tipo_errado_vira_valueerror_nao_typeerror(tmp_path):
    p = tmp_path / "params.json"
    for ruim in ({"valor_por_km": None}, {"nota_minima": []}, {"km_minimo": {}}):
        with pytest.raises(ValueError):
            params.salvar_params(ruim, p)


def test_arquivo_corrompido_ou_invalido_devolve_defaults(tmp_path):
    p = tmp_path / "params.json"
    p.write_text("{ nao é json", encoding="utf-8")
    assert params.ler_params(p) == params.DEFAULTS
    p.write_text(json.dumps({"valor_por_km": -5}), encoding="utf-8")
    assert params.ler_params(p) == params.DEFAULTS


def test_arquivo_no_formato_antigo_cai_nos_defaults(tmp_path):
    """A regra anterior gravava meta/preco_litro/pct_premiacao. Um arquivo
    desses não tem nenhum parâmetro da regra nova — e cair no default é melhor
    que calcular prêmio com valor que ninguém configurou."""
    p = tmp_path / "params.json"
    p.write_text(json.dumps({"meta": 2.0, "preco_litro": 4.93,
                             "pct_premiacao": 0.2, "km_minimo": 500.0}),
                 encoding="utf-8")
    lido = params.ler_params(p)
    assert lido["valor_por_km"] == params.DEFAULTS["valor_por_km"]
    assert lido["nota_minima"] == params.DEFAULTS["nota_minima"]
