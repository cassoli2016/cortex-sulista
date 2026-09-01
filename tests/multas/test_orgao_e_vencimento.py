"""Filtro por órgão autuador e semáforo de vencimento na tela de Multas.

O cuidado central desta tela: a baixa do auto quase nunca volta para o ERP (19
de 1.305 em 24 meses) porque a defesa é conduzida por escritório externo. Todo
número derivado de "em aberto" tem de dizer que fala do CADASTRO, não do caixa.
"""
from __future__ import annotations

import json
from pathlib import Path

from api.queries import MULTA_DET_SQL, MULTA_KPI_SQL, MULTA_ORGAO_SQL, _MULTA_BASE
from tests.frontend.conftest import USUARIO

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")


def test_sql_aceita_filtro_de_orgao():
    assert "%(orgao)s" in _MULTA_BASE
    assert "orgaopublico" in _MULTA_BASE


def test_sql_continua_compativel_com_pg93_e_latin1():
    for sql in (MULTA_KPI_SQL, MULTA_DET_SQL, MULTA_ORGAO_SQL):
        assert "FILTER (WHERE" not in sql.upper()
        sql.encode("latin-1")


def test_kpi_conta_vencidos_somente_entre_os_em_aberto():
    assert "dtliquidacao IS NULL AND r.dtbaixa IS NULL" in MULTA_KPI_SQL
    assert "dtvencimento < current_date" in MULTA_KPI_SQL


def test_detalhe_traz_vencimento_e_orgao():
    assert "AS vencimento" in MULTA_DET_SQL
    assert "AS orgao" in MULTA_DET_SQL


def test_select_de_orgao_existe_na_tela():
    assert 'id="fMulOrgao"' in S
    bloco = S.split("function qsView(k){", 1)[1].split("\n}", 1)[0]
    assert "k==='mul'" in bloco and "orgao" in bloco


def test_a_tela_avisa_que_o_numero_e_do_cadastro_nao_do_caixa():
    """Sem este aviso, 931 autos vencidos seriam lidos como 931 multas não
    pagas — e não são."""
    assert "pelo CADASTRO, não pelo caixa" in S
    assert "escritório externo" in S


def _abrir(pg, base_url, dados):
    def rota(route):
        u = route.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            dados if "/api/frota/multas" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#mul")
    pg.wait_for_selector("#view-mul.on", timeout=20000)
    # A TELA DO ERP VIROU DUAS ABAS DENTRO DA SMARTEC em 31/08/2026: as duas
    # telas de multa fundiram-se numa só, e a nova HERDOU o id `mul` — que já
    # estava concedido a Diretoria e Frota, e um id novo faria multas sumirem
    # do menu deles.
    #
    # O conteúdo do ERP agora carrega SOB DEMANDA (`data-ao-abrir`), então
    # abrir a aba não é contornar o teste: é o caminho de quem usa, e é
    # também o que faz o gráfico ser desenhado com o contêiner já visível.
    pg.evaluate("abaTrocar('smt','hist')")
    pg.wait_for_selector("#kpis-mul .kpi", timeout=20000)
    pg.evaluate("abaTrocar('smt','resp')")
    pg.wait_for_selector("#mul-veic tr.forn-row", timeout=20000)
    return erros


def _dados(vencimento="2020-01-10", paga=False):
    return {
        "kpis": {"multas": 3, "valor": 900.0, "pontos": 0, "com_valor": 3,
                 "com_pontos": 0, "com_motorista": 3, "pagas": 0,
                 "pendente_valor": 900.0, "veiculos": 1, "com_vencimento": 3,
                 "vencidos": 2, "vencidos_valor": 600.0, "vencendo": 1},
        "mensal": [], "tipos": [],
        "veiculos": [{"placa": "AAA1A11", "utilizacao": "FROTA", "multas": 3,
                      "valor": 900.0, "pontos": 0, "ocultas": 0,
                      "multas_lista": [
                          {"data": "2019-12-01", "infracao": "Velocidade",
                           "orgao": "ANTT", "motorista": "FULANO", "local": "SP/SP",
                           "pontos": 0, "valor": 300.0, "vencimento": vencimento,
                           "paga": paga}]}],
        "motoristas": [],
        "orgaos": [{"orgao": "PRF", "multas": 360, "valor": 1.0, "pontos": 0},
                   {"orgao": "ANTT", "multas": 67, "valor": 2.0, "pontos": 0}],
        "dt_de": "2024-08-18", "dt_ate": "2026-08-18", "placa": None,
        "orgao": None, "atualizado_em": "2026-08-18T10:00:00",
        "fonte": "teste"}


def test_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    assert _abrir(pg, base, _dados()) == []


def test_select_de_orgao_e_preenchido_pela_consulta(pagina):
    pg, base = pagina
    _abrir(pg, base, _dados())
    opcoes = pg.eval_on_selector_all("#fMulOrgao option", "e=>e.map(x=>x.textContent)")
    assert "Todos" in opcoes[0]
    assert any("ANTT" in o for o in opcoes)
    assert any("PRF" in o for o in opcoes)


def test_vencidos_viraram_ALERTA_com_a_ressalva(pagina):
    """Era o 5º KPI numa grade de 4 — órfão sozinho na segunda linha. Virou
    ALERTA em 31/08/2026 (a anatomia da casa põe ali o que exige ação), e a
    ressalva do cadastro×caixa foi JUNTO: sem ela, 330 autos vencidos se
    leriam como 330 multas sem pagar."""
    pg, base = pagina
    _abrir(pg, base, _dados())
    kpis = pg.inner_text("#kpis-mul")
    assert "Vencidos em aberto" not in kpis, "o 5º KPI órfão voltou para a grade k4"
    alertas = pg.inner_text("#alerts-mul")
    assert "vencidos em aberto no cadastro" in alertas.lower()
    assert "pelo CADASTRO" in alertas


def test_auto_vencido_em_aberto_fica_marcado(pagina):
    pg, base = pagina
    _abrir(pg, base, _dados(vencimento="2020-01-10", paga=False))
    pg.click("#mul-veic tr.forn-row")
    html = pg.inner_html("#mul-det-0")
    assert "venceu há" in html


def test_auto_pago_nao_e_marcado_como_vencido(pagina):
    """Semáforo só vale para o que está em aberto no cadastro."""
    pg, base = pagina
    _abrir(pg, base, _dados(vencimento="2020-01-10", paga=True))
    pg.click("#mul-veic tr.forn-row")
    assert "venceu há" not in pg.inner_html("#mul-det-0")


def test_auto_sem_vencimento_mostra_travessao(pagina):
    pg, base = pagina
    _abrir(pg, base, _dados(vencimento=None))
    pg.click("#mul-veic tr.forn-row")
    assert "sem data de vencimento" in pg.inner_html("#mul-det-0")
