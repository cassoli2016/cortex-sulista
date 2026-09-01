# -*- coding: utf-8 -*-
"""Os consertos do motor (v0.198.0) e o bloco `norte`.

Cada teste é uma sabotagem dirigida da medição que motivou o conserto:
- dia em curso no ritmo derrubava a receita prevista em R$ 3,57 mi na manhã
  do dia 1º (dublê com a ordem de grandeza REAL: meta de R$ 12,9 mi);
- razão ÷ completude no modo fechando inflou o CV de agosto em ~R$ 3 mi;
- FINANC por sazonal errou R$ 344 mil em julho onde o nível erraria 70 mil.
"""
from __future__ import annotations

from api.previsao import motor


# ---------------------------------------------------------------------------
# C1 — o dia em curso fica FORA do ritmo
# ---------------------------------------------------------------------------

def test_dia_1_de_manha_preve_pelo_historico_e_nao_pelo_parcial():
    """Manhã do dia 1º: nenhum dia fechado, R$ 77,8 mil emitidos contra meta
    diária de R$ 571 mil. Com o dia parcial no ritmo a previsão saía 64% da
    meta; sem ele, tem de sair ≈ meta × atingimento histórico (90%)."""
    r = motor.prever_receita(
        real_acum=0.0,          # dias FECHADOS: nenhum
        meta_acum=0.0,          # meta até ontem: nada
        meta_mes=12_894_574.0,
        ating_hist=0.90,
        dias_meta_decorridos=0,
        real_hoje=77_800.0,
    )
    assert abs(r["previsto"] - 12_894_574.0 * 0.90) < 1.0
    assert "dia em curso fora do ritmo" in " ".join(r["premissas"])


def test_o_parcial_de_hoje_e_piso_e_nunca_reduz():
    """Último dia do mês: o já emitido hoje supera a projeção do restante —
    o fato vence a projeção, nunca o contrário."""
    r = motor.prever_receita(
        real_acum=11_000_000.0, meta_acum=12_000_000.0,
        meta_mes=12_500_000.0, ating_hist=0.90,
        dias_meta_decorridos=25, real_hoje=600_000.0,
    )
    # restante = 500k × ritmo (~0,917) ≈ 458k < 600k emitidos hoje
    assert r["previsto"] >= 11_000_000.0 + 600_000.0


def test_sem_real_hoje_mantem_o_comportamento_de_sempre_regressao():
    r = motor.prever_receita(10_735_390.66, 11_756_257.68, 12_894_574.0,
                             0.90, 24)
    ritmo_obs = 10_735_390.66 / 11_756_257.68
    esperado = 10_735_390.66 + (12_894_574.0 - 11_756_257.68) * ritmo_obs
    assert abs(r["previsto"] - esperado) < 1.0


# ---------------------------------------------------------------------------
# C2 — teto anti-inflação do modo fechando
# ---------------------------------------------------------------------------

def _curva_frac(frac):
    """Curva mínima: fração `frac` no dia consultado, sem dispersão."""
    return {"ag": {"CV - PEDAGIO": {5: frac}}, "global": {5: frac},
            "ag_disp": {"CV - PEDAGIO": {5: 0.0}}, "global_disp": {5: 0.0}}


def test_razao_dividida_que_supera_o_maximo_historico_cai_para_o_piso():
    """Pedágio de agosto: −176 mil ÷ 35% = −498 mil, 3,4× a mediana (a fatura
    do TAG entra em LOTE). Com o teto, vale max(|razão|, |nível|)."""
    est = motor.estimar_m1(
        {"CV - PEDAGIO": -176_000.0}, _curva_frac(0.35), 5,
        {"CV - PEDAGIO": {"previsto": -145_000.0, "estrategia": "nivel",
                          "premissas": ["mediana 3m"]}},
        max_hist_por_ag={"CV - PEDAGIO": 190_000.0},
    )
    r = est["CV - PEDAGIO"]
    assert r["previsto"] == -176_000.0          # razão (maior em módulo que o nível)
    assert "acima de qualquer mes ja registrado" in " ".join(r["premissas"])


