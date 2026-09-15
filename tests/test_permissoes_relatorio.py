"""Relatório de permissões da Gestão (pedido de quem opera, 15/09/2026).

O que ele não pode fazer é DISCORDAR do sistema. Relatório de acesso que diz
"fulano não abre a DRE" enquanto o servidor deixa fulano abrir a DRE é pior
que relatório nenhum — é nele que a revisão de acessos confia. Por isso:

1. o acesso sai de `acessos.detalhar()`, que é o `efetivas()` da sessão com a
   origem anotada — e o teste de propriedade abaixo cobra que as duas contas
   dão SEMPRE o mesmo conjunto;
2. com sessão de verdade, o relatório de uma pessoa é o `/api/auth/me` dela;
3. só administrador lê (é o mapa de quem abre o quê na casa inteira).
"""
from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from api import acessos, auth

SENHA = "senha-de-teste-123"
TODAS = ["fluxo", "dre", "cop", "supfila", "folha"]


# ─────────────────────────────────────────────── a regra, sem banco ────────

def test_cada_tela_diz_de_onde_veio():
    d = acessos.detalhar(["fluxo", "dre"],
                         [("cop", "liberar"), ("dre", "tirar"), ("folha", "tirar")],
                         False, TODAS)
    assert d["telas"] == [{"chave": "fluxo", "origem": "perfil"},
                          {"chave": "cop", "origem": "liberada"}]
    assert d["tiradas"] == ["dre"], (
        "tirar o que a pessoa nem teria (folha) é inerte e não aparece como tirada")
    assert d["ajustes_ignorados"] == 0


def test_liberar_o_que_o_perfil_ja_da_continua_sendo_perfil():
    """Senão a revisão acharia uma "exceção" que não muda acesso nenhum."""
    d = acessos.detalhar(["fluxo"], [("fluxo", "liberar")], False, TODAS)
    assert d["telas"] == [{"chave": "fluxo", "origem": "perfil"}]


def test_administrador_ignora_os_ajustes_e_diz_quantos_estao_guardados():
    d = acessos.detalhar(TODAS, [("dre", "tirar"), ("cop", "liberar")], True, TODAS)
    assert [t["chave"] for t in d["telas"]] == TODAS
    assert {t["origem"] for t in d["telas"]} == {"administrador"}
    assert d["tiradas"] == [] and d["abas_tiradas"] == []
    assert d["ajustes_ignorados"] == 2


def test_aba_tirada_so_aparece_se_a_pessoa_ve_a_tela():
    aba = next(k for k, u in acessos.ABAS.items() if u["tela"] == "dre")
    com = acessos.detalhar(["dre"], [(aba, "tirar")], False, ["dre", "fluxo"])
    sem = acessos.detalhar(["fluxo"], [(aba, "tirar")], False, ["dre", "fluxo"])
    assert com["abas_tiradas"] == [aba]
    assert sem["abas_tiradas"] == []


def _combinacoes():
    """Todo perfil possível sobre 4 telas × todo conjunto de até 3 ajustes."""
    telas = TODAS[:4]
    ajustes = [(t, e) for t in telas + ["folha", "aposentada"] for e in ("liberar", "tirar")]
    for n in range(len(telas) + 1):
        for perfil in itertools.combinations(telas, n):
            for k in range(4):
                for aj in itertools.combinations(ajustes, k):
                    for admin in (False, True):
                        yield list(perfil), list(aj), admin


def test_o_relatorio_nunca_discorda_do_acesso_da_sessao():
    """Propriedade, sobre TODAS as combinações pequenas: o conjunto de telas e
    de abas que o relatório mostra é exatamente o que `efetivas()` — a conta
    da sessão — concede. Inclui ajuste de tela aposentada (inerte) e ajustes
    contraditórios (liberar e tirar a mesma tela: "tirar" vence)."""
    n = 0
    for perfil, aj, admin in _combinacoes():
        telas, abas = acessos.efetivas(perfil if not admin else TODAS, aj, admin, TODAS)
        d = acessos.detalhar(perfil if not admin else TODAS, aj, admin, TODAS)
        assert [t["chave"] for t in d["telas"]] == telas, (perfil, aj, admin)
        assert d["abas_tiradas"] == abas
        assert not set(d["tiradas"]) & set(telas), "tela tirada não pode estar entre as que abre"
        n += 1
    assert n > 1000, f"só {n} combinações — a varredura encolheu"


# ─────────────────────────────────────── com sessão de verdade ────────────

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
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES('Atende','',0,%s)",
                  (auth._agora(),))
        atende = c.execute("SELECT id FROM perfis WHERE nome='Atende'").fetchone()["id"]
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'supfila')", (atende,))
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'fluxo')", (atende,))
        for nome, email, perfil, ativo in (("Chefe", "chefe@exemplo.test", adm, 1),
                                           ("Beto", "beto@exemplo.test", atende, 1),
                                           ("Caio", "caio@exemplo.test", atende, 0)):
            c.execute("""INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                              deve_trocar_senha, criado_em)
                         VALUES(%s,%s,%s,%s,%s,0,%s)""",
                      (nome, email, auth._ph.hash(SENHA), perfil, ativo, auth._agora()))
        ids = {r["email"].split("@")[0]: r["id"]
               for r in c.execute("SELECT id, email FROM usuarios").fetchall()}
    return {"ids": ids}


def _entrar(email: str) -> TestClient:
    from api.main import app
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def test_o_relatorio_de_uma_pessoa_e_o_acesso_que_ela_tem(casa):
    chefe = _entrar("chefe@exemplo.test")
    r = chefe.post(f"/api/gestao/usuarios/{casa['ids']['beto']}", json={"acessos": [
        {"chave": "cop", "efeito": "liberar"}, {"chave": "supfila", "efeito": "tirar"}]})
    assert r.status_code == 200, r.text

    rel = chefe.get("/api/gestao/permissoes")
    assert rel.status_code == 200, rel.text
    rel = rel.json()
    beto = next(u for u in rel["usuarios"] if u["email"] == "beto@exemplo.test")
    assert {t["chave"]: t["origem"] for t in beto["telas"]} == {
        "fluxo": "perfil", "cop": "liberada",
        "apps": "todo_logado", "radar": "todo_logado", "sup": "todo_logado"}
    assert beto["tiradas"] == ["supfila"]

    me = _entrar("beto@exemplo.test").get("/api/auth/me").json()
    assert set(me["telas"]) == {t["chave"] for t in beto["telas"]
                                if t["origem"] != "todo_logado"}, (
        "o relatório diz uma coisa e a sessão libera outra")

    chefe_u = next(u for u in rel["usuarios"] if u["email"] == "chefe@exemplo.test")
    assert chefe_u["admin"] and {"gestao", "srv"} <= {t["chave"] for t in chefe_u["telas"]}
    caio = next(u for u in rel["usuarios"] if u["email"] == "caio@exemplo.test")
    assert caio["ativo"] is False, "inativo também sai: a tela é que escolhe mostrar"
    # o registro nomeia as telas que não estão em TELAS, senão a tela mostraria a chave crua
    assert {"sup", "apps", "radar", "gestao", "srv"} <= {t["chave"] for t in rel["telas"]}
    assert "jornf" not in {t["chave"] for t in rel["telas"]}


def test_so_administrador_le_o_relatorio(casa):
    assert _entrar("beto@exemplo.test").get("/api/gestao/permissoes").status_code == 403
