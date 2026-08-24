"""Confronto do limite rotativo com uma série de saldos projetados.

O caso que definiu o desenho: a primeira versão confrontava a série INTEIRA e
anunciava "descoberto de R$ 10,4 milhões em jul/2027". Não era falta de
dinheiro — era falta de faturamento lançado. Os meses distantes ficam
negativos por construção, porque a receita ainda não virou título e o custo
já está lá.
"""
from __future__ import annotations

import pytest

from api.queries import _credito_na_serie, _horizonte_confiavel


def _pt(rotulo, saldo, pagar=1000.0):
    return {"periodo": rotulo, "rotulo": rotulo, "saldo": saldo, "pagar": pagar}


# --------------------------------------------------------------------------
# Corte do horizonte
# --------------------------------------------------------------------------

def test_atrasado_sai_da_analise():
    """'Atrasado' é estoque de vencidos, não um período futuro — somar o
    rotativo contra ele misturaria as duas coisas."""
    pts = [_pt("atrasado", -9e6), _pt("2026-08", -100.0), _pt("2026-09", -100.0),
           _pt("2026-10", -100.0), _pt("2026-11", -100.0)]
    assert all(p["periodo"] != "atrasado" for p in _horizonte_confiavel(pts, "periodo"))


def test_corta_onde_os_pagaveis_desabam():
    """Mesma régua do gráfico: abaixo de 40% da média dos três primeiros, o que
    sobra é receita estimada contra custo que não existe no ERP."""
    pts = [_pt("m1", -1.0, 1000.0), _pt("m2", -1.0, 1000.0), _pt("m3", -1.0, 1000.0),
           _pt("m4", -1.0, 900.0), _pt("m5", -1.0, 100.0), _pt("m6", -1.0, 50.0)]
    janela = _horizonte_confiavel(pts, "periodo")
    assert [p["periodo"] for p in janela] == ["m1", "m2", "m3", "m4"]


def test_serie_curta_passa_inteira():
    pts = [_pt("m1", -1.0), _pt("m2", -1.0)]
    assert len(_horizonte_confiavel(pts, "periodo")) == 2


def test_pagaveis_estaveis_nao_cortam_nada():
    pts = [_pt(f"m{i}", -1.0, 1000.0) for i in range(1, 7)]
    assert len(_horizonte_confiavel(pts, "periodo")) == 6


# --------------------------------------------------------------------------
# Confronto com o limite
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _limite(tmp_path, monkeypatch):
    from api.financeiro import credito
    monkeypatch.setattr(credito, "CAMINHO", tmp_path / "credito.json")
    credito.gravar([{"banco": "A", "limite": 300000.0, "taxa_mes": 10.0},
                    {"banco": "B", "limite": 200000.0, "taxa_mes": 20.0}])


def test_saldo_positivo_nao_consome_limite():
    r = _credito_na_serie([_pt(f"m{i}", 5000.0) for i in range(1, 6)],
                          "saldo", "periodo")
    assert r["periodos_no_limite"] == 0 and r["periodos_estourados"] == 0
    assert r["maior_necessidade"] == 0.0


def test_negativo_dentro_do_limite_nao_e_estouro():
    """R$ 380 mil com R$ 500 mil de limite é mês apertado, não mês sem saída —
    era isso que o vermelho único não distinguia."""
    r = _credito_na_serie([_pt("m1", -380000.0)] + [_pt(f"m{i}", 10.0)
                                                    for i in range(2, 6)],
                          "saldo", "periodo")
    assert r["periodos_no_limite"] == 1
    assert r["periodos_estourados"] == 0
    assert r["maior_descoberto"] == 0.0
    # consome o barato primeiro: 300k a 10% + 80k a 20% = 30k + 16k
    assert r["custo_total_estimado"] == pytest.approx(46000.0, abs=0.01)


def test_negativo_acima_do_limite_reporta_o_descoberto():
    r = _credito_na_serie([_pt("m1", -800000.0)] + [_pt(f"m{i}", 10.0)
                                                    for i in range(2, 6)],
                          "saldo", "periodo")
    assert r["periodos_estourados"] == 1
    assert r["maior_descoberto"] == pytest.approx(300000.0, abs=0.01)
    assert r["primeiro_estouro"] == "m1"


def test_criticos_ordenam_pelo_maior_descoberto():
    pts = [_pt("m1", -600000.0), _pt("m2", -900000.0), _pt("m3", -700000.0),
           _pt("m4", 10.0), _pt("m5", 10.0)]
    r = _credito_na_serie(pts, "saldo", "periodo")
    assert [c["rotulo"] for c in r["criticos"]] == ["m2", "m3", "m1"]


def test_o_limite_nao_e_somado_ao_saldo():
    """Limite é crédito, não caixa. Se fosse somado, um saldo de -400k com
    500k de limite viraria +100k de 'disponível' — e ninguém veria o custo."""
    r = _credito_na_serie([_pt("m1", -400000.0)] + [_pt(f"m{i}", 10.0)
                                                    for i in range(2, 6)],
                          "saldo", "periodo")
    assert r["criticos"] == []            # não estourou
    assert r["maior_necessidade"] == 400000.0   # a necessidade continua inteira
    assert r["custo_total_estimado"] > 0        # e ela tem preço


def test_sem_limite_configurado_devolve_nada(monkeypatch):
    from api.financeiro import credito
    monkeypatch.setattr(credito, "ler", lambda: [])
    monkeypatch.setattr(credito, "resumo", lambda hoje=None: {"total": 0})
    assert _credito_na_serie([_pt("m1", -100.0)], "saldo", "periodo") is None


def test_horizonte_analisado_e_declarado():
    """A tela precisa dizer até onde olhou, senão o número parece cobrir o
    horizonte inteiro do filtro."""
    pts = [_pt("m1", -1.0, 1000.0), _pt("m2", -1.0, 1000.0), _pt("m3", -1.0, 1000.0),
           _pt("m4", -1.0, 50.0), _pt("m5", -1.0, 50.0)]
    r = _credito_na_serie(pts, "saldo", "periodo")
    assert r["periodos_analisados"] == 3
    assert r["ate"] == "m3"
    assert r["cortou"] is True
