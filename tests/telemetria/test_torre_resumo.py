# -*- coding: utf-8 -*-
"""O agregado de telemetria da Torre não pode ser envenenado por leitura furada.

Medido em produção (02/09/2026): 14 de 105 veículos traziam leitura impossível
— uma delas com 66.762 LITROS num mês (tanque de caminhão tem 400 a 600) e
outra com 50.796 km em dois dias. Somando tudo, o km/l da frota dava 0,71 e o
painel de TV o pintava de vermelho contra o alvo de 2,5, enquanto o cartão ao
lado dizia que 91 veículos tinham leitura válida e só 26 estavam abaixo do
alvo: o número principal contradizia o próprio subtítulo.
"""
from __future__ import annotations
from api.gobrax import torre


def _linha(placa, km, litros, km_l, vel=60.0):
    return {"placa": placa, "km": km, "litros": litros, "km_l": km_l,
            "vel_media": vel, "freadas": 10, "freadas_alta": 1, "odometro": 1}


def _resumo(monkeypatch, linhas):
    monkeypatch.setattr(torre.arm, "competencia_atual",
                        lambda _t: {"competencia": "2026-09", "quando": "2026-09-02 14:30:14"})
    monkeypatch.setattr(torre.arm, "ler", lambda _t, _c: linhas)
    return torre.resumo()


def test_leitura_furada_nao_entra_no_km_l_da_frota(monkeypatch):
    bons = [_linha(f"AAA{i}A11", 1000.0, 320.0, 3.12) for i in range(9)]
    # 50.796 km para 66.762 litros dá 0,76 km/l — e a régua da casa
    # (consumo.KM_L_MIN/MAX, 0,5 a 15,0) ACEITA esse valor. O que o ERP grava
    # nas linhas realmente furadas é pior: 0,11 aqui, fora da faixa por baixo.
    furado = _linha("ZZZ9Z99", 50796.0, 66762.0, 0.11)
    r = _resumo(monkeypatch, bons + [furado])

    assert r["disponivel"] is True
    assert r["com_consumo_valido"] == 9
    assert r["leitura_suspeita"] == 1
    # 9000 km / 2880 l = 3,12 — a linha furada não entra
    assert r["km_l_frota"] == 3.12
    # e o bruto continua visível, para se saber quanto foi descartado
    assert r["km_total"] == 9000.0 and r["km_total_bruto"] == 59796.0
    assert r["litros_total"] == 2880.0 and r["litros_total_bruto"] == 69642.0


def test_agregado_impossivel_vira_n_d_em_vez_de_vermelho(monkeypatch):
    """Cinto e suspensório: se TODAS as leituras forem furadas, não sobra
    régua — e número impossível some da tela, não é pintado de vermelho."""
    r = _resumo(monkeypatch, [_linha("ZZZ9Z99", 100.0, 900.0, 0.11)])
    assert r["km_l_frota"] is None
    assert r["com_consumo_valido"] == 0 and r["leitura_suspeita"] == 1


def test_velocidade_impossivel_nao_sobe_a_media(monkeypatch):
    """A coleta trouxe uma linha com 5.210 km/h; sozinha ela levava a média da
    frota de 44 para 101,8 km/h."""
    bons = [_linha(f"AAA{i}A11", 1000.0, 320.0, 3.12, vel=44.0) for i in range(9)]
    r = _resumo(monkeypatch, bons + [_linha("ZZZ9Z99", 1000.0, 320.0, 3.12, vel=5210.0)])
    assert r["vel_media"] == 44.0
    assert r["vel_fora_da_faixa"] == 1


def test_freada_por_mil_km_usa_o_km_saneado(monkeypatch):
    """Um veículo com 50 mil km espúrios diluía a taxa da frota inteira."""
    bons = [_linha(f"AAA{i}A11", 1000.0, 320.0, 3.12) for i in range(9)]
    r = _resumo(monkeypatch, bons + [_linha("ZZZ9Z99", 50000.0, 60000.0, 0.11)])
    # 9 linhas boas × 1 freada alta = 9, sobre 9.000 km = 1,0 por mil km
    assert r["freadas_alta_por_mil_km"] == 1.0


def test_sem_coleta_nao_levanta(monkeypatch):
    monkeypatch.setattr(torre.arm, "competencia_atual", lambda _t: None)
    monkeypatch.setattr(torre.arm, "ler", lambda _t, _c: [])
    r = torre.resumo()
    assert r["disponivel"] is False and "motivo" in r
