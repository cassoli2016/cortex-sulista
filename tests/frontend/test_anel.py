# -*- coding: utf-8 -*-
"""O anel do CÓRTEX na tela de login e no menu lateral.

Desde 02/09/2026 o nome CÓRTEX vive DENTRO do anel do menu (bloco `.marca`),
não acima dele: soltos, liam-se como dois elementos; juntos, viram uma marca.

O que só se prova no navegador: o canvas ACENDE (pixels não transparentes
depois de um quadro — um canvas de largura zero ou um script que não
carregou ficam mudos, sem erro). O anel do MENU gira SEMPRE, sem depender
de consulta em voo: ele saiu da topbar em 02/09/2026, onde acendia e apagava
a cada carga e virava um pisca. Quem indica consulta em voo é a barra do
topo (#loadbar), e há teste garantindo que o anel não voltou para lá.
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


def test_o_anel_esta_no_login_e_no_menu_e_nao_na_topbar():
    assert HTML.count('<canvas id="lg-anel"') == 1
    assert HTML.count('<canvas id="menuanel"') == 1
    assert "loadanel" not in HTML, "o anel voltou a ser indicador de carga na topbar"
    # o anel e o nome vivem no MESMO bloco .marca, com o nome DENTRO do anel
    i = HTML.index('<div class="marca">')
    bloco = HTML[i:HTML.index('</div>', HTML.index('</span>', i))]
    assert 'id="menuanel"' in bloco and '<span class="mk">CÓRTEX</span>' in bloco
    # o nome fica em HTML por cima, nunca desenhado no canvas: precisa continuar
    # selecionável, legível por leitor de tela e nítido em qualquer densidade
    assert '.brandwrap .marca .mk{position:absolute' in HTML
    # e NAO tem o atributo hidden: gira sempre. O espaco antes e de proposito —
    # sem ele o aria-hidden do proprio canvas casaria e o teste passaria a mentir.
    tag = re.search(r'<canvas id="menuanel"[^>]*>', HTML).group(0)
    assert " hidden" not in tag, tag
    assert "body.tvmode .menuanel" in HTML, "painel de TV não esconde o anel"


def test_o_gancho_de_carga_nao_mexe_mais_em_anel():
    """A barra do topo continua sendo o indicador de consulta em voo; o anel
    saiu desse gancho para não piscar a cada carga."""
    i = HTML.index("mostraBarra: (v) =>")
    assert "anel" not in HTML[i:i + 300]


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


def test_o_anel_do_menu_gira_sem_consulta_em_voo(pagina):
    """O anel do menu é a marca viva, não um indicador: acende com a tela
    parada, sem nenhuma requisição pendente, e continua aceso depois."""
    pg, base_url = pagina
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(ADMIN) if "/api/auth/me" in r.request.url else "{}"))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#oc")
    pg.wait_for_selector("#view-oc.on", timeout=15000)
    # a barra de carga já apagou: não há nada em voo
    pg.wait_for_selector("#loadbar[hidden]", state="attached", timeout=10000)
    pg.wait_for_timeout(500)
    assert erros == [], erros
    assert pg.evaluate("() => !document.getElementById('menuanel').hidden")
    assert _pixels_acesos(pg, "#menuanel") > 100
    # e segue girando: um segundo depois continua aceso
    pg.wait_for_timeout(1000)
    assert _pixels_acesos(pg, "#menuanel") > 100