def test_sem_teto_o_comportamento_antigo_continua_sabotagem():
    """Sabotagem: SEM max_hist o mesmo caso divide pela curva — se este teste
    falhar, o teto passou a agir onde não foi pedido."""
    est = motor.estimar_m1(
        {"CV - PEDAGIO": -176_000.0}, _curva_frac(0.35), 5,
        {"CV - PEDAGIO": {"previsto": -145_000.0, "estrategia": "nivel",
                          "premissas": []}},
    )
    assert abs(est["CV - PEDAGIO"]["previsto"] - (-176_000.0 / 0.35)) < 1.0


def test_estimativa_dentro_do_historico_nao_e_tetada():
    est = motor.estimar_m1(
        {"CV - PEDAGIO": -100_000.0}, _curva_frac(0.80), 5,
        {"CV - PEDAGIO": {"previsto": -145_000.0, "estrategia": "nivel",
                          "premissas": []}},
        max_hist_por_ag={"CV - PEDAGIO": 190_000.0},
    )
    assert abs(est["CV - PEDAGIO"]["previsto"] - (-125_000.0)) < 1.0


# ---------------------------------------------------------------------------
# C3 — FINANC sai de sazonal para nível
# ---------------------------------------------------------------------------

def test_financ_agora_e_nivel():
    assert motor.estrategia_do_agrupador("FINANC - CUSTO DO CAPITAL DE GIRO") == "nivel"
    assert motor.estrategia_do_agrupador("INDENIZACOES E AVARIAS") == "sazonal"


# ---------------------------------------------------------------------------
# O norte: classificação declarada
# ---------------------------------------------------------------------------

def test_classe_da_linha_cobre_o_dre_inteiro_sem_inventar():
    from api.queries import DRE_MODELO
    assert motor.classe_da_linha("CUSTO FIXO") == "comprometido"
    assert motor.classe_da_linha("CUSTO VARIAVEL") == "proporcional"
    assert motor.classe_da_linha("RESULTADO NAO OPERACIONAL") == "fora"
    assert motor.classe_da_linha("RECEITA BRUTA") is None      # receita não é classe
    # toda linha direta do modelo (menos a receita) tem classe declarada:
    # linha sem classe sumiria do norte em silêncio
    sem_classe = [rot for rot, _n, tipo, _s in DRE_MODELO
                  if tipo != "formula" and rot != "RECEITA BRUTA"
                  and motor.classe_da_linha(rot) is None]
    assert sem_classe == [], sem_classe


# ---------------------------------------------------------------------------
# Cenários — a aritmética marginal no mesmo motor
# ---------------------------------------------------------------------------

def test_cenario_meta_e_melhor_que_ritmo_quando_atinge_menos_de_100():
    from api.previsao.servico import _montar_norte
    casc = {"RECEITA BRUTA": 11_600_000.0, "RESULTADO DO EXERCICIO": -900_000.0}
    diario = {"real_acum": 0.0, "meta_acum": 0.0, "meta_mes": 12_894_574.0,
              "dias_meta_restantes": 25}
    n = _montar_norte(casc, {}, [], {"vfc": {}, "breakeven": None}, diario,
                      0.90, {"pct_impostos": -0.19, "razao_cr": -0.498})
    c = n["cenarios"]
    assert c["meta"]["resultado"] > c["ritmo"]["resultado"]
    assert c["meta"]["receita"] == 12_894_574.0
    # sensibilidade marginal: 1 − |impostos| − |frete| ≈ 0,312
    assert abs(c["sensibilidade"] - (1 - 0.19 - 0.498)) < 1e-9


def test_norte_alavanca_respeita_o_piso_de_materialidade():
    from api.previsao.servico import _montar_norte
    casc = {"RECEITA BRUTA": 12_890_000.0, "RESULTADO DO EXERCICIO": 10_000.0}
    diario = {"real_acum": 12_880_000.0, "meta_acum": 12_880_000.0,
              "meta_mes": 12_894_574.0, "dias_meta_restantes": 1}
    n = _montar_norte(casc, {}, [], {"vfc": {}, "breakeven": None}, diario,
                      0.99, {})
    # fechar na meta vale ~R$ 14,5 mil — abaixo do piso de R$ 50 mil
    assert n["alavancas"] == []
