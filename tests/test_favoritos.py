"""Favoritos de tela, por usuário.

O QUE ISTO É, E O QUE JÁ EXISTIA
================================
O drawer já tinha **"Suas mais usadas"**, derivada de comportamento e guardada
no `localStorage`: ninguém escolhe, ela se forma sozinha. Favorito é o oposto —
**escolha explícita** — e por isso mora no banco e segue a pessoa entre o
computador e o celular. Guardá-lo no navegador faria o favorito do desktop não
existir no telefone, que é onde o acesso rápido mais importa.

A REGRA QUE ESTES TESTES GUARDAM
================================
**O RBAC é aplicado na LEITURA, nunca apagando.** Favorito de tela cujo acesso
foi revogado deixa de aparecer, mas a linha fica: apagar destruiria a escolha
de quem recupera o acesso na semana seguinte e esperaria encontrar tudo como
deixou. Filtrar na leitura custa nada e é reversível; apagar não.

E o filtro é obrigatório dos dois lados — servidor e tela. A lista pode ter
sido carregada antes de uma troca de perfil, e oferecer atalho para tela que a
pessoa não vê mais é vazamento de navegação, mesmo com a rota barrando depois.
"""
from __future__ import annotations

import pytest

from api import favoritos, pglocal


@pytest.fixture
def usuario(esquema_pg):
    """Um usuário de verdade: a tabela tem FK para `usuarios`."""
    favoritos.ESQUEMA = esquema_pg
    # `perfis.id` e `usuarios.id` sao GENERATED ALWAYS AS IDENTITY: o banco
    # recusa id explicito. Insere e le de volta.
    pglocal.executar(
        "INSERT INTO perfis(nome, admin, criado_em) "
        "VALUES ('Teste', 0, '2026-08-30')", esquema=esquema_pg)
    pid = pglocal.um("SELECT id FROM perfis WHERE nome = 'Teste'",
                     esquema=esquema_pg)["id"]
    pglocal.executar(
        "INSERT INTO usuarios(nome, email, senha_hash, perfil_id, criado_em) "
        "VALUES ('T', 't@s.local', 'x', %s, '2026-08-30')", (pid,),
        esquema=esquema_pg)
    uid = pglocal.um("SELECT id FROM usuarios WHERE email = 't@s.local'",
                     esquema=esquema_pg)["id"]
    try:
        yield uid
    finally:
        favoritos.ESQUEMA = None


TODAS = {"home", "fluxo", "prem", "veic", "comb", "km"}


# ── o básico ────────────────────────────────────────────────────────────────


def test_comeca_vazio(usuario):
    assert favoritos.listar(usuario, TODAS) == []


def test_alternar_LIGA_e_DESLIGA(usuario):
    assert favoritos.alternar(usuario, "prem", TODAS)["favorito"] is True
    assert favoritos.listar(usuario, TODAS) == ["prem"]
    assert favoritos.alternar(usuario, "prem", TODAS)["favorito"] is False
    assert favoritos.listar(usuario, TODAS) == []


def test_o_novo_entra_no_FIM(usuario):
    """Quem acabou de favoritar sabe onde procurar. Empurrar os outros para
    baixo mexeria numa ordem que a pessoa arrumou."""
    for t in ("prem", "veic", "comb"):
        favoritos.alternar(usuario, t, TODAS)
    assert favoritos.listar(usuario, TODAS) == ["prem", "veic", "comb"]


# ── o RBAC ──────────────────────────────────────────────────────────────────


def test_favorito_de_tela_SEM_ACESSO_nao_aparece(usuario):
    favoritos.alternar(usuario, "prem", TODAS)
    favoritos.alternar(usuario, "veic", TODAS)
    assert favoritos.listar(usuario, {"prem"}) == ["prem"]


def test_e_a_linha_NAO_e_apagada_quando_o_acesso_volta(usuario):
    """A parte que importa: perder acesso esconde, não destrói. Quem recupera
    o acesso encontra tudo como deixou."""
    favoritos.alternar(usuario, "prem", TODAS)
    favoritos.alternar(usuario, "veic", TODAS)
    assert favoritos.listar(usuario, {"prem"}) == ["prem"]      # veic sumiu
    assert favoritos.listar(usuario, TODAS) == ["prem", "veic"]  # e voltou


def test_favoritar_tela_SEM_ACESSO_e_RECUSADO(usuario):
    """E a recusa é DITA: quem chamou está oferecendo uma tela que não devia,
    e engolir isso esconderia o defeito."""
    with pytest.raises(PermissionError, match="Sem acesso"):
        favoritos.alternar(usuario, "srv", TODAS)


