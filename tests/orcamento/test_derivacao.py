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


def test_conta_esporadica_cai_para_mediana_so_nos_meses_com_movimento():
    """Decisão do usuário (C1 da revisão final, opção b): a mediana entra SÓ nos
    meses-calendário cujo espelho teve movimento. A regra original gravava a
    mediana nos 12 meses e anualizava a conta em ~12x (R$ 43,7 mi de baseline
    contra R$ 3,9 mi de histórico nas 91 contas esporádicas da base real)."""
    # 2 meses de 12 = 17% < 75%: não é recorrente
    hist = {"9|900": {"2025-09": 300.0, "2026-02": 100.0}}
    linhas = derivar(hist, MESES, 0.0)
    got = _por_mes(linhas, "9|900")
    assert len(got) == 12
    # set/fev (meses com movimento no espelho) recebem a mediana
    assert got[9]["origem"] == "mediana" and got[9]["valor_baseline"] == 200.0
    assert got[2]["origem"] == "mediana" and got[2]["valor_baseline"] == 200.0
    # os outros 10 meses ficam zerados, nunca com a mediana espalhada
    for m in set(range(1, 13)) - {9, 2}:
        assert got[m]["origem"] == "sem_base", f"mês {m}"
        assert got[m]["valor_baseline"] == 0.0, f"mês {m}"
    assert all(l["meses_com_dado"] == 2 for l in got.values())


def test_esporadica_total_anual_fica_na_ordem_do_historico():
    """O total dos 12 meses tem de ser mediana x n (~historico), nunca mediana x 12."""
    hist = {"9|900": {"2025-09": 300.0, "2026-02": 100.0}}
    got = _por_mes(derivar(hist, MESES, 0.0), "9|900")
    total = sum(l["valor_baseline"] for l in got.values())
    assert total == 400.0            # mediana(200) x 2 meses; a regra antiga dava 2400
    hist_fator = derivar(hist, MESES, -0.05)
    assert sum(l["valor_baseline"] for l in _por_mes(hist_fator, "9|900").values()) == 380.0


def test_corte_de_recorrencia_em_75_por_cento():
    assert RECORRENCIA_MIN == 0.75
    # 9 de 12 = 75% -> recorrente
    nove = {m: 1000.0 for m in MESES[:9]}
    got = _por_mes(derivar({"1|100": nove}, MESES, 0.0), "1|100")
    assert got[8]["origem"] == "espelho"      # ago tem base
    # 8 de 12 = 67% -> mediana nos 8 meses com movimento (ago/25..mar/26)
    oito = {m: 1000.0 for m in MESES[:8]}
    got8 = _por_mes(derivar({"1|101": oito}, MESES, 0.0), "1|101")
    meses_com = {int(m[5:7]) for m in MESES[:8]}
    assert all(got8[m]["origem"] == "mediana" for m in meses_com)
    assert all(got8[m]["origem"] == "sem_base" for m in set(range(1, 13)) - meses_com)


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
    assert got[1]["origem"] == "mediana" and got[1]["valor_baseline"] == 600.0
    assert got[2]["origem"] == "mediana"
    # o mês lançado com 0 não é movimento: não recebe a mediana
    assert got[3]["origem"] == "sem_base" and got[3]["valor_baseline"] == 0.0
    assert all(l["meses_com_dado"] == 2 for l in got.values())


def test_todas_as_contas_recebem_12_meses():
    hist = {"1|100": {m: 1.0 for m in MESES}, "2|200": {"2026-03": 5.0}}
    linhas = derivar(hist, MESES, 0.0)
    assert len(linhas) == 24
    assert sorted({l["mes"] for l in linhas}) == list(range(1, 13))


# ------------------------------------------------- semestre × sazonalidade

from api.orcamento.derivacao import derivar_semestre, indices_sazonais

MESES6 = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
MESES24 = [f"{a}-{m:02d}" for a in (2024, 2025) for m in range(7, 13)] + \
          [f"{a}-{m:02d}" for a in (2025, 2026) for m in range(1, 7)]
