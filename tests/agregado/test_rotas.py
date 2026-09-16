# -*- coding: utf-8 -*-
"""As rotas do app do agregado — e a exceção que elas abrem no fail-closed.

A CASA TEM TRÊS EXCEÇÕES AO MIDDLEWARE, E ELAS NÃO SÃO IGUAIS. No rastreio a
porta é ABERTA de verdade (não há conta do outro lado). No app do motorista e
aqui, ela só TROCA DE PORTEIRO: existe sessão, mas com cookie e tabela
próprios, ilegíveis para o middleware do painel, que responderia 401 a uma
sessão perfeitamente válida. A liberação é por PREFIXO de propósito — listar
rota a rota daria 401 num app que funciona, e o sintoma mandaria procurar o
defeito no middleware, longe da causa.

O PREÇO DESSA ESCOLHA É ESTE ARQUIVO. Uma rota nova sob `/api/agregado/` que
esqueça `_agr_eu(req)` nasce aberta e a falha é MUDA: a rota funciona, devolve
o extrato financeiro certo, e não pergunta de quem ele é. O guard não conhece a
lista de rotas: ele a DESCOBRE, então rota nova entra no teste sozinha.
"""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

#: As únicas que respondem sem sessão. Cada uma é uma DECISÃO, escrita aqui:
#:
#:   entrar/confirmar — é assim que se entra; não há sessão ainda.
#:   sair             — quem clicou já quer estar fora, e um 401 aqui deixaria
#:                      o cookie no aparelho de quem pediu para sair.
#:   mestre/*         — é assim que se abre uma sessão de conferência. O
#:                      porteiro delas é `mestre.conferir()`, que LEVANTA, e há
#:                      teste próprio cobrando que as duas recusem sem código e
#:                      que nenhuma devolva nome de agregado antes de conferir
#:                      o segredo.
#:
#: Acrescentar uma linha a este conjunto é abrir ao mundo o extrato de um
#: fornecedor. Quem acrescentar sem escrever o porquê está pedindo para o
#: revisor não perceber.
SEM_SESSAO = {"/api/agregado/entrar", "/api/agregado/confirmar",
              "/api/agregado/sair", "/api/agregado/mestre/agregados",
              "/api/agregado/mestre/entrar"}


def rotas_do_app() -> list:
    from api.main import app
    fora = []
    for r in app.routes:
        caminho = getattr(r, "path", "")
        if caminho.startswith("/api/agregado/") and caminho not in SEM_SESSAO:
            fora.append((caminho, sorted(m for m in (r.methods or set())
                                         if m not in ("HEAD", "OPTIONS"))))
    return fora


def _chamavel(caminho: str) -> str:
    """`/api/agregado/acertos/{filial}/{numero}` → `/api/agregado/acertos/1/1`.

    O `1` é seguro e não enfraquece nada: a sessão é exigida ANTES de qualquer
    consulta, então a resposta continua sendo 401 exista ou não o acerto 1. Sem
    a substituição o FastAPI responderia 422 (o `{filial}` não é inteiro) e a
    asserção quebraria por forma, não por falta de sessão — e a tentação, nesse
    momento, seria pôr a rota em `SEM_SESSAO`, que é justamente o que este
    arquivo existe para impedir.
    """
    return re.sub(r"\{[^}]+\}", "1", caminho)


def test_toda_rota_do_app_exige_sessao():
    """O guard que faz a exceção do prefixo caber. NÃO tem lista fixa."""
    from api.main import app
    c = TestClient(app)
    achadas = rotas_do_app()
    assert achadas, "nenhuma rota de agregado encontrada — o guard ficou cego"
    for caminho, metodos in achadas:
        for metodo in metodos:
            r = c.request(metodo, _chamavel(caminho), json={})
            assert r.status_code == 401, (
                f"{metodo} {caminho} respondeu {r.status_code} SEM SESSÃO — "
                "rota nova sem `_agr_eu(req)` nasce aberta ao mundo")


def test_a_pagina_e_o_prefixo_estao_liberados_no_middleware():
    """Sem isto o app responde 401 em tudo, e o defeito parece ser do app."""
    from api import auth
    assert auth._PUBLICAS_AGREGADO == ("/api/agregado/",)
    assert auth._rota_publica("/agregado")
    assert auth._rota_publica("/agregado/")
    assert auth._rota_publica("/api/agregado/entrar")
    assert auth._rota_publica("/api/agregado/acertos")
    # e o que NÃO é do app segue fechado
    assert not auth._rota_publica("/api/operacao/cco")
    assert not auth._rota_publica("/api/agregado")      # sem a barra não é prefixo


def test_o_cookie_do_agregado_nao_chega_ao_painel_nem_ao_app_do_motorista():
    """O `path` do cookie é a única coisa que torna IMPOSSÍVEL — e não só
    improvável — uma sessão de agregado aparecer numa requisição de outra
    parte do sistema."""
    from api.agregado import sessao as asessao
    from api.motorista import sessao as msessao
    assert asessao.COOKIE_PATH == "/api/agregado"
    assert asessao.COOKIE != msessao.COOKIE
    assert not "/api/motorista".startswith(asessao.COOKIE_PATH)
    assert not "/api/auth".startswith(asessao.COOKIE_PATH)


def test_o_app_esta_registrado_como_aplicativo_da_casa():
    """Aplicativo fora do registro não aparece no menu e ninguém descobre —
    por isso `tests/test_aplicativos.py` cobra pelo DISCO. Aqui fica a parte
    que é deste app: o cartão existe e aponta para a página certa."""
    from api import aplicativos
    app = aplicativos.por_id("agregado")
    assert app and app["arquivo"] == "agregado.html" and app["rota"] == "/agregado"
    assert "WhatsApp" in app["entrada"]
