# -*- coding: utf-8 -*-
"""A hora extra PAGA × o saldo do banco — pelo saldo do EXTRATO.

A HISTÓRIA DESTE ARQUIVO
========================
Até a v1.80.0 ele guardava a frase "no mês em que a casa mais pagou, o saldo
do banco SUBIU" — lida em `saldonacompet`, e com ela a conclusão de que o
pagamento não baixa o saldo. Em 14/09/2026 o Extrato do Banco de Horas oficial
do Globus mostrou o contrário: aquele campo é um ACUMULADOR, e o saldo que o
ERP reporta (saldo anterior + crédito − débito) ZERA o credor quando a casa
paga. Os dois lados continuam na mesma linha do tempo; o que mudou foi qual
saldo é o saldo.

O dublê é LITERAL no formato do Globus: o banco em HH.MM, a folha em hora
decimal — e as duas só se comparam depois da conversão.
"""
from __future__ import annotations

from datetime import date

import pytest

from api import frequencia as F

_PAGOS = [{"comp": "2026-07", "pessoas": 34, "horas": 650.2, "reais": 1.0},
          {"comp": "2026-08", "pessoas": 60, "horas": 1506.7, "reais": 2.0}]
_BAIXAS = [{"comp": "2026-08", "horas": 86.4}]
_LINHAS = [
    {"comp": "2026-07", "anterior": 90.00, "credito": 8.33, "debito": 0.0},
    {"comp": "2026-08", "anterior": 98.33, "credito": 36.00, "debito": 1.37},
    {"comp": "2026-08", "anterior": -17.36, "credito": 0.0, "debito": 0.0},
]


def _confronto(monkeypatch, pagos=_PAGOS, linhas=_LINHAS, baixas=_BAIXAS):
    def falso(sql, p=None):
        s = " ".join(sql.split()).upper()
        assert "SALDONACOMPET" not in s, "o saldo é o do extrato, não o acumulador"
        if "FLP_FICHAEVENTOS" in s and "CODEVENTO = 1016" in s:
            return baixas
        if "FLP_FICHAEVENTOS" in s:
            return pagos
        return linhas

    monkeypatch.setattr(F, "_q", falso)
    from api import queries
    queries._RESP_CACHE.clear()
    try:
        return F.confronto()
    finally:
        queries._RESP_CACHE.clear()


def test_pago_e_saldo_na_MESMA_linha_com_o_saldo_do_extrato(monkeypatch):
    d = _confronto(monkeypatch)
    jul, ago = [x for x in d["serie"] if x["comp"] in ("2026-07", "2026-08")]
    assert jul["saldo"] == pytest.approx((98 * 60 + 33) / 60, abs=0.01)
    # 98:33 + 36:00 − 1:37 = 132:56 — só o CREDOR entra no saldo credor
    assert ago["saldo"] == pytest.approx((132 * 60 + 56) / 60, abs=0.01)
    assert ago["pago_h"] == 1506.7, "a folha é hora decimal e entra como está"
    assert ago["variacao"] == pytest.approx(ago["saldo"] - jul["saldo"], abs=0.1)
    assert ago["debito_banco"] == pytest.approx(97 / 60, abs=0.01)
    assert ago["baixa_pela_folha"] == 86.4
    assert d["pago_h"] == pytest.approx(2156.9, abs=0.1)


def test_o_mes_CORRENTE_fica_fora_do_saldo(monkeypatch):
    """Ele não fechou: o saldo dele é pedaço, e a folha dele nem existe."""
    corrente = date.today().strftime("%Y-%m")
    d = _confronto(monkeypatch, pagos=[], baixas=[],
                   linhas=[{"comp": corrente, "anterior": 10.00, "credito": 0.0,
                            "debito": 0.0}])
    assert d["serie"] == []


def test_confronto_sobrevive_a_mes_sem_um_dos_lados(monkeypatch):
    """Mês com pagamento e sem saldo (ou o contrário) não pode derrubar a
    série: cada lado devolve um conjunto de meses diferente."""
    d = _confronto(monkeypatch, pagos=[{"comp": "2026-08", "pessoas": 1,
                                        "horas": 10.0, "reais": 1.0}],
                   linhas=[], baixas=[])
    assert len(d["serie"]) == 1
    assert d["serie"][0]["saldo"] is None and d["serie"][0]["variacao"] is None


def test_nenhum_mes_e_rotulado_como_FECHAMENTO(monkeypatch):
    """O fato se lê na série (o saldo cai no mês pago); rótulo por heurística
    já quase entrou aqui e levava junto mês que não era fechamento."""
    for x in _confronto(monkeypatch)["serie"]:
        assert "fechamento" not in x
