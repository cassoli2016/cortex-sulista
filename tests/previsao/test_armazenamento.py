"""Persistência de ajustes manuais e snapshots.

Migrado para o PostgreSQL local em 27/08/2026: onde havia um `.db` em
`tmp_path`, agora há um SCHEMA exclusivo do teste. Sem banco, pula dizendo por
quê — ver tests/conftest.py e docs/MIGRACAO_POSTGRES.md.
"""
from __future__ import annotations

import pytest

from api.previsao import armazenamento as arm


def test_ajuste_crud(esquema_pg):
    db = esquema_pg
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


def _log(esquema):
    """A trilha lida direto do banco, sem passar pelo módulo: o que se quer
    conferir é o que FOI GRAVADO, não o que a função diz ter gravado."""
    from api import pglocal
    return pglocal.query("SELECT autor, acao, detalhe FROM prev_log ORDER BY id",
                         esquema=esquema)


def test_remocao_registra_o_autor_na_auditoria(esquema_pg):
    """Em controladoria "quem removeu o ajuste manual" e' A pergunta da
    auditoria: o prev_log nao pode gravar autor NULL na remocao."""
    db = esquema_pg
    arm.salvar_ajuste_prev(db, "2026-08", "CUSTO FIXO", "delta", -1000.0,
                           "rescisao", "cristian")
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO FIXO", "marina") is True
    linhas = _log(db)
    assert [r["acao"] for r in linhas] == ["ajuste", "ajuste_removido"]
    assert linhas[0]["autor"] == "cristian"
    assert linhas[1]["autor"] == "marina"          # antes: None (anonimo)
    assert linhas[1]["detalhe"] == "2026-08 CUSTO FIXO"


def test_remocao_sem_autor_continua_valida_e_nao_loga_no_vazio(esquema_pg):
    """autor e' opcional (call sites antigos seguem validos) e a remocao que
    nao apagou nada nao pode deixar rastro de auditoria."""
    db = esquema_pg
    arm.salvar_ajuste_prev(db, "2026-08", "CUSTO FIXO", "delta", -1.0, "x", "c")
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO FIXO") is True
    assert arm.remover_ajuste_prev(db, "2026-08", "CUSTO FIXO", "marina") is False
    linhas = _log(db)
    assert [r["acao"] for r in linhas] == ["ajuste", "ajuste_removido"]
    assert linhas[1]["autor"] is None


def test_ajuste_valida_tipo_e_motivo(esquema_pg):
    db = esquema_pg
    with pytest.raises(ValueError):
        arm.salvar_ajuste_prev(db, "2026-08", "RECEITA BRUTA", "percentual", 1.0, "x", "a")
    with pytest.raises(ValueError):
        arm.salvar_ajuste_prev(db, "2026-08", "RECEITA BRUTA", "delta", 1.0, "  ", "a")


def test_snapshot_upsert_e_leitura(esquema_pg):
    db = esquema_pg
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


def test_init_db_idempotente(esquema_pg):
    db = esquema_pg
    arm.init_db(db)  # nao explode nem apaga
    arm.registrar_log(db, "cristian", "teste", "detalhe")
