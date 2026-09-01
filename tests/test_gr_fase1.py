# -*- coding: utf-8 -*-
"""Gerenciamento de Risco — Fase 1 (v0.204.0)."""
from __future__ import annotations

from api.rasterintegra import servico


def _stub(monkeypatch, fontes):
    class _Cur:
        def __init__(self):
            self._i = 0

        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            if "rastreadora_retorno" in self._sql:
                return fontes
            return []

        def fetchone(self):
            import datetime as dt
            return {"ts": dt.datetime(2026, 9, 1, 12, 0)}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(servico.db, "get_conn", lambda: _Conn())
    from api import queries as q
    q._RESP_CACHE.clear()


def test_fonte_muda_dispara_o_alarme_e_a_viva_nao(monkeypatch):
    """O alarme é NÃO ESTÁ CHEGANDO AGORA: 90 min sem retorno numa fonte
    que entrega a cada minuto é fluxo parado — nunca contagem de tropeços."""
    _stub(monkeypatch, [
        {"fonte": "Raster", "n_6h": 300, "n_1h": 60,
         "ultima": "2026-09-01 11:59", "minutos_atras": 1.0},
        {"fonte": "OnixSat", "n_6h": 120, "n_1h": 0,
         "ultima": "2026-09-01 10:30", "minutos_atras": 90.0},
    ])
    d = servico.get_gr()
    por = {f["fonte"]: f for f in d["fluxo"]["fontes"]}
    assert por["Raster"]["mudo"] is False
    assert por["OnixSat"]["mudo"] is True
    assert d["fluxo"]["alarme"] is True


def test_sem_fonte_nenhuma_nao_estoura_e_nao_alarma_no_vazio(monkeypatch):
    _stub(monkeypatch, [])
    d = servico.get_gr()
    assert d["fluxo"]["fontes"] == []
    assert d["fluxo"]["alarme"] is False   # o VAZIO aparece na tela, dito
    assert d["cobertura"]["viagens"] == 0


def test_vinculo_gr_e_por_exists_nunca_join():
    """A tabela de vínculo tem `sequencia` (pode haver mais de uma linha por
    viagem) — um JOIN inflaria a contagem; o EXISTS é a regra."""
    assert "EXISTS" in servico.COBERTURA_SQL
    assert "NOT EXISTS" in servico.SEM_GR_SQL
    assert "JOIN programacaoembarque_gerenciadorarisco" not in servico.COBERTURA_SQL
