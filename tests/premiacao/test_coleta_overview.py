"""A coleta passa a vir do driversOverview, não do login Kratos."""
from __future__ import annotations

from datetime import datetime

import pytest

from api.premiacao import coleta

LINHAS = [{"driverId": 13, "driverName": "JEAN", "km": 5200.0, "nota": 99.0},
          {"driverId": 14, "driverName": "AGNALDO", "km": 2840.0, "nota": 81.0}]


def test_snapshot_registra_a_fonte_e_a_regra():
    snap = coleta.coletar_mes("2026-04", coletor=lambda mes, cliente=None: LINHAS,
                              agora=datetime(2026, 5, 2, 10, 0))
    assert snap["source"] == "gobrax-api-overview"
    assert snap["regra_fonte"] == "nota_km"
    assert len(snap["drivers"]) == 2


def test_mes_corrente_e_marcado_como_parcial():
    snap = coleta.coletar_mes("2026-05", coletor=lambda mes, cliente=None: LINHAS,
                              agora=datetime(2026, 5, 15, 10, 0))
    assert snap["parcial"] is True


def test_mes_fechado_nao_e_parcial():
    snap = coleta.coletar_mes("2026-04", coletor=lambda mes, cliente=None: LINHAS,
                              agora=datetime(2026, 5, 2, 10, 0))
    assert snap["parcial"] is False


def test_coleta_vazia_levanta_erro_em_vez_de_gravar_nada():
    """A regra que já custou um mês de dados: coleta vazia não pode virar
    snapshot, senão sobrescreve o mês bom com zero."""
    with pytest.raises(coleta.ColetaVazia):
        coleta.coletar_mes("2026-04", coletor=lambda mes, cliente=None: [],
                           agora=datetime(2026, 5, 2, 10, 0))
