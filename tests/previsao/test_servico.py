# tests/previsao/test_servico.py
from __future__ import annotations

from datetime import date

from api.previsao import motor
from api.previsao import servico
from api.previsao.servico import (FONTE_DIARIO, montar_resposta, resolver_modo,
                                  snapshot_se_integro)


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


def _ctx_com_diesel(custo_cartao: float):
    """ctx minimo + as pernas do combustivel.

    hist do agrupador -300/mes (LIQUIDO), recuperacao +200/mes -> diesel bruto
    -500/mes. Cartao historico 150 = 30% do bruto. No mes: razao -100 e
    recuperacao 60 -> bruto -160, entao a participacao observada e
    custo_cartao/160.
    """
    ctx = _ctx_minimo()
    meses6 = ctx["meses_hist"]
    ctx["diesel_agr"] = {
        "hist": {m: 200.0 for m in meses6},
        "km": {m: 1000.0 for m in meses6},
        "cta_hist": {m: 150.0 for m in meses6},
        "mtd": 60.0, "km_mtd": 500.0, "frac_mes": 0.5,
    }
    ctx["ctaplus"] = {"custo": custo_cartao, "abastecimentos": 10}
    return ctx


def test_cartao_na_participacao_de_sempre_NAO_avisa():
    """O aviso antigo comparava VALOR do cartao contra o LIQUIDO do agrupador e
    disparava todo mes - medido, o cartao valeu de 44% a 235% do liquido nos 6
    meses fechados. 30% do bruto e exatamente a mediana historica: silencio."""
    r = montar_resposta(_ctx_com_diesel(48.0))   # 48/160 = 30%
    assert not any("combust" in a.lower() for a in r["avisos"])


def test_cartao_fora_da_participacao_avisa_e_diz_os_dois_numeros():
    r = montar_resposta(_ctx_com_diesel(95.0))   # 95/160 = 59% contra 30%
    aviso = [a for a in r["avisos"] if "combust" in a.lower()]
    assert aviso, "participacao 29 pontos fora da mediana tem de avisar"
    assert "59%" in aviso[0] and "30%" in aviso[0]
    # "diverge" e a chave do classificador do digest (api/alertas)
    assert "diverge" in aviso[0].lower()


def test_combustivel_projeta_as_duas_pernas_separadas():
    """Bruto por NIVEL (mediana de 3 meses = -500) e recuperacao por KM
    (500/0,5 = 1000 km x R$ 0,20/km = 200). Liquido previsto = -300.

    Pelo caminho antigo o liquido -100 seria dividido pela completude do dia 10
    (10/30 = 33%) e viraria -300 por coincidencia de fixture; o que este teste
    fixa e a ESTRATEGIA e as premissas, que dizem qual perna e qual."""
    r = montar_resposta(_ctx_com_diesel(48.0))
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    cv = linhas["CUSTO VARIAVEL"]
    assert cv["estrategia"] == "combustivel_2pernas"
    texto = " ".join(cv["premissas"]).lower()
    assert "diesel bruto" in texto and "recuperacao do agregado" in texto
    assert abs(cv["previsto"] - (-300.0)) < 1e-6


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


# ---------------------------------------------------------------------------
# Degradacao POR FONTE (spec 11). A regra que governa os 3 testes abaixo: o
# default NEUTRO de cada driver produz um numero ERRADO em silencio (curva
# ausente -> completude 1,0 -> "razao parcial" virando "previsto"; diario
# ausente -> receita 0,00). Fonte fora tem de trocar de METODO e declarar,
# nunca cair no neutro.
# ---------------------------------------------------------------------------

def test_curva_ausente_nao_divide_cai_para_nivel_no_corrente():
    ctx = _ctx_minimo()
    # nivel (mediana 3m) distinto do que a divisao daria, para separar os dois
    ctx["hist_ag"]["CV - COMBUSTIVEL"] = {m: -700.0 for m in ctx["meses_hist"]}
    ctx["curva"] = {}                       # f_curva degradou
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # com curva o motor faria -100 / (10/30) = -300; com completude_em caindo
    # no neutro 1,0 daria -100 (razao parcial travestida de previsto). As duas
    # estao erradas: tem de vir o nivel, -700.
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-700.0)) < 1e-6
    assert linhas["CUSTO VARIAVEL"]["estrategia"] == "nivel"
    assert any("curva de completude indisponivel" in p
               for p in linhas["CUSTO VARIAVEL"]["premissas"])
    assert any("curva de completude indisponivel" in a.lower() for a in r["avisos"])
    # aviso aparece UMA vez, mesmo com varios agrupadores em razao_completude
    assert sum(1 for a in r["avisos"]
               if "curva de completude indisponivel" in a.lower()) == 1


