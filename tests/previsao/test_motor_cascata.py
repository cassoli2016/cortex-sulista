from __future__ import annotations

from api.previsao.motor import (aplicar_ajuste, banda_calibrada, banda_fallback,
                                estimar_m1, estrategia_do_agrupador,
                                linha_do_agrupador, montar_cascata, norm)


def test_estrategia_por_prefixo():
    assert estrategia_do_agrupador("CV - FRETE AGREGADOS") == "frete_compra"
    assert estrategia_do_agrupador("CV - FRETE TERCEIROS") == "frete_compra"
    assert estrategia_do_agrupador("CV - COMBUSTIVEL") == "razao_completude"
    assert estrategia_do_agrupador("CF - FOLHA MOT") == "nivel"
    assert estrategia_do_agrupador("OVERHEAD - FOLHA ADM") == "nivel"
    assert estrategia_do_agrupador("CF - DESPESAS ADM") == "razao_completude"
    assert estrategia_do_agrupador("FINANC - BANCOS") == "sazonal"
    assert estrategia_do_agrupador("CLASSIFICAR") == "runrate"
    # acento nao muda a decisao (normalizacao NFKD como no get_dre)
    assert estrategia_do_agrupador("CV - COMBUSTÍVEL") == "razao_completude"


def test_linha_do_agrupador_casa_com_dre_modelo():
    assert linha_do_agrupador("CV - COMBUSTIVEL") == "CUSTO VARIAVEL"
    assert linha_do_agrupador("CF - FOLHA MOT") == "CUSTO FIXO"
    assert linha_do_agrupador("RECEITA OPERACIONAL BRUTA AGREGADO") == "RECEITA BRUTA"
    assert linha_do_agrupador("FINANC - BANCOS") == "RESULTADO FINANCEIRO"
    assert linha_do_agrupador("XPTO SEM LINHA") is None


def test_cascata_fecha_o_resultado():
    direta = {"RECEITA BRUTA": 1000.0, "IMPOSTOS FEDERAIS": -78.0,
              "IMPOSTOS ESTADUAIS": -98.0, "IMPOSTOS MUNICIPAIS": -1.0,
              "CONTRIBUICAO PREVIDENCIARIA": -9.0, "ANULACOES": -5.0,
              "DESCONTOS": -2.0, "CUSTO FIXO": -200.0, "CUSTO VARIAVEL": -400.0,
              "CREDITOS TRIBUTARIOS": 50.0, "OVERHEAD": -100.0,
              "INDENIZACOES": -10.0, "OUTRAS DESPESAS/RECEITAS OPERACIONAIS": 5.0,
              "RESULTADO FINANCEIRO": -40.0, "RESULTADO NAO OPERACIONAL": 3.0}
    c = montar_cascata(direta)
    assert abs(c["DEDUCOES DA RECEITA"] - (-193.0)) < 1e-9
    assert abs(c["RECEITA LIQUIDA"] - 807.0) < 1e-9
    assert abs(c["CSP"] - (-550.0)) < 1e-9
    assert abs(c["LUCRO BRUTO"] - 257.0) < 1e-9
    assert abs(c["DESPESAS"] - (-105.0)) < 1e-9
    assert abs(c["RESULTADO OPERACIONAL (LOP 1)"] - 152.0) < 1e-9
    assert abs(c["RESULTADO DO EXERCICIO"] - 115.0) < 1e-9


def test_bandas():
    pess, otim = banda_fallback(100.0, [10.0, 10.0, 10.0, 10.0, 10.0, 10.0], 0.5)
    assert pess == otim == 100.0  # pstdev 0
    pess, otim = banda_fallback(100.0, [0.0, 20.0], 1.0)  # pstdev 10
    assert (pess, otim) == (90.0, 110.0)
    calib = {"5": {"p20": -0.10, "p80": 0.06}, "10": {"p20": -0.04, "p80": 0.02}}
    b = banda_calibrada(-1000.0, calib, 5)
    # erro relativo aplicado sobre |base|; p20 e o lado pessimista p/ resultado
    assert b is not None
    pess, otim = b
    assert abs(pess - (-1100.0)) < 1e-9 and abs(otim - (-940.0)) < 1e-9
    meio = banda_calibrada(-1000.0, calib, 7)  # interpolacao 5..10 (40%)
    assert abs(meio[0] - (-1000.0 - 1000.0 * 0.076)) < 1e-6
    assert banda_calibrada(1.0, None, 5) is None


def test_aplicar_ajuste():
    assert aplicar_ajuste(100.0, None) == (100.0, 0.0)
    assert aplicar_ajuste(100.0, {"tipo": "delta", "valor": -30.0}) == (70.0, -30.0)
    ef, shift = aplicar_ajuste(100.0, {"tipo": "valor", "valor": 250.0})
    assert (ef, shift) == (250.0, 150.0)


def test_estimar_m1_consolida_estima_e_faz_fallback():
    curva = {"ag": {"A": {d: (1.0 if d >= 40 else 0.5) for d in range(46)},
                    "B": {d: 0.1 for d in range(46)}},
             "linha": {}, "global": {d: 0.5 for d in range(46)}}
    fb = {"B": {"previsto": -700.0, "estrategia": "nivel", "premissas": ["fb"]}}
    r = estimar_m1({"A": -50.0, "B": -70.0}, curva, dia_rel=41, fallback_por_ag=fb)
    assert r["A"]["estrategia"] == "consolidado" and r["A"]["previsto"] == -50.0
    assert r["B"]["previsto"] == -700.0            # frac 0,1 < piso -> fallback
    r2 = estimar_m1({"A": -25.0}, curva, dia_rel=35, fallback_por_ag={})
    assert abs(r2["A"]["previsto"] - (-50.0)) < 1e-9   # -25 / 0,5
