"""Serve o index.html real e deixa o Playwright interceptar /api/**.

Mesma montagem de `tests/frontend/conftest.py` — repetida aqui em vez de
importada porque aquele conftest é escopo de diretório e o pytest não o
compartilha com este.
"""
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
DIR_API = RAIZ / "api"


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def pagina(base_url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pg = navegador.new_page()
        yield pg
        navegador.close()
