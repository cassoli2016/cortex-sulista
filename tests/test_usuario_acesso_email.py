"""O e-mail de acesso pela ROTA — no cadastro e no reenvio (14/09/2026).

De 29/08 (v0.144.0) a 14/09 (v1.78.0) o servidor sabia mandar o boas-vindas e
a TELA nunca pediu: o formulário de usuário não tinha a caixa, o payload não
levava `enviar_boas_vindas`, e `gesBvAviso()` procurava um elemento que não
existia. Três pessoas cadastradas em 14/09 esperaram um e-mail que nunca
saiu — e em toda a trilha não havia UM `usuario_boas_vindas`. Os testes do
módulo (`tests/test_boas_vindas.py`) provavam o e-mail; nenhum provava o
caminho até ele.

Aqui se prova a rota, com o envio trocado por uma caixa que guarda o que
sairia; `tests/frontend/test_usuario_acesso_email_e2e.py` prova que a tela
faz o pedido.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.correio import boas_vindas as bv

SENHA = "senha-de-teste-123"
URL = "https://cortex.exemplo.test"


@pytest.fixture
def cliente(esquema_pg, monkeypatch):
    """API de pé com um administrador logado, sobre um schema descartável."""
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute(
            """INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,
                                    deve_trocar_senha, criado_em)
               VALUES('Chefe','chefe@sulista.com.br',%s,%s,1,0,%s)""",
            (auth._ph.hash(SENHA), perfil["id"], auth._agora()))
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": "chefe@sulista.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


@pytest.fixture
def correio(monkeypatch):
    """O envio de verdade trocado por uma caixa que guarda o que sairia."""
    caixa = {"enviados": [], "falhar": ""}

    def _enviar(dests, assunto, corpo, **kw):
        if caixa["falhar"]:
            return {"ok": False, "erro": caixa["falhar"]}
        caixa["enviados"].append({"dests": list(dests), "corpo": corpo, **kw})
        return {"ok": True, "erro": "", "destinatarios": list(dests)}

    monkeypatch.setattr(bv.cfg, "configurado", lambda: True)
    monkeypatch.setattr(bv.envio, "enviar", _enviar)
    monkeypatch.setattr(auth, "_url_painel", lambda: URL)
    return caixa


def _perfil() -> int:
    with auth._conn() as c:
        return c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()["id"]


def _usuario(email: str) -> dict:
    with auth._conn() as c:
        return dict(c.execute("SELECT * FROM usuarios WHERE email=%s", (email,)).fetchone())


def _trilha(email: str) -> list[str]:
    with auth._conn() as c:
        return [r["detalhe"] for r in c.execute(
            "SELECT detalhe FROM audit_log WHERE acao='usuario_boas_vindas' AND alvo=%s "
            "ORDER BY id", (email,)).fetchall()]


def _senha_no(corpo: str) -> str:
    m = re.search(r"Senha provisória: (\S+)", corpo)
    assert m, "o e-mail não traz a senha provisória"
    return m.group(1)


def _entra(u: dict, senha: str) -> bool:
    try:
        return auth._ph.verify(u["senha_hash"], senha)
    except Exception:  # noqa: BLE001 — argon2 levanta no descasamento
        return False


def _criar(cli: TestClient, email: str = "evelyn@sulista.com.br", **campos):
    corpo = {"nome": "Evelyn Teste", "email": email, "perfil_id": _perfil(),
             "senha_temporaria": ""}
    corpo.update(campos)
    return cli.post("/api/gestao/usuarios", json=corpo)


# ──────────────────────────────────────────────────────────── cadastro ──────

def test_cadastro_com_o_pedido_manda_uma_senha_que_ENTRA(cliente, correio):
    r = _criar(cliente, enviar_boas_vindas=True)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["email"] == {"ok": True, "erro": ""}
    assert "senha_temporaria" not in corpo, "saiu por e-mail: não volta para a tela"

    assert [e["dests"] for e in correio["enviados"]] == [["evelyn@sulista.com.br"]]
    enviado = correio["enviados"][0]["corpo"]
    assert URL in enviado
    u = _usuario("evelyn@sulista.com.br")
    assert _entra(u, _senha_no(enviado)), "a senha do e-mail não é a gravada"
    assert u["deve_trocar_senha"] == 1
    assert _trilha("evelyn@sulista.com.br") == ["enviado"]


def test_cadastro_sem_o_pedido_nao_manda_nada(cliente, correio):
    r = _criar(cliente, senha_temporaria="temporaria-123")
    assert r.status_code == 200, r.text
    assert "email" not in r.json()
    assert correio["enviados"] == [] and _trilha("evelyn@sulista.com.br") == []


def test_envio_que_falha_devolve_a_senha_e_o_cadastro_FICA(cliente, correio):
    correio["falhar"] = "SMTP recusou"
    r = _criar(cliente, enviar_boas_vindas=True)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["email"]["ok"] is False and "SMTP recusou" in corpo["email"]["erro"]
    assert _entra(_usuario("evelyn@sulista.com.br"), corpo["senha_temporaria"])
    assert _trilha("evelyn@sulista.com.br") == ["falhou: SMTP recusou"]


# ───────────────────────────────────────────────────── reenvio (edição) ─────

def test_editar_com_o_pedido_TROCA_a_senha_e_manda_o_acesso(cliente, correio):
    """O caso dos três de 14/09: cadastrados sem e-mail. A senha antiga está
    em hash e não se recupera — o reenvio é sempre de uma senha NOVA, e a
    antiga para de valer."""
    _criar(cliente, senha_temporaria="temporaria-123")
    antes = _usuario("evelyn@sulista.com.br")
    r = cliente.post(f"/api/gestao/usuarios/{antes['id']}", json={"enviar_boas_vindas": True})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == {"ok": True, "erro": ""}
    assert "senha_temporaria" not in r.json()

    assert [e["dests"] for e in correio["enviados"]] == [["evelyn@sulista.com.br"]]
    depois = _usuario("evelyn@sulista.com.br")
    assert _entra(depois, _senha_no(correio["enviados"][0]["corpo"]))
    assert not _entra(depois, "temporaria-123"), "a senha antiga continuou valendo"
    assert depois["deve_trocar_senha"] == 1
    assert depois["token_ver"] == antes["token_ver"] + 1, "sessão aberta com a senha velha segue viva"
    assert _trilha("evelyn@sulista.com.br") == ["enviado"]


def test_editar_com_senha_digitada_manda_a_DIGITADA(cliente, correio):
    _criar(cliente, senha_temporaria="temporaria-123")
    uid = _usuario("evelyn@sulista.com.br")["id"]
    cliente.post(f"/api/gestao/usuarios/{uid}",
                 json={"enviar_boas_vindas": True, "resetar_senha": "digitada-pelo-admin-9"})
    assert _senha_no(correio["enviados"][0]["corpo"]) == "digitada-pelo-admin-9"


def test_o_email_vai_para_o_endereco_NOVO_quando_ele_muda_junto(cliente, correio):
    _criar(cliente, senha_temporaria="temporaria-123")
    uid = _usuario("evelyn@sulista.com.br")["id"]
    cliente.post(f"/api/gestao/usuarios/{uid}",
                 json={"email": "evelyn.nova@sulista.com.br", "enviar_boas_vindas": True})
    assert [e["dests"] for e in correio["enviados"]] == [["evelyn.nova@sulista.com.br"]]


def test_usuario_inativo_nao_recebe_acesso_e_nada_muda(cliente, correio):
    _criar(cliente, senha_temporaria="temporaria-123")
    uid = _usuario("evelyn@sulista.com.br")["id"]
    cliente.post(f"/api/gestao/usuarios/{uid}", json={"ativo": False})
    r = cliente.post(f"/api/gestao/usuarios/{uid}", json={"enviar_boas_vindas": True})
    assert r.status_code == 422 and "inativo" in r.json()["mensagem"]
    assert correio["enviados"] == []
    assert _entra(_usuario("evelyn@sulista.com.br"), "temporaria-123"), "a recusa trocou a senha"


def test_editar_sem_o_pedido_nao_manda_nada(cliente, correio):
    _criar(cliente, senha_temporaria="temporaria-123")
    uid = _usuario("evelyn@sulista.com.br")["id"]
    assert cliente.post(f"/api/gestao/usuarios/{uid}", json={"ramal": "115"}).status_code == 200
    assert correio["enviados"] == []
