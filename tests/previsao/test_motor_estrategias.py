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


def test_razao_completude_guarda_de_dispersao_escrituracao_em_lote():
    """dispersao > DISPERSAO_MAX (curva bimodal - lote) tem prioridade sobre a
    divisao normal, mesmo com frac dentro da faixa que dividiria em condicoes
    normais. Ex. real: julho/26 com razao ja 100% postada (R$ 11,56mi) dividida
    por uma completude media de 0,484 (bimodal) quase DOBRAVA a previsao."""
    fb = prever_nivel([-400.0, -420.0, -410.0], "fallback")
    sem_lote = prever_razao_completude(razao_mtd=-200.0, frac=0.5, fallback=fb,
                                       dispersao=0.10)
    assert sem_lote["estrategia"] == "razao_completude"  # dispersao baixa - divide normal
    assert abs(sem_lote["previsto"] - (-400.0)) < 1e-9
    com_lote = prever_razao_completude(razao_mtd=-200.0, frac=0.5, fallback=fb,
                                       dispersao=0.50)
    assert com_lote["previsto"] == fb["previsto"]        # nao divide - usa fallback
    assert com_lote["estrategia"] == fb["estrategia"]
    assert any("lote" in p.lower() for p in com_lote["premissas"])
    # default dispersao=0.0 preserva o comportamento de sempre (regressao)
    default = prever_razao_completude(razao_mtd=-200.0, frac=0.5, fallback=fb)
    assert default["estrategia"] == "razao_completude"


def test_frete_compra_conhecido_mais_projecao():
    # razao mostra -100, viagens mostram -180. O operacional entra CONVERTIDO
    # (95,5%): -180 x 0,955 = -171,9, ainda mais informativo que o razao -100.
    # receita prevista 1000, ja realizada 300 -> restante 700 * razao -0,5 = -350
    r = prever_frete_compra(razao_mtd=-100.0, vfc_mtd=180.0, receita_prev=1000.0,
                            receita_mtd=300.0, razao_custo_receita=-0.5,
                            conv=0.955)
    assert abs(r["previsto"] - (-180.0 * 0.955 + -350.0)) < 1e-9
    assert r["estrategia"] == "frete_compra"


def test_frete_compra_converte_o_operacional_mas_nao_o_razao():
    """O `valorfretecompra` e o CONTRATADO; o que chega ao razao e ~95,5% dele
    (glosa, acerto, diferenca de pedagio). Ja o razao e contabil por natureza e
    nao pode ser convertido de novo — seria descontar duas vezes."""
    # razao muito mais negativo que o operacional: manda o razao, sem conversao
    r = prever_frete_compra(razao_mtd=-900.0, vfc_mtd=100.0, receita_prev=100.0,
                            receita_mtd=100.0, razao_custo_receita=-0.5,
                            conv=0.955)
    assert abs(r["previsto"] - (-900.0)) < 1e-9


def test_a_conversao_esta_ancorada_em_medicao():
    """95,5% nao e chute: e a mediana de seis meses fechados (94,9 / 96,1 /
    100,4 / 94,2 / 92,6 / 96,5), com desvio de 2,4 p.p."""
    from api.previsao.motor import CONV_FRETE_CONTABIL
    assert 0.90 <= CONV_FRETE_CONTABIL <= 1.0


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


def test_a_premissa_do_frete_mostra_a_conversao_em_percentual_legivel():
    """Saiu "9550,0%" na primeira versao: `_pct` ja multiplica por 100 e eu
    multipliquei de novo. Premissa e texto que o usuario le para conferir a
    conta — numero absurdo ali destroi a confianca no resto."""
    r = prever_frete_compra(razao_mtd=-100.0, vfc_mtd=180.0, receita_prev=1000.0,
                            receita_mtd=300.0, razao_custo_receita=-0.5,
                            conv=0.955)
    texto = " ".join(r["premissas"])
    assert "95,5%" in texto and "9550" not in texto


# --- sazonal: media, mas sem o mes que nao pertence a serie -----------------
# MEDIDO: a conta OUTRAS RECEITAS - RECEITAS OPERACIONAIS teve R$ 1,46 mi em
# maio/26 contra 0 a R$ 5,9 mil nos outros cinco meses. A media espalhava
# R$ 245 mil de receita ficticia por TODO mes projetado, e era isso que fazia a
# linha DESPESAS aparecer R$ 211 mil menor do que a operacao comporta.

def test_sazonal_descarta_o_mes_nao_recorrente():
    from api.previsao.motor import prever_sazonal
    vals = [0.0, 2_403.0, 5_903.0, 1_459_692.0, 2_282.0, 0.0]
    r = prever_sazonal(vals, [1.0] * 6, 1.0,
                       ["2026-02", "2026-03", "2026-04", "2026-05",
                        "2026-06", "2026-07"])
    # media dos CINCO que restam, nao dos seis
    assert abs(r["previsto"] - (10_588.0 / 5)) < 1e-6


def test_sazonal_nomeia_o_mes_descartado():
    """Tirar R$ 1,46 mi em silencio troca um erro visivel por um invisivel."""
    from api.previsao.motor import prever_sazonal
    vals = [0.0, 2_403.0, 5_903.0, 1_459_692.0, 2_282.0, 0.0]
    r = prever_sazonal(vals, [1.0] * 6, 1.0,
                       ["2026-02", "2026-03", "2026-04", "2026-05",
                        "2026-06", "2026-07"])
    texto = " ".join(r["premissas"])
    assert "2026-05" in texto and "nao recorrente" in texto


def test_sazonal_MANTEM_custo_em_rajada():
    """Indenizacao trabalhista sai em dois meses do semestre e zero nos outros
    quatro: e real e a mediana a subestimaria. O maior salto legitimo medido na
    base foi 5,4x, bem abaixo do corte."""
    from api.previsao.motor import prever_sazonal
    vals = [-23_311.0, -19_545.0, -124_548.0, -22_705.0, -80_432.0, -14_910.0]
    r = prever_sazonal(vals, [1.0] * 6, 1.0)
    assert abs(r["previsto"] - (sum(vals) / 6)) < 1e-6
    assert not any("nao recorrente" in p for p in r["premissas"])


def test_sazonal_serie_toda_atipica_nao_fica_sem_base():
    """Se TODOS os pontos passassem do corte nao haveria contra o que comparar;
    o certo e usar a serie inteira, nao devolver zero."""
    from api.previsao.motor import prever_sazonal
    r = prever_sazonal([0.0, 0.0, 100.0], [1.0] * 3, 1.0)
    assert r["previsto"] > 0


def test_sazonal_sem_rotulo_de_mes_continua_funcionando():
    """Chamadas antigas (e o backtest) nao passam meses6."""
    from api.previsao.motor import prever_sazonal
    r = prever_sazonal([10.0, 12.0, 11.0], [1.0] * 3, 1.0)
    assert abs(r["previsto"] - 11.0) < 1e-6