def test_curva_ausente_no_fechando_tambem_cai_para_nivel():
    """Sem curva nao ha' como decidir consolidado/lote: o M-1 inteiro vai para
    o nivel. Sem o fix, completude_em devolveria 1,0 >= CONSOLIDADO_EM e TODA
    linha seria carimbada 'consolidado' — a razao parcial virando verdade."""
    ctx = _ctx_minimo()
    ctx.update({"mes": "2026-07", "modo": "fechando", "dia_rel": 32,
                "diario": None, "curva": {},
                "razao_ag_mes": {"RECEITA OPERACIONAL BRUTA AGREGADO": 400.0,
                                 "CV - COMBUSTIVEL": -50.0,
                                 "CF - FOLHA MOT": -10.0}})
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - 1000.0) < 1e-6   # mediana 3m
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-300.0)) < 1e-6
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-100.0)) < 1e-6
    assert linhas["RECEITA BRUTA"]["estrategia"] == "nivel"
    assert all(ln["estrategia"] != "consolidado" for ln in r["linhas"])
    assert any("curva de completude indisponivel" in a.lower() for a in r["avisos"])


def test_diario_ausente_no_corrente_preve_receita_por_nivel_nao_zero():
    ctx = _ctx_minimo()
    ctx["diario"] = None            # f_diario degradou
    ctx["ating_hist"] = None
    ctx["breakeven"] = None
    # folha com dispersao real (mediana dos 3 ultimos segue -100) para a banda
    # de fallback ter largura > 0 e o frac_rest ficar observavel
    ctx["hist_ag"]["CF - FOLHA MOT"] = {"2026-02": -80.0, "2026-03": -120.0,
                                        "2026-04": -90.0, "2026-05": -110.0,
                                        "2026-06": -100.0, "2026-07": -100.0}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # sem o fix: prever_receita(0,0,0,...) = 0,00 e a cascata inteira desaba
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - 1000.0) < 1e-6  # mediana 3m
    assert linhas["RECEITA BRUTA"]["estrategia"] == "nivel"
    # as linhas de % da receita consomem a receita de FALLBACK, nao 0
    assert abs(linhas["IMPOSTOS FEDERAIS"]["previsto"] - (1000.0 * -0.08)) < 1e-6
    assert r["kpis"]["atingimento_mtd"] is None and r["kpis"]["meta_mes"] is None
    assert any("driver fiscal" in a.lower() for a in r["avisos"])
    # a banda nao pode colapsar no cenario MAIS incerto (frac_rest > 0)
    cv = linhas["CUSTO FIXO"]
    assert cv["previsto_pess"] < cv["previsto_otim"]


def test_diario_ausente_frete_compra_nao_projeta_o_mes_inteiro_por_cima():
    """Com o diario fora, receita_mtd vem do RAZAO. Zerar receita_mtd faria
    prever_frete_compra somar o custo JA conhecido com a projecao do mes
    INTEIRO (dupla contagem do trecho decorrido)."""
    meses6 = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    ctx = _ctx_minimo()
    ctx["hist_ag"]["CV - FRETE AGREGADOS"] = {m: -200.0 for m in meses6}
    ctx["razao_ag_mes"]["CV - FRETE AGREGADOS"] = -60.0
    ctx["diario"] = None
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    # receita prevista = 1000 (nivel); receita MTD do razao = 300;
    # razao custo/receita 6m = -1200/6000 = -0,2; conhecido = min(-60, -0) = -60
    # esperado = -60 + (1000-300)*-0,2 = -200. Com receita_mtd=0 seria -260.
    frete = -60.0 + (1000.0 - 300.0) * (-1200.0 / 6000.0)
    combustivel = -300.0        # razao -100 / completude 10/30 (curva intacta)
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (frete + combustivel)) < 1e-6


def test_ops_ausente_vfc_zerado_e_ctaplus_none_tolerados():
    """f_ops fora: vfc zerado, ctaplus/cap None. Nao pode explodir, nao pode
    mudar as linhas que nao dependem de viagens, e o aviso de divergencia de
    combustivel (que compara contra os abastecimentos) simplesmente nao sai."""
    ctx = _ctx_minimo()
    ctx["vfc"] = {"frete_compra": 0.0, "receita_viagens": 0.0, "viagens": 0}
    ctx["ctaplus"] = None
    ctx["cap"] = None
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    base = montar_resposta(_ctx_minimo())
    base_linhas = {ln["linha"]: ln for ln in base["linhas"]}
    assert abs(linhas["RECEITA BRUTA"]["previsto"]
               - base_linhas["RECEITA BRUTA"]["previsto"]) < 1e-9
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"]
               - base_linhas["CUSTO VARIAVEL"]["previsto"]) < 1e-9
    assert r["kpis"]["cap_mes"] is None
    assert not any("combust" in a.lower() for a in r["avisos"])


