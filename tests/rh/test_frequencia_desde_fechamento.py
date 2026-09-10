# -*- coding: utf-8 -*-
"""O saldo que a tela publica é o do FECHAMENTO para cá, não o acumulado.

POR QUE
=======
O ERP acumula desde 2023 e nunca baixa o que é pago — em 24 meses foram pagas
27.516 h de hora extra e o evento de débito movimentou 156,4 h. Contar do
último fechamento semestral para cá dá outra ordem de grandeza:

    saldo desde ago/2026 ....   221,0 h credoras (36 pessoas) ·  R$ 3.738,83
    acumulado no ERP ........ 6.137,3 h                        · R$ 123.429

Os dois são verdadeiros sobre coisas diferentes, e a tela mostra os dois — mas
o primeiro é o que responde "quanto se deve HOJE".

A DATA DO FECHAMENTO VEM DE FORA DO SISTEMA
===========================================
`FECHAMENTO_CONHECIDO` é informado por quem opera: o ERP não registra que
fechou (nem baixa, nem grava a data). Quando ele passar a dar a baixa, a
constante sai — manter um zeramento escrito à mão em cima de um sistema que já
zera é a receita para descontar duas vezes.
"""
from __future__ import annotations

import pytest

from api import frequencia as F
from tests.rh.test_frequencia import _roteador


@pytest.fixture(autouse=True)
def _sem_oracle(monkeypatch):
    from api import queries
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(F.db, "query", _roteador)
    yield
    queries._RESP_CACHE.clear()


def test_o_saldo_do_fechamento_soma_so_credor():
    """Devedor não é passivo: a empresa não deve folga a quem deve horas."""
    d = F.saldo_desde_fechamento()
    assert d["credor_h"] == pytest.approx(41.0, abs=0.1)   # 26,0 + 15,0
    assert d["credores"] == 2
    assert d["devedor_h"] == pytest.approx(-56.0, abs=0.1)
    assert d["devedores"] == 1
    assert d["liquido_h"] == pytest.approx(-15.0, abs=0.1)


def test_o_devedor_nao_recebe_custo():
    d = F.saldo_desde_fechamento()
    dev = [p for p in d["pessoas"] if p["horas"] < 0]
    assert dev and all(p["custo"] == 0.0 for p in dev)


def test_a_pessoa_traz_NOME_e_nao_so_a_chapa():
    """A chapa é chave, não informação — quem lê a tela precisa do nome."""
    d = F.saldo_desde_fechamento()
    for p in d["pessoas"]:
        assert p["nome"], f"pessoa {p['chapa']} sem nome"
        assert p["filial"]


def test_credito_e_debito_viajam_junto_do_saldo():
    """Saldo sozinho não deixa conferir: 15 h pode ser 15 creditadas ou 22,6
    creditadas com 7,6 compensadas, e são situações diferentes."""
    p = {x["chapa"]: x for x in F.saldo_desde_fechamento()["pessoas"]}["003812"]
    assert p["credito"] == 22.6 and p["debito"] == 7.6
    assert p["horas"] == pytest.approx(15.0, abs=0.1)


def test_o_payload_da_tela_leva_o_saldo_do_fechamento():
    """Se sumir, a tela volta a publicar o acumulado como se fosse dívida."""
    d = F.get_banco_horas()
    assert "desde_fechamento" in d
    assert d["desde_fechamento"]["desde"] == F.FECHAMENTO_CONHECIDO


def test_o_acumulado_do_ERP_continua_no_payload():
    """Ele não some: é o que se concilia. O que muda é o lugar dele na tela."""
    d = F.get_banco_horas()
    assert d["kpis"]["passivo_horas"] > 0
    assert d["kpis"]["passivo_horas"] > d["desde_fechamento"]["credor_h"], (
        "o acumulado tem de ser MAIOR que o saldo do fechamento — se não for, "
        "um dos dois está medindo a janela errada")


def test_o_snapshot_do_copiloto_continua_sem_PESSOA():
    """O saldo novo trouxe uma lista com NOME para o payload. O snapshot vai
    para modelo externo e continua tendo de ser só escalar."""
    import json
    r = F.resumo_escalares()
    bruto = json.dumps(r, ensure_ascii=False).upper()
    for proibido in ("MAYCON", "ISABELLE", "VINICIUS", "003648", "CURITIBA"):
        assert proibido not in bruto, f"{proibido} vazou para o snapshot"
    assert all(not isinstance(v, (list, dict)) for v in r.values())
