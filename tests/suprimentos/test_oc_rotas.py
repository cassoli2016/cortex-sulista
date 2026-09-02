"""As três rotas de Suprimentos: recusa legível é 4xx, 5xx só para falha nossa.

O Cloudflare TROCA o corpo de 5xx pela página dele — uma data inválida que
caísse no `except Exception` genérico viraria "erro 500" sem pista. Chamadas
diretas às funções (o middleware devolveria 401 sem sessão).
"""
from __future__ import annotations

import json

import psycopg
import pytest

from api import main, queries


def _corpo(r):
    return json.loads(r.body)


@pytest.mark.parametrize("kw", [
    {"dt_de": "2026-13-40"}, {"dt_ate": "ontem"}, {"status": "entregue"},
])
def test_ordens_compra_recusa_parametro_invalido_com_422(kw):
    r = main.ordens_compra(**kw)
    assert r.status_code == 422
    c = _corpo(r)
    assert c["erro"] == "parametro_invalido" and c["mensagem"]


def test_ordens_compra_inverte_datas_trocadas(monkeypatch):
    visto = {}

    def falso(filial, dt_de, dt_ate, **k):
        visto.update(de=dt_de, ate=dt_ate, **k)
        return {"ok": 1}
    monkeypatch.setattr(queries, "get_ordens_compra", falso)
    r = main.ordens_compra(dt_de="2026-08-31", dt_ate="2026-06-01", fornecedor="  forn  ", status="atrasada")
    assert r.status_code == 200
    assert visto["de"] == "2026-06-01" and visto["ate"] == "2026-08-31"
    assert visto["fornecedor"] == "forn" and visto["status"] == "atrasada"


@pytest.mark.parametrize("dias_min", [-1, 3001])
def test_pendentes_recusa_dias_min_fora_do_intervalo(dias_min):
    r = main.oc_pendentes(dias_min=dias_min)
    assert r.status_code == 422


def test_pendentes_padrao_e_o_limiar_de_parada(monkeypatch):
    visto = {}
    monkeypatch.setattr(queries, "get_oc_pendentes", lambda dias_min: visto.update(d=dias_min) or {})
    assert main.oc_pendentes().status_code == 200
    assert visto["d"] == 30


@pytest.mark.parametrize("kw", [{"dt_de": "2026-02-30"}, {"dt_ate": "x"}, {"origem": "TALVEZ"}])
def test_custos_recusa_parametro_invalido_com_422(kw):
    r = main.suprimentos_custos(**kw)
    assert r.status_code == 422
    assert _corpo(r)["erro"] == "parametro_invalido"


def test_custos_inverte_datas_e_normaliza_filtros(monkeypatch):
    visto = {}

    def falso(de, ate, origem=None, filial=None):
        visto.update(de=de, ate=ate, origem=origem, filial=filial)
        return {}
    monkeypatch.setattr(queries, "get_custos", falso)
    r = main.suprimentos_custos("2026-08-31", "2026-08-01", origem=" sem nf ", filial=" 1 - FIL  MTZ ")
    assert r.status_code == 200
    assert visto["de"] == "2026-08-01" and visto["ate"] == "2026-08-31"
    assert visto["origem"] == "sem nf" and visto["filial"] == "1 - FIL  MTZ"


@pytest.mark.parametrize("chamar, alvo", [
    (lambda: main.ordens_compra(), "get_ordens_compra"),
    (lambda: main.oc_pendentes(), "get_oc_pendentes"),
    (lambda: main.suprimentos_custos(), "get_custos"),
])
def test_banco_fora_e_503_e_falha_nossa_e_500_em_json(monkeypatch, chamar, alvo):
    def fora(*a, **k):
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(queries, alvo, fora)
    r = chamar()
    assert r.status_code == 503 and _corpo(r)["erro"] == "banco_inacessivel"

    def bug(*a, **k):
        raise KeyError("coluna_que_nao_existe")
    monkeypatch.setattr(queries, alvo, bug)
    r = chamar()
    assert r.status_code == 500
    c = _corpo(r)
    assert c["erro"] == "erro_consulta" and c["mensagem"]
    assert "coluna_que_nao_existe" not in json.dumps(c)     # nunca str(exc) cru
