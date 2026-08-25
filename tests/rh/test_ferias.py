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
