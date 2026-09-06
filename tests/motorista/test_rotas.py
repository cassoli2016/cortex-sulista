# -*- coding: utf-8 -*-
"""As rotas do app — e a exceção que elas abrem no fail-closed da casa.

A CASA TEM DUAS EXCEÇÕES AO MIDDLEWARE, E ELAS NÃO SÃO IGUAIS. No rastreio a
porta é ABERTA de verdade (não há conta do outro lado), e por isso lá a
liberação é rota por rota, com teste provando que o PREFIXO não vale — uma
rota nova nasceria aberta na internet.

Aqui a porta só TROCA DE PORTEIRO: o motorista tem sessão, mas com cookie e
tabela próprios, ilegíveis para o middleware do painel, que responderia 401 a
uma sessão perfeitamente válida. A liberação é por PREFIXO de propósito —
listar rota a rota daria 401 num app que funciona, e o sintoma mandaria
procurar o defeito no middleware, longe da causa.

O PREÇO DESSA ESCOLHA É ESTE ARQUIVO. Uma rota nova sob `/api/motorista/` que
esqueça `_eu(req)` nasce aberta e a falha é MUDA: a rota funciona, devolve o
dado certo, e não pergunta quem está lendo. `test_toda_rota_do_app_exige_sessao`
varre o app inteiro e é o que impede isso — ele não conhece a lista de rotas,
ele a DESCOBRE, então rota nova entra no teste sozinha.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.motorista import sessao as msessao

#: As únicas que respondem sem sessão. Cada uma é uma DECISÃO, escrita aqui:
#:
#:   entrar/confirmar — é assim que se entra; não há sessão ainda.
#:   sair             — quem clicou já quer estar fora, e um 401 aqui deixaria
#:                      o cookie no aparelho de quem pediu para sair.
#:
#: Acrescentar uma linha a este conjunto é abrir uma rota ao mundo. Quem
#: acrescentar sem escrever o porquê está pedindo para o revisor não perceber.
SEM_SESSAO = {"/api/motorista/entrar", "/api/motorista/confirmar",
              "/api/motorista/sair"}


def rotas_do_app() -> list:
    from api.main import app
    fora = []
    for r in app.routes:
        caminho = getattr(r, "path", "")
        if caminho.startswith("/api/motorista/") and caminho not in SEM_SESSAO:
            fora.append((caminho, sorted(m for m in (r.methods or set())
                                         if m not in ("HEAD", "OPTIONS"))))
    return fora


def test_toda_rota_do_app_exige_sessao():
    """O guard que faz a exceção do prefixo caber. NÃO tem lista fixa."""
    from api.main import app
    c = TestClient(app)
    achadas = rotas_do_app()
    assert achadas, "nenhuma rota de motorista encontrada — o guard ficou cego"
    for caminho, metodos in achadas:
        for metodo in metodos:
            r = c.request(metodo, caminho, json={})
            assert r.status_code == 401, (
                f"{metodo} {caminho} respondeu {r.status_code} SEM SESSÃO — "
                "rota nova sem `_eu(req)` nasce aberta ao mundo")


def test_sair_e_a_excecao_e_ela_e_deliberada():
    """Sair sem sessão devolve 200: quem clicou já quer estar fora, e um 401
    aqui deixaria o cookie no aparelho de quem pediu para sair."""
    from api.main import app
    r = TestClient(app).post("/api/motorista/sair")
    assert r.status_code == 200 and r.json()["ok"]


def test_a_pagina_e_a_api_do_app_sao_publicas_para_o_middleware():
    assert auth._rota_publica("/motorista")
    assert auth._rota_publica("/motorista/")
    assert auth._rota_publica("/api/motorista/entrar")
    assert auth._rota_publica("/api/motorista/viagem")


def test_o_resto_do_api_continua_fechado():
    for rota in ("/api/visao-geral", "/api/jornada/motorista",
                 "/api/telemetria/motoristas", "/api/gestao/usuarios",
                 "/api/auth/me", "/api/motoristas"):
        assert not auth._rota_publica(rota), "%s ficou aberta" % rota


def test_a_liberacao_nao_escapa_do_prefixo():
    """`/api/motorista` sem barra NÃO entra: sem isso, `/api/motoristas`
    (plural, uma rota interna qualquer que alguém crie amanhã) casaria."""
    assert not auth._rota_publica("/api/motorista")
    assert not auth._rota_publica("/api/motoristas/lista")


# --------------------------------------------------- os dois mundos separados

def test_cookie_de_motorista_nao_abre_o_painel(esq):
    """O ponto inteiro da identidade separada.

    Mesmo com um token de motorista VÁLIDO, o painel responde 401: o cookie
    dele tem outro nome, e `auth.sessao_atual` não sabe lê-lo.
    """
    from api.main import app
    from .conftest import cadastrar
    cadastrar(esq, "MOT-1", "5547999990001")
    sid = msessao.abrir("MOT-1", esquema=esq)
    token = msessao.emitir("MOT-1", sid)

    c = TestClient(app)
    c.cookies.set(msessao.COOKIE, token)
    for rota in ("/api/auth/me", "/api/visao-geral", "/api/gestao/usuarios"):
        assert c.get(rota).status_code in (401, 403), rota


def test_token_do_painel_nao_vale_no_app(esq):
    """E a volta: um token de painel, assinado com o MESMO segredo da casa,
    não abre o app. Quem fecha isso é o `tipo` dentro do token.

    ESTE TESTE JÁ FOI VERDE PELO MOTIVO ERRADO, e a sabotagem o pegou: com um
    `auth._emitir_token(1, 1)` qualquer, quem recusava era o `if not sid` —
    tirar a conferência de `tipo` do código não deixava o teste vermelho, e o
    guard não guardava nada.

    Agora a colisão é COMPLETA e nada além do `tipo` sobra para barrar: o
    token do painel carrega `sid` (ele leva a sessão da auditoria de uso) e o
    `sub` dele é o id do usuário — que é um número, exatamente como o
    `cadastro.codigo` de um motorista costuma ser.
    """
    from api.main import app
    from .conftest import cadastrar
    cadastrar(esq, "1", "5547999990001")           # código numérico, como no ERP
    sid = msessao.abrir("1", esquema=esq)
    token_painel = auth._emitir_token(1, 1, sid)   # sub="1", sid=sid, sem tipo

    c = TestClient(app)
    c.cookies.set(msessao.COOKIE, token_painel)
    assert c.get("/api/motorista/eu").status_code == 401


def test_o_cookie_do_app_nem_e_enviado_ao_painel():
    """`path` no prefixo da API do app: o navegador não manda o cookie de
    motorista para `/api/dre`. Torna impossível, e não só improvável, que uma
    sessão de motorista apareça numa requisição de tela da casa."""
    assert msessao.COOKIE_PATH == "/api/motorista"
    assert msessao.COOKIE != auth.COOKIE
