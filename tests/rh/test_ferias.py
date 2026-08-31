"""Ferias: a data que manda e a da DOBRA, e ficha parada nao e passivo.

Regra da CLT: a cada 12 meses trabalhados fecha um periodo AQUISITIVO e nasce
o direito a 30 dias; a empresa tem os 12 meses seguintes (periodo CONCESSIVO)
para conceder. Passou disso, paga em dobro (art. 137).

Medido em 25/08/2026: 196 ativos, ficha de ferias para todos (100%), 65 com
direito adquirido, ZERO em dobra, 1 chegando ao limite em 90 dias, 19 de
ferias ou com data marcada (6 hoje) e 2 fichas paradas no cadastro.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
FOLHA = RAIZ / "api" / "queries_folha.py"
HTML = RAIZ / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def fonte() -> str:
    return FOLHA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


# ---------------------------------------------------------------- regra CLT
def test_o_limite_e_o_aquisitivo_MAIS_12_MESES(fonte):
    """O fim do periodo aquisitivo nao e prazo nenhum — e quando o direito
    NASCE. O que dispara a dobra e ele mais 12 meses."""
    assert "_FER_LIM" in fonte
    m = re.search(r'_FER_LIM = "(.*?)"', fonte)
    assert m and "ADD_MONTHS(fe.proxaquifinfer,12)" in m.group(1), (
        "o limite legal e o fim do aquisitivo + 12 meses")


def test_a_fila_so_traz_quem_ja_tem_direito(fonte):
    """Quem ainda esta no aquisitivo nao tem o que agendar; misturado, a fila
    comecaria por quem nao e problema de ninguem."""
    i = fonte.index("fila = [_linha(r) for r in _qb(")
    assert "fe.proxaquifinfer <= TRUNC(SYSDATE)" in fonte[i:i + 1400]


# ------------------------------------------------------- ficha parada != dobra
def test_ficha_parada_sai_do_indicador_de_dobra(fonte):
    """Dois registros apontam limite vencido ha 23 e 19 anos, com periodo
    aquisitivo atual e gozo NULOS: a ficha nunca foi processada. Conta-los como
    dobra anunciaria um passivo trabalhista que nao existe — mesma licao da
    Manutencao Preventiva, onde desvio maior que um ciclo inteiro do proprio
    indicador e cadastro furado, nao operacao."""
    assert "_FER_LIMITE_ABSURDO_DIAS" in fonte
    i = fonte.index("em_dobra")
    bloco = fonte[i - 200:i + 300]
    assert "sano" in bloco, "o contador de dobra tem de excluir a ficha parada"


def test_a_ficha_parada_volta_como_lista_propria(fonte):
    """Excluir do indicador nao pode virar esconder: essas pessoas nunca vao
    aparecer em alerta nenhum ate alguem acertar o GLOBUS."""
    assert '"fichas_paradas": paradas' in fonte
    assert '"ficha_parada"' in fonte


def test_o_corte_do_absurdo_e_um_periodo_concessivo_inteiro(fonte):
    """Corte generoso de proposito: atraso real de meses ainda tem de doer."""
    m = re.search(r"_FER_LIMITE_ABSURDO_DIAS = (\d+)", fonte)
    assert m and int(m.group(1)) >= 365


# ---------------------------------------------------------------------- tela
def test_zero_em_dobra_so_fica_verde_se_nao_houver_ficha_parada(html):
    """Com ficha parada existe gente cujo estado real ninguem sabe. Verde ali
    afirmaria "esta tudo certo" sobre 194 de 196."""
    i = html.index("kpi('Férias em DOBRA'")
    bloco = html[i:i + 700]
    assert "(k.ficha_parada||0)>0 ? '' : 'pos'" in bloco
    assert "fichas em dia" in bloco, (
        "o subtitulo tem de dizer sobre quantas fichas a afirmacao vale")


def test_o_card_de_ficha_parada_some_quando_nao_ha(html):
    """Card vazio permanente vira ruido; ele so aparece quando ha o que
    corrigir."""
    assert 'id="card-fer-paradas" hidden' in html
    assert "card.hidden = PA.length===0" in html


def test_concordancia_de_numero_nos_avisos(html):
    """A tela ja mostrou "1 dias" uma vez (Comunicacao Rastreadora)."""
    for trecho in ("k.dobra_prazo===1?' funcionário chega'",
                   "k.em_dobra===1?' funcionário'",
                   "k.ficha_parada===1?' ficha de férias parada'"):
        assert trecho in html, f"falta concordancia: {trecho}"


def test_a_tela_esta_registrada_em_todos_os_lugares(html):
    assert 'id="view-ferias"' in html
    assert 'data-view="ferias"' in html
    assert 'href="#ferias" onclick="fecharDrawer()"' in html
    assert "ferias:'Férias — Vencimento'" in html
    assert "ferias:'Rh'" in html
    assert "ferias:loadFerias" in html


def test_a_rota_esta_no_rbac():
    auth = (RAIZ / "api" / "auth.py").read_text(encoding="utf-8")
    assert '"ferias":  ("Férias — Vencimento", "Recursos Humanos"),' in auth
    assert '("/api/rh/ferias",                frozenset({"ferias"})),' in auth
    assert "perfis_modelo_v28" in auth


# ----------------------------------------------------------------------- PII
def test_nao_devolve_salario_nem_cpf(fonte):
    i = fonte.index("def get_ferias(")
    corpo = fonte[i:]
    for proibido in ("salbase", "cpfcnpj", "pis_inss", "salario"):
        assert proibido not in corpo.lower()


def test_usa_o_mesmo_criterio_de_ativo_das_outras_telas(fonte):
    """A tela de CNH ja errou nisso e contou motorista demitido como ativo.
    Aqui a base tem de ser a de `vw_funcionarios`, como o Headcount."""
    i = fonte.index("_FER_BASE")
    assert "vf.situacaofunc = 'A'" in fonte[i:i + 400]


# ===========================================================================
# O SEGUNDO PERIODO — a pergunta que a tela nao respondia
#
# A COINCIDENCIA QUE FAZ A LEITURA: o segundo periodo aquisitivo comeca no dia
# em que o primeiro fecha e dura 12 meses; o periodo CONCESSIVO do primeiro
# dura os mesmos 12 meses. Entao a data em que o segundo FECHA e a mesma em que
# o primeiro entra em DOBRA. "Quem esta indo para o segundo periodo e precisa
# gozar o primeiro" e "quem vai cair em dobra" sao a MESMA pergunta — e a
# primeira e a acionavel, porque ninguem agenda ferias por causa do art. 137.
#
# MEDIDO EM 31/08/2026: 191 ativos, 65 ja no segundo periodo, ZERO deles com
# data marcada, 13 ja passaram de 6 meses do segundo, 1 chega ao limite em 90
# dias. A distribuicao do acumulo: 126 ainda no primeiro, 52 ate 6 meses do
# segundo, 13 entre 6 e 12 — ninguem acima de 12.
# ===========================================================================
import json as _json

from api import queries_folha as _qf


def _linhas_falsas(sql, params=None):
    """Duble que carrega o que a base REALMENTE tem e e facil esquecer:
    alguem com gozo agendado (para o contador de "sem data" nao virar a
    contagem inteira), um mes sem ninguem fechando periodo (que o `GROUP BY`
    nao devolve) e uma pessoa com 11 meses do segundo periodo corridos."""
    if "COUNT(*) ativos" in sql:
        return [{"ativos": 191, "ficha_parada": 0, "em_dobra": 0,
                 "dobra_prazo": 1, "dobra_30": 0, "com_direito": 65,
                 "sem_agenda": 64, "segundo_6": 13,
                 "em_ferias_ou_agendado": 20, "em_ferias_agora": 7}]
    if "GROUP BY vf.descsecao" in sql:
        return [{"filial": "FILIAL CURITIBA", "n": 43, "com_direito": 13,
                 "em_dobra": 0, "dobra_prazo": 1, "agendados": 4,
                 "ficha_parada": 0}]
    if "meses_2o" in sql and "nomefunc" in sql:
        return [
            {"nome": "JULIANA KARINE VERONEZ", "chapa": "1234",
             "funcao": "ANALISTA", "filial": "FILIAL CURITIBA",
             "adm": "2024-11-04", "aq_fim": "2025-11-03",
             "limite": "2026-11-03", "dias_ate": 64, "meses_2o": 9,
             "agendado": 0, "gozo_ini": None, "gozo_fim": None},
            {"nome": "MONICA DE FREITAS", "chapa": "5678",
             "funcao": "ASSISTENTE", "filial": "FILIAL SBC",
             "adm": "2019-12-02", "aq_fim": "2025-12-01",
             "limite": "2026-12-01", "dias_ate": 92, "meses_2o": 8,
             "agendado": 1, "gozo_ini": "2026-09-10", "gozo_fim": "2026-10-09"},
            # limite ABSURDO para o `min`: ficha com o acumulo estourado nao
            # pode virar "14/12" na barra da tela.
            {"nome": "FICHA ESQUISITA", "chapa": "9", "funcao": "X",
             "filial": "MATRIZ", "adm": "2010-01-01", "aq_fim": "2024-01-01",
             "limite": "2025-01-01", "dias_ate": -50, "meses_2o": 19,
             "agendado": 0, "gozo_ini": None, "gozo_fim": None},
        ]
    if "gozofinfer >= TRUNC(SYSDATE)" in sql and "agora" in sql:
        return []
    if "ganham" in sql:
        # setembro e novembro; OUTUBRO nao volta, e e ele que prova o eixo
        # gerado.
        return [{"m": "2026-09", "ganham": 5}, {"m": "2026-11", "ganham": 12}]
    if "dobram" in sql:
        return [{"m": "2026-11", "dobram": 1}]
    if "CONNECT BY LEVEL" in sql:
        base = ["2026-08", "2026-09", "2026-10", "2026-11"]
        return [{"m": m} for m in base]
    if "COUNT(DISTINCT fe.codintfunc) pessoas" in sql:
        return [{"linhas": 192, "pessoas": 191}]
    if "TRUNC(ADD_MONTHS" in sql and "aq_atual" in sql:
        return []
    return [{"agora": "2026-08-31 09:00"}]


@pytest.fixture()
def ferias(monkeypatch):
    monkeypatch.setattr(_qf.db, "query", _linhas_falsas)
    return _qf.get_ferias()


def test_a_fila_diz_quanto_do_SEGUNDO_periodo_ja_correu(ferias):
    """"8" sozinho nao diz nada: e o quanto FALTA que decide o agendamento. E
    o valor e limitado a 0..12 — ficha com acumulo estourado apareceria como
    "19/12" numa barra que so vai ate 12, e a barra passaria da caixa."""
    f = {x["nome"]: x for x in ferias["fila"]}
    assert f["JULIANA KARINE VERONEZ"]["meses_2o"] == 9
    assert f["FICHA ESQUISITA"]["meses_2o"] == 12, "tem de saturar em 12"


def test_a_fila_distingue_quem_JA_TEM_data_marcada(ferias):
    """Ter direito adquirido e normal; nao ter data marcada e o que vira
    trabalho. Sem a distincao, a fila trata igual quem ja resolveu e quem nao."""
    f = {x["nome"]: x for x in ferias["fila"]}
    assert f["MONICA DE FREITAS"]["agendado"] is True
    assert f["JULIANA KARINE VERONEZ"]["agendado"] is False


def test_o_KPI_conta_quem_esta_SEM_data_marcada(ferias):
    """65 com direito e 65 sem agenda sao o mesmo fato lido de dois jeitos, e
    so o segundo e acionavel."""
    assert ferias["kpis"]["sem_agenda"] == 64
    assert ferias["kpis"]["segundo_6"] == 13


def test_o_eixo_dos_12_meses_e_GERADO_e_nao_colhido(ferias):
    """Outubro nao volta de nenhuma das duas consultas. Colhido, o grafico
    poria setembro ao lado de novembro e desenharia continuidade sobre um mes
    que existe e vale zero — a mesma armadilha que ligou abril em agosto na
    serie da jornada."""
    meses = [x["mes"] for x in ferias["agenda_mensal"]]
    assert meses == ["2026-08", "2026-09", "2026-10", "2026-11"]
    out = next(x for x in ferias["agenda_mensal"] if x["mes"] == "2026-10")
    assert out["ganham"] == 0 and out["dobram"] == 0


def test_ganham_e_dobram_sao_populacoes_DIFERENTES(ferias):
    """Uma e entrada de trabalho (fecha periodo), a outra e prazo vencendo (a
    fila de hoje batendo no limite). Somar as duas daria um total que nao quer
    dizer nada, e por isso o grafico as poe agrupadas, nunca empilhadas."""
    nov = next(x for x in ferias["agenda_mensal"] if x["mes"] == "2026-11")
    assert nov["ganham"] == 12 and nov["dobram"] == 1


def test_ficha_DUPLICADA_vira_sensor_e_nao_silencio(ferias):
    """`vw_ferias` tem 1.696 linhas para 1.693 pessoas — tres fichas
    duplicadas, hoje todas de demitidos. Se uma voltar a ficar ativa, o join
    conta a pessoa duas vezes e o passivo dela sai dobrado SEM que nenhum
    numero pareca errado: os totais continuam plausiveis e as proporcoes se
    mantem. E a familia do join com vigencia, e so contar os dois lados
    denuncia."""
    assert ferias["duplicadas"] == 1


def test_o_payload_atravessa_o_JSON(ferias):
    _json.dumps(ferias)
