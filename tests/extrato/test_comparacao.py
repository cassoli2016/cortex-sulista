"""Comparação extrato x ERP — função pura, sem banco."""
from __future__ import annotations

from api.extrato.comparacao import (agregar_extrato, comparar, farol, saldo_derivado)


def _l(dt, valor):
    return {"dt": dt, "valor": valor, "tipo": "C" if valor >= 0 else "D"}


def _erp(dt, credito, debito, saldo):
    return {"dt": dt, "credito": credito, "debito": debito, "saldo": saldo}


def test_agregar_separa_credito_e_debito_por_dia():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0), _l("2026-07-01", -30.0),
                               _l("2026-07-02", -5.0)])
    assert por_dia["2026-07-01"] == {"credito": 100.0, "debito": 30.0,
                                     "liquido": 70.0, "qtd": 2}
    assert por_dia["2026-07-02"]["debito"] == 5.0


def test_saldo_derivado_da_ancora_para_tras_e_para_frente():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0), _l("2026-07-02", -40.0)])
    # ancora: saldo 1.060 ao fim de 02/07 -> fim de 01/07 = 1.100
    d = saldo_derivado(por_dia, [{"dt": "2026-07-02", "saldo": 1060.0}])
    assert round(d["2026-07-02"], 2) == 1060.00
    assert round(d["2026-07-01"], 2) == 1100.00


def test_saldo_derivado_sem_ancora_e_vazio():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0)])
    assert saldo_derivado(por_dia, []) == {}


def test_dia_que_bate_ao_centavo_e_ok():
    dias = comparar([_l("2026-07-01", 100.0), _l("2026-07-01", -30.0)],
                    [{"dt": "2026-07-01", "saldo": 70.0}],
                    [_erp("2026-07-01", 100.0, 30.0, 70.0)])
    assert len(dias) == 1
    assert dias[0]["estado"] == "OK"
    assert dias[0]["d_saldo"] == 0.0


def test_diferenca_de_um_centavo_ainda_e_ok():
    dias = comparar([_l("2026-07-01", 100.0)], [{"dt": "2026-07-01", "saldo": 100.0}],
                    [_erp("2026-07-01", 100.01, 0.0, 100.0)])
    assert dias[0]["estado"] == "OK"


def test_divergencia_de_credito_marca_diverge_com_delta():
    dias = comparar([_l("2026-07-01", 100.0)], [{"dt": "2026-07-01", "saldo": 100.0}],
                    [_erp("2026-07-01", 90.0, 0.0, 100.0)])
    assert dias[0]["estado"] == "DIVERGE"
    assert round(dias[0]["d_credito"], 2) == 10.0


def test_divergencia_de_saldo_marca_diverge():
    dias = comparar([_l("2026-07-01", 100.0)], [{"dt": "2026-07-01", "saldo": 100.0}],
                    [_erp("2026-07-01", 100.0, 0.0, 95.0)])
    assert dias[0]["estado"] == "DIVERGE"
    assert round(dias[0]["d_saldo"], 2) == 5.0


def test_dia_so_no_extrato_e_so_no_erp():
    dias = comparar([_l("2026-07-01", 100.0)], [],
                    [_erp("2026-07-02", 50.0, 0.0, 150.0)])
    estados = {d["dt"]: d["estado"] for d in dias}
    assert estados == {"2026-07-01": "SO_EXTRATO", "2026-07-02": "SO_ERP"}


def test_sem_ancora_de_saldo_compara_so_fluxo():
    dias = comparar([_l("2026-07-01", 100.0)], [],
                    [_erp("2026-07-01", 100.0, 0.0, 999.0)])
    assert dias[0]["ext_saldo"] is None
    assert dias[0]["d_saldo"] is None
    assert dias[0]["estado"] == "OK"       # fluxo bate; saldo não é comparável


def test_farol_ok_diverge_sem_mapa_e_desatualizado():
    ok = [{"dt": "2026-07-31", "estado": "OK", "d_saldo": 0.0}]
    assert farol(ok, "2026-07-31", "2026-08-01")["estado"] == "ok"
    div = [{"dt": "2026-07-31", "estado": "DIVERGE", "d_saldo": -12.5}]
    f = farol(div, "2026-07-31", "2026-08-01")
    assert (f["estado"], f["delta"]) == ("diverge", -12.5)
    assert farol(ok, "2026-07-31", "2026-08-01", mapeada=False)["estado"] == "sem_mapa"
    # ultimo upload ha mais de 7 dias
    velho = farol(ok, "2026-07-20", "2026-08-01")
    assert velho["estado"] == "desatualizado"
    assert velho["dias_sem_extrato"] == 12


def test_farol_sem_nenhum_dia():
    f = farol([], None, "2026-08-01")
    assert f["estado"] == "desatualizado"
    assert f["dt"] is None


def test_ancora_sem_lancamento_com_saldo_erp_diferente_e_diverge():
    # LEDGERBAL cai no fechamento do arquivo (02/07), dia sem nenhum lancamento.
    # ERP diverge 50 nesse dia exato -> tem que aparecer, nao sumir atras do dia
    # anterior (que bate).
    dias = comparar(
        [_l("2026-07-01", 100.0)],
        [{"dt": "2026-07-02", "saldo": 150.0}],
        [_erp("2026-07-01", 100.0, 0.0, 150.0), _erp("2026-07-02", 0.0, 0.0, 200.0)],
    )
    por_dt = {d["dt"]: d for d in dias}
    assert por_dt["2026-07-02"]["estado"] == "DIVERGE"
    assert round(por_dt["2026-07-02"]["d_saldo"], 2) == -50.0
    f = farol(dias, "2026-07-02", "2026-07-02")
    assert f["estado"] == "diverge"
    assert f["dt"] == "2026-07-02"


def test_ancora_sem_lancamento_com_saldo_erp_igual_e_ok_sem_inventar_credito_debito():
    dias = comparar(
        [_l("2026-07-01", 100.0)],
        [{"dt": "2026-07-02", "saldo": 150.0}],
        [_erp("2026-07-01", 100.0, 0.0, 150.0), _erp("2026-07-02", 0.0, 0.0, 150.0)],
    )
    por_dt = {d["dt"]: d for d in dias}
    dia2 = por_dt["2026-07-02"]
    assert dia2["estado"] == "OK"
    assert dia2["d_credito"] is None
    assert dia2["d_debito"] is None


def test_saldo_derivado_usa_ancora_mais_recente_entre_duas():
    por_dia = agregar_extrato([_l("2026-07-01", 100.0), _l("2026-07-02", -40.0),
                               _l("2026-07-03", 10.0)])
    # duas ancoras: a mais recente (03/07) manda, a de 01/07 e ignorada
    d = saldo_derivado(por_dia, [{"dt": "2026-07-01", "saldo": 9999.0},
                                  {"dt": "2026-07-03", "saldo": 1070.0}])
    assert round(d["2026-07-03"], 2) == 1070.0
    assert round(d["2026-07-02"], 2) == 1060.0
    assert round(d["2026-07-01"], 2) == 1100.0
