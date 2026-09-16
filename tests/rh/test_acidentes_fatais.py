# -*- coding: utf-8 -*-
"""O registro de acidente com vítima fatal (`api/rh/acidentes_fatais.py`,
migration 0099), num schema descartável.

A regra que não pode falhar mora no BANCO: registro não se apaga nem se edita,
e a retirada acontece uma vez. Os testes batem direto na tabela para provar
que é o banco — e não a rota — quem recusa.
"""
from __future__ import annotations

from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from api import auth, pglocal
from api.rh import acidentes_fatais as af

HOJE = date(2026, 9, 16)
BASE = {"data": "2026-09-10", "filial": "Matriz", "descricao": "Descrição do ocorrido."}


@pytest.fixture
def esq(esquema_pg, monkeypatch):
    monkeypatch.setattr(af, "ESQUEMA", esquema_pg)
    return esquema_pg


def _reg(**mudar):
    return af.registrar({**BASE, **mudar}, autor="ana@sulista.com.br", hoje=HOJE)


def test_registra_e_lista(esq):
    r = _reg()
    assert (r["data"], r["filial"], r["autor"], r["retirado_em"]) == ("2026-09-10", "Matriz", "ana@sulista.com.br", None)
    assert [x["id"] for x in af.listar()] == [r["id"]]


@pytest.mark.parametrize("mudar,trecho", [
    ({"data": "2026-09-17"}, "futura"), ({"data": "10/09/2026"}, "Data inválida"),
    ({"filial": "Curitiba"}, "fora da lista"), ({"descricao": "   "}, "descrição"),
    ({"descricao": "x" * 1001}, "passa de"),
])
def test_recusa_entrada_invalida(esq, mudar, trecho):
    with pytest.raises(af.Recusa, match=trecho):
        _reg(**mudar)
    assert af.listar() == []


def test_o_banco_nao_deixa_apagar_nem_editar(esq):
    r = _reg()
    with pytest.raises(psycopg.errors.RaiseException, match="não se apaga"):
        pglocal.executar("DELETE FROM sst_acidente_fatal WHERE id = %s", (r["id"],), esq)
    with pytest.raises(psycopg.errors.RaiseException, match="não se edita"):
        pglocal.executar("UPDATE sst_acidente_fatal SET filial = 'SBC' WHERE id = %s", (r["id"],), esq)
    assert af.listar()[0]["filial"] == "Matriz"


def test_retira_uma_vez_com_motivo_e_a_linha_fica(esq):
    r = _reg()
    with pytest.raises(af.Recusa, match="motivo"):
        af.retirar(r["id"], "  ", autor="ana@sulista.com.br")
    x = af.retirar(r["id"], "Registrado na filial errada.", autor="bia@sulista.com.br")
    assert x["retirado_por"] == "bia@sulista.com.br" and x["retirado_motivo"]
    with pytest.raises(af.Recusa, match="já retirado"):
        af.retirar(r["id"], "de novo", autor="ana@sulista.com.br")
    # e nem pelo banco a retirada se reescreve
    with pytest.raises(psycopg.errors.RaiseException, match="já retirado"):
        pglocal.executar("UPDATE sst_acidente_fatal SET retirado_motivo = 'outro' WHERE id = %s", (r["id"],), esq)
    assert len(af.listar()) == 1


def test_a_tv_conta_so_os_validos(esq):
    a = _reg(data="2026-03-02")
    _reg(data="2026-05-20")
    _reg(data="2025-01-01")                      # antes da janela
    af.retirar(a["id"], "engano", autor="ana@sulista.com.br")
    assert af.datas_validas(date(2025, 10, 1)) == ["2026-05-20"]


# ═══════════════════════════════════════════════ as rotas, com sessão ═══
SENHA = "senha-de-teste-123"
URL = "/api/qualidade/acidentes-fatais"


@pytest.fixture
def cliente(esq, monkeypatch):
    from api.main import app
    monkeypatch.setattr(auth, "ESQUEMA", esq)
    auth.init_db()
    with auth._conn() as c:
        perfil = c.execute("SELECT id FROM perfis WHERE admin=1 ORDER BY id LIMIT 1").fetchone()
        c.execute("""INSERT INTO usuarios(nome, email, senha_hash, perfil_id, ativo, deve_trocar_senha, criado_em)
                     VALUES('Ana Qualidade','ana@sulista.com.br',%s,%s,1,0,%s)""",
                  (auth._ph.hash(SENHA), perfil["id"], auth._agora()))
    cli = TestClient(app)
    r = cli.post("/api/auth/login", json={"email": "ana@sulista.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    return cli


def test_as_rotas_sao_da_tela_qualidade():
    for rota in (URL, URL + "/1/retirar"):
        assert [t for p, t in auth.ROTA_TELAS if rota.startswith(p)][0] == frozenset({"qual"})


def test_sem_sessao_e_401():
    from api.main import app
    c = TestClient(app)
    assert c.get(URL).status_code == 401
    assert c.post(URL, json=BASE).status_code == 401


def test_registra_retira_e_audita_com_o_autor_da_sessao(cliente, esq):
    r = cliente.post(URL, json={**BASE, "data": date.today().isoformat()})
    assert r.status_code == 200, r.text
    reg = r.json()["registro"]
    assert reg["autor"] == "ana@sulista.com.br"
    x = cliente.post(f"{URL}/{reg['id']}/retirar", json={"motivo": "Teste de retirada."})
    assert x.status_code == 200 and x.json()["registro"]["retirado_por"] == "ana@sulista.com.br"
    acoes = {r2["acao"] for r2 in pglocal.query(
        "SELECT acao FROM audit_log WHERE acao LIKE 'acidente_fatal%%'", None, esq)}
    assert acoes == {"acidente_fatal_registrar", "acidente_fatal_retirar"}
    assert [y["id"] for y in cliente.get(URL).json()["registros"]] == [reg["id"]]


def test_recusa_e_409_com_a_mensagem(cliente):
    r = cliente.post(URL, json={**BASE, "filial": "Lua"})
    assert r.status_code == 409 and "fora da lista" in r.json()["mensagem"]
    r = cliente.post(f"{URL}/999999/retirar", json={"motivo": "x"})
    assert r.status_code == 409
