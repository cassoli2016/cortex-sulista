"""O filtro de PLACA da tela de Multas vale para TODAS as abas.

Até 14/09/2026 o campo Placa da barra só chegava às duas abas do ERP
(`/api/frota/multas`): `/api/smartec/painel` não recebia parâmetro nenhum, e as
seis abas da Smartec mostravam a frota inteira sob o campo preenchido. Quem
filtrou acreditou no resultado — campo que aceita valor e não muda nada é pior
que campo nenhum.

O guard é por COMPORTAMENTO, na rota: duas placas no banco, o painel pedido com
uma, e cada chave do payload conferida com o próprio assert. Um `all(...)` só
sobre o payload aprovaria a chave que viesse VAZIA; por isso o primeiro teste
prova que, sem filtro, as duas placas estão em cada chave.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from api import pglocal
from api.smartec import armazenamento as arm
from api.smartec import leitura as lei

from .test_armazenamento import MULTA, NOTIFICACAO

A, RENAVAM_A = "BBX3375", "1142889448"
B, RENAVAM_B = "ASC3306", "1234567890"

# as chaves do payload que são LISTAS com placa em cada linha
LISTAS = ("multas", "notificacoes", "por_veiculo", "licencas", "antt",
          "historico")


def _de_b(corpo: dict, **extra) -> dict:
    return dict(corpo, PLACA=B, RENAVAM=RENAVAM_B, **extra)


class _AvaFalso:
    """O `veiculo` do ERP, só o que `cobertura()` lê."""
    LINHAS = [
        {"placa": A, "renavam": RENAVAM_A, "tipofrota": 1,
         "numerofrota": "10", "utilizacao": "FROTA"},
        {"placa": B, "renavam": RENAVAM_B, "tipofrota": 1,
         "numerofrota": "20", "utilizacao": "FROTA"},
    ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        linhas = self.LINHAS

        class _Cursor:
            def fetchall(self):
                return linhas
        return _Cursor()


@pytest.fixture
def painel(esquema_pg, monkeypatch):
    esq = esquema_pg
    monkeypatch.setattr(lei, "ESQUEMA", esq)
    monkeypatch.setattr("api.db.get_conn", lambda *a, **k: _AvaFalso())

    arm.gravar_infracoes([
        MULTA,
        _de_b(MULTA, IDENTIFICADOR_SMARTEC="b-multa", AIT="1VB0000001",
              MOTORISTA_NOME="CONDUTOR B"),
        # as que vão SAIR da lista, para o histórico ter linha das duas
        dict(MULTA, IDENTIFICADOR_SMARTEC="a-sumiu", AIT="1VA0000009"),
        _de_b(MULTA, IDENTIFICADOR_SMARTEC="b-sumiu", AIT="1VB0000009"),
    ], "multa", esq)
    prazo = (date.today() + timedelta(days=3)).strftime("%d/%m/%Y")
    arm.gravar_infracoes([
        dict(NOTIFICACAO, PRAZO_INDICACAO=prazo),
        _de_b(NOTIFICACAO, IDENTIFICADOR_SMARTEC="b-notif",
              PRAZO_INDICACAO=prazo),
    ], "notificacao", esq)
    with pglocal.get_conn(esq) as cx:
        cx.execute("UPDATE smt_infracoes SET sumiu_em = now() "
                   "WHERE ait IN ('1VA0000009', '1VB0000009')")
    arm.gravar_veiculos([
        {"RENAVAM": RENAVAM_A, "PLACA": A, "TIPO": "SEMIRREBOQUE", "UF": "PR"},
        {"RENAVAM": RENAVAM_B, "PLACA": B, "TIPO": "CAMINHAO TRATOR",
         "UF": "PR"},
    ], esq)
    arm.gravar_licencas([
        {"Renavam": RENAVAM_A, "Placa": A, "Frota": "MTZ",
         "Cronotacografo": "04/07/2026"},
        {"Renavam": RENAVAM_B, "Placa": B, "Frota": "MTZ",
         "Cronotacografo": "04/07/2027"},
    ], esq)
    antt = {"PROCESSO": "50501.353726/2026-17", "DATA_INFRACAO": "07/04/2026",
            "TIPO": "Vale Pedágio", "DESCRICAO": "Vale Pedágio",
            "SITUACAO": "Congelado por Defesa Tempestiva", "IMPEDITIVA": 0,
            "LOCAL": "Rodovia BR116 Km 542"}
    arm.gravar_antt([dict(antt, AIT="FELVP00382452026", PLACA=A),
                     dict(antt, AIT="FELVP00382462026", PLACA=B)], esq)

    def chamar(placa=None) -> dict:
        from api import main
        resp = main.smartec_painel(placa=placa)
        assert resp.status_code == 200, resp.body
        return json.loads(resp.body)
    return chamar


@pytest.mark.parametrize("digitado,esperado", [
    ("BBX3375", "BBX3375"), ("bbx-3375", "BBX3375"), (" bbx 3375 ", "BBX3375"),
    ("", None), ("  ", None), ("-", None), (None, None)])
def test_a_placa_vai_ao_formato_da_smartec(digitado, esperado):
    assert lei.placa_filtro(digitado) == esperado


def test_sem_placa_o_painel_traz_as_duas(painel):
    """A base do guard: sem ela, o teste com filtro passaria por vacuidade."""
    d = painel()
    assert d["placa"] is None
    for chave in LISTAS:
        assert {x["placa"] for x in d[chave]} == {A, B}, chave
    assert d["kpis"]["multas"]["n"] == 2
    assert d["kpis"]["antt"]["n"] == 2
    assert d["cobertura"]["proprios"] == 2


@pytest.mark.parametrize("digitado", ["BBX3375", "bbx-3375", "X337"])
def test_a_placa_recorta_toda_leitura_por_veiculo(painel, digitado):
    d = painel(digitado)
    assert d["placa"] == lei.placa_filtro(digitado)
    for chave in LISTAS:
        placas = {x["placa"] for x in d[chave]}
        assert placas == {A}, f"{chave} não seguiu a placa: {placas}"
    k = d["kpis"]
    assert k["multas"]["n"] == 1
    assert k["notificacoes"]["n"] == 1
    assert k["prazo"]["no_prazo"] == 1
    assert k["licencas"]["total"] == 1
    assert k["antt"]["n"] == 1
    assert k["frota"]["cadastrados"] == 1
    assert sum(x["n"] for x in d["por_infracao"]) == 1
    assert sum(x["n"] for x in d["por_orgao"]) == 1
    assert sum(x["multas"] for x in d["mensal"]) == 1
    assert sum(x["notificacoes"] for x in d["mensal"]) == 1
    assert sum(x["n"] for x in d["antt_mensal"]) == 1
    assert sum(x["n"] for x in d["antt_situacao"]) == 1
    assert sum(x["multas"] + x["notificacoes"]
               for x in d["por_motorista"]) == 2
    assert d["cobertura"]["proprios"] == 1


def test_placa_sem_nada_esvazia_em_vez_de_ignorar(painel):
    d = painel("ZZZ9Z99")
    for chave in LISTAS:
        assert d[chave] == [], chave
    assert d["kpis"]["multas"] == {}
    assert d["kpis"]["antt"]["n"] == 0
    assert d["cobertura"]["proprios"] == 0
