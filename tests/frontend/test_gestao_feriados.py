# -*- coding: utf-8 -*-
"""A aba Feriados da Gestão, no navegador.

O que só o navegador prova: a folga que a web NÃO deu (Carnaval, ponto
facultativo) aparece DESMARCADA e se liga pela tela; o feriado da casa leva UF
e município ao servidor; e o ano sem busca DIZ que vale a lista da lei — senão
uma tabela vazia se leria como "não há feriado".
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _estado(ano, com_coleta=True):
    itens = [
        {"id": 1, "data": f"{ano}-02-17", "dia_semana": "terça", "nome": "Carnaval",
         "tipo": "facultativo", "uf": "", "municipio": "", "folga": False,
         "fonte": "brasilapi", "criado_por": None, "folga_por": None, "folga_em": None},
        {"id": 2, "data": f"{ano}-09-07", "dia_semana": "segunda",
         "nome": "Independência do Brasil", "tipo": "nacional", "uf": "", "municipio": "",
         "folga": True, "fonte": "brasilapi", "criado_por": None, "folga_por": None,
         "folga_em": None},
        {"id": 3, "data": f"{ano}-03-09", "dia_semana": "segunda",
         "nome": "Aniversário da cidade", "tipo": "municipal", "uf": "SC",
         "municipio": "Cidade Dublê", "folga": True, "fonte": "manual",
         "criado_por": "rh@exemplo.test", "folga_por": "rh@exemplo.test", "folga_em": None},
    ] if com_coleta else []
    return {"ano": ano, "itens": itens,
            "coleta": ({"ok_em": f"{ano}-09-12T10:00:00", "itens": 14, "divergencias": [],
                        "erro": None, "erro_em": None} if com_coleta else None),
            "fonte": "https://brasilapi.com.br/api/feriados/v1/%d" % ano}


def _abrir(pg, base_url, com_coleta=True):
    enviados: list = []

    def rota(route):
        req = route.request
        u = req.url.split("?")[0]
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/gestao/calendario" in u and req.method in ("POST", "DELETE"):
            enviados.append((req.method, u.split("/api/")[1], json.loads(req.post_data or "{}")))
            corpo = {"ok": True, "itens": 14, "folgas": 10, "divergencias": [], "id": 9,
                     "data": "2026-03-09", "nome": "x", "tipo": "municipal", "uf": "SC",
                     "municipio": "x", "folga": True}
        elif "/gestao/calendario" in u:
            ano = int(req.url.split("ano=")[1]) if "ano=" in req.url else 2026
            corpo = _estado(ano, com_coleta)
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-feriados", timeout=20000)
    pg.click("#gtab-feriados")
    pg.wait_for_selector("#fer-tab tr", timeout=15000)
    return enviados


def test_a_aba_mostra_o_tipo_e_a_FOLGA_de_cada_data(pagina):
    pg, base = pagina
    _abrir(pg, base)
    tab = pg.inner_text("#fer-tab")
    assert "Ponto facultativo" in tab and "Nacional (lei)" in tab
    assert "Cidade Dublê/SC" in tab
    assert not pg.is_checked("#fer-tab input.fer-folga[data-id='1']"), \
        "o Carnaval não pode nascer como folga"
    assert pg.is_checked("#fer-tab input.fer-folga[data-id='2']")
    assert "buscado na web" in pg.inner_text("#fer-status")


def test_marcar_a_folga_do_Carnaval_VAI_ao_servidor(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    with pg.expect_request(lambda r: "/calendario/1/folga" in r.url, timeout=15000):
        pg.check("#fer-tab input.fer-folga[data-id='1']")
    assert enviados[-1] == ("POST", "gestao/calendario/1/folga", {"folga": True})


def test_o_feriado_da_casa_leva_UF_e_MUNICIPIO(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    pg.fill("#fer-data", "2026-03-19")
    pg.fill("#fer-nome", "Padroeiro da cidade")
    pg.select_option("#fer-tipo", "municipal")
    pg.fill("#fer-uf", "SC")
    pg.fill("#fer-mun", "Cidade Dublê")
    with pg.expect_request(lambda r: r.url.split("?")[0].endswith("/gestao/calendario")
                           and r.method == "POST", timeout=15000):
        pg.click("#fer-salvar")
    assert enviados[-1][2] == {"data": "2026-03-19", "nome": "Padroeiro da cidade",
                               "tipo": "municipal", "uf": "SC", "municipio": "Cidade Dublê"}
    pg.select_option("#fer-tipo", "empresa")
    assert not pg.is_visible("#fer-box-uf") and not pg.is_visible("#fer-box-mun")


def test_o_botao_BUSCA_o_ano_escolhido_na_web(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    with pg.expect_request(lambda r: "/calendario/buscar" in r.url, timeout=15000):
        pg.click("#fer-buscar")
    metodo, rota, corpo = enviados[-1]
    assert rota == "gestao/calendario/buscar" and corpo["ano"] == int(pg.input_value("#fer-ano"))


def test_ano_sem_busca_DIZ_que_vale_a_lei(pagina):
    """Tabela vazia sem explicação se lê como "não há feriado"."""
    pg, base = pagina
    _abrir(pg, base, com_coleta=False)
    assert "vale a lista federal da lei" in pg.inner_text("#fer-status")
