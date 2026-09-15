# -*- coding: utf-8 -*-
"""O quadrante de manutenção da TV de operação (15/09/2026).

Quem opera trocou a telemetria do quadrante superior direito por manutenção:
revisões vencidas e a vencer, parados em manutenção — cavalo e semirreboque
sempre separados. As consultas rodam contra um cursor falso: o que se testa
aqui é a montagem do payload. As SQL foram executadas contra o ERP real
antes da entrega.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from api import queries


class _Hoje(date):
    """31 de MARÇO: o mês anterior (fevereiro) é mais curto, e a janela
    equivalente tem de parar no último dia dele."""

    @classmethod
    def today(cls):
        return cls(2026, 3, 31)


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(queries, "date", _Hoje)
    monkeypatch.setattr(queries, "get_manutencao_preventiva", lambda *a, **k: PREV)
    yield
    queries._RESP_CACHE.clear()


PREV = {"kpis": {"tracoes_vencidas": 1, "tracoes_proximas": 3, "tracoes_avaliadas": 66,
                 "carretas_vencidas": 2, "carretas_proximas": 12, "carretas_avaliadas": 175},
        "horizonte": 30,
        "tracoes": [{"frota": "C901", "veiculo": "AAA1A11", "status": "vencida", "km_faltante": -557},
                    {"frota": "C902", "veiculo": "BBB2B22", "status": "proxima", "km_faltante": 2149}],
        "carretas": [{"frota": None, "veiculo": "SSS9S99", "status": "vencida", "dias": -15},
                     {"frota": "S903", "veiculo": "TTT9T99", "status": "proxima", "dias": 11}]}


def _v(placa, motor, em_viagem=0, os_abertas=0, desde=None):
    return {"placa": placa, "utilizacao": "FROTA", "com_motor": motor, "ult_saida": None,
            "em_viagem": em_viagem, "os_abertas": os_abertas, "os_desde": desde}


# hoje = 31/03/2026
VEIC = [
    _v("CAV0001", True, os_abertas=1, desde=date(2026, 3, 20)),   # 11 dias: longa
    _v("CAV0002", True, os_abertas=2, desde=date(2026, 3, 24)),   # 7 dias: NÃO é "mais de 7"
    _v("CAV0003", True, em_viagem=1, os_abertas=1, desde=date(2026, 1, 5)),  # rodando
    _v("CAV0004", True),
    _v("SEM0001", False, os_abertas=1, desde=date(2026, 3, 30)),
    _v("SEM0002", False, os_abertas=1, desde=date(2026, 2, 1)),   # 58 dias: longa
    _v("SEM0003", False),
]
MES = {"preventivas": 26, "corretivas": 62, "socorro": 15}
ANT = {"preventivas": 30, "corretivas": 70, "socorro": 12}


def _banco(monkeypatch, respostas=None):
    respostas = dict(respostas or {})
    respostas.setdefault(queries.PROG_VEIC_DISP_SQL, VEIC)
    vistos: list = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.sql, self.p = sql, params
            vistos.append((sql, params))

        def _valor(self):
            if self.sql == queries.MANUT_TV_MES_SQL:
                return MES if self.p["de"] == queries.date.today().replace(day=1) else ANT
            if "current_timestamp AS ts" in self.sql:
                return {"ts": datetime(2026, 3, 31, 10, 0)}
            return respostas.get(self.sql)

        def fetchall(self):
            v = self._valor()
            return [dict(x) for x in v] if isinstance(v, list) else []

        def fetchone(self):
            v = self._valor()
            return dict(v) if isinstance(v, dict) else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return Cur()

    monkeypatch.setattr(queries.db, "get_conn", lambda: Conn())
    return vistos


def test_parado_e_oficina_longa_por_cavalo_e_semirreboque(monkeypatch):
    _banco(monkeypatch)
    of = queries.get_manutencao_tv()["oficina"]
    # com viagem aberta o veículo está rodando, mesmo com OS aberta
    assert of["cavalos"] == {"frota": 4, "parados": 2, "longa": 1}
    assert of["semirreboques"] == {"frota": 3, "parados": 2, "longa": 1}
    assert of["longa_dias"] == queries.OFICINA_LONGA_DIAS == 7


def test_o_mes_anterior_e_recortado_ate_o_mesmo_dia(monkeypatch):
    """31/03 contra fevereiro, que só tem 28: a janela para no dia 28. Mês
    inteiro de um lado e mês em curso do outro fariam todo começo de mês
    parecer melhora."""
    vistos = _banco(monkeypatch)
    d = queries.get_manutencao_tv()
    janelas = [(p["de"], p["ate"]) for sql, p in vistos if sql == queries.MANUT_TV_MES_SQL]
    assert janelas == [(date(2026, 3, 1), date(2026, 4, 1)),
                       (date(2026, 2, 1), date(2026, 3, 1))]
    objetivos = {(p["prev"], p["corr"], p["socorro"]) for sql, p in vistos
                 if sql == queries.MANUT_TV_MES_SQL}
    assert objetivos == {(14, 15, 16)}
    assert d["mes"] == {"preventivas": 26, "corretivas": 62, "socorro": 15,
                        "socorro_ant": 12, "dia": 31, "mes_ant": "2026-02"}


def test_no_meio_do_mes_o_anterior_para_no_mesmo_dia(monkeypatch):
    """O caso de 31/03 sozinho não prova a janela: lá o fevereiro recortado
    termina em 01/03, o mesmo lugar do mês INTEIRO, e trocar a regra pelo mês
    cheio passava verde (sabotado em 15/09/2026). No dia 15, o agosto
    comparável vai do dia 1 ao 15, e não até 31."""
    class _Dia15(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 15)
    monkeypatch.setattr(queries, "date", _Dia15)
    vistos = _banco(monkeypatch)
    d = queries.get_manutencao_tv()
    janelas = [(p["de"], p["ate"]) for sql, p in vistos if sql == queries.MANUT_TV_MES_SQL]
    assert janelas == [(date(2026, 9, 1), date(2026, 9, 16)),
                       (date(2026, 8, 1), date(2026, 8, 16))]
    assert (d["mes"]["dia"], d["mes"]["mes_ant"], d["mes"]["socorro_ant"]) == (15, "2026-08", 12)


def test_as_revisoes_vem_da_preventiva_com_as_vencidas_por_nome(monkeypatch):
    _banco(monkeypatch)
    r = queries.get_manutencao_tv()["revisoes"]
    assert r["cavalos"] == {"vencidas": 1, "a_vencer": 3, "avaliados": 66}
    assert r["semirreboques"] == {"vencidas": 2, "a_vencer": 12, "avaliados": 175}
    # o quanto JÁ PASSOU, positivo; sem número de frota, a placa
    assert r["vencidas"] == [{"frota": "C901", "km": 557}, {"frota": "SSS9S99", "dias": 15}]


def test_parado_em_manutencao_e_a_MESMA_conta_da_tracao_em_os(monkeypatch):
    """O cartão de tração (k1) e o de manutenção (k2) ficam na mesma parede:
    se as duas contas divergissem, a TV se contradiria sozinha."""
    _banco(monkeypatch, {
        queries.PROG_DIESEL_SQL: {"custo": 0.0},
        queries.PROG_KM_PROPRIO_SQL: {"km": 0.0},
        queries.PROG_MOT_DISP_SQL: [],
        queries.PROG_AGR_DISP_SQL: {"total": 0},
    })
    prog = queries.get_programacao()
    of = queries.get_manutencao_tv()["oficina"]
    assert of["cavalos"]["parados"] == prog["kpis"]["tracao_os"]
    assert of["cavalos"]["parados"] + of["semirreboques"]["parados"] == prog["kpis"]["frota_os"]
    # e a data da OS não vaza para o payload da programação
    assert "os_desde" not in json.dumps(prog, default=str)