MESES24 = sorted(set(MESES24))  # jul/24..jun/26, 24 meses


def _serie_linha(valor_por_mes_cal: dict[int, float]) -> dict[str, float]:
    return {m: valor_por_mes_cal.get(int(m[5:7]), 100.0) for m in MESES24}


def test_indice_sazonal_captura_a_queda_de_dezembro():
    serie = {"RECEITA BRUTA": _serie_linha({12: 40.0})}   # dez=40, resto=100
    idx, flat = indices_sazonais(serie, MESES24)
    # media_geral = (22*100 + 2*40)/24 = 95 -> dez = 40/95, demais = 100/95
    assert abs(idx["RECEITA BRUTA"][12] - 40.0 / 95.0) < 1e-9
    assert abs(idx["RECEITA BRUTA"][3] - 100.0 / 95.0) < 1e-9
    assert abs(sum(idx["RECEITA BRUTA"].values()) / 12 - 1.0) < 1e-9   # média 1
    assert flat == []


def test_indice_vira_flat_nas_tres_guardas():
    quase_zero = {m: (100.0 if int(m[5:7]) % 2 else -100.0) for m in MESES24}
    pico = {m: (50.0 if m == "2026-03" else 1.0) for m in MESES24}
    curta = {m: 100.0 for m in MESES24[6:]}            # só 18 meses
    idx, flat = indices_sazonais(
        {"OSCILA": quase_zero, "PICO": pico, "CURTA": curta}, MESES24)
    assert sorted(flat) == ["CURTA", "OSCILA", "PICO"]
    for linha in ("OSCILA", "PICO", "CURTA"):
        assert all(v == 1.0 for v in idx[linha].values())


def test_derivar_semestre_nivel_x_indice_x_fator():
    hist = {"1|100": {m: 100.0 for m in MESES6}}       # nível = 600/6 = 100
    indices = {"CUSTO VARIAVEL": {m: (0.6 if m == 12 else 1.0) for m in range(1, 13)}}
    mapa = {"1|100": "CUSTO VARIAVEL"}
    linhas = derivar_semestre(hist, MESES6, indices, mapa, 0.0)
    por_mes = {l["mes"]: l for l in linhas if l["conta"] == "1|100"}
    assert len(por_mes) == 12
    assert por_mes[12]["valor_baseline"] == 60.0        # 100 × 0,6
    assert por_mes[3]["valor_baseline"] == 100.0
    assert all(l["origem"] == "semestre" for l in por_mes.values())
    assert all(l["meses_com_dado"] == 6 for l in por_mes.values())
    com_fator = derivar_semestre(hist, MESES6, indices, mapa, -0.10)
    assert {l["mes"]: l for l in com_fator}[12]["valor_baseline"] == 54.0


def test_derivar_semestre_conta_sem_movimento_e_linha_sem_indice():
    hist = {"7|700": {}, "1|100": {"2026-02": 300.0}}   # nível 1|100 = 50
    linhas = derivar_semestre(hist, MESES6, {}, {"1|100": "LINHA X", "7|700": "LINHA X"}, 0.0)
    por_conta = {}
    for l in linhas:
        por_conta.setdefault(l["conta"], []).append(l)
    assert all(l["origem"] == "sem_base" and l["valor_baseline"] == 0.0
               for l in por_conta["7|700"])
    # linha sem índice calculado -> flat (índice 1): todos os meses = nível
    assert all(l["valor_baseline"] == 50.0 for l in por_conta["1|100"])
    assert all(l["meses_com_dado"] == 1 for l in por_conta["1|100"])


def test_derivar_semestre_esporadica_diluida_sem_mediana():
    """Sem corte de recorrência: 1 mês de 600 no semestre vira nível 100 em
    todos os meses — o total anual (~1200 com índice flat) é 2× o semestre."""
    hist = {"9|900": {"2026-04": 600.0}}
    linhas = derivar_semestre(hist, MESES6, {}, {"9|900": None}, 0.0)
    assert sum(l["valor_baseline"] for l in linhas) == 1200.0
