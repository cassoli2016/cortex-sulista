"""A aba Integrações da Gestão, contra o index.html real.

O que se protege aqui: o token entra e não volta. Nem no payload, nem no DOM
depois de salvo, nem num campo preenchido "para o usuário conferir".
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

STATUS_CONFIGURADO = {"credenciais": [
    {"nome": "GOBRAX_TOKEN", "descricao": "Token da API Gobrax (telemetria e premiação)",
     "configurado": True, "mascarado": "eyJh…kP74", "origem": "cofre",
     "atualizado_em": "2026-08-19 15:00:00"}]}

STATUS_VAZIO = {"credenciais": [
    {"nome": "GOBRAX_TOKEN", "descricao": "Token da API Gobrax (telemetria e premiação)",
     "configurado": False, "mascarado": None, "origem": None,
     "atualizado_em": None}]}


def _abrir(pg, base_url, status=None):
    enviados = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/gestao/credenciais" in u:
            if route.request.method == "POST":
                enviados.append(json.loads(route.request.post_data))
                corpo = {"nome": "GOBRAX_TOKEN", "configurado": True,
                         "mascarado": "abcd…wxyz", "origem": "cofre"}
            else:
                corpo = status or STATUS_CONFIGURADO
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#gestao")
    pg.wait_for_selector("#gtab-integracoes", timeout=20000)
    pg.click("#gtab-integracoes")
    pg.wait_for_selector("#ges-creds .badge", timeout=10000)
    return enviados, erros


def test_aba_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_mostra_a_credencial_mascarada_e_a_origem(pagina):
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#ges-creds")
    assert "configurado" in texto
    assert "eyJh…kP74" in texto
    assert "salvo aqui na tela" in texto


def test_campo_do_token_nasce_vazio_e_e_do_tipo_password(pagina):
    """Nunca preencher o campo com o segredo — nem para o usuário conferir."""
    pg, base = pagina
    _abrir(pg, base)
    campo = pg.locator("#cred-GOBRAX_TOKEN")
    assert campo.get_attribute("type") == "password"
    assert campo.input_value() == ""


def test_nao_configurado_avisa_que_a_integracao_esta_desligada(pagina):
    pg, base = pagina
    _abrir(pg, base, status=STATUS_VAZIO)
    texto = pg.inner_text("#ges-creds")
    assert "não configurado" in texto
    assert "desligada" in texto


def test_salvar_envia_o_valor_e_limpa_o_campo(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    pg.fill("#cred-GOBRAX_TOKEN", "token-novo-de-teste-123456")
    pg.click("#ges-creds button.btn")
    pg.wait_for_timeout(600)
    assert enviados and enviados[0]["valor"] == "token-novo-de-teste-123456"
    # o segredo não pode ficar no DOM depois de enviado
    assert pg.input_value("#cred-GOBRAX_TOKEN") == ""


def test_salvar_vazio_nao_chama_a_api(pagina):
    pg, base = pagina
    enviados, _ = _abrir(pg, base)
    pg.click("#ges-creds button.btn")
    pg.wait_for_timeout(400)
    assert enviados == []
