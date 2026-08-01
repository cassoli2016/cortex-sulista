"""Persistência local do extrato (SQLite) — sem AVA, sem rede."""
from __future__ import annotations

import pytest

from api.extrato import armazenamento as arm


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "extrato.db"
    arm.init_db(p)
    return p


def _item(dt="2026-07-01", valor=100.0, tipo="C", hist="TED RECEBIDA",
          doc="123", fitid="F1"):
    return {"dt": dt, "valor": valor, "tipo": tipo, "historico": hist,
            "numerodoc": doc, "fitid": fitid}


def test_conta_criada_uma_vez(db):
    a = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau 539349")
    b = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau 539349")
    assert a == b
    assert len(arm.listar_contas(db)) == 1


def test_grava_lancamentos_e_dedup_por_fitid(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r1 = arm.gravar_lancamentos(db, cid, [_item(), _item(fitid="F2", valor=-50.0, tipo="D")],
                                "ext.ofx", "ofx")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    # re-upload do MESMO arquivo: nada entra de novo
    r2 = arm.gravar_lancamentos(db, cid, [_item(), _item(fitid="F2", valor=-50.0, tipo="D")],
                                "ext.ofx", "ofx")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)
    assert len(arm.lancamentos(db, cid, "2026-07-01", "2026-07-31")) == 2


def test_dedup_sem_fitid_usa_hash_e_preserva_repetidos_do_dia(db):
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    # dois lançamentos IDÊNTICOS no mesmo dia são legítimos (duas tarifas iguais)
    itens = [_item(fitid=None), _item(fitid=None)]
    r1 = arm.gravar_lancamentos(db, cid, itens, "ext.csv", "csv")
    assert (r1["novas"], r1["duplicadas"]) == (2, 0)
    r2 = arm.gravar_lancamentos(db, cid, itens, "ext.csv", "csv")
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)


def test_apagar_importacao_remove_lancamentos(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    r = arm.gravar_lancamentos(db, cid, [_item()], "ext.ofx", "ofx")
    assert arm.apagar_importacao(db, r["importacao_id"]) == 1
    assert arm.lancamentos(db, cid, "2026-07-01", "2026-07-31") == []
    assert arm.listar_importacoes(db) == []


def test_mapeamento_erp_e_mapa_csv(db):
    cid = arm.obter_ou_criar_conta(db, "csv:itau", "Itau CSV")
    arm.mapear_conta(db, cid, 341, "0098", "539349", rotulo="Itau conta movimento")
    arm.salvar_mapa_csv(db, cid, {"dt": 0, "valor": 3, "historico": 1})
    c = arm.conta_por_ident(db, "csv:itau")
    assert (c["erp_banco"], c["erp_agencia"], c["erp_conta"]) == (341, "0098", "539349")
    assert c["rotulo"] == "Itau conta movimento"
    assert c["mapa_csv"] == {"dt": 0, "valor": 3, "historico": 1}


def test_saldo_extrato_upsert(db):
    cid = arm.obter_ou_criar_conta(db, "341/0098/539349", "Itau")
    arm.gravar_saldo_extrato(db, cid, "2026-07-31", 1000.0)
    arm.gravar_saldo_extrato(db, cid, "2026-07-31", 1200.0)   # reimport corrige
    assert arm.saldos_extrato(db, cid) == [{"dt": "2026-07-31", "saldo": 1200.0}]
