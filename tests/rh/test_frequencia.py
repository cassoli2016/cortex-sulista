# -*- coding: utf-8 -*-
"""Frequência e banco de horas — o que a tela promete e o que ela recusa.

MEDIDO EM 09/09/2026 (GLOBUS, empresa 1):
    público com ponto ..........      92 de 195 ativos (motorista não bate)
    banco de horas ............. ver tests/rh/test_banco_de_horas_extrato.py
    HE paga em dinheiro ........  11.042,4 h  R$ 222.341,95  (57,5% do total)
    HE creditada no banco ......   8.147,9 h
    ajuste manual de marcação ..  26,6% dos dias-pessoa, 99,5% "ESQUECIMENTO"

POR QUE O DUBLÊ TEM O FORMATO QUE TEM
=====================================
Ele copia o que o Oracle REALMENTE devolve, com as três armadilhas que já
custaram número errado aqui:

  - o MÊS EM CURSO nas batidas, que precisa sair marcado `parcial` e NÃO
    pode alimentar alarme.

Os literais são copiados da medição real, nunca derivados das constantes do
módulo: dublê montado a partir do que se testa não testa nada.
"""
from __future__ import annotations

import pytest

from api import frequencia as F


# ── o que o Oracle devolve, por consulta ────────────────────────────────────
_PUBLICO = [{"ativos": 195, "com_freq": 92, "com_horario": 37}]

_FRESCOR = [{"ultimo_dia": "2026-09-06", "ultima_digitacao": "2026-09-05 15:19",
             "dias_atraso": 3}]
_COLETA = [{"ultima_coleta": "2026-09-05 15:10", "horas_desde": 98}]

_COMPS = [{"c": "2026-09"}, {"c": "2026-08"}, {"c": "2026-07"}]
_FECHADA = [{"c": "2026-08"}]

_HE_PAGA = [{"h": 11042.4, "rs": 222341.95}]

_ORIGEM = [
    {"mes": "2026-06", "total": 3167, "relogio": 3047, "digitada": 120, "outros": 0},
    {"mes": "2026-07", "total": 2964, "relogio": 2668, "digitada": 296, "outros": 0},
    {"mes": "2026-08", "total": 2897, "relogio": 2407, "digitada": 490, "outros": 0},
    # mês em curso: 423 movimentos contra 2.897 — base pequena demais para alarme
    {"mes": "2026-09", "total": 423, "relogio": 367, "digitada": 56, "outros": 0},
]
_AJUSTES = [
    {"mes": "2026-06", "total": 2628, "ajustados": 802},
    {"mes": "2026-07", "total": 2558, "ajustados": 838},
    {"mes": "2026-08", "total": 2703, "ajustados": 718},
    {"mes": "2026-09", "total": 418, "ajustados": 102},
]
_MOTIVOS = [{"motivo": "ESQUECIMENTO", "n": 28347}, {"motivo": "TREINAMENTO", "n": 146}]
_ABSENT = [
    {"mes": "2026-07", "faltas": 115, "atestados": 14, "trab": 1808},
    {"mes": "2026-08", "faltas": 133, "atestados": 21, "trab": 1734},
    {"mes": "2026-09", "faltas": 29, "atestados": 7, "trab": 311},
]
_DEFAS = [{"mediana": 6.0, "media": 7.5, "maximo": 35}]
_CORRENTE = [{"m": "2026-09"}]

# ── o que a folha PAGOU de hora extra, e a baixa pela folha ─────────────────
# (o saldo do banco que vai ao lado deles tem roteador próprio, no formato do
# extrato: `tests/rh/test_banco_de_horas_extrato.py`)
_PAGOS_CONF = [
    {"comp": "2026-07", "pessoas": 34, "horas": 650.2, "reais": 13278.34},
    {"comp": "2026-08", "pessoas": 60, "horas": 1506.7, "reais": 27945.42},
]
_BAIXAS_CONF = [{"comp": "2026-08", "horas": 86.4}]


def _roteador(sql, p=None):
    """Devolve o dublê pela ASSINATURA da consulta, não pela ordem de chamada.

    Roteador por ordem quebra em silêncio quando alguém acrescenta uma query no
    meio — e o teste passa a medir outra coisa sem falhar.
    """
    s = " ".join(sql.split()).upper()
    if "TEMFREQUENFUNC='S' THEN 1" in s.replace(" ", "") or "COM_FREQ" in s:
        return _PUBLICO
    if "FRQ_PONTOCERTIFICADO_LOG" in s:
        return _COLETA
    if "MAX(DTDIGIT)" in s and "FRQ_DIGITACAOMOVIMENTO" in s:
        return _FRESCOR
    if "SELECT DISTINCT TO_CHAR(COMPETENCIA" in s:
        return _COMPS
    if "MAX(COMPETENCIA)" in s and "< TRUNC(SYSDATE,'MM')" in s:
        return _FECHADA
    # O banco de horas (saldo, série, confronto, destino) tem roteador próprio,
    # no formato do extrato: `tests/rh/test_banco_de_horas_extrato.py`. Aqui
    # não há rota para `saldonacompet` — o campo não é saldo.
    if "CODEVENTO = 1016" in s:
        return _BAIXAS_CONF
    if "FLP_FICHAEVENTOS" in s and "COUNT(DISTINCT FF.CODINTFUNC) PESSOAS" in s:
        return _PAGOS_CONF
    if "FLP_FICHAEVENTOS" in s:
        return _HE_PAGA

    if "GERADORDIGIT='RL'" in s:
        return _ORIGEM
    if "FRQ_MOVTOMOTDIGIT" in s and "DESCMOTIVO" in s:
        return _MOTIVOS
    if "FRQ_MOVTOMOTDIGIT" in s:
        return _AJUSTES
    if "'FALTA'" in s:
        return _ABSENT
    if "MEDIAN(" in s:
        return _DEFAS
    if "TRUNC(SYSDATE,'MM'),'YYYY-MM') M FROM DUAL" in s:
        return _CORRENTE
    raise AssertionError("consulta sem dublê: " + s[:160])


