# -*- coding: utf-8 -*-
"""A agenda de e-mail da Gestão: a opção "só dias úteis", no navegador.

O servidor já recusa dia útil fora do diário e já descreve "todo dia útil"
(`tests/correio/test_inadimplencia.py`). O que só o navegador prova é o
caminho de ida e volta pela TELA: a opção aparece onde vale, a escolha chega ao
servidor, e editar um agendamento traz a escolha de volta — sem isso, salvar de
novo um agendamento de dia útil o faria voltar a sair no sábado, calado.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

AGENDA = {
    "agendamentos": [{
        "id": 7, "relatorio": "inadimplencia", "relatorio_nome": "Inadimplência — o dia",
        "destinatarios": "financeiro@exemplo.test", "frequencia": "diario",
        "hora": "13:00", "dia_semana": None, "dia_mes": None, "dias_uteis": True,
        "ativo": True, "ultima_execucao": None, "ultimo_resultado": None,
        "quando": "todo dia útil às 13:00", "proxima": "2026-09-14 13:00",
        "pronto": False, "motivo": "faltam 60 min"}],
    "relatorios": [{"id": "inadimplencia", "nome": "Inadimplência — o dia",
                    "descricao": "x"},
                   {"id": "digest", "nome": "Alertas do painel", "descricao": "x"}],
    "smtp_configurado": True, "janela_atraso_min": 240,
    "gerado_em": "2026-09-12 10:00:00",
}


def _abrir(pg, base_url):
    enviados: list = []

    def rota(route):
        req = route.request
        if "/api/auth/me" in req.url:
            corpo = ADMIN
        elif "/gestao/correio/agenda" in req.url and req.method == "POST":
            enviados.append(json.loads(req.post_data or "{}"))
            corpo = {"ok": True, "id": 8}
        elif "/gestao/correio/agenda" in req.url:
            corpo = AGENDA
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-email", timeout=20000)
    pg.click("#gtab-email")
    pg.wait_for_selector("#ag-tab tbody tr", timeout=15000)
    return enviados


def test_a_opcao_de_dia_util_so_aparece_no_DIARIO(pagina):
    """Um semanal marcado no sábado com "só dias úteis" nunca sairia."""
    pg, base = pagina
    _abrir(pg, base)
    pg.select_option("#ag-freq", "diario")
    assert pg.is_visible("#ag-box-dutil")
    pg.select_option("#ag-freq", "semanal")
    assert not pg.is_visible("#ag-box-dutil")
    pg.select_option("#ag-freq", "mensal")
    assert not pg.is_visible("#ag-box-dutil")


def test_a_escolha_VAI_ao_servidor(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    pg.select_option("#ag-rel", "inadimplencia")
    pg.fill("#ag-dest", "financeiro@exemplo.test")
    pg.select_option("#ag-freq", "diario")
    pg.fill("#ag-hora", "13:00")
    pg.select_option("#ag-dutil", "1")
    with pg.expect_request(lambda r: "/gestao/correio/agenda" in r.url and r.method == "POST",
                           timeout=15000):
        pg.click("#ag-salvar")
    corpo = enviados[-1]
    assert corpo["dias_uteis"] is True
    assert corpo["frequencia"] == "diario" and corpo["hora"] == "13:00"
    assert corpo["relatorio"] == "inadimplencia"


def test_editar_TRAZ_a_escolha_de_volta(pagina):
    """Sem isto, abrir o agendamento para mudar o destinatário e salvar o
    faria voltar a sair no fim de semana, calado."""
    pg, base = pagina
    _abrir(pg, base)
    assert "todo dia útil às 13:00" in pg.inner_text("#ag-tab")
    pg.click("#ag-tab button.gbtn:has-text('editar')")
    assert pg.input_value("#ag-dutil") == "1"
    assert pg.is_visible("#ag-box-dutil")
