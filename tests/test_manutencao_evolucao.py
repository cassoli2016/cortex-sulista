# -*- coding: utf-8 -*-
"""A evolução da Manutenção (v0.201.0): objetivo decodificado, oficinas com
taxa de retorno, reincidência <30d e custo/km — regras montadas em Python
sobre as linhas do banco, testáveis com dublê na ORDEM DE GRANDEZA real
(OS de R$ 1.700, não de R$ 17)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import queries


def _stub(monkeypatch, respostas):
    class _Cur:
        def __init__(self, filas):
            self.filas = list(filas)

        def execute(self, sql, params=None):
            self._atual = self.filas.pop(0) if self.filas else []

        def fetchone(self):
            r = self._atual
            return r[0] if isinstance(r, list) and r else r

        def fetchall(self):
            return self._atual if isinstance(self._atual, list) else []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def __init__(self, filas):
            self.filas = filas

        def cursor(self):
            return _Cur(self.filas)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(queries.db, "get_conn", lambda: _Conn(respostas))
    queries._RESP_CACHE.clear()


DT_DE = "2025-09-01"
DT_ATE = "2026-08-31"


def _respostas(defeito_rows=None, oficinas=None):
    kpis = {"ordens": 3540, "oss_com_pecas": 160, "oss_com_maoobra": 0,
            "custo": 6027508.0, "pecas": 270000.0, "maoobra": 0.0,
            "abertas": 25, "abertas_valor": 66491.0, "abertas_antigas": 1,
            "veiculos": 437, "valor_prev": 1913593.0, "valor_corr": 3689950.0,
            "valor_sinistro": 156484.0, "valor_outros": 267482.0}
    veiculos = [{"placa": "JOK3045", "utilizacao": "IMPLEMENTO", "ordens": 40,
                 "custo": 95600.0, "pecas": 0.0, "maoobra": 0.0, "abertas": 0,
                 "corr_valor": 90000.0, "motor": 0, "ano": 2007},
                {"placa": "BBX3411", "utilizacao": "IMPLEMENTO", "ordens": 12,
                 "custo": 30000.0, "pecas": 0.0, "maoobra": 0.0, "abertas": 0,
                 "corr_valor": 10000.0, "motor": 0, "ano": 2018}]
    km_carreta = [{"placa": "JOK3045", "km": 4858.0},
                  {"placa": "BBX3411", "km": 54000.0}]
    return [
        [kpis],                                    # MAN_KPI
        veiculos,                                  # MAN_VEIC
        [],                                        # MAN_DET
        km_carreta,                                # MAN_KM_CARRETA (sem trações)
        [],                                        # MAN_MENSAL
        oficinas if oficinas is not None else [],  # MAN_OFICINA
        defeito_rows if defeito_rows is not None else [],  # MAN_DEFEITO
        [],                                        # MAN_TEMPO
        [{"ts": __import__("datetime").datetime(2026, 9, 1, 10, 0)}],
    ]


def test_pct_corretiva_exclui_o_sinistro_dos_dois_lados(monkeypatch):
    """Sinistro não é manutenção: R$ 156 mil/12m que poluía o custo."""
    _stub(monkeypatch, _respostas())
    d = queries.get_manutencao(None, DT_DE, DT_ATE)
    k = d["kpis"]
    esperado = 100.0 * 3689950.0 / (1913593.0 + 3689950.0 + 267482.0)
    assert k["pct_corretiva"] == pytest.approx(esperado)


def test_rs_km_exige_km_minimo_no_recorte(monkeypatch):
    """4.858 km dá razão; 900 km daria R$ 100/km de artefato — n/d."""
    resp = _respostas()
    resp[3] = [{"placa": "JOK3045", "km": 4858.0},
               {"placa": "BBX3411", "km": 900.0}]
    _stub(monkeypatch, resp)
    d = queries.get_manutencao(None, DT_DE, DT_ATE)
    por = {v["placa"]: v for v in d["veiculos"]}
    assert por["JOK3045"]["rs_km"] == pytest.approx(95600.0 / 4858.0)
    assert por["BBX3411"]["rs_km"] is None


def test_reincidencia_e_par_do_mesmo_veiculo_e_defeito_em_menos_de_30d(monkeypatch):
    d1 = date(2026, 3, 1)
    rows = [
        {"descricao": "INSPECIONAR SIST ELETRICO", "veiculo": "AAA1111",
         "numero": 10, "dt": d1, "dt_ant": None, "num_ant": None,
         "valor": 1700.0, "oficina_ant": None},
        {"descricao": "INSPECIONAR SIST ELETRICO", "veiculo": "AAA1111",
         "numero": 11, "dt": d1 + timedelta(days=15), "dt_ant": d1,
         "num_ant": 10, "valor": 2500.0, "oficina_ant": "ELETRODIESEL"},
        # 45 dias: NÃO é retorno
        {"descricao": "INSPECIONAR FREIOS", "veiculo": "BBB2222",
         "numero": 20, "dt": d1 + timedelta(days=45), "dt_ant": d1,
         "num_ant": 19, "valor": 900.0, "oficina_ant": "VJM"},
    ]
    oficinas = [{"oficina": "ELETRODIESEL", "oss": 225, "veiculos": 112,
                 "valor": 124893.0, "valor_prev": 0.0, "valor_corr": 124893.0}]
    _stub(monkeypatch, _respostas(defeito_rows=rows, oficinas=oficinas))
    d = queries.get_manutencao(None, DT_DE, DT_ATE)
    assert d["kpis"]["reinc_pares"] == 1
    assert d["kpis"]["reinc_valor"] == 2500.0        # a OS de RETORNO, paga 2x
    assert d["reincidencias"][0]["placa"] == "AAA1111"
    of = d["oficinas"][0]
    assert of["retornos"] == 1                       # atribuído à 1ª oficina
    assert of["taxa_retorno"] == pytest.approx(100.0 / 225)


def test_oficina_pequena_nao_ganha_taxa(monkeypatch):
    """Taxa sem piso de amostra mente — menos de 100 OSs vira None."""
    oficinas = [{"oficina": "H S FURGOES", "oss": 5, "veiculos": 5,
                 "valor": 146445.0, "valor_prev": 0.0, "valor_corr": 0.0}]
    _stub(monkeypatch, _respostas(oficinas=oficinas))
    d = queries.get_manutencao(None, DT_DE, DT_ATE)
    assert d["oficinas"][0]["taxa_retorno"] is None


def test_linha_da_janela_alargada_nao_conta_no_pareto(monkeypatch):
    """A query alarga 30 dias para trás só para o lag ter contexto — a linha
    de fora do recorte não pode virar volume."""
    fora = {"descricao": "X", "veiculo": "CCC3333", "numero": 5,
            "dt": date(2025, 8, 20), "dt_ant": None, "num_ant": None,
            "valor": 100.0, "oficina_ant": None}
    _stub(monkeypatch, _respostas(defeito_rows=[fora]))
    d = queries.get_manutencao(None, DT_DE, DT_ATE)
    assert d["defeitos"] == []


def test_custo_idade_agrupa_por_faixa_com_km(monkeypatch):
    _stub(monkeypatch, _respostas())
    d = queries.get_manutencao(None, DT_DE, DT_ATE)
    faixas = {c["faixa"]: c for c in d["custo_idade"]}
    # JOK3045 (2007 → 19 anos) na 16+; BBX3411 (2018 → 8 anos) na 6-10
    assert faixas["16+ anos"]["veiculos"] == 1
    assert faixas["16+ anos"]["rs_km"] == pytest.approx(95600.0 / 4858.0)
    assert faixas["6-10 anos"]["rs_km"] == pytest.approx(30000.0 / 54000.0)
