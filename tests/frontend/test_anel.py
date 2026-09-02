# -*- coding: utf-8 -*-
"""O anel do CÓRTEX na tela de login e no carregamento das telas.

O que só se prova no navegador: o canvas do login ACENDE (pixels não
transparentes depois de um quadro — um canvas de largura zero ou um script
que não carregou ficam mudos, sem erro), e o anel do topo aparece enquanto
uma consulta está em voo e some quando ela termina.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HTML = (Path(__file__).resolve().parents[2] / "api" / "static" / "index.html").read_text(encoding="utf-8")
ANEL = (Path(__file__).resolve().parents[2] / "api" / "static" / "anel.js").read_text(encoding="utf-8")


def test_o_script_do_anel_esta_vendorizado_e_incluido():
    assert '<script src="/static/anel.js"></script>' in HTML
    assert "cortexAnel" in ANEL and "prefers-reduced-motion" in ANEL
    assert "cdn" not in ANEL.lower()


def test_login_e_topo_tem_o_canvas_e_o_hidden_e_respeitado():
    assert HTML.count('<canvas id="lg-anel"') == 1
    assert HTML.count('<canvas id="loadanel"') == 1
    assert re.search(r"\.loadanel\[hidden\]\{display:none\}", HTML)
    assert "body.tvmode .loadanel" in HTML, "painel de TV não tem indicador de carga"
    # o mesmo gancho que mostra a barra mostra o anel
    i = HTML.index("mostraBarra: (v) =>")
    assert "loadanel" in HTML[i:i + 300]


def _pixels_acesos(pg, sel):
    return pg.evaluate("""s => { const c=document.querySelector(s); if(!c) return -1;
        const x=c.getContext('2d'); const d=x.getImageData(0,0,c.width,c.height).data;
        let n=0; for(let i=3;i<d.length;i+=4) if(d[i]>20) n++; return n; }""", sel)


def test_o_anel_do_login_acende(pagina):
    pg, base_url = pagina
    pg.route("**/api/**", lambda r: r.fulfill(status=401, content_type="application/json", body="{}"))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html")
    pg.wait_for_selector("#loginOverlay:not(.oculto)", timeout=15000)
    pg.wait_for_timeout(700)
    assert erros == [], erros
    assert _pixels_acesos(pg, "#lg-anel") > 2000
    assert pg.evaluate("() => document.getElementById('lg-anel').clientWidth") >= 100


def test_o_anel_do_topo_aparece_durante_a_consulta_e_some_depois(pagina):
    pg, base_url = pagina

    # A consulta lenta é SEGURADA e liberada depois: dormir dentro do handler
    # de rota bloqueia o laço do Playwright síncrono inteiro, e a espera pela
    # visibilidade só rodaria depois de a resposta já ter chegado.
    presas = []

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(ADMIN))
            return
        if "ordens-compra" in u:
            presas.append(route)
            return
        route.fulfill(status=200, content_type="application/json", body="{}")
    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/index.html#oc")
    pg.wait_for_selector("#view-oc.on", timeout=15000)
    pg.wait_for_selector("#loadanel:not([hidden])", timeout=5000)
    pg.wait_for_timeout(400)             # escondido o laço dorme 120 ms; dá tempo de um quadro
    assert _pixels_acesos(pg, "#loadanel") > 100
    for r in presas:
        r.fulfill(status=200, content_type="application/json", body="{}")
    pg.wait_for_selector("#loadanel[hidden]", state="attached", timeout=10000)
