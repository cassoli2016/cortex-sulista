# -*- coding: utf-8 -*-
"""Evolução mensal do consumo e motoristas (v0.203.0)."""
from __future__ import annotations

import json

import pytest

from api.gobrax import consumo, motoristas


def test_o_eixo_da_evolucao_e_GERADO_e_mes_furado_aparece(monkeypatch):
    """Coletas em 2026-05 e 2026-07 (junho FURADO): o eixo tem de trazer
    junho rotulado como sem coleta — o GROUP BY o engoliria e maio emendaria
    em julho."""
    monkeypatch.setattr(consumo.armazenamento, "competencias",
                        lambda c: ["2026-05", "2026-07"])
    monkeypatch.setattr(consumo.armazenamento, "ler",
                        lambda c, comp: [{"placa": "AAA1111", "km": 10000.0,
                                          "litros": 3300.0, "km_l": 3.03,
                                          "cobertura_tel": 0.9}])
    monkeypatch.setattr(consumo.armazenamento, "ultima", lambda c: None)

    class _Cur:
        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import api.db as db
    monkeypatch.setattr(db, "get_conn", lambda: _Conn())

    class _Hoje(consumo.armazenamento.__class__ if False else object):
        pass

    import datetime as dt

    class _D(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 15)
    monkeypatch.setattr("api.gobrax.consumo.armazenamento", consumo.armazenamento)
    # fixa o relógio dentro do get_evolucao (usa datetime.date importado local)
    monkeypatch.setattr(dt, "date", _D)

    d = consumo.get_evolucao()
    comps = [m["competencia"] for m in d["meses"]]
    assert comps == ["2026-05", "2026-06", "2026-07", "2026-08"]
    junho = next(m for m in d["meses"] if m["competencia"] == "2026-06")
    assert junho["coletado"] is False              # rotulado, nunca engolido
    agosto = next(m for m in d["meses"] if m["competencia"] == "2026-08")
    assert agosto["coletado"] is False             # corrente sem coleta idem
    julho = next(m for m in d["meses"] if m["competencia"] == "2026-07")
    assert julho["coletado"] is True


def test_ranking_de_motoristas_tem_piso_e_conta_quem_ficou_fora(tmp_path, monkeypatch):
    monkeypatch.setattr(motoristas, "DIR_PREMIACAO", tmp_path)
    (tmp_path / "premiacao-2026-07.json").write_text(json.dumps({
        "month": "2026-07", "parcial": False,
        "drivers": [
            {"driverId": 1, "driverName": "A", "km": 5000.0, "nota": 90.0},
            {"driverId": 2, "driverName": "B", "km": 300.0, "nota": 100.0},
            {"driverId": 3, "driverName": "C", "km": 2000.0, "nota": 70.0},
        ]}), encoding="utf-8")
    d = motoristas.get_motoristas()
    nomes = [r["nome"] for r in d["ranking"]]
    assert nomes == ["A", "C"]                     # B: 300 km < piso — fora
    assert d["abaixo_piso"] == 1                   # mas CONTADO, nunca sumido
    # a mediana da série também ignora quem está abaixo do piso
    assert d["serie"][0]["nota_mediana"] == 80.0   # mediana de 90 e 70
    assert d["serie"][0]["no_piso"] == 2


def test_snapshot_furado_nao_derruba_a_leitura(tmp_path, monkeypatch):
    monkeypatch.setattr(motoristas, "DIR_PREMIACAO", tmp_path)
    (tmp_path / "premiacao-2026-06.json").write_text("{quebrado", encoding="utf-8")
    (tmp_path / "premiacao-2026-07.json").write_text(json.dumps({
        "month": "2026-07",
        "drivers": [{"driverId": 1, "driverName": "A", "km": 900.0,
                     "nota": 88.0}]}), encoding="utf-8")
    d = motoristas.get_motoristas()
    assert d["competencias"] == ["2026-07"]        # o furado sai calado do jeito certo
    assert len(d["ranking"]) == 1
