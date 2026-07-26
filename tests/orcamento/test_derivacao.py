"""Testes da derivação do baseline orçamentário (mês espelho + tendência)."""
from __future__ import annotations

from api.orcamento.derivacao import RECORRENCIA_MIN, derivar

# 12 meses fechados de base: ago/25 .. jul/26
MESES = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
         "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]


def _por_mes(linhas, conta):
    return {l["mes"]: l for l in linhas if l["conta"] == conta}


def test_conta_recorrente_usa_mes_espelho():
    # valor diferente em cada mês: o alvo tem de pegar o MESMO mês-calendário
    hist = {"1|100": {m: float(i + 1) * 1000 for i, m in enumerate(MESES)}}
    linhas = derivar(hist, MESES, 0.0)
    got = _por_mes(linhas, "1|100")
    assert got[12]["valor_baseline"] == 5000.0   # dez alvo <- 2025-12 (5º da lista)
    assert got[1]["valor_baseline"] == 6000.0    # jan alvo <- 2026-01
    assert got[7]["valor_baseline"] == 12000.0   # jul alvo <- 2026-07
    assert all(l["origem"] == "espelho" for l in got.values())


def test_fator_de_tendencia_multiplica():
    hist = {"1|100": {m: 1000.0 for m in MESES}}
    linhas = derivar(hist, MESES, -0.10)
    assert _por_mes(linhas, "1|100")[3]["valor_baseline"] == 900.0


def test_sazonalidade_de_dezembro_e_preservada():
    # dez vale 40% dos demais — o baseline de dezembro tem de refletir isso
    hist = {"1|100": {m: (4000.0 if m.endswith("-12") else 10000.0) for m in MESES}}
    got = _por_mes(derivar(hist, MESES, 0.0), "1|100")
    assert got[12]["valor_baseline"] == 4000.0
    assert got[11]["valor_baseline"] == 10000.0


def test_conta_esporadica_cai_para_mediana_e_marca_base_fraca():
    # 2 meses de 12 = 17% < 75%: não é recorrente
    hist = {"9|900": {"2025-09": 300.0, "2026-02": 100.0}}
    linhas = derivar(hist, MESES, 0.0)
    got = _por_mes(linhas, "9|900")
    assert len(got) == 12
    assert all(l["origem"] == "mediana" for l in got.values())
    assert all(l["valor_baseline"] == 200.0 for l in got.values())  # mediana(100,300)
    assert all(l["meses_com_dado"] == 2 for l in got.values())


def test_corte_de_recorrencia_em_75_por_cento():
    assert RECORRENCIA_MIN == 0.75
    # 9 de 12 = 75% -> recorrente
    nove = {m: 1000.0 for m in MESES[:9]}
    got = _por_mes(derivar({"1|100": nove}, MESES, 0.0), "1|100")
    assert got[8]["origem"] == "espelho"      # ago tem base
    # 8 de 12 = 67% -> mediana
    oito = {m: 1000.0 for m in MESES[:8]}
    got8 = _por_mes(derivar({"1|101": oito}, MESES, 0.0), "1|101")
    assert all(l["origem"] == "mediana" for l in got8.values())


def test_mes_sem_base_em_conta_recorrente_sai_zerado_e_marcado():
    # recorrente (11 de 12), mas sem dezembro: dez alvo não pode inventar valor
    hist = {"1|100": {m: 1000.0 for m in MESES if m != "2025-12"}}
    got = _por_mes(derivar(hist, MESES, 0.0), "1|100")
    assert got[12]["valor_baseline"] == 0.0
    assert got[12]["origem"] == "sem_base"
    assert got[1]["origem"] == "espelho"


def test_valores_negativos_de_custo_sao_preservados():
    # custo entra como credito-debito, ou seja, negativo
    hist = {"4|400": {m: -2500.0 for m in MESES}}
    got = _por_mes(derivar(hist, MESES, 0.20), "4|400")
    assert got[5]["valor_baseline"] == -3000.0


def test_conta_sem_nenhum_movimento_sai_sem_base():
    got = _por_mes(derivar({"7|700": {}}, MESES, 0.0), "7|700")
    assert len(got) == 12
    assert all(l["origem"] == "sem_base" and l["valor_baseline"] == 0.0
               for l in got.values())


def test_zero_nao_conta_como_mes_com_movimento():
    # conta lançada com 0 em 10 meses e valor em 2 não é recorrente
    hist = {"5|500": {m: 0.0 for m in MESES}}
    hist["5|500"]["2026-01"] = 500.0
    hist["5|500"]["2026-02"] = 700.0
    got = _por_mes(derivar(hist, MESES, 0.0), "5|500")
    assert all(l["origem"] == "mediana" for l in got.values())
    assert all(l["meses_com_dado"] == 2 for l in got.values())


def test_todas_as_contas_recebem_12_meses():
    hist = {"1|100": {m: 1.0 for m in MESES}, "2|200": {"2026-03": 5.0}}
    linhas = derivar(hist, MESES, 0.0)
    assert len(linhas) == 24
    assert sorted({l["mes"] for l in linhas}) == list(range(1, 13))
