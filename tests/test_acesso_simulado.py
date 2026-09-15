"""Acesso simulado: o administrador vê o sistema como outra pessoa vê.

Pedido de quem opera (15/09/2026): "validar quais telas estão liberadas e os
acessos que o usuário possui". O que esta suíte segura, com sessão de verdade:

1. **É o acesso DA PESSOA**, tirado da mesma conta da sessão dela: o
   /api/auth/me simulado é o /api/auth/me dela, e o SERVIDOR recusa o que ela
   não abre (esconder o menu seria só metade).
2. **Só leitura**: toda gravação é recusada enquanto dura.
3. **Sair do sistema durante a simulação derruba o ADMINISTRADOR**, nunca a
   pessoa simulada — que nem sabe que foi simulada.
4. **O token não se transfere**: preso ao administrador que o pediu, vencido
   não vale, e nas mãos de quem não é administrador não faz nada.
5. **Fica na trilha**: início e fim no audit_log.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from api import auth

SENHA = "senha-de-teste-123"
PAINEL = "/api/suporte/atendimento/painel"


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
        for nome, email, perfil, ativo in (("Chefe", "chefe@exemplo.test", adm, 1),
                                           ("Dani", "dani@exemplo.test", adm, 1),
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


def _simular(cli: TestClient, uid: int):
    r = cli.post(f"/api/gestao/simular/{uid}")
    assert r.status_code == 200, r.text
    assert cli.cookies.get(auth.COOKIE_SIMULA), "o cookie da simulação não foi gravado"
    return r


def test_simulado_ve_exatamente_o_que_a_pessoa_ve(casa):
    chefe, beto = _entrar("chefe@exemplo.test"), _entrar("beto@exemplo.test")
    proprio = beto.get("/api/auth/me").json()
    _simular(chefe, casa["ids"]["beto"])
    me = chefe.get("/api/auth/me").json()
    assert me["email"] == "beto@exemplo.test" and me["admin"] is False
    assert me["telas"] == proprio["telas"], "a simulação mostra um acesso que a pessoa não tem"
    assert me["simulacao"]["por_email"] == "chefe@exemplo.test"
    assert proprio["simulacao"] is None


def test_o_servidor_recusa_na_simulacao_o_que_a_pessoa_nao_abre(casa):
    chefe = _entrar("chefe@exemplo.test")
    assert chefe.get("/api/gestao/usuarios").status_code == 200
    _simular(chefe, casa["ids"]["beto"])
    assert chefe.get("/api/gestao/usuarios").status_code == 403, "Beto não é administrador"
    assert chefe.get("/api/rh/people").status_code == 403, "Beto não tem o People Analytics"
    assert chefe.get(PAINEL).status_code == 200, "Beto tem a fila do Suporte"


def test_simulacao_e_so_leitura(casa):
    chefe = _entrar("chefe@exemplo.test")
    _simular(chefe, casa["ids"]["beto"])
    r = chefe.post("/api/auth/perfil", json={"ramal": "123"})
    assert r.status_code == 409 and r.json()["erro"] == "simulacao_so_leitura", r.text
    assert "Beto" in r.json()["mensagem"]
    r = chefe.post("/api/auth/trocar-senha", json={"senha_atual": SENHA, "senha_nova": "x" * 20})
    assert r.status_code == 409, "trocar a senha de quem está sendo simulado"


def test_sair_da_simulacao_volta_a_ser_voce_e_fica_na_trilha(casa):
    chefe = _entrar("chefe@exemplo.test")
    _simular(chefe, casa["ids"]["beto"])
    assert chefe.post("/api/auth/simulacao/sair").status_code == 200
    me = chefe.get("/api/auth/me").json()
    assert me["email"] == "chefe@exemplo.test" and me["simulacao"] is None
    with auth._conn() as c:
        acoes = [(r["usuario"], r["acao"], r["alvo"]) for r in c.execute(
            "SELECT usuario, acao, alvo FROM audit_log WHERE acao LIKE 'simulacao_%' ORDER BY id")]
    assert acoes == [("chefe@exemplo.test", "simulacao_inicio", "beto@exemplo.test"),
                     ("chefe@exemplo.test", "simulacao_fim", "beto@exemplo.test")]


def test_sair_do_sistema_na_simulacao_derruba_o_administrador_e_nao_a_pessoa(casa):
    chefe, beto = _entrar("chefe@exemplo.test"), _entrar("beto@exemplo.test")
    sessao_chefe = chefe.cookies.get(auth.COOKIE)
    _simular(chefe, casa["ids"]["beto"])
    assert chefe.post("/api/auth/logout").status_code == 200
    assert beto.get("/api/auth/me").status_code == 200, (
        "o logout na simulação invalidou o login de quem foi simulado")
    from api.main import app
    velho = TestClient(app)
    velho.cookies.set(auth.COOKIE, sessao_chefe)
    assert velho.get("/api/auth/me").status_code == 401, "a sessão do administrador seguiu valendo"


def test_o_token_esta_preso_ao_administrador_que_o_pediu(casa):
    chefe, dani, beto = (_entrar("chefe@exemplo.test"), _entrar("dani@exemplo.test"),
                         _entrar("beto@exemplo.test"))
    _simular(chefe, casa["ids"]["beto"])
    tok = chefe.cookies.get(auth.COOKIE_SIMULA)
    dani.cookies.set(auth.COOKIE_SIMULA, tok)
    assert dani.get("/api/auth/me").json()["email"] == "dani@exemplo.test", (
        "outro administrador herdou a simulação do primeiro")
    beto.cookies.set(auth.COOKIE_SIMULA, tok)
    me = beto.get("/api/auth/me").json()
    assert me["email"] == "beto@exemplo.test" and me["simulacao"] is None


def _forjar(sub, alvo, *, tipo="simulacao", horas=1):
    agora = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(sub), "alvo": str(alvo), "tipo": tipo,
                       "iat": agora - timedelta(hours=2), "exp": agora + timedelta(hours=horas)},
                      auth.SECRET, algorithm="HS256")


def test_token_vencido_ou_de_outro_tipo_nao_vale(casa):
    chefe = _entrar("chefe@exemplo.test")
    ids = casa["ids"]
    for tok in (_forjar(ids["chefe"], ids["beto"], horas=-1),
                _forjar(ids["chefe"], ids["beto"], tipo="sessao"),
                _forjar(ids["chefe"], ids["caio"]),          # inativo
                "lixo.que.nao.e.jwt"):
        chefe.cookies.set(auth.COOKIE_SIMULA, tok)
        assert chefe.get("/api/auth/me").json()["email"] == "chefe@exemplo.test", tok


def test_quem_nao_e_administrador_nao_simula(casa):
    beto = _entrar("beto@exemplo.test")
    assert beto.post(f"/api/gestao/simular/{casa['ids']['caio']}").status_code == 403


@pytest.mark.parametrize("quem,codigo", [("chefe", 409), ("caio", 409), (None, 404)])
def test_nao_se_simula_a_si_mesmo_nem_inativo(casa, quem, codigo):
    chefe = _entrar("chefe@exemplo.test")
    uid = casa["ids"][quem] if quem else 999999
    assert chefe.post(f"/api/gestao/simular/{uid}").status_code == codigo
    assert not chefe.cookies.get(auth.COOKIE_SIMULA)


def test_perder_o_perfil_de_administrador_encerra_a_simulacao(casa):
    """A trava é "administrador AGORA", relida a cada clique."""
    chefe = _entrar("chefe@exemplo.test")
    _simular(chefe, casa["ids"]["beto"])
    with auth._conn() as c:
        atende = c.execute("SELECT id FROM perfis WHERE nome='Atende'").fetchone()["id"]
        c.execute("UPDATE usuarios SET perfil_id=%s WHERE email='chefe@exemplo.test'", (atende,))
    me = chefe.get("/api/auth/me").json()
    assert me["email"] == "chefe@exemplo.test" and me["simulacao"] is None
