# -*- coding: utf-8 -*-
"""A página de rastreio aberta pelo link do E-MAIL não pode dizer "você já
recebe por WhatsApp".

Até 13/09/2026 só o aviso de WhatsApp mandava link (`#c=`), e a página deduzia:
chegou por link, já está cadastrado. O e-mail de monitoramento de cliente
passou a mandar o mesmo link, e a dedução virou mentira na tela de quem nunca
se cadastrou — foi o primeiro teste de quem opera que mostrou isso. O e-mail
marca a origem (`&o=email`); estes guards leem o NAVEGADOR, não o texto do HTML.
"""
from __future__ import annotations

import json

from tests.frontend.test_rastreio_responsivo import CARGA

TOKEN = "AQEUAP6QAQAB-VBXGzOXh_h38Q"


def _abrir(pg, base, fragmento):
    pedidos = []

    def link(route):
        pedidos.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(CARGA))

    pg.route("**/api/rastreio/link*", link)
    pg.route("**/vendor/leaflet/**", lambda r: r.abort())
    pg.goto(f"{base}/static/rastreio.html#{fragmento}")
    pg.wait_for_selector(".zap")
    return pedidos


def test_link_do_EMAIL_convida_em_vez_de_dizer_que_ja_recebe(pagina):
    pg, base = pagina
    pedidos = _abrir(pg, base, f"c={TOKEN}&o=email")
    zap = pg.inner_text(".zap")
    assert "Quero receber por WhatsApp" in zap
    assert "já recebe" not in zap and "SAIR" not in zap
    # o token vai inteiro para a API, sem a marca grudada nele
    assert pedidos and pedidos[0].endswith("t=" + TOKEN)
    # e o fragmento sai da barra de endereços, marca inclusive
    assert "#" not in pg.url


def test_link_do_WHATSAPP_continua_como_era(pagina):
    """Sem marca vale o de sempre: quem chegou pelo aviso de WhatsApp está,
    de fato, cadastrado."""
    pg, base = pagina
    _abrir(pg, base, f"c={TOKEN}")
    zap = pg.inner_text(".zap")
    assert "Você já recebe os avisos desta carga por WhatsApp" in zap
    assert "Quero receber" not in zap


def test_o_botao_leva_a_busca_com_o_documento_e_pede_o_CNPJ(pagina):
    """Cadastrar exige o segundo fator (documento + 4 dígitos do CNPJ), que o
    link não carrega: o botão não pula a prova, ele encurta o caminho até ela."""
    pg, base = pagina
    _abrir(pg, base, f"c={TOKEN}&o=email")
    pg.click("#btnQuero")
    pg.wait_for_selector("#form", state="visible")
    assert pg.input_value("#doc") == "1234"            # "CT-e 1234" da carga
    assert pg.input_value("#cnpj") == ""
    assert pg.evaluate("document.activeElement && document.activeElement.id") == "cnpj"
    assert "CNPJ" in pg.inner_text("#msg")
