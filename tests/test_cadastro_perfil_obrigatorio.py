"""Cadastro de usuário: o perfil é escolha obrigatória (15/09/2026).

A tela nascia com o ADMINISTRADOR selecionado (a lista vem com ele primeiro),
e um "Criar usuário" desatento criava alguém que vê tudo e mexe na Gestão.
A tela agora nasce em branco; o servidor, que é quem vale, recusa perfil
ausente dizendo o que falta.
"""
from __future__ import annotations

import pytest

from tests.test_acesso_simulado import _entrar, casa  # noqa: F401  (fixture)


@pytest.mark.parametrize("perfil", [None, 0, ""])
def test_criar_usuario_sem_perfil_e_recusado_dizendo_o_que_falta(casa, perfil):  # noqa: F811
    chefe = _entrar("chefe@exemplo.test")
    corpo = {"nome": "Nova Pessoa", "email": "nova@exemplo.test",
             "senha_temporaria": "provisoria-123"}
    if perfil is not None:
        corpo["perfil_id"] = perfil
    r = chefe.post("/api/gestao/usuarios", json=corpo)
    assert r.status_code == 422, r.text
    assert r.json()["erro"] == "perfil_obrigatorio"
    assert "Escolha o perfil" in r.json()["mensagem"]
    lista = chefe.get("/api/gestao/usuarios").json()["usuarios"]
    assert "nova@exemplo.test" not in {u["email"] for u in lista}, "criou mesmo assim"


def test_perfil_que_nao_existe_continua_inexistente(casa):  # noqa: F811
    chefe = _entrar("chefe@exemplo.test")
    r = chefe.post("/api/gestao/usuarios", json={
        "nome": "Nova Pessoa", "email": "nova@exemplo.test",
        "senha_temporaria": "provisoria-123", "perfil_id": 999999})
    assert r.status_code == 422 and "inexistente" in r.json()["mensagem"]
