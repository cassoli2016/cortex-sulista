# tests/previsao/test_servico.py
from __future__ import annotations

from datetime import date

from api.previsao import motor
from api.previsao.servico import montar_resposta, resolver_modo


def test_resolver_modo():
    assert resolver_modo("2026-08", date(2026, 8, 2)) == ("corrente", 2)
    modo, dia_rel = resolver_modo("2026-07", date(2026, 8, 2))
    assert modo == "fechando" and dia_rel == 32          # 01/07 -> 02/08 = 32 dias
    assert resolver_modo("2026-05", date(2026, 8, 2))[0] == "fechado"
    assert resolver_modo("2026-07", date(2026, 9, 20))[0] == "fechado"  # dia_rel > 45


def _ctx_minimo():
    """Contexto sintetico: receita via driver, folha via nivel, combustivel via
    razao/completude. Numeros recomputaveis a mao."""
    meses6 = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    hist = {
        "RECEITA OPERACIONAL BRUTA AGREGADO": {m: 1000.0 for m in meses6},
        "CF - FOLHA MOT": {m: -100.0 for m in meses6},
        "CV - COMBUSTIVEL": {m: -300.0 for m in meses6},
        "IMPOSTOS FEDERAIS": {m: -80.0 for m in meses6},
    }
    return {
        "mes": "2026-08", "modo": "corrente", "dia_rel": 10,
        "hoje": "2026-08-10", "dias_meta_decorridos": 8,
        "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 300.0,
                         "CF - FOLHA MOT": -5.0, "CV - COMBUSTIVEL": -100.0,
                         "IMPOSTOS FEDERAIS": -24.0},
        "hist_ag": hist, "meses_hist": meses6,
        "diario": {"real_acum": 310.0, "meta_acum": 320.0, "meta_mes": 1000.0},
        "ating_hist": 0.90,
        "curva": {"ag": {"CV - COMBUSTIVEL": {d: min(1.0, d / 30) for d in range(46)}},
                  "linha": {}, "global": {d: min(1.0, d / 30) for d in range(46)}},
        "vfc": {"frete_compra": 0.0, "receita_viagens": 0.0, "viagens": 0},
        "ctaplus": {"custo": 95.0, "abastecimentos": 10},
        "cap": {"valor": 500.0, "titulos": 3},
        "breakeven": None, "orcado_linha": {"RECEITA BRUTA": 1100.0},
        "meses_circulares": [], "calibracao": {}, "ajustes": {},
        "indices": ({}, []),  # (indices_por_linha, linhas_flat)
        "snapshots": [], "fontes": [],
    }


def test_montar_resposta_corrente():
    r = montar_resposta(_ctx_minimo())
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # receita: 310 + (1000-320) * ritmo; ritmo = 310/320 (>=3 dias uteis)
    ritmo = 310.0 / 320.0
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - (310.0 + 680.0 * ritmo)) < 1e-6
    assert linhas["RECEITA BRUTA"]["estrategia"] == "driver_fiscal"
    # folha (nivel): mediana 3m = -100
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-100.0)) < 1e-6
    # combustivel: -100 / (10/30) = -300
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-300.0)) < 1e-6
    # impostos: pct 6m = -80/1000 = -8% da receita prevista
    rec_prev = linhas["RECEITA BRUTA"]["previsto"]
    assert abs(linhas["IMPOSTOS FEDERAIS"]["previsto"] - (rec_prev * -0.08)) < 1e-6
    # cascata fecha: RESULTADO = soma das partes
    assert abs(r["kpis"]["resultado_previsto"]
               - linhas["RESULTADO DO EXERCICIO"]["previsto"]) < 1e-9
    # realizado contabil exposto por linha
    assert abs(linhas["RECEITA BRUTA"]["realizado"] - 300.0) < 1e-9


def test_ajuste_manual_aplicado_e_marcado():
    ctx = _ctx_minimo()
    ctx["ajustes"] = {"CUSTO FIXO": {"tipo": "delta", "valor": -120.0,
                                     "motivo": "rescisao", "autor": "c",
                                     "criado_em": "2026-08-01"}}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-220.0)) < 1e-6
    assert linhas["CUSTO FIXO"]["ajuste"]["motivo"] == "rescisao"


def test_aviso_divergencia_combustivel():
    ctx = _ctx_minimo()
    ctx["ctaplus"] = {"custo": 200.0, "abastecimentos": 10}  # razao MTD = -100
    r = montar_resposta(ctx)
    assert any("combust" in a.lower() for a in r["avisos"])


