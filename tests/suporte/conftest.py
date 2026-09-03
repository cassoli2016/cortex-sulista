"""Fixtures do Suporte: schema descartável com dois usuários (um comum, um
administrador) e TODOS os stores do módulo redirecionados para ele."""
from __future__ import annotations

import pytest

from api import auth, notificacoes
from api.suporte import comum

SENHA = "senha-de-teste-123"


@pytest.fixture
def sup(esquema_pg, monkeypatch):
    monkeypatch.setattr(comum, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(notificacoes, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        adm = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES('Comum','sem telas',0,%s)", (auth._agora(),))
        comum_id = c.execute("SELECT id FROM perfis WHERE nome='Comum'").fetchone()["id"]
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em) VALUES('Suporte','atende',0,%s)", (auth._agora(),))
        sup_id = c.execute("SELECT id FROM perfis WHERE nome='Suporte'").fetchone()["id"]
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'supfila')", (sup_id,))
        for nome, email, perfil, tel in (("Ana Usuária", "ana@sulista.local", comum_id, "5547999990001"),
                                        ("Beto Suporte", "beto@sulista.local", sup_id, ""),
                                        ("Chefe Admin", "chefe@sulista.local", adm["id"], "")):
            c.execute("""INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo, deve_trocar_senha, criado_em, telefone)
                         VALUES(%s,%s,%s,%s,1,0,%s,%s)""",
                      (nome, email, auth._ph.hash(SENHA), perfil, auth._agora(), tel or None))
        ids = {r["email"]: r["id"] for r in c.execute("SELECT id, email FROM usuarios").fetchall()}
    return {
        "esquema": esquema_pg,
        "ana": {"id": ids["ana@sulista.local"], "nome": "Ana Usuária", "email": "ana@sulista.local", "telas": [], "admin": False},
        "beto": {"id": ids["beto@sulista.local"], "nome": "Beto Suporte", "email": "beto@sulista.local", "telas": ["supfila"], "admin": False},
        "chefe": {"id": ids["chefe@sulista.local"], "nome": "Chefe Admin", "email": "chefe@sulista.local", "telas": [], "admin": True},
    }


PAYLOAD = {"tipo": "bug", "gravidade": "alta", "titulo": "Saldo não bate",
           "descricao": "O saldo da tela de caixa não bate com o extrato.",
           "contexto": {"tela": "fluxo", "tela_nome": "Fluxo de Caixa", "filtros": "filial=1", "versao": "v0.212.0",
                        "navegador": "Chrome", "tela_px": "1920x1080", "erros": ["TypeError: x"]},
           "anexos": [{"nome": "print.png", "b64": "iVBORw0KGgo="}],
           "canais": {"email": True, "whatsapp": True}}
