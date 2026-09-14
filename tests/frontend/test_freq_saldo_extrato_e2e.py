# -*- coding: utf-8 -*-
"""A aba Saldo da Frequência mostra o EXTRATO do Globus, no navegador.

O payload NÃO é escrito à mão: ele sai do próprio `frequencia.get_banco_horas()`
rodando sobre o dublê do extrato (`tests/rh/test_banco_de_horas_extrato.py`).
Dublê de tela escrito à mão deixa a tela e o servidor divergirem no formato
sem nenhum teste perceber — e o `renderFreq` foi reescrito inteiro em
14/09/2026, quando a tela deixou de ler o acumulador.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

CASA = {**USUARIO, "admin": True, "perfil": "Administrador"}


@pytest.fixture
def payload(monkeypatch):
    from api import frequencia as F
    from api import queries
    from tests.rh import test_banco_de_horas_extrato as T
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(F.db, "query", T._roteador)
    try:
        return json.loads(json.dumps(F.get_banco_horas(), ensure_ascii=False))
    finally:
        queries._RESP_CACHE.clear()


def _abrir(pg, base_url, banco):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/rh/frequencia/banco-horas" in u:
            corpo = banco
        elif "/api/rh/frequencia" in u or "/api/pontocertificado" in u:
            corpo = {"configurado": False}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo, ensure_ascii=False))

    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 1500, "height": 1000})
    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#freq")
    pg.wait_for_selector("#kpis-freq .kpi", timeout=20000)
    return erros


def test_os_KPIs_saem_em_HH_MM_e_dizem_o_que_foi_LEVADO(pagina, payload):
    pg, base = pagina
    erros = _abrir(pg, base, payload)
    txt = pg.inner_text("#kpis-freq")
    assert "146:24 h" in txt, txt
    assert "Levado para 09/2026" in txt and "-17:36 h" in txt
    assert "2 de 2 credores pagos e zerados" in txt
    assert "Acumulado no ERP" not in txt, "voltou o KPI do acumulador"
    assert not erros, erros


def test_por_pessoa_tem_as_COLUNAS_DO_EXTRATO(pagina, payload):
    pg, base = pagina
    _abrir(pg, base, payload)
    pg.evaluate("abaTrocar('freq','pessoas')")
    pg.wait_for_selector("#freq-pessoas tbody tr", timeout=10000)
    # `text_content`, e não `inner_text`: o cabeçalho de tabela e o selo são
    # maiúsculos pelo CSS, e `inner_text` devolve o texto JÁ transformado.
    cab = pg.text_content("#freq-pessoas thead")
    for col in ("Saldo anterior", "Movimento", "Saldo no fim do mês", "Levado para 09/2026"):
        assert col in cab, cab
    a = pg.locator("#freq-pessoas tbody tr:has-text('PESSOA A')").text_content()
    for v in ("98:33", "34:23", "132:56", "0:00"):
        assert v in a, a
    fora = pg.text_content("#freq-cadastro")
    assert "PESSOA E" in fora and "desligado" in fora
    assert "PESSOA E" not in pg.text_content("#freq-pessoas")


def test_o_confronto_NAO_afirma_mais_que_o_saldo_subiu(pagina, payload):
    pg, base = pagina
    _abrir(pg, base, payload)
    corpo = pg.inner_text("#aba-freq-passivo")
    assert "nao se encontram" not in corpo and "não se encontram" not in corpo
    assert pg.locator("#freq-conf-aviso").count() == 0
    assert pg.locator("#freq-janela-aviso").count() == 0
