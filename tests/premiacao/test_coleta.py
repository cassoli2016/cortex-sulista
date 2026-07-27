from __future__ import annotations

import json
from datetime import datetime

from api.premiacao.coleta import coletar_mes, gravar_snapshot, ler_index, ler_snapshot


class FakeCliente:
    """Devolve os shapes reais da API para 2 motoristas / 3 veículos."""
    def __init__(self):
        self.chamadas = []

    def get(self, path, params=None):
        self.chamadas.append((path, dict(params or {})))
        if path == "/vehicles":
            return {"customers": [{"vehicles": [
                {"id": 101, "plate": "AAA1A11", "truckModel": "DAF XF",
                 "currentDriver": {"driverId": 7, "driverName": "3797 - GABRIEL"}},
                {"id": 102, "plate": "BBB2B22", "truckModel": "SCANIA R",
                 "currentDriver": {"driverId": 8, "driverName": "3818 - EDUARDO"}},
                {"id": 103, "plate": "CCC3C33", "truckModel": "VOLVO FH"},
            ]}]}
        if path == "/drivers":
            return {"drivers": [{"id": 7, "documentNumber": "18399788805"},
                                {"id": 8, "documentNumber": "12345678901"}]}
        if path.endswith("/analysis"):
            return {"data": {"performances": [
                {"driverId": 7, "scores": {"generalScore": 80, "idleScore": 82},
                 "percentages": {"idle": {"percentage": 12}},
                 "stats": {"totalMileage": 6756.61, "consumptionAverage": 5.33,
                           "totalConsumption": 1200, "averageSpeed": 55, "odometer": 90000}},
                {"driverId": 8, "scores": {"generalScore": 74},
                 "percentages": {},
                 "stats": {"totalMileage": 1277.97, "consumptionAverage": 0}},
            ]}}
        raise AssertionError(f"chamada inesperada: {path}")


def test_snapshot_mascara_cpf_e_nunca_grava_cru(tmp_path):
    snap = coletar_mes(FakeCliente(), "2026-06", agora=datetime(2026, 7, 27, 8, 0))
    caminho = gravar_snapshot(snap, tmp_path)
    bruto = caminho.read_text(encoding="utf-8")
    assert "18399788805" not in bruto and "12345678901" not in bruto
    d = json.loads(bruto)["drivers"][0]
    assert d["documento"].startswith("18") and "•" in d["documento"]


def test_mes_fechado_e_corrente(tmp_path):
    agora = datetime(2026, 7, 27, 8, 0)
    fechado = coletar_mes(FakeCliente(), "2026-06", agora=agora)
    assert fechado["parcial"] is False
    assert fechado["periodEnd"] == "2026-06-30T23:59:59Z"
    corrente = coletar_mes(FakeCliente(), "2026-07", agora=agora)
    assert corrente["parcial"] is True
    assert corrente["periodEnd"].startswith("2026-07-27")


def test_analysis_recebe_todos_os_veiculos_e_lotes_de_10():
    cli = FakeCliente()
    coletar_mes(cli, "2026-06", agora=datetime(2026, 7, 27))
    path, params = next(c for c in cli.chamadas if c[0].endswith("/analysis"))
    assert params["vehicles"] == "101,102,103"      # TODOS, não só os com motorista
    assert set(params["drivers"].split(",")) == {"7", "8"}


def test_sem_media_entra_no_snapshot_com_media_none():
    snap = coletar_mes(FakeCliente(), "2026-06", agora=datetime(2026, 7, 27))
    por_id = {d["driverId"]: d for d in snap["drivers"]}
    assert por_id[7]["media"] == 5.33 and por_id[7]["nota"] == 80
    assert por_id[8]["media"] is None               # consumptionAverage 0 -> None
    assert por_id[7]["vehicles"] == [{"plate": "AAA1A11", "model": "DAF XF"}]
    assert snap["frota_telemetria"] == {"veiculos": 3, "com_motorista": 2}


def test_index_ordena_do_mais_recente(tmp_path):
    agora = datetime(2026, 7, 27)
    gravar_snapshot(coletar_mes(FakeCliente(), "2026-06", agora=agora), tmp_path)
    gravar_snapshot(coletar_mes(FakeCliente(), "2026-07", agora=agora), tmp_path)
    idx = ler_index(tmp_path)
    assert [i["month"] for i in idx] == ["2026-07", "2026-06"]
    assert idx[1]["label"] == "Junho / 2026"
    assert ler_snapshot("2026-06", tmp_path)["month"] == "2026-06"
    assert ler_snapshot("2099-01", tmp_path) is None