def test_modo_fechando_consolida_e_estima():
    ctx = _ctx_minimo()
    ctx.update({"mes": "2026-07", "modo": "fechando", "dia_rel": 32,
                "diario": None,
                "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 1000.0,
                                 "CV - COMBUSTIVEL": -290.0,
                                 "CF - FOLHA MOT": -10.0}})
    # curva: combustivel ja ~100% em d32; folha 10% em d32 (abaixo do piso)
    ctx["curva"] = {"ag": {"CV - COMBUSTIVEL": {d: 1.0 for d in range(46)},
                           "CF - FOLHA MOT": {d: 0.10 for d in range(46)}},
                    "linha": {}, "global": {d: 1.0 for d in range(46)}}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-290.0)) < 1e-6   # consolidado
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-100.0)) < 1e-6       # fallback nivel
    assert 0.0 < r["kpis"]["consolidacao_pct"] <= 1.0


def test_vfc_none_nao_explode_e_frete_cai_na_projecao():
    """vfc.frete_compra/receita_viagens None (1o dia do mes, antes da 1a
    viagem com dtsaida) nao pode explodir com TypeError em abs(None) dentro
    de motor.prever_frete_compra. None tem de se comportar EXATAMENTE como
    0.0 (nenhum frete de compra conhecido ainda - so' resta a projecao pela
    receita)."""
    meses6 = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]

    ctx_none = _ctx_minimo()
    ctx_none["hist_ag"]["CV - FRETE AGREGADOS"] = {m: -200.0 for m in meses6}
    ctx_none["razao_ag_mes"]["CV - FRETE AGREGADOS"] = -60.0
    ctx_none["vfc"] = {"frete_compra": None, "receita_viagens": None, "viagens": 0}
    r_none = montar_resposta(ctx_none)  # nao pode levantar TypeError

    ctx_zero = _ctx_minimo()
    ctx_zero["hist_ag"]["CV - FRETE AGREGADOS"] = {m: -200.0 for m in meses6}
    ctx_zero["razao_ag_mes"]["CV - FRETE AGREGADOS"] = -60.0
    ctx_zero["vfc"] = {"frete_compra": 0.0, "receita_viagens": 0.0, "viagens": 0}
    r_zero = montar_resposta(ctx_zero)

    linhas_none = {ln["linha"]: ln for ln in r_none["linhas"]}
    linhas_zero = {ln["linha"]: ln for ln in r_zero["linhas"]}
    assert abs(linhas_none["CUSTO VARIAVEL"]["previsto"]
               - linhas_zero["CUSTO VARIAVEL"]["previsto"]) < 1e-9


def test_dia_util_fechando_usa_dia_rel_quando_dias_meta_decorridos_e_zero():
    """dias_meta_decorridos so' e' >0 no modo corrente; em 'fechando' a chave
    existe valendo 0, entao o fallback para dia_rel tem de vir de `or`, nao do
    default posicional de dict.get (que so' dispara com a chave AUSENTE).
    Sem o fix, banda_calibrada interpolaria no dia 0 (clampado ao piso da
    calibracao, dia 5) para um mes que na verdade esta' no dia 32."""
    ctx = _ctx_minimo()
    ctx.update({"mes": "2026-07", "modo": "fechando", "dia_rel": 32,
                "dias_meta_decorridos": 0, "diario": None,
                "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 1000.0,
                                 "CV - COMBUSTIVEL": -290.0,
                                 "CF - FOLHA MOT": -10.0}})
    ctx["curva"] = {"ag": {"CV - COMBUSTIVEL": {d: 1.0 for d in range(46)},
                           "CF - FOLHA MOT": {d: 0.10 for d in range(46)}},
                    "linha": {}, "global": {d: 1.0 for d in range(46)}}
    calib_linha = {"5": {"p20": -0.5, "p80": 0.5}, "40": {"p20": -0.1, "p80": 0.1}}
    ctx["calibracao"] = {"CUSTO FIXO": calib_linha}

    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}

    base = -100.0  # fallback nivel (mediana 3m de CF - FOLHA MOT), sem ajuste
    certo = motor.banda_calibrada(base, calib_linha, 32)   # dia_rel=32 (correto)
    errado = motor.banda_calibrada(base, calib_linha, 5)   # dia 0 clampado ao piso (bug antigo)
    assert abs(linhas["CUSTO FIXO"]["previsto_pess"] - min(certo)) < 1e-6
    assert abs(linhas["CUSTO FIXO"]["previsto_otim"] - max(certo)) < 1e-6
    assert abs(linhas["CUSTO FIXO"]["previsto_pess"] - min(errado)) > 1.0


# ---------------------------------------------------------------------------
# Defeito MATERIAL (validacao final): escrituracao em lote (curva bimodal)
# nao pode dividir pela media. Reproduz julho/26: RECEITA BRUTA dobrando de
# ~R$11,56mi para ~R$23,9mi ao dividir a razao (ja 100% postada) por uma
# completude media de 0,484 medida sobre uma curva bimodal (fev/mar/mai
# escrituram tarde, abr/jun/jul cedo). IMPOSTOS FEDERAIS/ESTADUAIS tem o
# mesmo padrao de escrituracao e sofriam o mesmo dobro.
# ---------------------------------------------------------------------------

