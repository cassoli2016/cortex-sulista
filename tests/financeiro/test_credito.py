"""Limites de cheque empresa — o que cobre o buraco quando antecipar não basta.

O número que motivou o módulo: o rotativo custa de 12,90% a 16,20% ao mês,
contra ~2% da antecipação. É de seis a oito vezes mais caro, o que inverte a
prioridade — antecipar é o PRIMEIRO recurso, não o último antes do limite.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.financeiro import credito


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setattr(credito, "CAMINHO", tmp_path / "credito.json")


def test_padrao_traz_a_posicao_informada():
    linhas = credito.ler()
    assert {l["banco"] for l in linhas} == {"Itaú", "Santander", "Sicredi"}
    assert credito.resumo()["total"] == 485000.0


def test_ordem_e_da_taxa_menor_para_a_maior():
    """Consumir o limite caro primeiro queima dinheiro sem motivo."""
    taxas = [l["taxa_mes"] for l in credito.ler()]
    assert taxas == sorted(taxas)
    assert credito.ler()[0]["banco"] == "Sicredi"


def test_taxa_efetiva_e_ponderada_pelo_limite():
    """Média simples mentiria: o Sicredi é o mais barato E o menor limite."""
    r = credito.resumo()
    media_simples = sum(l["taxa_mes"] for l in r["linhas"]) / 3
    assert r["taxa_efetiva"] == pytest.approx(15.67, abs=0.01)
    assert r["taxa_efetiva"] > media_simples


def test_cobertura_consome_do_mais_barato_e_reporta_o_que_sobra():
    c = credito.cobrir(3151222.68)
    assert c["coberto"] == 485000.0
    assert c["descoberto"] == pytest.approx(2666222.68, abs=0.01)
    assert [u["banco"] for u in c["usos"]] == ["Sicredi", "Itaú", "Santander"]
    assert c["custo_mes"] == pytest.approx(75999.0, abs=0.01)


def test_buraco_menor_que_o_limite_nao_usa_o_banco_caro():
    c = credito.cobrir(25000.0)
    assert c["descoberto"] == 0.0
    assert [u["banco"] for u in c["usos"]] == ["Sicredi"]
    assert c["custo_mes"] == pytest.approx(3225.0, abs=0.01)


def test_limite_vencendo_em_90_dias_aparece():
    r = credito.resumo(hoje=date(2026, 8, 24))
    assert [v["banco"] for v in r["vencendo"]] == ["Santander"]
    assert r["vencendo"][0]["dias_para_vencer"] == 62


def test_taxa_anual_no_lugar_da_mensal_e_recusada():
    """Trocar 15,69% a.m. por 188% a.a. faria o custo do buraco errar 12x."""
    with pytest.raises(ValueError, match="ANUAL"):
        credito.gravar([{"banco": "X", "limite": 1000, "taxa_mes": 188.0}])


def test_gravar_substitui_o_padrao():
    credito.gravar([{"banco": "Novo", "limite": 50000, "taxa_mes": 9.5}])
    assert credito.resumo()["total"] == 50000.0
    assert credito.ler()[0]["banco"] == "Novo"


def test_linha_inativa_sai_da_conta():
    credito.gravar([{"banco": "A", "limite": 100.0, "taxa_mes": 10.0},
                    {"banco": "B", "limite": 900.0, "taxa_mes": 11.0,
                     "ativo": False}])
    assert credito.resumo()["total"] == 100.0
