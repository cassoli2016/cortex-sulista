"""Indicadores de condução e trilha do veículo."""
from __future__ import annotations

from datetime import date

import pytest

from api.gobrax import performance, rastro

RESP_PERF = {"records": [{
    "vehicleIdentification": "ABC-1234",
    "drivers": [{"driverName": "MARCOS SANTOS", "cpf": "11122233344",
                 "startDate": "2026-07-03T00:00:00+0000",
                 "endDate": "2026-07-07T23:59:59+0000"}],
    "indicators": {
        "cruiseControl": {"duration": 0, "percentage": 0},
        "ecoRoll": {"duration": 2.5, "percentage": 0.64},
        "economicRange": {"duration": 144.01, "percentage": 36.92, "score": 1},
    }}]}

RESP_POS = {"success": True, "data": [{
    "identification": "GBX1234",
    "positions": [
        {"date": "2026-07-15 11:41:07", "lat": -6.323385, "lon": -47.440385, "speed": 60},
        {"date": "2026-07-15 11:51:07", "lat": -6.323385, "lon": -47.44039},
        {"date": "2026-07-15 12:01:07", "lat": None, "lon": None, "speed": 10},
    ]}]}


class ClienteFalso:
    def __init__(self, resp):
        self.resp = resp
        self.chamadas = []

    def get(self, caminho, params=None, timeout=120):
        self.chamadas.append((caminho, params))
        return self.resp


def test_performance_exige_placa():
    """Sem placa a API responde 404; recusar antes evita a ida à rede."""
    with pytest.raises(ValueError):
        performance.coletar("", "2026-07", cliente=ClienteFalso(RESP_PERF))


def test_performance_devolve_SO_os_indicadores_que_vieram():
    """Devolver os 14 do catálogo com valor nulo inventaria medida que a API
    não fez — e a tela desenharia linha vazia como se fosse desempenho zero."""
    d = performance.coletar("ABC-1234", "2026-07", cliente=ClienteFalso(RESP_PERF))
    rotulos = {i["rotulo"] for i in d["indicadores"]}
    assert rotulos == {"Faixa econômica", "Piloto automático", "Eco-roll (embalo)"}
    eco = [i for i in d["indicadores"] if i["chave"] == "economicRange"][0]
    assert eco["percentual"] == 36.92 and eco["nota_fornecedor"] == 1


def test_performance_traz_o_motorista_sem_o_cpf():
    d = performance.coletar("ABC-1234", "2026-07", cliente=ClienteFalso(RESP_PERF))
    assert d["motoristas"][0]["nome"] == "MARCOS SANTOS"
    assert "11122233344" not in repr(d)


def test_performance_sem_registro_nao_quebra():
    d = performance.coletar("XXX", "2026-07", cliente=ClienteFalso({"records": []}))
    assert d["indicadores"] == [] and d["motoristas"] == []


def test_rastro_descarta_ponto_sem_coordenada():
    linhas = rastro.coletar(date(2026, 7, 15), cliente=ClienteFalso(RESP_POS))
    assert len(linhas[0]["pontos"]) == 2


def test_rastro_aceita_ponto_sem_velocidade():
    linhas = rastro.coletar(date(2026, 7, 15), cliente=ClienteFalso(RESP_POS))
    assert linhas[0]["pontos"][1]["velocidade"] is None


def test_rastro_de_uma_placa_usa_o_caminho_especifico():
    c = ClienteFalso(RESP_POS)
    rastro.coletar(date(2026, 7, 15), placa="GBX1234", cliente=c)
    assert c.chamadas[0][0].endswith("/positions/GBX1234")


def test_rastro_da_frota_usa_o_caminho_geral():
    c = ClienteFalso(RESP_POS)
    rastro.coletar(date(2026, 7, 15), cliente=c)
    assert c.chamadas[0][0].endswith("/positions")


def test_rastro_pede_o_dia_inteiro():
    c = ClienteFalso(RESP_POS)
    rastro.coletar(date(2026, 7, 15), cliente=c)
    params = c.chamadas[0][1]
    assert params["startDate"] == "2026-07-15 00:00:00"
    assert params["endDate"] == "2026-07-15 23:59:59"
