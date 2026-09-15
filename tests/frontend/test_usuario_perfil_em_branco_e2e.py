# -*- coding: utf-8 -*-
"""Cadastro de usuário na tela: o perfil nasce EM BRANCO (15/09/2026).

Antes, o select nascia no primeiro perfil da lista — o administrador — e um
"Criar usuário" desatento criava alguém que vê tudo. O servidor recusa perfil
ausente (`tests/test_cadastro_perfil_obrigatorio.py`); aqui se prova que a
tela não manda nada sem a escolha, e que escolher administrador AVISA.
"""
from __future__ import annotations

from tests.frontend.test_acesso_simulado_e2e import ADMIN, _abrir


def _novo(pg, base):
    posts, erros = _abrir(pg, base, ADMIN, "#gestao")
    pg.wait_for_selector("#ges-usr tr", timeout=20000)
    pg.click("text=+ Novo usuário")
    pg.wait_for_selector("#gu-perfil", timeout=10000)
    return posts, erros


def test_o_perfil_nasce_em_branco_e_nao_no_administrador(pagina):
    pg, base = pagina
    _, erros = _novo(pg, base)
    assert pg.eval_on_selector("#gu-perfil", "e => e.value") == ""
    assert "escolha o perfil" in pg.eval_on_selector(
        "#gu-perfil", "e => e.options[e.selectedIndex].textContent")
    assert pg.inner_text("#gu-perfil-hint").strip() == ""
    assert not erros, erros


def test_criar_sem_perfil_nao_manda_nada_e_diz_por_que(pagina):
    pg, base = pagina
    posts, _ = _novo(pg, base)
    pg.fill("#gu-nome", "Nova Pessoa")
    pg.fill("#gu-email", "nova@exemplo.test")
    pg.fill("#gu-senha", "provisoria-123")
    pg.click("text=Criar usuário")
    assert "Escolha o perfil" in pg.inner_text("#m-err")
    assert "/api/gestao/usuarios" not in posts, "a tela mandou o cadastro sem perfil"


def test_escolher_administrador_avisa_o_que_isso_da(pagina):
    pg, base = pagina
    _novo(pg, base)
    pg.select_option("#gu-perfil", "1")
    aviso = pg.inner_text("#gu-perfil-hint")
    assert "Administrador vê todas as telas e mexe na Gestão" in aviso
    assert "(acesso total)" in pg.eval_on_selector(
        "#gu-perfil", "e => e.options[e.selectedIndex].textContent")
