# -*- coding: utf-8 -*-
"""Frequência e banco de horas — o que a tela promete e o que ela recusa.

MEDIDO EM 09/09/2026 (GLOBUS, empresa 1):
    público com ponto ..........      92 de 195 ativos (motorista não bate)
    passivo credor .............   5.838,1 h  ≈ R$ 123.428  em 60 pessoas
    saldo parado (fora dos KPIs)    2 casos, sendo um de −823,5 h congelado
    HE paga em dinheiro ........  11.042,4 h  R$ 222.341,95  (57,5% do total)
    HE creditada no banco ......   8.147,9 h
    ajuste manual de marcação ..  26,6% dos dias-pessoa, 99,5% "ESQUECIMENTO"

POR QUE O DUBLÊ TEM O FORMATO QUE TEM
=====================================
Ele copia o que o Oracle REALMENTE devolve, com as três armadilhas que já
custaram número errado aqui:

  - uma pessoa AFASTADA com saldo enorme e congelado (a razão movimento/saldo
    é 0,01): é ela que prova que o corte de cadastro existe e funciona. Sem
    ela, todo teste de KPI passaria por vacuidade;
  - o MÊS EM CURSO na série e nas batidas, que precisa sair marcado `parcial`
    e NÃO pode alimentar alarme;
  - um saldo pequeno e parado, que NÃO é cadastro furado — o corte tem duas
    condições e um dublê com só a primeira aprovaria um corte pela metade.

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

# saldo, credito, debito, salbase, saldo_6m, movimento
_PESSOAS = [
    # trabalha e acumula: movimento alto contra o saldo → fica nos KPIs
    {"chapa": "002605", "nome": "EDSON R M", "filial": "FILIAL SBC",
     "funcao": "ANALISTA OPERACI", "situacao": "A", "saldo": 430.1,
     "credito": 12.0, "debito": 3.0, "salbase": 3596.0, "saldo_6m": 392.3,
     "movimento": 78.7},
    {"chapa": "003671", "nome": "JOYCE A C", "filial": "FILIAL CURITIBA",
     "funcao": "ANALISTA OP SR", "situacao": "A", "saldo": 395.5,
     "credito": 20.0, "debito": 8.0, "salbase": 4000.0, "saldo_6m": 282.5,
     "movimento": 239.6},
    # AFASTADA, saldo gigante e CONGELADO: razão 8,3/823,5 = 0,01 → cadastro
    {"chapa": "003437", "nome": "ALZIRA A S", "filial": "FILIAL CURITIBA",
     "funcao": "SEQUENCIADOR", "situacao": "F", "saldo": -823.5,
     "credito": 0.0, "debito": 0.0, "salbase": 2100.0, "saldo_6m": -832.3,
     "movimento": 8.3},
    # saldo PEQUENO e parado: razão baixa, mas abaixo do piso de horas →
    # continua nos KPIs. É este que impede o corte de virar "razão sozinha".
    {"chapa": "003851", "nome": "GUILHERME B P", "filial": "MATRIZ - T.I",
     "funcao": "APRENDIZ", "situacao": "A", "saldo": 6.4,
     "credito": 0.0, "debito": 0.0, "salbase": 1200.0, "saldo_6m": 3.5,
     "movimento": 0.0},
    # devedor comum
    {"chapa": "003599", "nome": "FILIPE V", "filial": "FILIAL CURITIBA",
     "funcao": "ANALISTA OP JR", "situacao": "A", "saldo": -247.2,
     "credito": 4.4, "debito": 0.4, "salbase": 2800.0, "saldo_6m": -205.0,
     "movimento": 43.4},
]

_SERIE = [
    {"comp": "2026-07", "credor": 5915.2, "devedor": -2529.6, "liquido": 3385.6, "pessoas": 104},
    {"comp": "2026-08", "credor": 6160.9, "devedor": -2527.3, "liquido": 3633.5, "pessoas": 106},
    # o mês EM CURSO: a série o mostra, marcado
    {"comp": "2026-09", "credor": 6137.5, "devedor": -2680.2, "liquido": 3457.3, "pessoas": 108},
]

_HE_PAGA = [{"h": 11042.4, "rs": 222341.95}]
_BH_12M = [{"cred": 8147.9, "deb": 5450.5}]

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
    if "VW_FUNCIONARIOS VF" in s and "FRQ_BANCOHORAS B" in s:
        return _PESSOAS
    if "SUM(CASE WHEN SALDONACOMPET > 0" in s:
        return _SERIE
    if "FLP_FICHAEVENTOS" in s:
        return _HE_PAGA
    if "SUM(CREDITO)" in s:
        return _BH_12M
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


# ── o corte de cadastro ─────────────────────────────────────────────────────
def test_saldo_congelado_sai_dos_kpis_e_vai_para_cadastro():
    d = F.get_banco_horas()
    nomes = [c["nome"] for c in d["cadastro"]]
    assert "ALZIRA A S" in nomes, "saldo parado de -823,5 h tinha de sair dos KPIs"
    assert "ALZIRA A S" not in [p["nome"] for p in d["pessoas"]]
    assert d["kpis"]["em_cadastro"] == 1


def test_o_saldo_congelado_nao_contamina_o_saldo_liquido():
    """Com ele dentro, o líquido seria 3.633,5 h — 23% menor. O número que a
    tela publica é o dos saldos VIVOS."""
    d = F.get_banco_horas()
    vivos = round(sum(p["horas"] for p in d["pessoas"]), 1)
    assert d["kpis"]["saldo_liquido"] == vivos
    assert d["kpis"]["saldo_liquido"] == pytest.approx(584.8, abs=0.2)


def test_saldo_pequeno_e_parado_NAO_e_cadastro_furado():
    """O corte tem DUAS condições. O aprendiz com 6,4 h e movimento zero tem
    razão 0,0 — se o piso de horas sumisse, ele viraria 'cadastro' e a lista
    de conferência encheria de gente que não tem nada a conferir."""
    d = F.get_banco_horas()
    assert "GUILHERME B P" in [p["nome"] for p in d["pessoas"]]
    assert "GUILHERME B P" not in [c["nome"] for c in d["cadastro"]]


def test_o_motivo_do_corte_traz_a_evidencia_numerica():
    """Achado sem número é opinião: a linha precisa dizer saldo e movimento."""
    d = F.get_banco_horas()
    motivo = d["cadastro"][0]["motivo"]
    assert "823" in motivo and "8.3" in motivo


# ── o passivo ───────────────────────────────────────────────────────────────
def test_o_passivo_conta_so_o_credor():
    """Devedor não é passivo: a empresa não deve folga a quem deve horas."""
    d = F.get_banco_horas()
    assert d["kpis"]["passivo_horas"] == pytest.approx(430.1 + 395.5 + 6.4, abs=0.1)
    assert d["kpis"]["pessoas_credoras"] == 3
    assert d["kpis"]["horas_devedoras"] < 0


def test_o_custo_e_estimativa_e_a_premissa_vai_junto():
    """Número sem premissa vira verdade. 430,1 h × (3596/220) × 1,5."""
    d = F.get_banco_horas()
    edson = [p for p in d["pessoas"] if p["nome"] == "EDSON R M"][0]
    assert edson["custo"] == pytest.approx(430.1 * (3596.0 / 220) * 1.5, abs=0.5)
    assert "220" in d["premissa_custo"]


def test_devedor_nao_recebe_custo():
    d = F.get_banco_horas()
    dev = [p for p in d["pessoas"] if p["horas"] < 0]
    assert dev and all(p["custo"] == 0.0 for p in dev)


# ── o mês em curso ──────────────────────────────────────────────────────────
def test_a_competencia_padrao_e_a_ultima_FECHADA():
    """A importação do AFD é manual: o mês em curso não é parcial, é
    indeterminado."""
    assert F.get_banco_horas()["competencia"] == "2026-08"


def test_a_serie_mostra_o_mes_em_curso_MARCADO():
    """Escondê-lo faria a série parecer terminada num mês que não fechou."""
    s = F.get_banco_horas()["serie"]
    assert s[-1]["comp"] == "2026-09" and s[-1]["parcial"] is True
    assert all(x["parcial"] is False for x in s[:-1])


# ── o destino da hora extra ─────────────────────────────────────────────────
def test_a_fracao_que_vira_dinheiro_e_a_pergunta_do_regime():
    d = F.get_banco_horas()["destino_he"]
    assert d["pct_em_dinheiro"] == pytest.approx(57.5, abs=0.2)
    assert d["pago_reais"] == pytest.approx(222341.95, abs=0.01)


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


# ── PII ─────────────────────────────────────────────────────────────────────
def test_o_snapshot_do_copiloto_nao_leva_PESSOA_nenhuma():
    """O snapshot vai para modelo externo. Nome, chapa e filial não sobem —
    e é isso, não um filtro esperto, que permite o fallback."""
    import json
    r = F.resumo_escalares()
    assert r, "o snapshot não pode vir vazio com o dublê respondendo"
    bruto = json.dumps(r, ensure_ascii=False)
    for proibido in ("EDSON", "ALZIRA", "002605", "FILIAL SBC", "CURITIBA"):
        assert proibido not in bruto.upper(), f"{proibido} vazou para o snapshot"
    assert all(not isinstance(v, (list, dict)) for v in r.values()), \
        "só escalar sobe: lista ou dicionário aqui é porta aberta para PII"


def test_o_snapshot_leva_o_passivo_e_a_fracao_em_dinheiro():
    """Escalar não quer dizer inútil: são estes dois números que o Copiloto
    precisa para responder sobre banco de horas."""
    r = F.resumo_escalares()
    assert r["banco_horas_passivo_h"] > 0
    assert r["he_pct_paga_em_dinheiro"] == pytest.approx(57.5, abs=0.2)
    assert r["pessoas_com_ponto"] == 92
