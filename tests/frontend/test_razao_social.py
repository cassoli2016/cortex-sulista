# -*- coding: utf-8 -*-
"""A razão social sob o título da tela (#empNome).

Ela vem de /api/financeiro/filtros por initFiltros(). Até 02/09/2026 essa
função só era chamada por load() (Financeiro) e loadOc() (Ordens de Compra):
abrir qualquer uma das outras telas deixava o campo com o travessão do HTML,
e o painel parecia de outra empresa. Agora entrar() carrega uma vez, no
arranque, e estes testes prendem esse comportamento numa tela que NÃO é do
Financeiro nem de Ordens de Compra.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
RAIZ = Path(__file__).resolve().parents[2]
HTML = (RAIZ / "api" / "static" / "index.html").read_text(encoding="utf-8")
FILTROS = {"empresa": "TRANSPORTADORA SULISTA S/A",
           "filiais": [{"codigo": 1, "nome": "FIL MTZ", "uf": "SP"}]}


def test_o_arranque_carrega_os_filtros_sem_depender_da_tela():
    """entrar() não pode delegar a carga da razão social à tela que abrir."""
    i = HTML.index("function entrar()")
    j = HTML.index("\n}", i)
    assert "initFiltros()" in HTML[i:j], "entrar() não carrega os filtros"


def _rota(pg, vistas_vazias=True):
    def h(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = json.dumps(ADMIN)
        elif "/api/financeiro/filtros" in u:
            corpo = json.dumps(FILTROS)
        else:
            corpo = "{}"
        route.fulfill(status=200, content_type="application/json", body=corpo)
    pg.route("**/api/**", h)


def test_a_razao_social_aparece_numa_tela_fora_do_financeiro(pagina):
    pg, base_url = pagina
    _rota(pg)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    # #mprev (Manutenção Preventiva) não é Financeiro nem Ordens de Compra e
    # nem sequer tem barra de filtros — é o caso que estava quebrado.
    pg.goto(base_url + "/static/index.html#mprev")
    pg.wait_for_selector("#view-mprev.on", timeout=15000)
    pg.wait_for_function(
        "() => (document.getElementById('empNome').textContent || '').trim().length > 3",
        timeout=10000)
    assert erros == [], erros
    assert pg.inner_text("#empNome").strip() == "TRANSPORTADORA SULISTA S/A"


def test_a_razao_social_nao_fica_no_travessao_do_html(pagina):
    """O HTML nasce com '—' no lugar; se a carga falhar em silêncio, o teste
    acima passaria por acidente em qualquer texto — este prende o travessão."""
    pg, base_url = pagina
    _rota(pg)
    pg.goto(base_url + "/static/index.html#veic")
    pg.wait_for_selector("#view-veic.on", timeout=15000)
    pg.wait_for_function(
        "() => document.getElementById('empNome').textContent.trim() !== '—'",
        timeout=10000)
