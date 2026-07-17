"""Testes do modelo de linhas da DRE por cliente (espelho ate Margem Direta)."""
from __future__ import annotations

from api.dre_cliente.modelo import (
    LINHAS_CLIENTE,
    classificar_cf,
    classificar_cv,
    metodo_da_linha,
    rotulos,
)
from api.queries import DRE_MODELO

# linhas ate MC seguem a ordem da DRE oficial; CUSTO FIXO e reordenado (apos MC,
# formato por-cliente do spec) e as linhas MARGEM sao novas.
_PRE_MC = ["RECEITA BRUTA", "DEDUCOES DA RECEITA", "IMPOSTOS FEDERAIS",
           "IMPOSTOS ESTADUAIS", "IMPOSTOS MUNICIPAIS", "CONTRIBUICAO PREVIDENCIARIA",
           "ANULACOES", "DESCONTOS", "RECEITA LIQUIDA", "CUSTO VARIAVEL",
           "CREDITOS TRIBUTARIOS"]


def test_lista_termina_em_margem_direta():
    assert rotulos()[-1] == "MARGEM DIRETA DO CLIENTE"
    assert "MARGEM DE CONTRIBUICAO" in rotulos()
    assert "CUSTO FIXO" in rotulos()


def test_pre_mc_e_subsequencia_da_dre_oficial():
    oficiais = [l[0] for l in DRE_MODELO]
    filtradas = [o for o in oficiais if o in set(_PRE_MC)]
    assert filtradas == _PRE_MC


def test_nao_desce_estrutura_nem_lucro_bruto():
    assert "LUCRO BRUTO" not in rotulos()
    assert "CSP" not in rotulos()


def test_metodo_por_linha():
    assert metodo_da_linha("IMPOSTOS FEDERAIS") == "deducao_pct"
    assert metodo_da_linha("CONTRIBUICAO PREVIDENCIARIA") == "deducao_pct"
    assert metodo_da_linha("CREDITOS TRIBUTARIOS") == "credito_pct"
    assert metodo_da_linha("RECEITA LIQUIDA") == "formula"
    assert metodo_da_linha("RECEITA BRUTA") == "direto_viagem"
    assert metodo_da_linha("CUSTO FIXO") == "fixo_dia_veiculo"
    assert metodo_da_linha("MARGEM DIRETA DO CLIENTE") == "formula"


def test_classificar_cv():
    assert classificar_cv("CV - FRETE AGREGADOS") == "direto_viagem"
    assert classificar_cv("CV - FRETE TERCEIROS") == "direto_viagem"
    assert classificar_cv("CV - MANUTENCAO") == "taxa_km"
    assert classificar_cv("CV - PNEUS") == "taxa_km"
    assert classificar_cv("CV - COMBUSTIVEL") == "combustivel_km"
    assert classificar_cv("CV - PEDAGIO") == "direto_viagem"


def test_classificar_cf():
    assert classificar_cf("CF - LOCACAO DE EQUIPAMENTOS") == "locado"
    assert classificar_cf("CF - DEPRECIACAO OPERACIONAL") == "proprio"
    assert classificar_cf("CF - JUROS DE FINANCIAMENTOS") == "proprio"
    assert classificar_cf("CF - FOLHA MOT") == "ativo"
    assert classificar_cf("CF - RASTREAMENTO") == "ativo"
    assert classificar_cf("CF - IPVA/LICENCIAMENTOS") == "ativo"
    assert classificar_cf("CF - SEGURO DE VEICULOS") == "ativo"
    assert classificar_cf("CF - PESSOAL OPERACIONAL") == "nao_desce"
    assert classificar_cf("CF - DESPESAS ADM") == "nao_desce"
    assert classificar_cf("CF - SEGURO PATRIMONIAL") == "nao_desce"


def test_formula_componentes_da_margem_direta():
    linha = next(l for l in LINHAS_CLIENTE if l.rotulo == "MARGEM DIRETA DO CLIENTE")
    assert linha.componentes == ["MARGEM DE CONTRIBUICAO", "CUSTO FIXO"]