def test_todas_as_fontes_ok_e_identico_ao_comportamento_anterior():
    """Regressao da onda de fix: com TODAS as fontes presentes, os numeros e
    os avisos sao exatamente os de antes (nenhum aviso novo, nenhuma linha
    trocando de estrategia)."""
    r = montar_resposta(_ctx_minimo())
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    ritmo = 310.0 / 320.0
    assert abs(linhas["RECEITA BRUTA"]["previsto"] - (310.0 + 680.0 * ritmo)) < 1e-9
    assert linhas["RECEITA BRUTA"]["estrategia"] == "driver_fiscal"
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (-300.0)) < 1e-9
    assert linhas["CUSTO VARIAVEL"]["estrategia"] == "razao_completude"
    assert abs(linhas["CUSTO FIXO"]["previsto"] - (-100.0)) < 1e-9
    # A intencao deste teste e: com todas as fontes presentes, NENHUM aviso de
    # DEGRADACAO de fonte aparece. O aviso de escrituracao e de outra familia —
    # ele fala do razao contabil, nao das fontes — e dispara aqui porque o ctx
    # minimo tem custo pouco escriturado contra a receita. Filtrar por familia
    # preserva a guarda original em vez de afroux-la para uma lista qualquer.
    degradacao = [a for a in r["avisos"] if "escriturado" not in a]
    assert degradacao == []
    assert r["fontes"] == []


def _ctx_meta_zerada() -> dict:
    """Driver fiscal que RESPONDEU, com linhas, mas com a meta do mes toda
    zerada (meta nao cadastrada) — o gatilho mais provavel da degradacao."""
    ctx = _ctx_minimo()
    ctx["diario"] = {"real_acum": 310.0, "meta_acum": 0.0, "meta_mes": 0.0}
    ctx["dias_meta_decorridos"] = 0
    ctx["ating_hist"] = None
    ctx["fontes"] = [{"nome": "razao contabil (AVA)", "ok": True, "driver": True},
                     {"nome": FONTE_DIARIO, "ok": True, "driver": True}]
    return ctx


def test_diario_com_meta_zerada_e_fonte_fora_nao_driver_fiscal():
    """BLOQUEADOR: com meta_mes = 0, prever_receita devolvia meta_rest = 0 e
    previsto = MTD (ou R$ 0,00) carimbado 'driver_fiscal', chip VERDE e nenhum
    aviso. Um dict truthy nao e' uma fonte saudavel."""
    ctx = _ctx_meta_zerada()
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    rb = linhas["RECEITA BRUTA"]
    assert abs(rb["previsto"] - 1000.0) < 1e-6      # mediana 3m, nao a meta
    assert rb["estrategia"] == "nivel"
    assert rb["previsto"] != 0.0 and abs(rb["previsto"] - 310.0) > 1.0   # nem 0 nem MTD
    # chip vermelho na fonte certa (e so' nela)
    por_nome = {f["nome"]: f for f in r["fontes"]}
    assert por_nome[FONTE_DIARIO]["ok"] is False
    assert por_nome["razao contabil (AVA)"]["ok"] is True
    # aviso dizendo a CAUSA (meta) + o aviso do metodo trocado
    assert any("meta diaria do mes sem valor" in a.lower() for a in r["avisos"])
    assert any("driver fiscal" in a.lower() for a in r["avisos"])
    # KPIs derivados da meta somem em vez de mostrar zero-por-lacuna
    assert r["kpis"]["meta_mes"] is None and r["kpis"]["atingimento_mtd"] is None
    # montar_resposta e' PURA: a lista de fontes do ctx nao foi mutada
    assert ctx["fontes"][1]["ok"] is True


def test_snapshot_nao_grava_com_driver_degradado(monkeypatch):
    """BLOQUEADOR: gravar_snapshot e' INSERT OR REPLACE por (data, mes, linha)
    — uma rodada degradada sobrescreveria para sempre o ponto bom do dia."""
    gravou: list[tuple] = []
    monkeypatch.setattr(servico.arm, "gravar_snapshot",
                        lambda path, data, mes, linhas: gravou.append((data, mes)))

    degradado = montar_resposta(_ctx_meta_zerada())
    assert snapshot_se_integro(degradado, "2026-08", "2026-08-04") is False
    assert gravou == []

    ctx_ok = _ctx_minimo()
    ctx_ok["fontes"] = [{"nome": FONTE_DIARIO, "ok": True, "driver": True}]
    assert snapshot_se_integro(montar_resposta(ctx_ok), "2026-08", "2026-08-04") is True
    assert gravou == [("2026-08-04", "2026-08")]


