# -*- coding: utf-8 -*-
"""Acesso simulado, no navegador (15/09/2026).

Quem decide o acesso é o servidor (`tests/test_acesso_simulado.py`); aqui se
prova o que o administrador VÊ: a faixa que diz que é simulação, de quem e
até quando, e as duas portas — "Simular" na Gestão e "Sair da simulação".
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO
from tests.frontend.test_gestao_permissoes_e2e import GESTAO, PERMISSOES, _USR

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador", "telas": [], "id": 3,
         "simulacao": None}
BETO_SIMULADO = {**USUARIO, "admin": False, "perfil": "Operação", "telas": ["fluxo"],
                 "id": 7, "nome": "Beto Lima", "email": "beto@exemplo.test",
                 "simulacao": {"por_nome": "Chefe Souza", "por_email": "chefe@exemplo.test",
                               "expira": "2026-09-15 11:42:00"}}
USUARIOS = {"usuarios": [
    {**_USR, "id": 3, "nome": "Chefe Souza", "email": "chefe@exemplo.test",
     "perfil_id": 1, "perfil": "Administrador", "perfil_admin": 1},
    {**_USR, "id": 7, "nome": "Beto Lima", "email": "beto@exemplo.test",
     "perfil_id": 2, "perfil": "Operação"},
    {**_USR, "id": 9, "nome": "Caio Antigo", "email": "caio@exemplo.test",
     "perfil_id": 2, "perfil": "Operação", "ativo": 0}]}


def _abrir(pg, base, quem, hash_=""):
    posts: list[str] = []

    def rota(route):
        u = route.request.url
        caminho = "/" + u.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        if route.request.method == "POST":
            posts.append(caminho)
            corpo = {"ok": True}
        elif caminho == "/api/auth/me":
            corpo = quem
        elif caminho == "/api/gestao/usuarios":
            corpo = USUARIOS
        else:
            corpo = {**GESTAO, "/api/gestao/permissoes": PERMISSOES}.get(caminho, {})
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base}/static/index.html{hash_}")
    return posts, erros


def test_a_faixa_diz_quem_esta_sendo_simulado_e_ate_quando(pagina):
    pg, base = pagina
    posts, erros = _abrir(pg, base, BETO_SIMULADO)
    pg.wait_for_selector("#simFaixa", timeout=20000)
    texto = pg.inner_text("#simFaixa")
    assert "Simulando o acesso de Beto Lima" in texto
    assert "Só leitura" in texto and "11:42" in texto
    # o menu é o DELE: sem Gestão para quem não é administrador
    assert pg.evaluate("() => podeVer('gestao')") is False
    assert pg.evaluate("() => podeVer('fluxo')") is True
    # a faixa não pode tapar a tela nem empurrar nada para o lado
    caixa = pg.eval_on_selector("#simFaixa", "e => { const r = e.getBoundingClientRect();"
                                " return [r.left, r.right, innerWidth]; }")
    assert caixa[0] >= 0 and caixa[1] <= caixa[2], caixa
    assert not erros, erros


def test_sair_da_simulacao_chama_o_servidor(pagina):
    pg, base = pagina
    posts, _ = _abrir(pg, base, BETO_SIMULADO)
    pg.wait_for_selector("#simFaixa button", timeout=20000)
    with pg.expect_request(lambda r: r.url.endswith("/api/auth/simulacao/sair")):
        pg.click("#simFaixa button")
    assert "/api/auth/simulacao/sair" in posts


def test_sem_simulacao_nao_ha_faixa(pagina):
    pg, base = pagina
    _abrir(pg, base, ADMIN, "#gestao")
    pg.wait_for_selector("#ges-usr tr", timeout=20000)
    assert pg.query_selector("#simFaixa") is None


def test_simular_na_gestao_pede_ao_servidor_e_nao_se_oferece_para_voce_nem_inativo(pagina):
    pg, base = pagina
    posts, erros = _abrir(pg, base, ADMIN, "#gestao")
    pg.wait_for_selector("#ges-usr tr", timeout=20000)
    estado = pg.eval_on_selector_all(
        "#ges-usr button[data-simular]", "els => els.map(e => [e.dataset.simular, e.disabled])")
    assert estado == [["3", True], ["7", False], ["9", True]], estado
    with pg.expect_request(lambda r: r.url.endswith("/api/gestao/simular/7")):
        pg.click('#ges-usr button[data-simular="7"]')
    assert "/api/gestao/simular/7" in posts
    assert not erros, erros
