from __future__ import annotations

import json

import pytest

from api.premiacao.params import DEFAULTS, ler_params, salvar_params


def test_arquivo_ausente_devolve_defaults(tmp_path):
    p = ler_params(tmp_path / "nao_existe.json")
    assert p == DEFAULTS
    assert p["meta"] == 2.0 and p["preco_litro"] == 4.93
    assert p["pct_premiacao"] == 0.20 and p["km_minimo"] == 500.0


def test_round_trip_e_merge_com_defaults(tmp_path):
    f = tmp_path / "params.json"
    salvar_params({"meta": 2.2}, f)
    p = ler_params(f)
    assert p["meta"] == 2.2
    assert p["pct_premiacao"] == 0.20          # não informado mantém default
    salvar_params({"pct_premiacao": 0.25}, f)
    p2 = ler_params(f)
    assert p2["meta"] == 2.2 and p2["pct_premiacao"] == 0.25


def test_validacao_rejeita_valores_impossiveis(tmp_path):
    f = tmp_path / "params.json"
    for ruim in ({"meta": 0}, {"meta": -1}, {"preco_litro": 0},
                 {"pct_premiacao": 1.5}, {"pct_premiacao": -0.1}, {"km_minimo": -5}):
        with pytest.raises(ValueError):
            salvar_params(ruim, f)
    assert not f.exists()                       # inválido não grava


def test_chave_desconhecida_e_ignorada(tmp_path):
    f = tmp_path / "params.json"
    salvar_params({"meta": 2.1, "hacker": "x"}, f)
    assert "hacker" not in json.loads(f.read_text())
