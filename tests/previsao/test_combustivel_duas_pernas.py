# tests/previsao/test_combustivel_duas_pernas.py
"""CV - COMBUSTIVEL: o agrupador e um LIQUIDO e nao pode ser projetado inteiro.

Medido no razao (fev-jul/26): o diesel bruto varia 9% em torno do nivel, a
recuperacao do diesel do agregado sai a R$ 1,31/km com desvio de R$ 0,18 — e o
LIQUIDO, que e a diferenca dos dois, tem 3,4x de amplitude nos mesmos seis
meses. Projetar o liquido e projetar o ruido; dividi-lo pela curva de
completude (montada sobre sum(abs(...)), o MOVIMENTO das duas pernas) e pior:
no dia 24 essa curva vale de 19% a 77% conforme o mes.
"""
from __future__ import annotations

from api.previsao import servico
from api.previsao.motor import prever_diesel_agregado
from api.previsao.sql import CTAPLUS_MES_SQL, DIESEL_AGREGADO_SQL, KM_AGREGADO_MES_SQL


# --- a perna da recuperacao ------------------------------------------------

def test_recuperacao_sai_do_km_vezes_o_rs_por_km():
    r = prever_diesel_agregado(km_prev=1_000_000.0, rs_por_km=1.30,
                               razao_mtd=400_000.0)
    assert abs(r["previsto"] - 1_300_000.0) < 1e-6
    assert r["estrategia"] == "diesel_km"


def test_recuperacao_tem_piso_no_que_ja_esta_lancado():
    """Lancamento e fato; R$/km e estimativa. Se o razao ja reconheceu mais
    recuperacao do que o km sugere, quem manda e o razao."""
    r = prever_diesel_agregado(km_prev=100_000.0, rs_por_km=1.30,
                               razao_mtd=900_000.0)
    assert abs(r["previsto"] - 900_000.0) < 1e-6


def test_recuperacao_sem_nada_lancado_usa_so_o_km():
    r = prever_diesel_agregado(km_prev=500_000.0, rs_por_km=1.20, razao_mtd=0.0)
    assert abs(r["previsto"] - 600_000.0) < 1e-6


# --- o SQL das duas pernas -------------------------------------------------

NOVAS = (DIESEL_AGREGADO_SQL, KM_AGREGADO_MES_SQL, CTAPLUS_MES_SQL)


def test_sql_novo_respeita_pg93_e_latin1():
    for sql in NOVAS:
        assert "FILTER (WHERE" not in sql.upper()
        assert "percentile_cont" not in sql.lower()
        sql.encode("latin-1")


def test_diesel_agregado_filtra_pela_conta_e_ignora_historico_18():
    assert "coalesce(l.historico, 0) <> 18" in DIESEL_AGREGADO_SQL
    assert "upper(p.descricao) LIKE %(padrao)s" in DIESEL_AGREGADO_SQL


def test_km_do_agregado_exclui_cancelada_e_pega_so_agregado_e_terceiro():
    assert "dtcancelamento IS NULL" in KM_AGREGADO_MES_SQL
    assert "semaforo = 1" in KM_AGREGADO_MES_SQL
    assert "tipofrota IN (2,3)" in KM_AGREGADO_MES_SQL


def test_km_do_agregado_entra_no_vfc_para_o_mes_corrente():
    """O R$/km precisa do km do MES; sem esta coluna o ctx nao tem denominador
    e a recuperacao volta calada para a perna unica."""
    from api.previsao.sql import VFC_MTD_SQL
    assert "km_agregado" in VFC_MTD_SQL


def test_ctaplus_mensal_exclui_placa_de_agregado_e_terceiro():
    assert "NOT IN ('AGR', 'TER')" in CTAPLUS_MES_SQL
    assert "v.placa IS NOT NULL" in CTAPLUS_MES_SQL


# --- o aviso que era falso positivo estrutural -----------------------------

def test_aviso_do_combustivel_nao_compara_mais_valor_contra_valor():
    """O cartao e PARTE do diesel proprio, nunca o total: contra o LIQUIDO do
    agrupador ele valeu de 44% a 235% nos 6 meses fechados, entao o aviso
    antigo ('Combustivel diverge') disparava todo mes. Agora compara
    PARTICIPACAO contra a mediana dos 3 meses fechados."""
    fonte = (servico.__file__).replace(".pyc", ".py")
    with open(fonte, encoding="utf-8") as f:
        src = f.read()
    assert "DIVERGENCIA_COMB" not in src
    assert hasattr(servico, "PARTICIPACAO_CTA_MAX")
    # o texto CONTINUA dizendo "diverge" de proposito: e a chave que
    # api/alertas._alertas_previsao usa para levar o aviso ao digest. O que
    # mudou e a conta - participacao contra mediana, nao valor contra valor.
    assert "razao MTD" not in src.split("PARTICIPACAO_CTA_MAX")[-1]
    assert "mediana nos 3 meses fechados" in src


def test_tolerancia_da_participacao_e_em_pontos_e_nao_percentual():
    """0,12 = 12 PONTOS de participacao. Como fracao relativa (12% de 28%)
    a banda seria de 3 pontos e o aviso voltaria a gritar todo mes."""
    assert 0.05 <= servico.PARTICIPACAO_CTA_MAX <= 0.25


# --- o contexto que alimenta a projecao ------------------------------------

def _ctx(**kw):
    base = {"diesel_agr": {"hist": {"2026-05": 1_000.0, "2026-06": 1_100.0,
                                    "2026-07": 1_200.0},
                           "km": {"2026-05": 1_000.0, "2026-06": 1_000.0,
                                  "2026-07": 1_000.0},
                           "mtd": 400.0, "km_mtd": 800.0, "frac_mes": 0.8}}
    base["diesel_agr"].update(kw)
    return base


MESES = ["2026-05", "2026-06", "2026-07"]


def test_ctx_calcula_rs_por_km_e_extrapola_o_km_do_mes():
    c = servico._diesel_agregado_ctx(_ctx(), MESES)
    assert abs(c["rs_km"] - 1.1) < 1e-9          # mediana de 1,0 / 1,1 / 1,2
    assert abs(c["km_prev"] - 1_000.0) < 1e-9    # 800 / 0,8
    assert c["mtd"] == 400.0


def test_ctx_desiste_sem_historico_suficiente():
    """Sem tres meses nao ha mediana de R$/km que se sustente. Devolver None e
    voltar ao comportamento anterior e melhor que inventar um coeficiente que
    ninguem confere."""
    assert servico._diesel_agregado_ctx(
        _ctx(hist={"2026-07": 1_200.0}), MESES) is None


def test_ctx_desiste_sem_km_no_mes():
    assert servico._diesel_agregado_ctx(_ctx(km_mtd=0.0), MESES) is None


def test_ctx_carrega_o_historico_para_derivar_o_bruto():
    """O bruto de cada mes e o LIQUIDO do agrupador menos a recuperacao daquele
    mes: sem o historico da recuperacao no ctx nao da para montar a serie do
    bruto e o nivel sairia do liquido de novo."""
    c = servico._diesel_agregado_ctx(_ctx(), MESES)
    assert c["hist"]["2026-06"] == 1_100.0