@pytest.fixture(autouse=True)
def _sem_oracle(monkeypatch):
    """Nenhum teste daqui fala com o Oracle — e o cache do módulo é limpo
    entre eles, senão o primeiro teste responde por todos."""
    from api import queries
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(F.db, "query", _roteador)
    yield
    queries._RESP_CACHE.clear()


# ── o denominador ───────────────────────────────────────────────────────────
def test_o_publico_e_quem_bate_ponto_nao_o_quadro():
    """92 de 195. Percentual sobre o quadro mentiria por um fator de dois."""
    p = F.publico()
    assert p["com_frequencia"] == 92
    assert p["ativos"] == 195
    assert p["com_frequencia"] < p["ativos"]


def test_a_cobertura_de_horario_contratual_e_dita_e_nao_escondida():
    """Só 37 dos 92 têm CODHORA. Previsto × realizado nasce com 40% de
    cobertura, e a tela precisa poder dizer isso."""
    assert F.publico()["com_horario"] == 37


# ── o banco de horas ────────────────────────────────────────────────────────
# O saldo, os totais, a série e o destino da hora extra têm arquivo próprio,
# com o dublê no formato do EXTRATO do Globus (HH.MM, saldo anterior + movimento):
# `tests/rh/test_banco_de_horas_extrato.py`. Os testes que moravam aqui
# guardavam o corte de "saldo parado" e o passivo pelo `saldonacompet` — um
# acumulador que o extrato oficial desmentiu em 14/09/2026.


# ── os avisos ───────────────────────────────────────────────────────────────
def test_o_alarme_mede_MES_FECHADO_nunca_o_em_curso():
    """Agosto fechou em 16,9% de batida digitada; setembro tem 13,2% sobre 423
    movimentos. O aviso tem de citar AGOSTO — alarme sobre base de sorte é
    ruído, e ruído ensina a ignorar o painel."""
    avisos = F.get_batidas()["avisos"]
    dp = [a for a in avisos if "digitada" in a["titulo"]]
    assert dp, "o pico de batida digitada tinha de acender"
    assert "2026-08" in dp[0]["titulo"]
    assert "2026-09" not in dp[0]["titulo"]


def test_o_aviso_de_atraso_diz_que_a_importacao_e_manual():
    """Sem isso, quem lê conclui que o sistema quebrou — e o que houve foi
    ninguém ter rodado a importação."""
    a = [x for x in F.get_batidas()["avisos"] if "enxerga" in x["titulo"]]
    assert a and "manual" in a[0]["detalhe"]


def test_as_series_de_batida_marcam_o_mes_em_curso():
    """AS TRÊS, e o absenteísmo é a que faltava.

    Ele subiu sem o campo e o KPI publicou setembro — 311 dias trabalhados
    contra os 1.734 de agosto —, dizendo 8,5% de falta onde o mês fechado deu
    7,1%. Nenhum teste pegou: o dublê tinha o campo que o SQL não produzia.
    Quem achou foi renderizar a tela com dado REAL.
    """
    b = F.get_batidas()
    for serie in ("origem", "ajustes", "absenteismo"):
        assert b[serie][-1]["parcial"] is True, f"{serie} não marcou o mês em curso"
        assert all(x["parcial"] is False for x in b[serie][:-1]),             f"{serie} marcou como parcial um mês que já fechou"


def test_o_KPI_de_absenteismo_le_o_ultimo_mes_FECHADO():
    """O que a tela publica é agosto (7,1%), não setembro (8,5%)."""
    b = F.get_batidas()
    fechados = [x for x in b["absenteismo"] if not x["parcial"]]
    assert fechados[-1]["mes"] == "2026-08"
    assert fechados[-1]["pct_falta"] == pytest.approx(7.1, abs=0.1)


def test_absenteismo_sai_em_dia_pessoa_e_nao_em_linha():
    """`FRQ_DIGITACAOMOVIMENTO` tem 1,3 a 2,7 linhas por pessoa-dia. Contar
    linha inflou 'faltas' de 1.179 para 2.981 na primeira medição."""
    ago = [x for x in F.get_batidas()["absenteismo"] if x["mes"] == "2026-08"][0]
    assert ago["faltas"] == 133
    assert ago["pct_falta"] == pytest.approx(100 * 133 / (1734 + 133), abs=0.1)


# ── o snapshot do Copiloto ──────────────────────────────────────────────────
# Ele chama o banco de horas, e por isso mora no arquivo do extrato, com o
# roteador que conhece as consultas dele: `test_banco_de_horas_extrato.py`
# (saldo credor, levado, fração paga em dinheiro, e nenhum nome).
