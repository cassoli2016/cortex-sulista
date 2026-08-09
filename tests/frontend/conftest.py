"""Fixtures compartilhadas dos testes de frontend.

Servem o index.html real por um http.server e deixam o Playwright interceptar
todas as rotas /api/**, para testar a UI sem banco, sem tunel e sem AVA.
"""
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[2]
DIR_API = RAIZ / "api"

USUARIO = {
    "nome": "Teste", "email": "teste@sulista.local", "perfil": "admin",
    "admin": True, "telas": [],
}

# grava cada transicao do atributo hidden de #loadbar em window.__barraLog
ESPIA = """
window.__barraLog = [];
(function liga(){
  if (!document.documentElement) { document.addEventListener('readystatechange', liga, {once:true}); return; }
  new MutationObserver(function(ms){
    for (var i=0;i<ms.length;i++){
      var t = ms[i].target;
      if (t && t.id === 'loadbar') window.__barraLog.push(!t.hidden);
    }
  }).observe(document.documentElement, {subtree:true, attributes:true, attributeFilter:['hidden']});
})();
"""


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def pagina(base_url):
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pg = navegador.new_page()
        pg.add_init_script(ESPIA)
        yield pg, base_url
        navegador.close()
