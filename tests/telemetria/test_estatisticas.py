"""Normalização das estatísticas e do odômetro."""
from __future__ import annotations

from api.gobrax import estatisticas, odometro

RESP_STATS = {"records": [
    {"vehicleIdentification": "ABC-1234", "averageSpeed": 60.0,
     "consumptionAverage": 1.73, "odometer": 291862.215, "totalConsumption": 12.82,
     "totalMileage": 22.17, "totalBreakingOnHighSpeed": 0, "totalBreaking": 9},
    {"vehicleIdentification": "DDD-4444", "averageSpeed": 71.0,
     "consumptionAverage": 0, "odometer": 311202.110, "totalConsumption": 0,
     "totalMileage": 0, "totalBreakingOnHighSpeed": 1, "totalBreaking": 19},
]}

RESP_ODO = {"records": [
    {"vehicleIdentification": "ABC-1234", "odometer": 140773.04,
     "lastUpdated": "2026-07-31 23:59:35+0000"},
    {"vehicleIdentification": "SEM-LEITURA", "odometer": 0, "lastUpdated": None},
]}


class ClienteFalso:
    def __init__(self, resp):
        self.resp = resp
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        self.chamadas.append((caminho, params))
        return self.resp


def test_estatisticas_normaliza_os_campos():
    r = estatisticas.coletar("2026-07", cliente=ClienteFalso(RESP_STATS))[0]
    assert r["placa"] == "ABC-1234"
    assert r["km_l"] == 1.73
    assert r["km"] == 22.17
    assert r["litros"] == 12.82
    assert r["freadas"] == 9
    assert r["freadas_alta"] == 0


def test_estatisticas_pede_o_mes_inteiro():
    c = ClienteFalso(RESP_STATS)
    estatisticas.coletar("2026-07", cliente=c)
    _caminho, params = c.chamadas[0]
    assert params["startDate"] == "2026-07-01 00:00:00"
    assert params["endDate"] == "2026-07-31 23:59:59"


def test_fevereiro_tem_o_ultimo_dia_certo():
    c = ClienteFalso(RESP_STATS)
    estatisticas.coletar("2026-02", cliente=c)
    assert c.chamadas[0][1]["endDate"] == "2026-02-28 23:59:59"


def test_veiculo_sem_consumo_fica_com_km_l_nulo_nao_zero():
    """Zero é uma medida; ausência não é. Um km/l zero entraria na média da
    frota e a puxaria para baixo sem que ninguém tenha rodado mal."""
    linhas = estatisticas.coletar("2026-07", cliente=ClienteFalso(RESP_STATS))
    ddd = [l for l in linhas if l["placa"] == "DDD-4444"][0]
    assert ddd["km_l"] is None


def test_odometro_normaliza_e_marca_sem_leitura():
    linhas = odometro.coletar("2026-07", cliente=ClienteFalso(RESP_ODO))
    ok = [l for l in linhas if l["placa"] == "ABC-1234"][0]
    assert ok["odometro"] == 140773.04
    assert ok["lido_em"] == "2026-07-31 23:59:35+0000"
    sem = [l for l in linhas if l["placa"] == "SEM-LEITURA"][0]
    assert sem["odometro"] is None


def test_resposta_sem_records_devolve_lista_vazia():
    assert estatisticas.coletar("2026-07", cliente=ClienteFalso({})) == []
    assert odometro.coletar("2026-07", cliente=ClienteFalso({})) == []
