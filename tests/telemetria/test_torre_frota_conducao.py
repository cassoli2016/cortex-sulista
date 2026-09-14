# -*- coding: utf-8 -*-
"""A telemetria da TV de operação é SÓ da frota rodando, com três
indicadores de condução (13/09/2026).

Quem opera pediu o km/l "somente dos veículos da frota que estão rodando" e
trocou três cartões que ninguém sabia ler (abaixo do alvo, leitura
descartada, carga sem veículo) por motor ligado parado, faixa extra-econômica
e pedal crítico — que já vinham na coleta diária de performance e eram
lidos só na premiação.

As linhas de dublê copiam o FORMATO do cache real: `performance` grava a
identificação como "PLACA - FROTA", e `estatisticas` grava só a placa. Foi
esse desencontro que fez 47 dos 49 veículos parecerem fora do ERP na primeira
medição.
"""
from __future__ import annotations

from api.gobrax import torre


def _est(placa, km, litros, km_l):
    return {"placa": placa, "km": km, "litros": litros, "km_l": km_l,
            "vel_media": 50.0, "freadas": 10, "freadas_alta": 1, "odometro": 1}


def _perf(ident, idle, mov, extra, alta, media, baixa):
    # formato real do cache: {"pct", "h", "nota"} por indicador
    f = lambda h: {"pct": None, "h": h, "nota": 0.0}  # noqa: E731
    return {"placa": ident, "motoristas": [],
            "idle": f(idle), "movement": f(mov), "extraEconomicRange": f(extra),
            "pedalPressureOnHig": f(alta), "pedalPressureOnMid": f(media),
            "pedalPressureOnLow": f(baixa)}


def _cache(monkeypatch, estatisticas, performance):
    dados = {"estatisticas": estatisticas, "performance": performance}
    monkeypatch.setattr(torre.arm, "competencia_atual",
                        lambda c: {"competencia": "2026-09",
                                   "quando": "2026-09-13 08:31:16"} if dados[c] else None)
    monkeypatch.setattr(torre.arm, "ler", lambda c, _comp: dados[c])


def test_placa_norm_iguala_as_duas_coletas():
    assert torre.placa_norm("AAA1A11 - FR1234") == "AAA1A11"
    assert torre.placa_norm(" aaa-1a11 ") == "AAA1A11"
    assert torre.placa_norm(None) == ""


def test_com_frota_o_consumo_e_so_da_frota_rodando(monkeypatch):
    _cache(monkeypatch, [
        _est("AAA1A11", 1000.0, 400.0, 2.5),     # frota
        _est("BBB2B22", 1000.0, 250.0, 4.0),     # frota
        _est("AGR0A00", 1000.0, 1000.0, 1.0),    # agregado: fica fora
        _est("CCC3C33", 0.0, 0.0, None),          # frota PARADA: fica fora
    ], [])
    r = torre.resumo(frota={"AAA1A11", "BBB2B22", "CCC3C33"})
    assert r["escopo"] == "frota"
    assert r["veiculos"] == 2
    # 2000 km / 650 l — o agregado de 1,0 km/l não puxa a frota para baixo
    assert r["km_l_frota"] == round(2000 / 650, 2)


def test_sem_frota_o_comportamento_antigo_continua(monkeypatch):
    _cache(monkeypatch, [_est("AAA1A11", 1000.0, 400.0, 2.5),
                         _est("AGR0A00", 1000.0, 1000.0, 1.0)], [])
    r = torre.resumo()
    assert r["escopo"] == "todos" and r["veiculos"] == 2


def test_frota_sem_ninguem_rodando_diz_isso(monkeypatch):
    _cache(monkeypatch, [_est("AGR0A00", 1000.0, 1000.0, 1.0)], [])
    r = torre.resumo(frota={"AAA1A11"})
    assert r["disponivel"] is False and "frota" in r["motivo"]


def test_conducao_e_razao_de_tempo_somada_e_nao_media_de_percentual(monkeypatch):
    """Dois veículos: um com 10 de motor (5 parado = 50%) e outro com 190
    (19 parado = 10%). A média dos percentuais daria 30%; a frota ficou
    parada 24 de 200 = 12%. O de 10 não pode pesar igual ao de 190."""
    _cache(monkeypatch, [], [
        _perf("AAA1A11 - FR1", idle=5, mov=5, extra=4, alta=1, media=1, baixa=8),
        _perf("BBB2B22 - FR2", idle=19, mov=171, extra=150, alta=9, media=10, baixa=81),
    ])
    c = torre.conducao(frota={"AAA1A11", "BBB2B22"})
    assert c["motor_parado_pct"] == 12.0
    # extra-econômica é do tempo ANDANDO: 154 de 176
    assert c["faixa_extra_eco_pct"] == round(100 * 154 / 176, 1)
    # pedal crítico é pressão alta sobre as três: 10 de 110 -- com DUAS
    # casas (14/09/2026: com uma, 14,29 e 14,34 viravam o mesmo 14,3)
    assert c["pedal_critico_pct"] == 9.09
    assert c["faixa_extra_eco_pct"] == 87.5      # esta segue com uma casa
    assert c["conducao_veiculos"] == 2


def test_conducao_filtra_a_frota_pela_placa_antes_do_traco(monkeypatch):
    _cache(monkeypatch, [], [
        _perf("AAA1A11 - FR1", idle=10, mov=90, extra=80, alta=1, media=1, baixa=8),
        _perf("AGR0A00", idle=90, mov=10, extra=0, alta=9, media=0, baixa=1),
    ])
    c = torre.conducao(frota={"AAA1A11"})
    assert c["motor_parado_pct"] == 10.0 and c["conducao_veiculos"] == 1


def test_sem_coleta_de_performance_os_indicadores_sao_nulos(monkeypatch):
    """Nulo, e não zero: zero afirmaria motor nunca parado."""
    _cache(monkeypatch, [_est("AAA1A11", 1000.0, 400.0, 2.5)], [])
    r = torre.resumo(frota={"AAA1A11"})
    assert r["disponivel"] is True
    assert r["motor_parado_pct"] is None and r["pedal_critico_pct"] is None
    assert r["conducao_veiculos"] == 0
