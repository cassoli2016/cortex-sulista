"""Testes da carga de parametros versionados da DRE por cliente."""
from __future__ import annotations

from api.dre_cliente.params import Params, carregar_params


def test_carregar_params_le_yaml():
    p = carregar_params()
    assert isinstance(p, Params)
    # chaves obrigatorias de deducoes
    for imposto in ("federais", "estaduais", "municipais", "previdenciaria"):
        assert imposto in p.deducoes_pct
        assert isinstance(p.deducoes_pct[imposto], float)
    # chaves de creditos
    for natureza in ("combustivel", "pneus", "manutencao", "frete_contratado"):
        assert natureza in p.creditos_pct
    assert p.rateio_intra_viagem in ("peso", "receita")
    assert isinstance(p.taxa_km_janela_meses, int) and p.taxa_km_janela_meses > 0
    assert isinstance(p.preco_diesel_fallback, float) and p.preco_diesel_fallback > 0


def test_params_deducoes_nao_negativas():
    p = carregar_params()
    assert all(v >= 0 for v in p.deducoes_pct.values())
    assert all(v >= 0 for v in p.creditos_pct.values())


def test_carregar_params_faltando_chave_levanta(tmp_path):
    ruim = tmp_path / "ruim.yaml"
    ruim.write_text("rateio_intra_viagem: peso\n", encoding="utf-8")
    try:
        carregar_params(ruim)
    except ValueError:
        return
    raise AssertionError("esperava ValueError por chave obrigatoria faltando")
