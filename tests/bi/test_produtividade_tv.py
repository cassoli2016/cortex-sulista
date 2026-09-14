# -*- coding: utf-8 -*-
"""O que a produtividade passou a entregar para o painel de TV `tvprod`.

Duas mudanças no servidor, as duas por causa da TV (13/09/2026):

* o veículo das listas (os mais produtivos e os parados) ganha o NÚMERO DE
  FROTA pela régua da casa (`frota_identidade`), porque a parede chama o
  veículo pela frota, não pela placa;
* a consulta ganhou CACHE: eram 7 consultas ao ERP a cada chamada, e a TV
  recarrega de minuto em minuto.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from api import auth, copiloto, queries


@pytest.fixture(autouse=True)
def cache_limpo():
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


def _banco(monkeypatch, veiculos, parados):
    execucoes = []

    class Cur:
        def __init__(self):
            self.sql = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.sql = sql
            execucoes.append(sql)

        def fetchone(self):
            if self.sql == queries.PROD_KPI_SQL:
                return {"veiculos": 2, "viagens": 10, "dias_com_viagem": 5,
                        "km_carregado": 1000.0, "km_vazio": 100.0, "receita": 5000.0}
            if self.sql == queries.PROD_FROTA_SQL:
                return {"n": 3}
            return {"ts": datetime(2026, 9, 13, 20, 0)}

        def fetchall(self):
            if self.sql == queries.PROD_VEIC_SQL:
                return [dict(v) for v in veiculos]
            if self.sql == queries.PROD_PARADOS_SQL:
                return [dict(p) for p in parados]
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return Cur()

    monkeypatch.setattr(queries.db, "get_conn", lambda: Conn())
    return execucoes


def _veic(placa, frota):
    return {"placa": placa, "modalidade": "FROTA", "tipo": "CAVALO", "viagens": 3,
            "dias_ativos": 2, "km_carregado": 500.0, "km_vazio": 50.0,
            "receita": 1000.0, "ultima_viagem": date(2026, 9, 12), "numerofrota": frota}


def _parado(placa, frota, viagens=5):
    return {"placa": placa, "modalidade": "LOCACAO", "tipo": "CAVALO",
            "numerofrota": frota, "ultima_viagem": date(2026, 5, 1),
            "viagens_historicas": viagens, "dias_parado": 135}


def test_as_listas_trazem_o_numero_de_frota_pela_regua_da_casa(monkeypatch):
    _banco(monkeypatch,
           [_veic("AAA1A11", "582"), _veic("BBB2B22", "BBB2B22")],   # placa copiada
           [_parado("CCC3C33", "700"), _parado("DDD4D44", None)])
    d = queries.get_produtividade_veiculos(None, "2026-08-15", "2026-09-13")
    assert [(v["frota"], v["rotulo"]) for v in d["veiculos"]] == [
        ("582", "582 · AAA1A11"), (None, "BBB2B22")]
    assert [(v["frota"], v["rotulo"]) for v in d["ociosos"]] == [
        ("700", "700 · CCC3C33"), (None, "DDD4D44")]
    assert all("numerofrota" not in v for v in d["veiculos"] + d["ociosos"])


def test_a_segunda_chamada_nao_volta_ao_erp(monkeypatch):
    execs = _banco(monkeypatch, [_veic("AAA1A11", "1")], [])
    queries.get_produtividade_veiculos(None, "2026-08-15", "2026-09-13")
    n = len(execs)
    queries.get_produtividade_veiculos(None, "2026-08-15", "2026-09-13")
    assert len(execs) == n, "a TV recarrega de minuto em minuto: 7 consultas por vez"


def test_a_tela_de_tv_esta_registrada_no_rbac_e_no_copiloto():
    assert "tvprod" in auth.TELAS
    rota = dict(auth.ROTA_TELAS)["/api/bi/produtividade-veiculos"]
    assert {"prodveic", "tvprod"} <= set(rota)
    modelos = {nome: telas for nome, _d, telas in auth._PERFIS_MODELO}
    assert "tvprod" in modelos["Painéis TV"]
    telas, _abas = copiloto.FONTE_TELAS["produtividade_veiculos"]
    assert "tvprod" in telas
