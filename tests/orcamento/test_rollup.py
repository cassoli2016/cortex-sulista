"""Testes do rollup conta -> agrupador -> linha da DRE."""
from __future__ import annotations

from api.orcamento.rollup import (contas_sem_agrupador, linha_da_conta,
                                  mapa_conta_linha)

AGRUP = {
    "1|100": "CV - COMBUSTIVEL",
    "1|101": "CF - LOCACAO DE EQUIPAMENTOS",
    "1|102": "OVERHEAD - DESPESAS ADM",
    "1|103": "RECEITA OPERACIONAL BRUTA",
    "1|104": "IMPOSTOS FEDERAIS",
}


def test_conta_cai_na_linha_certa_da_cascata():
    assert linha_da_conta("1|100", AGRUP, {}) == "CUSTO VARIAVEL"
    assert linha_da_conta("1|101", AGRUP, {}) == "CUSTO FIXO"
    assert linha_da_conta("1|102", AGRUP, {}) == "OVERHEAD"
    assert linha_da_conta("1|103", AGRUP, {}) == "RECEITA BRUTA"
    assert linha_da_conta("1|104", AGRUP, {}) == "IMPOSTOS FEDERAIS"


def test_ajuste_contabil_local_muda_a_linha():
    """Reclassificar na tela de Contabilidade tem de mover o orçado junto."""
    ajustes = {"1|100": {"agrupador": "CF - LOCACAO DE EQUIPAMENTOS"}}
    assert linha_da_conta("1|100", AGRUP, ajustes) == "CUSTO FIXO"


def test_conta_sem_agrupador_nao_tem_linha():
    assert linha_da_conta("9|999", AGRUP, {}) is None


def test_mapa_cobre_todas_as_contas_conhecidas():
    m = mapa_conta_linha(AGRUP, {})
    assert set(m) == set(AGRUP)
    assert m["1|100"] == "CUSTO VARIAVEL"


def test_lista_as_contas_que_precisam_ser_classificadas():
    contas = ["1|100", "9|998", "9|999"]
    assert contas_sem_agrupador(contas, AGRUP, {}) == ["9|998", "9|999"]


def test_ajuste_resolve_conta_antes_sem_agrupador():
    ajustes = {"9|999": {"agrupador": "CV - MANUTENCAO"}}
    assert contas_sem_agrupador(["9|999"], AGRUP, ajustes) == []
    assert linha_da_conta("9|999", AGRUP, ajustes) == "CUSTO VARIAVEL"