def test_tela_vazia_e_recusada(usuario):
    with pytest.raises(ValueError):
        favoritos.alternar(usuario, "", TODAS)


# ── o teto ──────────────────────────────────────────────────────────────────


def test_acima_do_LIMITE_e_recusado_com_o_motivo(usuario):
    """O teto não é limitação técnica: é a razão de o favorito existir. Trinta
    atalhos não encurtam caminho nenhum — viram outro menu, com o agravante de
    estar fora de ordem alfabética e sem agrupamento."""
    telas = {f"t{i}" for i in range(favoritos.LIMITE + 2)}
    for i in range(favoritos.LIMITE):
        favoritos.alternar(usuario, f"t{i}", telas)
    with pytest.raises(ValueError, match="máximo|deixa de ser atalho"):
        favoritos.alternar(usuario, f"t{favoritos.LIMITE}", telas)
    # e tirar um libera espaço
    favoritos.alternar(usuario, "t0", telas)
    assert favoritos.alternar(usuario, f"t{favoritos.LIMITE}",
                              telas)["favorito"] is True


# ── a ordem ─────────────────────────────────────────────────────────────────


def test_reordenar_grava_a_ordem(usuario):
    for t in ("prem", "veic", "comb"):
        favoritos.alternar(usuario, t, TODAS)
    favoritos.reordenar(usuario, ["comb", "prem", "veic"], TODAS)
    assert favoritos.listar(usuario, TODAS) == ["comb", "prem", "veic"]


def test_reordenar_IGNORA_tela_que_nao_e_favorita(usuario):
    """A lista que chega da tela pode estar velha (outra aba, outro aparelho).
    Tratá-la como verdade absoluta apagaria um favorito criado no celular há
    um minuto."""
    favoritos.alternar(usuario, "prem", TODAS)
    favoritos.reordenar(usuario, ["km", "prem"], TODAS)
    assert favoritos.listar(usuario, TODAS) == ["prem"]


def test_o_que_a_tela_NAO_mandou_fica_no_fim(usuario):
    """Some da ordenação, não da lista — favorito criado noutro aparelho
    enquanto esta aba estava aberta não pode se perder."""
    for t in ("prem", "veic", "comb"):
        favoritos.alternar(usuario, t, TODAS)
    favoritos.reordenar(usuario, ["comb"], TODAS)
    assert favoritos.listar(usuario, TODAS)[0] == "comb"
    assert set(favoritos.listar(usuario, TODAS)) == {"prem", "veic", "comb"}


# ── o catálogo de telas favoritáveis ────────────────────────────────────────


def test_as_telas_do_MENU_estao_todas_cobertas():
    """`srv`, `gestao` e `jornf` existem no menu e NÃO estão em `TELAS` —
    são liberadas por `admin` ou alcançadas como drill-down. Sem
    `TELAS_FORA_DO_RBAC`, o administrador não conseguiria favoritar a Saúde do
    Servidor: a validação usaria `TELAS` e a recusaria como "sem acesso", que
    é o oposto da verdade.

    Este teste é o que impede a lista de envelhecer: tela nova que fique fora
    dos dois conjuntos quebra aqui, e não vira favorito impossível.
    """
    import re
    from pathlib import Path

    from api import auth
    html = (Path(__file__).resolve().parents[1] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    bloco = re.search(r"const VIEWS = \{(.*?)\};", html, re.S).group(1)
    views = set(re.findall(r"(\w+):", bloco))
    cobertas = set(auth.TELAS) | set(auth.TELAS_FORA_DO_RBAC)
    assert not (views - cobertas), (
        "tela no menu sem entrada em TELAS nem em TELAS_FORA_DO_RBAC: "
        + ", ".join(sorted(views - cobertas)))
    assert not (cobertas - views), (
        "entrada de RBAC sem tela no menu: "
        + ", ".join(sorted(cobertas - views)))


def test_o_admin_pode_favoritar_TUDO():
    from api import auth
    perm = auth.telas_favoritaveis({"id": 1, "admin": True, "telas": []})
    assert "srv" in perm and "prem" in perm


def test_o_nao_admin_so_ve_as_dele():
    from api import auth
    perm = auth.telas_favoritaveis(
        {"id": 1, "admin": False, "telas": ["prem", "veic"]})
    assert perm == {"prem", "veic"}
    assert "srv" not in perm


def test_sem_sessao_nao_favorita_nada():
    from api import auth
    assert auth.telas_favoritaveis(None) == set()
