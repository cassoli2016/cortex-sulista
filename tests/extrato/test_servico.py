"""Serviço do extrato: importação ponta a ponta (SQLite real, AVA mockado)."""
from __future__ import annotations

import pytest

from api.extrato import armazenamento as arm
from api.extrato import servico
from tests.extrato.test_parser_ofx import OFX_SGML


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "extrato.db"
    arm.init_db(p)
    return p


def test_importar_ofx_conta_nova_pede_mapeamento(db):
    r = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    assert r["ok"] is False
    assert r["precisa"] == "mapa_erp"
    assert r["conta"]["ident"] == "341/0098/539349"
    # os lançamentos JÁ ficam gravados — o mapeamento é só o vínculo com o ERP
    assert r["novas"] == 2
    assert len(r["contas"]) == 1        # um extrato por conta no arquivo


def test_importar_ofx_conta_mapeada_grava_e_reimport_nao_duplica(db):
    r1 = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    arm.mapear_conta(db, r1["conta_id"], 341, "0098", "539349")
    r2 = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    assert r2["ok"] is True
    assert (r2["novas"], r2["duplicadas"]) == (0, 2)
    assert r2["dt_de"] == "2026-07-02" and r2["dt_ate"] == "2026-07-03"
    # o saldo do LEDGERBAL entrou
    assert arm.saldos_extrato(db, r1["conta_id"]) == [{"dt": "2026-07-31", "saldo": 123456.78}]


def test_importar_csv_sem_mapa_pede_mapa_csv(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    r = servico.importar(bruto, "banco.csv", path=db)
    assert r["ok"] is False
    assert r["precisa"] == "mapa_csv"
    assert r["preview"]["amostra"][0] == ["Data", "Historico", "Valor"]


def test_importar_csv_com_mapa_salvo(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    r = servico.importar(bruto, "banco.csv", path=db)
    cid = r["conta_id"]
    arm.salvar_mapa_csv(db, cid, {"dt": 0, "historico": 1, "valor": 2})
    arm.mapear_conta(db, cid, 341, "0098", "539349")
    r2 = servico.importar(bruto, "banco.csv", path=db)
    assert r2["ok"] is True and r2["novas"] == 1


def test_importar_arquivo_ilegivel_levanta_valueerror(db):
    with pytest.raises(ValueError):
        servico.importar(b"\x00\x01 nao sou extrato", "x.ofx", path=db)


def test_painel_cruza_com_erp_mockado(db, monkeypatch):
    r = servico.importar(OFX_SGML.encode("cp1252"), "itau.ofx", path=db)
    arm.mapear_conta(db, r["conta_id"], 341, "0098", "539349")

    def fake_query(sql, params=None):
        return [{"dt": "2026-07-02", "credito": 15000.50, "debito": 0.0, "saldo": 15000.50},
                {"dt": "2026-07-03", "credito": 0.0, "debito": 2340.75, "saldo": 12659.75}]

    monkeypatch.setattr(servico.db, "query", fake_query)
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["contas"] == 1
    assert d["kpis"]["dias_validados"] == 2
    assert len(d["contas"]) == 1
    assert d["contas"][0]["farol"]["estado"] in ("ok", "diverge", "desatualizado")
    dias = {x["dt"]: x for x in d["dias"]}
    assert dias["2026-07-02"]["erp_credito"] == 15000.50


def test_painel_sem_conta_nenhuma_nao_quebra(db, monkeypatch):
    monkeypatch.setattr(servico.db, "query", lambda sql, params=None: [])
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["contas"] == 0
    assert d["dias"] == []


# --- FIX 1: maior_diferenca nao pode priorizar saldo por truthiness ---------

def test_painel_maior_diferenca_usa_o_maior_delta_nao_o_saldo(db, monkeypatch):
    cid = arm.obter_ou_criar_conta(db, "1/2/3", "conta unica")
    arm.mapear_conta(db, cid, 1, "2", "3")
    arm.gravar_lancamentos(db, cid, [
        {"dt": "2026-07-01", "valor": 1000.0, "tipo": "C", "historico": "x", "numerodoc": ""},
    ], "a.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid, "2026-07-01", 1000.0)

    def fake_query(sql, params=None):
        # credito diverge em R$ 500 (causa real do DIVERGE); saldo diverge so
        # R$ 0,007, abaixo da tolerancia de 1 centavo - nao e a causa
        return [{"dt": "2026-07-01", "credito": 500.0, "debito": 0.0, "saldo": 999.993}]

    monkeypatch.setattr(servico.db, "query", fake_query)
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["maior_diferenca"] == 500.0


def test_painel_maior_diferenca_com_saldo_zero_legitimo_nao_desvia(db, monkeypatch):
    cid = arm.obter_ou_criar_conta(db, "1/2/4", "conta debito")
    arm.mapear_conta(db, cid, 1, "2", "4")
    arm.gravar_lancamentos(db, cid, [
        {"dt": "2026-07-01", "valor": -100.0, "tipo": "D", "historico": "y", "numerodoc": ""},
    ], "b.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid, "2026-07-01", 900.0)

    def fake_query(sql, params=None):
        # debito diverge em R$ 80 (causa real do DIVERGE); credito e saldo batem
        # exatamente (diferenca 0,0 legitima) - nenhum dos dois pode "vencer" o
        # debito so por serem falsy
        return [{"dt": "2026-07-01", "credito": 0.0, "debito": 20.0, "saldo": 900.0}]

    monkeypatch.setattr(servico.db, "query", fake_query)
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["maior_diferenca"] == 80.0


def test_painel_maior_diferenca_aponta_para_conta_e_dia_certos(db, monkeypatch):
    cid_a = arm.obter_ou_criar_conta(db, "1/2/A", "Conta A")
    arm.mapear_conta(db, cid_a, 1, "2", "A")
    arm.gravar_lancamentos(db, cid_a, [
        {"dt": "2026-07-01", "valor": 100.0, "tipo": "C", "historico": "a", "numerodoc": ""},
    ], "a.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid_a, "2026-07-01", 100.0)

    cid_b = arm.obter_ou_criar_conta(db, "1/2/B", "Conta B")
    arm.mapear_conta(db, cid_b, 1, "2", "B")
    arm.gravar_lancamentos(db, cid_b, [
        {"dt": "2026-07-05", "valor": 300.0, "tipo": "C", "historico": "b", "numerodoc": ""},
    ], "b.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid_b, "2026-07-05", 300.0)

    def fake_query(sql, params=None):
        # Conta A diverge R$ 10 no credito; Conta B diverge R$ 200 - o maior
        # desvio geral tem que apontar para a conta/dia de B, nao de A
        if params["conta"] == "A":
            return [{"dt": "2026-07-01", "credito": 90.0, "debito": 0.0, "saldo": 100.0}]
        return [{"dt": "2026-07-05", "credito": 100.0, "debito": 0.0, "saldo": 300.0}]

    monkeypatch.setattr(servico.db, "query", fake_query)
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["maior_diferenca"] == 200.0
    assert d["kpis"]["maior_diferenca_conta"] == "Conta B"
    assert d["kpis"]["maior_diferenca_dt"] == "2026-07-05"
