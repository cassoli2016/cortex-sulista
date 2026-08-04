"""Cada estratégia recomputável à mão. Sinal: custo NEGATIVO."""
from __future__ import annotations

from api.previsao.motor import (mediana, prever_frete_compra, prever_nivel,
                                prever_pct_receita, prever_razao_completude,
                                prever_receita, prever_sazonal)


def test_receita_ritmo_puro_apos_3_dias_uteis():
    # meta 100, acumulada 40; realizado 36 -> ritmo 0,90; restante 60*0,90=54
    r = prever_receita(real_acum=36.0, meta_acum=40.0, meta_mes=100.0,
                       ating_hist=0.85, dias_meta_decorridos=3)
    assert abs(r["previsto"] - (36.0 + 60.0 * 0.90)) < 1e-9
    assert r["estrategia"] == "driver_fiscal"
    assert any("ritmo" in p for p in r["premissas"])


def test_receita_blend_no_primeiro_dia_util():
    # w = 1/3: ritmo = (1/3)*0,90 + (2/3)*0,85 = 0,8667
    r = prever_receita(36.0, 40.0, 100.0, 0.85, dias_meta_decorridos=1)
    ritmo = (1 / 3) * 0.90 + (2 / 3) * 0.85
    assert abs(r["previsto"] - (36.0 + 60.0 * ritmo)) < 1e-9


def test_receita_sem_meta_cai_no_historico():
    r = prever_receita(0.0, 0.0, 100.0, 0.85, 0)
    assert abs(r["previsto"] - 85.0) < 1e-9  # meta_mes * ating_hist


def test_pct_receita_sinal_negativo():
    r = prever_pct_receita(receita_prev=1000.0, pct=-0.0778, nome_pct="federais 6m")
    assert abs(r["previsto"] - (-77.8)) < 1e-9
    assert r["estrategia"] == "pct_receita"


def test_nivel_mediana():
    assert mediana([1.0, 5.0, 3.0]) == 3.0
    assert mediana([1.0, 2.0, 3.0, 4.0]) == 2.5
    r = prever_nivel([-700.0, -760.0, -720.0], "folha 3m")
    assert r["previsto"] == -720.0 and r["estrategia"] == "nivel"
    assert prever_nivel([], "x")["previsto"] == 0.0


def test_razao_completude_e_guarda_de_divisor():
    fb = prever_nivel([-400.0, -420.0, -410.0], "fallback")
    ok = prever_razao_completude(razao_mtd=-200.0, frac=0.5, fallback=fb)
    assert abs(ok["previsto"] - (-400.0)) < 1e-9
    assert ok["estrategia"] == "razao_completude"
    guard = prever_razao_completude(razao_mtd=-10.0, frac=0.1, fallback=fb)
    assert guard["previsto"] == fb["previsto"]          # nunca divide por quase-zero
    assert any("completude" in p for p in guard["premissas"])


def test_frete_compra_conhecido_mais_projecao():
    # razao mostra -100, viagens mostram -180 (mais informacao) -> conhecido=-180
    # receita prevista 1000, ja realizada 300 -> restante 700 * razao -0,5 = -350
    r = prever_frete_compra(razao_mtd=-100.0, vfc_mtd=180.0, receita_prev=1000.0,
                            receita_mtd=300.0, razao_custo_receita=-0.5)
    assert abs(r["previsto"] - (-180.0 + -350.0)) < 1e-9
    assert r["estrategia"] == "frete_compra"


def test_sazonal_nivel_x_indice():
    # 6 meses de -100 com indices 1.0 -> nivel -100; indice alvo 0,8 -> -80
    r = prever_sazonal([-100.0] * 6, [1.0] * 6, indice_alvo=0.8)
    assert abs(r["previsto"] - (-80.0)) < 1e-9
    assert r["estrategia"] == "sazonal"


def test_formatacao_pt_br_receita():
    """Valida formatação pt-BR em premissas (separador de milhar ponto, decimal vírgula)."""
    r = prever_receita(real_acum=36000.0, meta_acum=40000.0, meta_mes=100000.0,
                       ating_hist=0.85, dias_meta_decorridos=3)
    # Deve conter "R$ 36.000" (pt-BR com ponto separador de milhar)
    assert any("R$ 36.000" in p for p in r["premissas"])
    # Deve conter "R$ 40.000"
    assert any("R$ 40.000" in p for p in r["premissas"])


def test_formatacao_pt_br_percentual():
    """Valida formatação pt-BR em percentuais (vírgula decimal, símbolo %)."""
    r = prever_pct_receita(receita_prev=1000.0, pct=-0.0778, nome_pct="federais 6m")
    # Deve conter "-7,78%" (pt-BR com vírgula decimal)
    assert any("-7,78%" in p for p in r["premissas"])