def test_corrente_dispersao_alta_cai_para_nivel_em_vez_de_dividir():
    ctx = _ctx_minimo()
    # nivel (mediana 3m) deliberadamente diferente do que a divisao
    # razao/completude daria, para distinguir as duas estrategias
    ctx["hist_ag"]["CV - COMBUSTIVEL"] = {m: -700.0 for m in ctx["meses_hist"]}
    # dispersao alta no ag em dia_rel=10 (escrituracao em lote/bimodal)
    ctx["curva"]["ag_disp"] = {"CV - COMBUSTIVEL": {d: 0.5 for d in range(46)}}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # sem o fix, a divisao razao/completude daria -100 / (10/30) = -300;
    # com dispersao > 0,35 tem de cair para o nivel (mediana 3m) = -700
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-700.0)) < 1e-6
    assert any("lote" in p.lower() for p in linhas["CUSTO VARIAVEL"]["premissas"])


def test_fechando_dispersao_alta_razao_acima_do_nivel_usa_razao():
    """Reproduz o defeito de julho/26: razao ja 100% postada e MAIOR que o
    nivel historico -> o lote ja entrou, a razao e' o melhor conhecido."""
    ctx = _ctx_minimo()
    ctx.update({"mes": "2026-07", "modo": "fechando", "dia_rel": 34,
                "diario": None,
                "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 1156.0,
                                 "CV - COMBUSTIVEL": -290.0,
                                 "CF - FOLHA MOT": -10.0}})
    ctx["hist_ag"]["RECEITA OPERACIONAL BRUTA AGREGADO"] = \
        {m: 1000.0 for m in ctx["meses_hist"]}
    ctx["curva"] = {
        "ag": {"RECEITA OPERACIONAL BRUTA AGREGADO": {d: 0.484 for d in range(46)},
               "CV - COMBUSTIVEL": {d: 1.0 for d in range(46)},
               "CF - FOLHA MOT": {d: 0.10 for d in range(46)}},
        "ag_disp": {"RECEITA OPERACIONAL BRUTA AGREGADO": {d: 0.45 for d in range(46)}},
        "linha": {}, "linha_disp": {}, "global": {d: 1.0 for d in range(46)},
        "global_disp": {},
    }
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # sem o fix: 1156 / 0,484 = 2388,4 (quase o dobro) - o bug relatado
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - 1156.0) < 1e-6
    assert linhas["RECEITA BRUTA"]["estrategia"] == "lote"


def test_fechando_dispersao_alta_razao_perto_de_zero_usa_nivel():
    """Lado oposto do mesmo lote: razao ainda bem abaixo do nivel (o lote
    tardio ainda nao entrou) -> usa o nivel, nao a razao artificialmente
    baixa."""
    ctx = _ctx_minimo()
    ctx.update({"mes": "2026-07", "modo": "fechando", "dia_rel": 34,
                "diario": None,
                "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 40.0,
                                 "CV - COMBUSTIVEL": -290.0,
                                 "CF - FOLHA MOT": -10.0}})
    ctx["hist_ag"]["RECEITA OPERACIONAL BRUTA AGREGADO"] = \
        {m: 1000.0 for m in ctx["meses_hist"]}
    ctx["curva"] = {
        "ag": {"RECEITA OPERACIONAL BRUTA AGREGADO": {d: 0.484 for d in range(46)},
               "CV - COMBUSTIVEL": {d: 1.0 for d in range(46)},
               "CF - FOLHA MOT": {d: 0.10 for d in range(46)}},
        "ag_disp": {"RECEITA OPERACIONAL BRUTA AGREGADO": {d: 0.45 for d in range(46)}},
        "linha": {}, "linha_disp": {}, "global": {d: 1.0 for d in range(46)},
        "global_disp": {},
    }
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - 1000.0) < 1e-6
    assert linhas["RECEITA BRUTA"]["estrategia"] == "lote"


def test_dispersao_zero_mantem_comportamento_atual_regressao():
    """Curva homogenea (dispersao 0, presente e explicita - nao so' ausente)
    tem de manter o resultado de antes desta correcao."""
    ctx = _ctx_minimo()
    ctx["curva"]["ag_disp"] = {"CV - COMBUSTIVEL": {d: 0.0 for d in range(46)}}
    ctx["curva"]["linha_disp"] = {}
    ctx["curva"]["global_disp"] = {d: 0.0 for d in range(46)}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-300.0)) < 1e-6  # igual ao teste original
