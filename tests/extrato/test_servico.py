"""Serviço do extrato: importação ponta a ponta (SQLite real, AVA mockado)."""
from __future__ import annotations

import pytest

from api.extrato import armazenamento as arm
from api.extrato import servico
from tests.extrato.test_parser_ofx import OFX_DUAS_CONTAS, OFX_SGML


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


# NOTA (fix round 2 / FINDING 1 - critical): o CSV nao traz a conta dentro do
# arquivo (ao contrario do OFX), entao ela deixou de ser inferida do NOME do
# arquivo ("extrato.csv" e o export padrao de varios internet bankings - dois
# bancos diferentes colidiam na mesma conta, aplicando o mapa/vinculo ERP de
# um aos lancamentos do outro, com `ok: true` e nenhum aviso). Os dois testes
# abaixo substituem os antigos `test_importar_csv_sem_mapa_pede_mapa_csv` e
# `test_importar_csv_com_mapa_salvo`, que dependiam do contrato antigo
# (conta inferida do nome do arquivo, sem `conta_id`) e por isso nao tem mais
# como passar sem reescrever - a mudanca de contrato e exatamente o fix.

def test_importar_csv_sem_conta_id_pede_conta_csv(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    r = servico.importar(bruto, "banco.csv", path=db)
    assert r["ok"] is False
    assert r["precisa"] == "conta_csv"
    assert r["preview"]["amostra"][0] == ["Data", "Historico", "Valor"]
    # nada foi gravado: nenhuma conta nova, nenhum lancamento
    assert arm.listar_contas(db) == []


def test_importar_csv_com_conta_sem_mapa_pede_mapa_csv(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    cid = arm.obter_ou_criar_conta(db, servico.ident_csv(341, "0098", "539349"), "Banco X")
    r = servico.importar(bruto, "banco.csv", path=db, conta_id=cid)
    assert r["ok"] is False
    assert r["precisa"] == "mapa_csv"
    assert r["conta_id"] == cid
    assert r["preview"]["amostra"][0] == ["Data", "Historico", "Valor"]
    assert arm.lancamentos(db, cid, "2026-01-01", "2026-12-31") == []


def test_importar_csv_com_mapa_salvo(db):
    bruto = b"Data;Historico;Valor\n01/07/2026;TED;10,00\n"
    cid = arm.obter_ou_criar_conta(db, servico.ident_csv(341, "0098", "539349"), "Banco X")
    arm.salvar_mapa_csv(db, cid, {"dt": 0, "historico": 1, "valor": 2})
    arm.mapear_conta(db, cid, 341, "0098", "539349")
    r2 = servico.importar(bruto, "banco.csv", path=db, conta_id=cid)
    assert r2["ok"] is True and r2["novas"] == 1


def test_importar_csv_mesmo_nome_arquivo_contas_diferentes_nao_mistura(db):
    """Prova do fix do Critical: dois CSV chamados IGUAL ("extrato.csv"), de
    bancos diferentes, com conta_id explicitos e DIFERENTES - os lancamentos
    tem que ficar em contas separadas, nunca misturados."""
    bruto_a = b"Data;Historico;Valor\n01/07/2026;TED BANCO A;10,00\n"
    bruto_b = b"Data;Historico;Valor\n02/07/2026;TED BANCO B;20,00\n"
    mapa = {"dt": 0, "historico": 1, "valor": 2}

    cid_a = arm.obter_ou_criar_conta(db, servico.ident_csv(1, "1", "A"), "Banco A")
    arm.salvar_mapa_csv(db, cid_a, mapa)
    cid_b = arm.obter_ou_criar_conta(db, servico.ident_csv(2, "2", "B"), "Banco B")
    arm.salvar_mapa_csv(db, cid_b, mapa)
    assert cid_a != cid_b

    servico.importar(bruto_a, "extrato.csv", path=db, conta_id=cid_a)
    servico.importar(bruto_b, "extrato.csv", path=db, conta_id=cid_b)

    lancs_a = arm.lancamentos(db, cid_a, "2026-07-01", "2026-07-31")
    lancs_b = arm.lancamentos(db, cid_b, "2026-07-01", "2026-07-31")
    assert len(lancs_a) == 1 and lancs_a[0]["historico"] == "TED BANCO A"
    assert len(lancs_b) == 1 and lancs_b[0]["historico"] == "TED BANCO B"


def test_ident_csv_formato():
    assert servico.ident_csv(341, "0098", "539349") == "csv:341/0098/539349"


def test_importar_ofx_multiplas_contas_relata_pendentes(db):
    r = servico.importar(OFX_DUAS_CONTAS.encode("utf-8"), "consolidado.ofx", path=db)
    assert r["novas"] == 2                 # soma das duas contas (1 lancamento cada)
    assert len(r["contas"]) == 2
    assert r["pendentes"] == 2              # nenhuma das duas tem vinculo ERP ainda

    # mapeia so a primeira conta do arquivo (341/0098/111)
    primeira_cid = r["contas"][0]["conta_id"]
    arm.mapear_conta(db, primeira_cid, 341, "0098", "111")

    r2 = servico.importar(OFX_DUAS_CONTAS.encode("utf-8"), "consolidado.ofx", path=db)
    assert r2["pendentes"] == 1


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


# --- Task 7 / FINDING 7: lancamentos_dia entrou no contrato do painel sem ---
# --- teste (usado por extbDetalhe no front, ao expandir um dia) -------------

def test_painel_traz_lancamentos_dia_da_conta_selecionada(db, monkeypatch):
    cid = arm.obter_ou_criar_conta(db, "1/2/3", "conta unica")
    arm.mapear_conta(db, cid, 1, "2", "3")
    arm.gravar_lancamentos(db, cid, [
        {"dt": "2026-07-02", "valor": 150.0, "tipo": "C", "historico": "ted", "numerodoc": "001"},
    ], "a.ofx", "ofx")

    monkeypatch.setattr(servico.db, "query", lambda sql, params=None: [])
    d = servico.painel("2026-07-01", "2026-07-31", conta_id=cid, path=db)
    assert d["conta_selecionada"] == cid
    assert d["lancamentos_dia"] == [
        {"dt": "2026-07-02", "valor": 150.0, "tipo": "C", "historico": "ted", "numerodoc": "001"},
    ]


def test_painel_sem_conta_selecionada_lancamentos_dia_vazio(db, monkeypatch):
    # conta_id=None e nenhuma conta cadastrada: nao ha o que selecionar
    # automaticamente, entao lancamentos_dia tem que vir vazio, nunca quebrar.
    monkeypatch.setattr(servico.db, "query", lambda sql, params=None: [])
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["conta_selecionada"] is None
    assert d["lancamentos_dia"] == []


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


# --- Fix round 5 / FINDING 3: painel reaproveita cmp._maior_delta em vez ----
# --- de duplicar "maior modulo entre os tres" - `maior_diferenca` continua -
# --- sendo o mesmo de antes (so a origem da logica mudou) ------------------

def test_painel_maior_diferenca_com_vencedor_negativo_continua_absoluto(db, monkeypatch):
    """`cmp._maior_delta` devolve o valor COM sinal (para o farol decidir
    acima/abaixo do ERP); `servico.painel` aplica `abs()` no chamador porque
    o KPI `maior_diferenca` sempre foi um valor absoluto. Este teste cobre o
    caso que os 3 testes acima não cobrem: o campo vencedor divergindo
    NEGATIVAMENTE (extrato abaixo do ERP) - se o `abs()` do refactor
    estivesse no lugar errado, `maior_diferenca` sairia negativo aqui."""
    cid = arm.obter_ou_criar_conta(db, "1/2/9", "conta credito negativo")
    arm.mapear_conta(db, cid, 1, "2", "9")
    arm.gravar_lancamentos(db, cid, [
        {"dt": "2026-07-01", "valor": 500.0, "tipo": "C", "historico": "z", "numerodoc": ""},
    ], "c.ofx", "ofx")
    arm.gravar_saldo_extrato(db, cid, "2026-07-01", 500.0)

    def fake_query(sql, params=None):
        # credito do extrato (500) fica ABAIXO do ERP (1000) -> d_credito =
        # 500-1000 = -500 (negativo); e a causa real do DIVERGE
        return [{"dt": "2026-07-01", "credito": 1000.0, "debito": 0.0, "saldo": 500.0}]

    monkeypatch.setattr(servico.db, "query", fake_query)
    d = servico.painel("2026-07-01", "2026-07-31", path=db)
    assert d["kpis"]["maior_diferenca"] == 500.0   # nunca -500.0


# --- FIX 2 / FINDING 3: painel nao pode consultar o ERP duas vezes pela ----
# --- mesma conta quando conta_id=None (selecao automatica) -----------------

def test_painel_nao_duplica_query_erp_na_selecao_automatica(db, monkeypatch):
    cid = arm.obter_ou_criar_conta(db, "1/2/3", "conta unica")
    arm.mapear_conta(db, cid, 1, "2", "3")
    arm.gravar_lancamentos(db, cid, [
        {"dt": "2026-07-01", "valor": 100.0, "tipo": "C", "historico": "x", "numerodoc": ""},
    ], "a.ofx", "ofx")

    chamadas = []

    def fake_query(sql, params=None):
        chamadas.append(params)
        return []

    monkeypatch.setattr(servico.db, "query", fake_query)
    servico.painel("2026-07-01", "2026-07-31", path=db)  # conta_id=None (default)
    assert len(chamadas) == 1
