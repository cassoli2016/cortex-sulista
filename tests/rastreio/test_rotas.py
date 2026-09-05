# -*- coding: utf-8 -*-
"""As rotas públicas do rastreio — e o que continua fechado ao lado delas.

Este arquivo guarda a única exceção ao fail-closed da casa. O risco de uma
exceção não é ela: é ela CRESCER. Alguém acrescenta `/api/rastreio/lista`
amanhã, o prefixo casa, e uma rota nova nasce aberta na internet sem ninguém
decidir isso.

Por isso aqui se cobra as duas metades: que as duas rotas do rastreio
respondam sem sessão, e que o resto do `/api/` continue devolvendo 401 na
mesma requisição anônima.
"""
from __future__ import annotations

import pytest

from api import auth


# --------------------------------------------------------------------------
# a lista de exceções
# --------------------------------------------------------------------------
def test_as_rotas_do_rastreio_sao_publicas():
    assert auth._rota_publica("/rastreio")
    assert auth._rota_publica("/rastreio/")
    assert auth._rota_publica("/api/rastreio/buscar")
    assert auth._rota_publica("/api/rastreio/carga")


def test_a_excecao_e_por_ROTA_e_nao_por_PREFIXO():
    """O guard central deste arquivo.

    Se a liberação fosse por prefixo, qualquer rota nova sob
    `/api/rastreio/` nasceria aberta na internet — inclusive uma que alguém
    criasse para depurar, com o registro cru do ERP dentro.
    """
    assert not auth._rota_publica("/api/rastreio/")
    assert not auth._rota_publica("/api/rastreio/tudo")
    assert not auth._rota_publica("/api/rastreio/buscar/interno")
    assert not auth._rota_publica("/api/rastreio")


def test_o_resto_do_api_continua_fechado():
    for rota in ("/api/visao-geral", "/api/dre/parecer", "/api/operacao/torre",
                 "/api/gestao/usuarios", "/api/pneus", "/api/auth/me"):
        assert not auth._rota_publica(rota), "%s ficou aberta" % rota


def test_a_lista_publica_do_rastreio_tem_SO_as_duas():
    """Um teste sobre o TAMANHO da exceção. Ele fica vermelho quando alguém
    acrescenta uma rota — e é essa a intenção: a conversa acontece na revisão,
    não depois, na internet."""
    assert set(auth._PUBLICAS_RASTREIO) == {
        "/api/rastreio/buscar", "/api/rastreio/carga"}


# --------------------------------------------------------------------------
# a página e o que ela carrega
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pagina() -> str:
    from pathlib import Path
    raiz = Path(auth.__file__).resolve().parent / "static" / "rastreio.html"
    return raiz.read_text(encoding="utf-8")


def test_a_pagina_publica_NAO_carrega_o_app_autenticado(pagina):
    """36 mil linhas de painel, o roteador por hash, o RBAC e o Leaflet não
    servem a quem só quer saber se a carga chegou — e seriam baixados no 4G do
    pátio de uma fábrica.

    O teste olha o que a página CARREGA, não o que ela menciona: a primeira
    versão procurava a string "index.html" e ficava vermelha por causa do
    comentário que explica justamente que ela não o carrega.
    """
    import re

    carregados = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", pagina)
    for u in carregados:
        assert "index.html" not in u, "a página carrega o app: %s" % u
        assert "leaflet" not in u.lower(), "a página carrega o Leaflet: %s" % u
        assert "/vendor/" not in u, "a página carrega vendor pesado: %s" % u
    # e o que ela carrega de proposito e curto: fonte, logo, favicon e o anel
    assert any("anel.js" in u for u in carregados)


def test_a_pagina_pede_os_DOIS_campos(pagina):
    assert 'id="doc"' in pagina and 'id="cnpj"' in pagina
    assert pagina.count("required") >= 2


def test_os_campos_sao_confortaveis_no_CELULAR(pagina):
    """`inputmode=numeric` abre o teclado numérico; `font-size:16px` impede o
    iOS de dar zoom sozinho ao focar — o zoom desloca a página e a pessoa
    perde o botão de vista."""
    assert pagina.count('inputmode="numeric"') >= 2
    assert "font-size:16px" in pagina
    assert "min-height:48px" in pagina


def test_a_pagina_declara_viewport_e_area_segura(pagina):
    assert "viewport-fit=cover" in pagina
    assert "env(safe-area-inset-bottom)" in pagina


def test_a_pagina_NAO_pede_indexacao(pagina):
    """Carga de cliente não entra em busca do Google."""
    assert 'name="robots"' in pagina and "noindex" in pagina


def test_a_pagina_tem_os_TRES_estados_de_tema(pagina):
    """A regra da casa: paleta clara no `:root` puro, o escuro do sistema
    guardado por `:not([data-theme="light"])`, e o `[data-theme="dark"]`
    repetindo os mesmos tokens."""
    assert "prefers-color-scheme: dark" in pagina
    assert ':root:not([data-theme="light"])' in pagina
    assert ':root[data-theme="dark"]' in pagina