def test_snapshot_grava_com_orcamento_ausente_que_nao_e_driver():
    """Ano sem versao de orcamento cadastrada (janeiro) e' estado NORMAL e nao
    entra em previsto nenhum: nao pode parar o snapshot diario."""
    ctx = _ctx_minimo()
    ctx["fontes"] = [{"nome": "razao contabil (AVA)", "ok": True, "driver": True},
                     {"nome": "orcamento (sem versao do ano)", "ok": False,
                      "driver": False}]
    r = montar_resposta(ctx)
    assert motor.fontes_fora(r["fontes"], apenas_drivers=True) == []
    assert motor.fontes_fora(r["fontes"]) == ["orcamento (sem versao do ano)"]


def test_frete_compra_usa_a_receita_das_viagens_e_nao_conta_duas_vezes():
    """CORRIGIR ANTES DO DEPLOY: `conhecido` sai das VIAGENS e a receita ja
    coberta por ele tem de sair das MESMAS viagens. Usando o faturamento MTD
    (regua diferente) a receita restante fica inflada e a projecao cobre de
    novo o trecho que o custo conhecido ja cobriu."""
    meses6 = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    ctx = _ctx_minimo()
    ctx["hist_ag"]["CV - FRETE AGREGADOS"] = {m: -200.0 for m in meses6}
    ctx["razao_ag_mes"]["CV - FRETE AGREGADOS"] = -60.0
    # viagens: custo 80 conhecido, receita 400 gerada por essas mesmas viagens
    ctx["vfc"] = {"frete_compra": 80.0, "receita_viagens": 400.0, "viagens": 5}
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}

    rec_prev = 310.0 + 680.0 * (310.0 / 320.0)          # driver fiscal intacto
    razao_cr = -1200.0 / 6000.0
    # o custo conhecido vem do operacional e entra CONVERTIDO para contabil
    conhecido = -80.0 * motor.CONV_FRETE_CONTABIL
    certo = conhecido + (rec_prev - 400.0) * razao_cr    # regua unica: viagens
    errado = conhecido + (rec_prev - 310.0) * razao_cr   # MTD fiscal (dupla contagem)
    combustivel = -300.0                                 # razao -100 / completude 10/30
    assert abs(linhas["CUSTO VARIAVEL"]["previsto"] - (certo + combustivel)) < 1e-6
    assert abs(certo - errado) > 1.0                     # o teste distingue os dois
    assert any("viagens do mes" in p for p in linhas["CUSTO VARIAVEL"]["premissas"])


def test_sem_curva_previsto_nunca_fica_abaixo_do_razao_ja_postado():
    """CORRIGIR ANTES DO DEPLOY: no fallback sem curva o nivel historico podia
    vir MENOR (em modulo) que o razao ja escriturado — o 'projetado' invertia
    de sinal e o RESULTADO ficava OTIMISTA, enquanto o aviso prometia numeros
    conservadores. Piso: nunca menos, em modulo, que o razao."""
    ctx = _ctx_minimo()
    ctx["curva"] = {}                                  # f_curva degradou
    # razao do mes JA' acima do nivel historico (mediana 3m = -300)
    ctx["razao_ag_mes"]["CV - COMBUSTIVEL"] = -520.0
    r = montar_resposta(ctx)
    linhas = {ln["linha"]: ln for ln in r["linhas"]}
    cv = linhas["CUSTO VARIAVEL"]
    assert abs(cv["previsto"] - (-520.0)) < 1e-6       # segue o razao, nao o -300
    assert cv["projetado"] <= 0.0                      # custo projetado nunca "sobra"
    assert any("piso do razao" in p for p in cv["premissas"])
    # o aviso nao promete mais "numeros conservadores"
    aviso = next(a for a in r["avisos"] if "curva de completude" in a.lower())
    assert "conservador" not in aviso.lower()
    assert "piso" in aviso.lower() and "subestimado" in aviso.lower()

    # e quando o razao ainda esta' abaixo do nivel, nada muda (regressao)
    ctx2 = _ctx_minimo()
    ctx2["curva"] = {}
    r2 = montar_resposta(ctx2)
    linhas2 = {ln["linha"]: ln for ln in r2["linhas"]}
    assert abs(linhas2["CUSTO VARIAVEL"]["previsto"] - (-300.0)) < 1e-6


def test_fontes_e_avisos_previos_do_ctx_chegam_na_resposta():
    """fontes[] e avisos_previos vem da camada de I/O (get_previsao) e passam
    intactos por montar_resposta — é o que a tela desenha nos chips."""
    ctx = _ctx_minimo()
    ctx["fontes"] = [{"nome": "razao contabil (AVA)", "ok": True},
                     {"nome": "viagens / abastecimentos / contas a pagar",
                      "ok": False}]
    ctx["avisos_previos"] = ["Viagens indisponiveis: teste."]
    r = montar_resposta(ctx)
    assert r["fontes"] == ctx["fontes"]
    assert r["avisos"][0] == "Viagens indisponiveis: teste."
