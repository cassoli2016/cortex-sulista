"""Testes da agregação orçado x realizado por linha da DRE."""
from __future__ import annotations

from api.orcamento.servico import montar_comparativo

MAPA = {"1|100": "CUSTO VARIAVEL", "1|101": "CUSTO VARIAVEL",
        "1|103": "RECEITA BRUTA", "9|999": None}


def _orc(conta, mes, valor):
    return {"conta": conta, "mes": mes, "valor_efetivo": valor,
            "valor_baseline": valor, "valor_ajustado": None,
            "origem": "espelho", "meses_com_dado": 12}


def test_soma_orcado_e_realizado_por_linha_ate_o_mes():
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    linhas_orc += [_orc("1|103", m, 5000.0) for m in range(1, 13)]
    realizado = {("1|100", 1): -900.0, ("1|100", 2): -1200.0,
                 ("1|103", 1): 4000.0, ("1|103", 2): 4000.0}
    r = montar_comparativo(linhas_orc, realizado, MAPA, ate_mes=2)
    por_linha = {l["linha"]: l for l in r["linhas"]}
    assert por_linha["CUSTO VARIAVEL"]["orcado"] == -2000.0
    assert por_linha["CUSTO VARIAVEL"]["realizado"] == -2100.0
    assert por_linha["RECEITA BRUTA"]["orcado"] == 10000.0
    assert por_linha["RECEITA BRUTA"]["realizado"] == 8000.0


def test_desvio_de_custo_acima_do_orcado_e_desfavoravel():
    """Custo realizado maior que o orçado estoura: favoravel=False."""
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -1300.0}, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["desvio"] == -300.0
    assert cv["favoravel"] is False


def test_custo_abaixo_do_orcado_e_favoravel():
    linhas_orc = [_orc("1|100", 1, -1000.0)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -700.0}, MAPA, ate_mes=1)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["desvio"] == 300.0
    assert cv["favoravel"] is True


def test_receita_abaixo_do_orcado_e_desfavoravel():
    linhas_orc = [_orc("1|103", 1, 5000.0)]
    r = montar_comparativo(linhas_orc, {("1|103", 1): 4000.0}, MAPA, ate_mes=1)
    rb = next(l for l in r["linhas"] if l["linha"] == "RECEITA BRUTA")
    assert rb["desvio"] == -1000.0
    assert rb["favoravel"] is False


def test_conta_sem_linha_nao_entra_no_total_e_e_reportada():
    linhas_orc = [_orc("1|100", 1, -1000.0), _orc("9|999", 1, -500.0)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=1)
    total_cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert total_cv["orcado"] == -1000.0
    assert "9|999" in r["sem_linha"]


def test_meses_depois_do_corte_ficam_fora_do_acumulado():
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=3)
    cv = next(l for l in r["linhas"] if l["linha"] == "CUSTO VARIAVEL")
    assert cv["orcado"] == -3000.0


def test_meses_faltando_na_base_sao_reportados():
    """Derivar espelho sobre base furada viraria zero com cara de orçamento."""
    from api.orcamento.servico import meses_faltando

    meses = ["2025-08", "2025-09", "2025-10"]
    hist = {"1|100": {"2025-08": 1.0}, "2|200": {"2025-09": 2.0}}
    assert meses_faltando(hist, meses) == ["2025-10"]


def test_base_completa_nao_reporta_falta():
    from api.orcamento.servico import meses_faltando

    meses = ["2025-08", "2025-09"]
    hist = {"1|100": {"2025-08": 1.0}, "2|200": {"2025-09": 2.0}}
    assert meses_faltando(hist, meses) == []


def test_grade_traz_as_12_celulas_mesmo_com_ano_nao_iniciado():
    """Sem isso a aba Montagem viria vazia num orçamento do ano que vem."""
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {}, MAPA, ate_mes=0)
    assert r["contas"] == []            # nada acumulado ainda
    g = next(x for x in r["grade"] if x["conta"] == "1|100")
    assert len(g["valores"]) == 12
    assert g["valores"][12] == -1000.0
    assert g["linha"] == "CUSTO VARIAVEL"


def test_serie_mensal_marca_o_mes_sem_realizado():
    """Mês sem realizado não pode virar barra zerada no gráfico."""
    linhas_orc = [_orc("1|100", m, -1000.0) for m in range(1, 13)]
    r = montar_comparativo(linhas_orc, {("1|100", 1): -900.0}, MAPA, ate_mes=1)
    serie = {s["mes"]: s for s in r["mensal"]}
    assert serie[1]["realizado"] == -900.0
    assert serie[1]["fechado"] is True
    assert serie[5]["realizado"] is None
    assert serie[5]["fechado"] is False
