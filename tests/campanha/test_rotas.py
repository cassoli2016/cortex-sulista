# -*- coding: utf-8 -*-
"""As rotas da campanha, com sessão de verdade.

O que só se prova aqui: o middleware é fail-closed para quem não tem a tela
`prem`, recusa legível é 409 (o Cloudflare troca o corpo dos 5xx pela página
dele), o sorteio deixa trilha ANTES de valer, e o CPF não trafega em lugar
nenhum — nem na entrada nem na saída.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import auth, campanha, pglocal
from api.campanha import armazenamento as arm, base, servico

SENHA = "senha-de-teste-123"


@pytest.fixture
def cli(esquema_pg, monkeypatch):
    for mod in (campanha, arm, servico):
        monkeypatch.setattr(mod, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(auth, "ESQUEMA", esquema_pg)
    auth.init_db()
    with auth._conn() as c:
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em)"
                  " VALUES('Comum','sem telas',0,%s)", (auth._agora(),))
        comum = c.execute("SELECT id FROM perfis WHERE nome='Comum'").fetchone()["id"]
        c.execute("INSERT INTO perfis(nome, descricao, admin, criado_em)"
                  " VALUES('Campanha','premiacao',0,%s)", (auth._agora(),))
        gest = c.execute("SELECT id FROM perfis WHERE nome='Campanha'").fetchone()["id"]
        c.execute("INSERT INTO perfil_telas(perfil_id, tela) VALUES(%s,'prem')",
                  (gest,))
        for nome, email, perfil in (("Ana", "ana@sulista.local", comum),
                                    ("Beto", "beto@sulista.local", gest)):
            c.execute(
                "INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo,"
                " deve_trocar_senha, criado_em) VALUES(%s,%s,%s,%s,1,0,%s)",
                (nome, email, auth._ph.hash(SENHA), perfil, auth._agora()))

    from api.main import app

    def entrar(email):
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "senha": SENHA})
        assert r.status_code == 200, r.text
        return c
    return {"ana": entrar("ana@sulista.local"),
            "beto": entrar("beto@sulista.local"), "esquema": esquema_pg}


CAMP = {"nome": "3º trimestre", "de_ciclo": "2026-10", "ate_ciclo": "2026-12",
        "premio": "Moto elétrica", "onde": "Matriz"}


def test_sem_sessao_e_401_e_sem_a_tela_e_403(cli):
    from api.main import app
    assert TestClient(app).get("/api/campanha").status_code == 401
    assert cli["ana"].get("/api/campanha").status_code == 403
    assert cli["beto"].get("/api/campanha").status_code == 200


def test_criar_e_listar(cli):
    r = cli["beto"].post("/api/campanha", json=CAMP)
    assert r.status_code == 200, r.text
    assert r.json()["peso_gobrax"] == 50
    d = cli["beto"].get("/api/campanha").json()
    assert d["vigente"]["nome"] == "3º trimestre"
    assert d["padrao"]["cat_elite"] == 90


def test_regua_invalida_e_RECUSA_legivel(cli):
    r = cli["beto"].post("/api/campanha", json={**CAMP, "peso_gr": 30})
    assert r.status_code == 409 and "somam" in r.json()["mensagem"]


def test_sortear_sem_foto_e_recusado_com_o_caminho_na_mensagem(cli):
    c = cli["beto"].post("/api/campanha", json=CAMP).json()
    r = cli["beto"].post(f"/api/campanha/{c['id']}/sortear",
                         json={"grupo": "FROTA"})
    assert r.status_code == 409
    assert "Feche o mês antes de sortear" in r.json()["mensagem"]


def test_o_sorteio_deixa_TRILHA_e_devolve_a_ata(cli):
    c = cli["beto"].post("/api/campanha", json=CAMP).json()
    arm.gravar_foto(c["id"], "2026-12", {"FROTA": {"linhas": [
        {"chave": "k1", "nome": "UM", "gobrax": 90.0, "conduta": 100.0,
         "gr": 90.0, "nota": 95.0, "categoria": "ELITE", "elegivel": True,
         "motivo": ""}]}}, esquema=cli["esquema"])
    r = cli["beto"].post(f"/api/campanha/{c['id']}/sortear",
                         json={"grupo": "FROTA", "semente": "s",
                               "ata": "evento na matriz"})
    assert r.status_code == 200, r.text
    assert r.json()["ganhador"] == "UM" and r.json()["elegiveis"] == 1
    acoes = [x["acao"] for x in pglocal.query(
        "SELECT acao FROM audit_log ORDER BY id", esquema=cli["esquema"])]
    assert "campanha_sortear" in acoes


def test_o_CPF_nao_trafega_nem_na_entrada_nem_na_saida(cli):
    """A chave do participante é opaca — o código do motorista agregado no ERP
    é o CPF, e quem faz a ponte é o servidor."""
    c = cli["beto"].post("/api/campanha", json=CAMP).json()
    cpf = "11122233344"
    arm.gravar_foto(c["id"], "2026-12", {"AGREGADO": {"linhas": [
        {"chave": base.chave(c["id"], cpf), "nome": "FULANO", "gobrax": 90.0,
         "conduta": 100.0, "gr": 90.0, "nota": 95.0, "categoria": "ELITE",
         "elegivel": True, "motivo": ""}]}}, esquema=cli["esquema"])
    r = cli["beto"].post(f"/api/campanha/{c['id']}/sortear",
                         json={"grupo": "AGREGADO", "semente": "s"})
    assert r.status_code == 200 and cpf not in r.text


def test_ciclo_invalido_e_campanha_inexistente_sao_RECUSA(cli):
    c = cli["beto"].post("/api/campanha", json=CAMP).json()
    r = cli["beto"].get(f"/api/campanha/{c['id']}/ciclo?ciclo=outubro")
    assert r.status_code == 409 and "Ciclo inválido" in r.json()["mensagem"]
    r = cli["beto"].get("/api/campanha/9999/ciclo")
    assert r.status_code == 409 and "não existe" in r.json()["mensagem"]
