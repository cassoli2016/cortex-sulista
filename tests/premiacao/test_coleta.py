from __future__ import annotations

import json
from datetime import datetime

import pytest

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


class FakeClienteMalformado:
    """Permite injetar uma resposta estruturalmente malformada (chave ausente/None)
    num endpoint específico, mantendo os outros bem-formados — para provar que a
    coleta detecta a falha em vez de gravar um snapshot vazio "válido"."""
    def __init__(self, quebrar: str):
        self.quebrar = quebrar

    def get(self, path, params=None):
        if path == "/vehicles":
            if self.quebrar == "vehicles":
                return {"customers": None}
            return {"customers": [{"vehicles": [
                {"id": 101, "plate": "AAA1A11", "truckModel": "DAF XF",
                 "currentDriver": {"driverId": 7, "driverName": "3797 - GABRIEL"}},
            ]}]}
        if path == "/drivers":
            if self.quebrar == "drivers":
                return {"drivers": None}
            return {"drivers": [{"id": 7, "documentNumber": "18399788805"}]}
        if path.endswith("/analysis"):
            if self.quebrar == "analysis":
                return {"data": None}
            return {"data": {"performances": [
                {"driverId": 7, "scores": {"generalScore": 80},
                 "percentages": {},
                 "stats": {"totalMileage": 100.0, "consumptionAverage": 5.0}},
            ]}}
        raise AssertionError(f"chamada inesperada: {path}")


def test_vehicles_malformado_levanta_valueerror():
    with pytest.raises(ValueError):
        coletar_mes(FakeClienteMalformado("vehicles"), "2026-06", agora=datetime(2026, 7, 27))


def test_drivers_malformado_levanta_valueerror():
    with pytest.raises(ValueError):
        coletar_mes(FakeClienteMalformado("drivers"), "2026-06", agora=datetime(2026, 7, 27))


def test_analysis_malformado_levanta_valueerror():
    with pytest.raises(ValueError):
        coletar_mes(FakeClienteMalformado("analysis"), "2026-06", agora=datetime(2026, 7, 27))


class FakeClienteVazio:
    """Cliente sem nenhum veículo/motorista — lista VAZIA mas bem-formada, que é
    dado legítimo (não deve levantar erro nem chamar /analysis, já que não há
    motorista nenhum para consultar)."""
    def get(self, path, params=None):
        if path == "/vehicles":
            return {"customers": [{"vehicles": []}]}
        if path == "/drivers":
            return {"drivers": []}
        raise AssertionError(f"chamada inesperada: {path}")


def test_lista_vazia_bem_formada_gera_snapshot_vazio_sem_erro():
    snap = coletar_mes(FakeClienteVazio(), "2026-06", agora=datetime(2026, 7, 27))
    assert snap["drivers"] == []
    assert snap["frota_telemetria"] == {"veiculos": 0, "com_motorista": 0}


def test_gravar_snapshot_nao_deixa_tmp_para_tras(tmp_path):
    """M1: a escrita passa por arquivo temporário + os.replace (atômico) — o
    diretório final não pode sobrar com nenhum .tmp-* de escrita interrompida,
    e o conteúdo gravado precisa estar correto (não truncado)."""
    snap = coletar_mes(FakeCliente(), "2026-06", agora=datetime(2026, 7, 27, 8, 0))
    gravar_snapshot(snap, tmp_path)

    sobras = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]
    assert sobras == []
    assert ler_snapshot("2026-06", tmp_path)["month"] == "2026-06"
    assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
