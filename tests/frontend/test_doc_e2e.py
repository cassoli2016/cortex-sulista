"""A tela de Documentacao (#doc) contra o index.html real.

O payload servido e o de verdade (documentacao.montar()), entao o teste cobre a
ponta a ponta: extracao do painel -> API -> render -> busca local.
"""
from __future__ import annotations

import json

from api import documentacao
from tests.frontend.conftest import USUARIO


def _mockar(pg):
    doc = documentacao.montar()

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = USUARIO
        elif "/api/documentacao" in u:
            corpo = doc
        elif "/api/versao" in u:
            corpo = {"versao": doc["versao"], "rotulo": doc["rotulo"], "data": "2026-08-08"}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    return doc


def _abrir(pg, base, viewport=None):
    if viewport:
        pg.set_viewport_size(viewport)
    doc = _mockar(pg)
    pg.goto(f"{base}/static/index.html#doc")
    pg.wait_for_selector("#doc-grupos .doc-grupo", timeout=20000)
    return doc


def test_renderiza_grupos_glossario_e_versoes(pagina):
    pg, base = pagina
    doc = _abrir(pg, base)
    assert pg.eval_on_selector_all("#doc-grupos .doc-grupo", "e=>e.length") == len(doc["grupos"])
    assert pg.eval_on_selector_all(".doc-glo dt", "e=>e.length") == len(doc["glossario"])
    assert pg.eval_on_selector_all(".doc-ver", "e=>e.length") == len(doc["versoes"])


def test_mostra_a_procedencia_extraida_do_painel(pagina):
    """O texto do ⓘ tem de chegar ate a tela — e o que faz a documentacao
    dizer de qual tabela cada numero saiu."""
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#doc-grupos")
    assert "CT-e" in texto
    assert "programacaoembarque" in texto


def test_rotulo_cx_no_cabecalho_e_no_rodape(pagina):
    pg, base = pagina
    doc = _abrir(pg, base)
    assert pg.inner_text("#doc-rotulo") == doc["rotulo"]
    assert pg.inner_text("#appVersao") == doc["rotulo"]
    assert doc["rotulo"].startswith("CX-")


def test_busca_local_filtra_e_conta(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.fill("#doc-q", "retorno vazio")
    pg.wait_for_timeout(300)
    assert "resultado" in pg.inner_text("#doc-cont")
    visiveis = pg.eval_on_selector_all(
        "#doc-grupos .doc-grupo", "es=>es.filter(e=>e.style.display!=='none').length")
    assert 0 < visiveis < 10, visiveis          # filtrou, mas nao zerou


def test_busca_sem_resultado_avisa(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.fill("#doc-q", "zzzzzznaoexiste")
    pg.wait_for_timeout(300)
    assert pg.is_visible("#doc-vazio")


def test_limpar_a_busca_devolve_tudo(pagina):
    pg, base = pagina
    doc = _abrir(pg, base)
    pg.fill("#doc-q", "zzzzzznaoexiste")
    pg.wait_for_timeout(300)
    pg.fill("#doc-q", "")
    pg.wait_for_timeout(300)
    assert pg.is_hidden("#doc-vazio")
    visiveis = pg.eval_on_selector_all(
        "#doc-grupos .doc-grupo", "es=>es.filter(e=>e.style.display!=='none').length")
    assert visiveis == len(doc["grupos"])


def test_no_mobile_nao_rola_na_horizontal_e_entra_na_gaveta(pagina):
    pg, base = pagina
    _abrir(pg, base, viewport={"width": 390, "height": 760})
    largura = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert largura[0] <= largura[1], f"pagina rola na horizontal: {largura}"
    assert pg.eval_on_selector_all('#drawer a[href="#doc"]', "e=>e.length") == 1
