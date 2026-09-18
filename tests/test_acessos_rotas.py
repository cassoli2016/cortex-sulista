"""Acessos por usuário com sessão de verdade (13/09/2026).

O que só se prova aqui, e não no teste de regra (`tests/test_acessos.py`):

1. **Vale no clique seguinte.** O ajuste entra no cálculo que `sessao_atual`
   refaz a cada requisição; ninguém precisa sair e entrar.
2. **É o SERVIDOR que recusa.** Tela tirada e aba tirada devolvem 403 na
   rota — esconder o botão é consequência, não a proteção.
3. **Admin ignora os ajustes**, e a trilha registra o que mudou.

As rotas-alvo são as da fila do Suporte (`/api/suporte/atendimento/*`, tela
`supfila`): leem só o banco da casa, e a lista de atendentes do módulo é um
dos lugares que passaram a usar o acesso efetivo.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import acessos, auth

SENHA = "senha-de-teste-123"
PAINEL = "/api/suporte/atendimento/painel"
AVISOS = "/api/suporte/atendimento/avisos"


@pytest.fixture
def casa(esquema_pg, monkeypatch):
    from api import notificacoes
    from api.suporte import comum
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(notificacoes, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        adm = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()["id"]
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES('Comum','',0,%s)",
                  (auth._agora(),))
        comum_p = c.execute("SELECT id FROM perfis WHERE nome='Comum'").fetchone()["id"]
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES('Atende','',0,%s)",
                  (auth._agora(),))
        atende_p = c.execute("SELECT id FROM perfis WHERE nome='Atende'").fetchone()["id"]
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'supfila')", (atende_p,))
        for nome, email, perfil in (("Chefe", "chefe@exemplo.test", adm),
                                    ("Ana", "ana@exemplo.test", comum_p),
                                    ("Beto", "beto@exemplo.test", atende_p)):
            c.execute("""INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                              deve_trocar_senha, criado_em)
                         VALUES(%s,%s,%s,%s,1,0,%s)""",
                      (nome, email, auth._ph.hash(SENHA), perfil, auth._agora()))
        ids = {r["email"].split("@")[0]: r["id"]
               for r in c.execute("SELECT id, email FROM usuarios").fetchall()}
    return {"esquema": esquema_pg, "ids": ids, "perfil_comum": comum_p}


def _entrar(email: str) -> TestClient:
    from api.main import app
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def _ajustar(chefe: TestClient, uid: int, **payload):
    r = chefe.post(f"/api/gestao/usuarios/{uid}", json=payload)
    assert r.status_code == 200, r.text
    return r


# ─────────────────────────────────────────────── vale no clique seguinte ───

def test_LIBERAR_tela_abre_a_rota_sem_novo_login(casa):
    chefe, ana = _entrar("chefe@exemplo.test"), _entrar("ana@exemplo.test")
    assert ana.get(PAINEL).status_code == 403
    _ajustar(chefe, casa["ids"]["ana"], acessos=[{"chave": "supfila", "efeito": "liberar"}])
    assert ana.get(PAINEL).status_code == 200, "a MESMA sessão, sem sair e entrar"
    assert "supfila" in ana.get("/api/auth/me").json()["telas"]


def test_TIRAR_tela_do_perfil_recusa_a_rota(casa):
    chefe, beto = _entrar("chefe@exemplo.test"), _entrar("beto@exemplo.test")
    assert beto.get(PAINEL).status_code == 200
    _ajustar(chefe, casa["ids"]["beto"], acessos=[{"chave": "supfila", "efeito": "tirar"}])
    r = beto.get(PAINEL)
    assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    assert "supfila" not in beto.get("/api/auth/me").json()["telas"]


def test_ADMIN_ignora_os_ajustes(casa):
    chefe = _entrar("chefe@exemplo.test")
    _ajustar(chefe, casa["ids"]["chefe"], acessos=[{"chave": "supfila", "efeito": "tirar"}])
    assert chefe.get(PAINEL).status_code == 200


# ───────────────────────────────────────────────────── aba bloqueável ──────

def test_aba_tirada_recusa_SO_a_rota_dela(casa, monkeypatch):
    monkeypatch.setattr(acessos, "ABAS", {"supfila.avisos": {
        "tela": "supfila", "rotulo": "Avisos", "abas": (("supfila", "avisos"),),
        "rotas": (AVISOS,)}})
    chefe, beto = _entrar("chefe@exemplo.test"), _entrar("beto@exemplo.test")
    _ajustar(chefe, casa["ids"]["beto"], acessos=[{"chave": "supfila.avisos", "efeito": "tirar"}])
    r = beto.get(AVISOS)
    assert r.status_code == 403 and "aba" in r.json()["mensagem"]
    assert beto.get(PAINEL).status_code == 200, "o resto da tela segue aberto"
    assert beto.get("/api/auth/me").json()["abas_ocultas"] == [["supfila", "avisos"]]
    assert chefe.get(AVISOS).status_code == 200, "admin não perde a aba"


# ───────────────────────────────────────────────────── página inicial ──────

def test_pagina_inicial_e_validada_contra_o_acesso(casa):
    chefe = _entrar("chefe@exemplo.test")
    r = chefe.post("/api/gestao/usuarios", json={
        "nome": "Duda", "email": "duda@exemplo.test", "senha_temporaria": "provisoria-123",
        "perfil_id": casa["perfil_comum"], "pagina_inicial": "supfila"})
    assert r.status_code == 422 and "página inicial" in r.json()["mensagem"]
    r = chefe.post("/api/gestao/usuarios", json={
        "nome": "Duda", "email": "duda@exemplo.test", "senha_temporaria": "provisoria-123",
        "perfil_id": casa["perfil_comum"], "pagina_inicial": "supfila",
        "acessos": [{"chave": "supfila", "efeito": "liberar"}]})
    assert r.status_code == 200, "liberada no MESMO cadastro, a página vale"


def test_pagina_inicial_chega_no_me_e_cai_no_padrao_sem_acesso(casa):
    chefe, beto = _entrar("chefe@exemplo.test"), _entrar("beto@exemplo.test")
    assert beto.get("/api/auth/me").json()["pagina_inicial"] is None
    _ajustar(chefe, casa["ids"]["beto"], pagina_inicial="supfila")
    assert beto.get("/api/auth/me").json()["pagina_inicial"] == "supfila"
    _ajustar(chefe, casa["ids"]["beto"], acessos=[{"chave": "supfila", "efeito": "tirar"}])
    assert beto.get("/api/auth/me").json()["pagina_inicial"] is None, "sem a tela, vale o radar"
    lista = chefe.get("/api/gestao/usuarios").json()["usuarios"]
    guardado = next(u for u in lista if u["id"] == casa["ids"]["beto"])
    assert guardado["pagina_inicial"] == "supfila", "a escolha fica; só não abre"
    assert guardado["acessos"] == [{"chave": "supfila", "efeito": "tirar"}]


def test_editar_outro_campo_nao_mexe_na_pagina_nem_nos_ajustes(casa):
    chefe = _entrar("chefe@exemplo.test")
    _ajustar(chefe, casa["ids"]["beto"], pagina_inicial="supfila",
             acessos=[{"chave": "cop", "efeito": "liberar"}])
    _ajustar(chefe, casa["ids"]["beto"], ramal="123")
    u = next(u for u in chefe.get("/api/gestao/usuarios").json()["usuarios"]
             if u["id"] == casa["ids"]["beto"])
    assert u["pagina_inicial"] == "supfila" and u["acessos"] == [{"chave": "cop", "efeito": "liberar"}]


def test_pagina_vazia_volta_ao_padrao(casa):
    chefe = _entrar("chefe@exemplo.test")
    _ajustar(chefe, casa["ids"]["beto"], pagina_inicial="supfila")
    _ajustar(chefe, casa["ids"]["beto"], pagina_inicial="")
    u = next(u for u in chefe.get("/api/gestao/usuarios").json()["usuarios"]
             if u["id"] == casa["ids"]["beto"])
    assert u["pagina_inicial"] is None


# ───────────────────────────────────────────── recusa, trilha e catálogo ───

def test_ajuste_invalido_e_4xx_com_motivo(casa):
    chefe = _entrar("chefe@exemplo.test")
    r = chefe.post(f"/api/gestao/usuarios/{casa['ids']['ana']}",
                   json={"acessos": [{"chave": "inventada", "efeito": "liberar"}]})
    assert r.status_code == 422 and "não é uma tela" in r.json()["mensagem"]


def test_a_trilha_diz_o_que_entrou_e_o_que_saiu(casa):
    chefe = _entrar("chefe@exemplo.test")
    _ajustar(chefe, casa["ids"]["ana"], pagina_inicial="radar",
             acessos=[{"chave": "supfila", "efeito": "liberar"}])
    _ajustar(chefe, casa["ids"]["ana"], acessos=[])
    with auth._conn() as c:
        linhas = [r["detalhe"] for r in c.execute(
            "SELECT detalhe FROM audit_log WHERE acao='usuario_editar' AND alvo=%s ORDER BY id",
            ("ana@exemplo.test",)).fetchall()]
    assert any("pagina_inicial=radar" in d and "+liberar supfila" in d for d in linhas), linhas
    assert any("-liberar supfila" in d for d in linhas), linhas


def test_catalogo_e_so_de_admin(casa):
    assert _entrar("beto@exemplo.test").get("/api/gestao/acessos/catalogo").status_code == 403
    d = _entrar("chefe@exemplo.test").get("/api/gestao/acessos/catalogo").json()
    assert set(d) == {"abas", "poderes", "paginas_de_todos", "paginas_de_admin",
                      "sem_menu"}
    assert "radar" in d["paginas_de_todos"]
    # OS PODERES entram aqui porque a ficha da pessoa é o único lugar onde eles
    # se dão — eles nascem desligados e não pertencem a perfil nenhum.
    assert any(x["chave"] == "poder.conferir_app" for x in d["poderes"])


def test_quem_nao_tem_ajuste_recebe_as_chaves_padrao(casa):
    me = _entrar("ana@exemplo.test").get("/api/auth/me").json()
    assert me["pagina_inicial"] is None and me["abas_ocultas"] == []


# ─────────────────────────────────── outros leitores do acesso efetivo ─────

def test_atendentes_do_suporte_seguem_o_acesso_efetivo(casa):
    from api.suporte import chamados
    ids = casa["ids"]
    nomes = {a["id"] for a in chamados.atendentes(casa["esquema"])}
    assert nomes == {ids["chefe"], ids["beto"]}
    chefe = _entrar("chefe@exemplo.test")
    _ajustar(chefe, ids["ana"], acessos=[{"chave": "supfila", "efeito": "liberar"}])
    _ajustar(chefe, ids["beto"], acessos=[{"chave": "supfila", "efeito": "tirar"}])
    nomes = {a["id"] for a in chamados.atendentes(casa["esquema"])}
    assert nomes == {ids["chefe"], ids["ana"]}, "chamado não vai para quem não o abre"


# ─────────────────────────── as travas de administrador (sem teste até aqui) ─

def test_admin_nao_rebaixa_o_ultimo_administrador(casa):
    r = _entrar("chefe@exemplo.test").post(
        f"/api/gestao/usuarios/{casa['ids']['chefe']}", json={"perfil_id": casa["perfil_comum"]})
    assert r.status_code == 422 and r.json()["erro"] == "ultimo_admin"


def test_admin_nao_desativa_a_si_mesmo(casa):
    r = _entrar("chefe@exemplo.test").post(
        f"/api/gestao/usuarios/{casa['ids']['chefe']}", json={"ativo": False})
    assert r.status_code == 422 and r.json()["erro"] == "auto_desativacao"


def test_admin_nao_exclui_a_si_mesmo(casa):
    r = _entrar("chefe@exemplo.test").post(
        f"/api/gestao/usuarios/{casa['ids']['chefe']}/excluir")
    assert r.status_code == 422 and r.json()["erro"] == "auto_exclusao"
