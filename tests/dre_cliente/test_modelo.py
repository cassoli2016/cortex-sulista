"""Testes do modelo de linhas da DRE por cliente (espelho ate MC)."""
from __future__ import annotations

from api.dre_cliente.modelo import (
    LINHAS_CLIENTE,
    classificar_cv,
    metodo_da_linha,
    rotulos,
)
from api.queries import DRE_MODELO


def test_lista_termina_em_margem_de_contribuicao():
    assert rotulos()[-1] == "MARGEM DE CONTRIBUICAO"


def test_backbone_e_subsequencia_da_dre_oficial():
    """As linhas (menos a MC, que e nova) aparecem na MESMA ordem da DRE_MODELO."""
    oficiais = [l[0] for l in DRE_MODELO]
    backbone = [r for r in rotulos() if r != "MARGEM DE CONTRIBUICAO"]
    filtradas = [o for o in oficiais if o in set(backbone)]
    assert filtradas == backbone


def test_nao_desce_custo_fixo_no_v1():
    assert "CUSTO FIXO" not in rotulos()
    assert "LUCRO BRUTO" not in rotulos()


def test_metodo_por_linha():
    assert metodo_da_linha("IMPOSTOS FEDERAIS") == "deducao_pct"
    assert metodo_da_linha("CONTRIBUICAO PREVIDENCIARIA") == "deducao_pct"
    assert metodo_da_linha("CREDITOS TRIBUTARIOS") == "credito_pct"
    assert metodo_da_linha("RECEITA LIQUIDA") == "formula"
    assert metodo_da_linha("RECEITA BRUTA") == "direto_viagem"


def test_classificar_cv():
    assert classificar_cv("CV - FRETE AGREGADOS") == "direto_viagem"
    assert classificar_cv("CV - FRETE TERCEIROS") == "direto_viagem"
    assert classificar_cv("CV - MANUTENCAO") == "taxa_km"
    assert classificar_cv("CV - PNEUS") == "taxa_km"
    assert classificar_cv("CV - COMBUSTIVEL") == "combustivel_km"
    assert classificar_cv("CV - PEDAGIO") == "direto_viagem"


def test_formula_componentes_da_mc():
    linha = next(l for l in LINHAS_CLIENTE if l.rotulo == "MARGEM DE CONTRIBUICAO")
    assert linha.componentes == ["RECEITA LIQUIDA", "CUSTO VARIAVEL", "CREDITOS TRIBUTARIOS"]
