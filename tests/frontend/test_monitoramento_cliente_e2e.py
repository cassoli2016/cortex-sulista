# -*- coding: utf-8 -*-
"""O cartão "Monitoramento de cliente" da Gestão › E-mail, no navegador.

O servidor já recusa grade ruim e já descreve a frase
(`tests/correio/test_monitoramento_grade.py`). O que só o navegador prova é o
caminho de ida e volta pela TELA: os dias, as mercadorias e a frequência
escolhidos chegam ao servidor, e editar traz de volta o que estava gravado —
sem isso, abrir um monitoramento para trocar o destinatário e salvar faria
ele voltar a sair aos domingos, ou para todas as mercadorias, calado.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

MONS = {
    "monitoramentos": [{
        "id": 3, "cliente_raiz": "12345678", "cliente_nome": "CLIENTE TESTE S.A.",
        "mercadorias": ["ESCADA"], "destinatarios": "logistica@cliente.test",
        "responder_para": "torre@sulista.test", "intervalo_min": 120,
        "hora_inicio": "06:00", "hora_fim": "22:00", "dias_semana": "12345",
        "anexar_planilha": True, "ativo": True, "ultima_execucao": None,
        "ultimo_resultado": None,
        "quando": "a cada 2 h, das 06:00 às 22:00, de segunda a sexta",
        "proxima": "2026-09-14 06:00", "pronto": False, "motivo": "x"}],
    "intervalos_min": [60, 120, 180, 240, 360],
    "smtp_configurado": True, "gerado_em": "2026-09-12 10:00:00",
}
CLIENTES = {"clientes": [{"raiz": "12345678", "nome": "CLIENTE TESTE S.A.", "cargas": 7352},
                         {"raiz": "87654321", "nome": "OUTRO CLIENTE", "cargas": 120}]}
MERCS = {"mercadorias": [{"chave": "CHASSI", "rotulo": "CHASSI", "cargas": 1900},
                         {"chave": "ESCADA", "rotulo": "ESCADAS", "cargas": 380}]}


def _abrir(pg, base_url):
    enviados: list = []

    def rota(route):
        req, url = route.request, route.request.url
        if "/api/auth/me" in url:
            corpo = ADMIN
        elif "/correio/monitoramento/clientes" in url:
            corpo = CLIENTES
        elif "/correio/monitoramento/mercadorias" in url:
            corpo = MERCS
        elif "/correio/monitoramento" in url and req.method == "POST":
            enviados.append(json.loads(req.post_data or "{}"))
            corpo = {"ok": True, "id": 4}
        elif "/correio/monitoramento" in url:
            corpo = MONS
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-email", timeout=20000)
    pg.click("#gtab-email")
    pg.wait_for_selector("#mon-tab tbody tr", timeout=15000)
    pg.wait_for_selector("#mon-cli option[value='12345678']", state="attached", timeout=15000)
    return enviados


def test_a_lista_diz_a_grade_em_frase(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#mon-tab")
    assert "CLIENTE TESTE S.A." in txt
    assert "a cada 2 h, das 06:00 às 22:00, de segunda a sexta" in txt
    assert "ESCADA" in txt


def test_o_formulario_VAI_ao_servidor(pagina):
    pg, base = pagina
    enviados = _abrir(pg, base)
    pg.select_option("#mon-cli", "12345678")
    pg.wait_for_selector("#mon-merc input[value='ESCADA']", timeout=15000)
    pg.check("#mon-merc input[value='ESCADA']")
    pg.fill("#mon-dest", "logistica@cliente.test")
    pg.fill("#mon-resp", "torre@sulista.test")
    pg.select_option("#mon-int", "180")
    pg.uncheck("#mon-dias input[value='6']")          # tira o sábado
    with pg.expect_request(lambda r: "/correio/monitoramento" in r.url and r.method == "POST",
                           timeout=15000):
        pg.click("#mon-salvar")
    c = enviados[-1]
    assert c["cliente_raiz"] == "12345678" and c["cliente_nome"] == "CLIENTE TESTE S.A."
    assert c["mercadorias"] == ["ESCADA"]
    assert c["dias_semana"] == "12345"
    assert c["intervalo_min"] == 180
    assert c["responder_para"] == "torre@sulista.test"
    assert c["ativo"] is False                         # nasce desligado
    assert c["anexar_planilha"] is True


def test_editar_TRAZ_a_escolha_de_volta(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#mon-tab button.gbtn:has-text('editar')")
    pg.wait_for_selector("#mon-merc input[value='ESCADA']", timeout=15000)
    assert pg.input_value("#mon-cli") == "12345678"
    assert pg.is_checked("#mon-merc input[value='ESCADA']")
    assert not pg.is_checked("#mon-merc input[value='CHASSI']")
    assert pg.is_checked("#mon-dias input[value='5']")
    assert not pg.is_checked("#mon-dias input[value='6']")
    assert pg.input_value("#mon-ativo") == "1"
    assert pg.input_value("#mon-resp") == "torre@sulista.test"
