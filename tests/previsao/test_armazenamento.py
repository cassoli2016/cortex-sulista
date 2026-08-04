"""Persistência de ajustes manuais e snapshots — SQLite isolado em tmp_path."""
from __future__ import annotations

import pytest

from api.previsao import armazenamento as arm


def test_ajuste_crud(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    arm.salvar_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL", "delta", -120000.0,
                           "rescisao prevista", "cristian")
    aj = arm.ler_ajustes_prev(db, "2026-08")
    assert aj["CUSTO VARIAVEL"]["tipo"] == "delta"
    assert aj["CUSTO VARIAVEL"]["valor"] == -120000.0
    assert aj["CUSTO VARIAVEL"]["motivo"] == "rescisao prevista"
    # sobrescrever a mesma (mes, linha) substitui, nao duplica
    arm.salvar_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL", "valor", -900000.0,
                           "valor fechado com o RH", "cristian")
    aj = arm.ler_ajustes_prev(db, "2026-08")
    assert len(aj) == 1 and aj["CUSTO VARIAVEL"]["tipo"] == "valor"
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL") is True
    assert arm.ler_ajustes_prev(db, "2026-08") == {}
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO VARIAVEL") is False


def test_ajuste_valida_tipo_e_motivo(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    with pytest.raises(ValueError):
        arm.salvar_ajuste_prev(db, "2026-08", "RECEITA BRUTA", "percentual", 1.0, "x", "a")
    with pytest.raises(ValueError):
        arm.salvar_ajuste_prev(db, "2026-08", "RECEITA BRUTA", "delta", 1.0, "  ", "a")


def test_snapshot_upsert_e_leitura(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    linhas = [{"linha": "RESULTADO DO EXERCICIO", "previsto_base": 100.0,
               "previsto_otim": 150.0, "previsto_pess": 50.0,
               "realizado_contabil": 40.0, "estrategia": "cascata"}]
    arm.gravar_snapshot(db, "2026-08-02", "2026-08", linhas)
    # regravar o MESMO dia substitui (idempotente por dia)
    linhas[0]["previsto_base"] = 110.0
    arm.gravar_snapshot(db, "2026-08-02", "2026-08", linhas)
    snaps = arm.ler_snapshots(db, "2026-08")
    assert len(snaps) == 1
    assert snaps[0]["previsto_base"] == 110.0
    assert snaps[0]["data"] == "2026-08-02"


def test_init_db_idempotente(tmp_path):
    db = tmp_path / "previsao.db"
    arm.init_db(db)
    arm.init_db(db)  # nao explode nem apaga
    arm.registrar_log(db, "cristian", "teste", "detalhe")
