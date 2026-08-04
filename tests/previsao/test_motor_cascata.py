from __future__ import annotations

from api.previsao.motor import (aplicar_ajuste, banda_calibrada, banda_fallback,
                                estimar_m1, estrategia_do_agrupador, fontes_fora,
                                linha_do_agrupador, montar_cascata, norm)


def test_fontes_fora_e_o_recorte_de_driver():
    fontes = [{"nome": "razao contabil (AVA)", "ok": True, "driver": True},
              {"nome": "curva de completude", "ok": False, "driver": True},
              {"nome": "orcamento (sem versao do ano)", "ok": False, "driver": False}]
    assert fontes_fora(fontes) == ["curva de completude",
                                   "orcamento (sem versao do ano)"]
    assert fontes_fora(fontes, apenas_drivers=True) == ["curva de completude"]
    assert fontes_fora([]) == [] and fontes_fora(None) == []
    # payload antigo (sem a chave driver) conta como driver — default seguro
    assert fontes_fora([{"nome": "x", "ok": False}], apenas_drivers=True) == ["x"]


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
    # a calibracao guarda err = (previsto - final)/|final| (backtest), entao o
    # fechamento provavel e' final ~= previsto - err x |previsto|: SUBTRAI.
    calib = {"5": {"p20": -0.10, "p80": 0.06}, "10": {"p20": -0.04, "p80": 0.02}}
    b = banda_calibrada(-1000.0, calib, 5)
    assert b is not None
    # -1000 - (-0,10)x1000 = -900 ; -1000 - 0,06x1000 = -1060
    assert abs(min(b) - (-1060.0)) < 1e-9 and abs(max(b) - (-900.0)) < 1e-9
    # CONTRATO (menor, maior), o mesmo de banda_fallback: a cascata soma as duas
    # fontes de banda na mesma ponta antes do min()/max() por linha, entao trocar
    # a ordem misturaria extremos e estreitaria a banda do RESULTADO.
    assert b[0] <= b[1]
    meio = banda_calibrada(-1000.0, calib, 7)  # interpolacao 5..10 (40%)
    # p20 interp = -0,076 -> -924 ; p80 interp = +0,044 -> -1044
    assert abs(max(meio) - (-1000.0 + 1000.0 * 0.076)) < 1e-6
    assert abs(min(meio) - (-1000.0 - 1000.0 * 0.044)) < 1e-6
    assert meio[0] <= meio[1]
    assert banda_calibrada(1.0, None, 5) is None


def test_banda_calibrada_fica_do_lado_do_erro_medido():
    """PINO DE INTENCAO (este e' o defeito que ja apareceu uma vez e pode
    voltar sem ninguem ver): o SINAL do erro decide o LADO da banda.

    err < 0 significa previsto < final, ou seja o metodo SUBESTIMA - o
    fechamento tende a vir ACIMA do previsto e a banda tem de ficar ACIMA.
    err > 0 e' o espelho. Vale para base positiva (receita) e negativa
    (custo), porque a escala e' |base| e o deslocamento e' assinado."""
    subestima = {"5": {"p20": -0.08, "p80": -0.02}}   # erros TODOS negativos
    superestima = {"5": {"p20": 0.02, "p80": 0.08}}   # erros TODOS positivos
    for base in (1000.0, -1000.0):
        b = banda_calibrada(base, subestima, 5)
        assert min(b) > base and max(b) > base, "metodo subestima -> banda ACIMA"
        b = banda_calibrada(base, superestima, 5)
        assert min(b) < base and max(b) < base, "metodo superestima -> banda ABAIXO"
    # caso real que motivou o fix: RECEITA BRUTA em D25 (p20 -3,24%/p80 -1,27%)
    receita = {"25": {"p20": -0.0324, "p80": -0.0127}}
    pess, otim = sorted(banda_calibrada(11_745_816.0, receita, 25))
    assert abs(pess - 11_745_816.0 * 1.0127) < 1.0
    assert abs(otim - 11_745_816.0 * 1.0324) < 1.0
    # erro que troca de sinal (p20 < 0 < p80) e' o unico caso em que o
    # previsto fica DENTRO da propria banda - e ai' fica, nos dois sentidos
    misto = {"5": {"p20": -0.05, "p80": 0.05}}
    for base in (1000.0, -1000.0):
        pess, otim = sorted(banda_calibrada(base, misto, 5))
        assert pess < base < otim


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


def test_estimar_m1_lote_bimodal_usa_o_maior_em_modulo():
    """Curva bimodal (dispersao alta) NAO pode dividir pela media - dobraria
    um mes "cedo" (razao ja completa) e esmagaria um mes "tardio" (lote nao
    entrou ainda). Reproduz o defeito real de julho/26: RECEITA BRUTA
    dobrando de ~R$11,56mi para ~R$23,9mi ao dividir por completude media
    0,484 numa curva bimodal."""
    curva = {"ag": {"REC": {d: 0.484 for d in range(46)}},
             "ag_disp": {"REC": {d: 0.45 for d in range(46)}},  # > DISPERSAO_MAX
             "linha": {}, "linha_disp": {}, "global": {d: 0.484 for d in range(46)},
             "global_disp": {}}
    fb_alto = {"REC": {"previsto": 1000.0, "estrategia": "nivel", "premissas": ["fb"]}}
    # razao ja superou o nivel (lote ja entrou) -> usa a razao como esta, SEM dividir
    r_cedo = estimar_m1({"REC": 1156.0}, curva, dia_rel=34, fallback_por_ag=fb_alto)
    assert r_cedo["REC"]["previsto"] == 1156.0     # nao e' 1156/0.484=2388.4 (o bug)
    assert r_cedo["REC"]["estrategia"] == "lote"
    assert any("lote" in p.lower() for p in r_cedo["REC"]["premissas"])
    # razao ainda bem abaixo do nivel (lote tardio nao entrou) -> usa o nivel
    r_tarde = estimar_m1({"REC": 40.0}, curva, dia_rel=34, fallback_por_ag=fb_alto)
    assert r_tarde["REC"]["previsto"] == 1000.0
    assert r_tarde["REC"]["estrategia"] == "lote"
