"""O Copiloto com sessão de verdade: o que chega AO MODELO é o recorte da pessoa.

A regra (tests/copiloto/test_acesso.py) só vale se as rotas passarem a sessão
adiante. Aqui o motor de IA é trocado por um dublê que GUARDA as mensagens que
receberia — e é o prompt de sistema delas que se confere, porque é ele que
sai da casa quando o chat cai no modelo externo.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import auth, copiloto

SENHA = "senha-de-teste-123"
PERGUNTA = {"mensagens": [{"role": "user", "content": "como está o caixa?"}]}


@pytest.fixture
def casa(esquema_pg, monkeypatch):
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        adm = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()["id"]
        for nome, telas in (("CaixaCop", ("cop", "fluxo")), ("DreCop", ("cop", "dre"))):
            c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES(%s,'',0,%s)",
                      (nome, auth._agora()))
            pid = c.execute("SELECT id FROM perfis WHERE nome=%s", (nome,)).fetchone()["id"]
            for t in telas:
                c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,%s)", (pid, t))
        pids = {r["nome"]: r["id"] for r in c.execute("SELECT id, nome FROM perfis").fetchall()}
        for nome, email, perfil in (("Chefe", "chefe@exemplo.test", adm),
                                    ("Ana", "ana@exemplo.test", pids["CaixaCop"]),
                                    ("Beto", "beto@exemplo.test", pids["DreCop"])):
            c.execute("""INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                              deve_trocar_senha, criado_em)
                         VALUES(%s,%s,%s,%s,1,0,%s)""",
                      (nome, email, auth._ph.hash(SENHA), perfil, auth._agora()))
        ids = {r["email"].split("@")[0]: r["id"]
               for r in c.execute("SELECT id, email FROM usuarios").fetchall()}

    # o retrato: uma fonte de mentira por fonte de verdade, e o motor trocado
    falsas = {f: (lambda f=f: {"valor_de": f}) for f in copiloto._FONTES_ROTULO}
    monkeypatch.setattr(copiloto, "_fontes_do_snapshot", lambda: falsas)
    monkeypatch.setattr(copiloto, "_SNAP", {"ts": 0.0, "texto": "", "falhas": [], "dados": {}})
    monkeypatch.setattr(copiloto, "ollama_status",
                        lambda *a, **k: {"ok": True, "modelo": "duble", "ts": 0.0})
    enviados: list[list[dict]] = []

    def chat_falso(msgs):
        enviados.append(msgs)
        return {"resposta": "ok", "modelo": "duble (local)", "tokens": None}

    def stream_falso(msgs):
        enviados.append(msgs)
        yield {"tipo": "delta", "texto": "ok"}
        yield {"tipo": "fim", "tokens": None}

    monkeypatch.setattr(copiloto, "_chat_ollama", chat_falso)
    monkeypatch.setattr(copiloto, "_stream_ollama", stream_falso)
    return {"ids": ids, "enviados": enviados}


def _entrar(email: str) -> TestClient:
    from api.main import app
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def _sistema(casa) -> str:
    return casa["enviados"][-1][0]["content"]


def test_o_chat_manda_ao_modelo_SO_o_recorte_da_pessoa(casa):
    ana = _entrar("ana@exemplo.test")
    assert ana.post("/api/copiloto/chat", json=PERGUNTA).status_code == 200
    s = _sistema(casa)
    assert '"valor_de": "financeiro_caixa"' in s
    assert '"valor_de": "onde_atacar"' not in s and "DRE Gerencial" not in s


def test_o_admin_manda_o_retrato_inteiro(casa):
    chefe = _entrar("chefe@exemplo.test")
    assert chefe.post("/api/copiloto/chat", json=PERGUNTA).status_code == 200
    assert '"valor_de": "onde_atacar"' in _sistema(casa)


def test_o_stream_tambem_corta(casa):
    ana = _entrar("ana@exemplo.test")
    r = ana.post("/api/copiloto/chat-stream", json=PERGUNTA)
    assert r.status_code == 200 and '"delta"' in r.text
    s = _sistema(casa)
    assert '"valor_de": "financeiro_caixa"' in s and '"valor_de": "onde_atacar"' not in s


def test_aba_tirada_sai_do_chat_no_clique_seguinte(casa):
    chefe, beto = _entrar("chefe@exemplo.test"), _entrar("beto@exemplo.test")
    beto.post("/api/copiloto/chat", json=PERGUNTA)
    assert '"valor_de": "onde_atacar"' in _sistema(casa)
    r = chefe.post(f"/api/gestao/usuarios/{casa['ids']['beto']}",
                   json={"acessos": [{"chave": "dre.atk", "efeito": "tirar"}]})
    assert r.status_code == 200, r.text
    beto.post("/api/copiloto/chat", json=PERGUNTA)
    s = _sistema(casa)
    assert '"valor_de": "onde_atacar"' not in s and '"valor_de": "dre_excluidos"' in s


def test_a_procedencia_do_status_e_a_da_pessoa(casa):
    ana = _entrar("ana@exemplo.test")
    ana.post("/api/copiloto/chat", json=PERGUNTA)
    ctx = ana.get("/api/copiloto/status").json()["contexto"]
    assert copiloto._FONTES_ROTULO["financeiro_caixa"] in ctx["fontes"]
    assert copiloto._FONTES_ROTULO["onde_atacar"] not in ctx["fontes"]
