"""Testes da montagem do SQL e da janela de meses fechados."""
from __future__ import annotations

from datetime import date

from api.orcamento.sql import (AGRUP_CONTA_SQL, HIST_CONTA_SQL, REAL_CONTA_SQL,
                               meses_fechados)


def test_mes_corrente_nunca_entra_na_base():
    # em 26/07/2026 a base termina em junho: julho está pela metade
    ms = meses_fechados(date(2026, 7, 26), 12)
    assert ms[-1] == "2026-06"
    assert "2026-07" not in ms
    assert len(ms) == 12
    assert ms[0] == "2025-07"


def test_janela_atravessa_a_virada_do_ano():
    ms = meses_fechados(date(2026, 1, 15), 12)
    assert ms[-1] == "2025-12"
    assert ms[0] == "2025-01"


def test_primeiro_dia_do_mes_tambem_exclui_o_corrente():
    ms = meses_fechados(date(2026, 3, 1), 3)
    assert ms == ["2025-12", "2026-01", "2026-02"]


def test_sql_nao_usa_recursos_ausentes_no_postgres_93():
    for sql in (HIST_CONTA_SQL, REAL_CONTA_SQL, AGRUP_CONTA_SQL):
        assert "FILTER (WHERE" not in sql.upper()
        assert "LATERAL" not in sql.upper()


def test_sql_trata_o_lado_nulo_do_lancamento():
    # valorcredito/valordebito vêm NULL no lado vazio: sem coalesce a linha some
    for sql in (HIST_CONTA_SQL, REAL_CONTA_SQL):
        assert "coalesce(l.valorcredito,0)" in sql
        assert "coalesce(l.valordebito,0)" in sql
        assert "coalesce(l.historico, 0) <> 18" in sql


def test_sql_usa_a_mesma_chave_de_conta_da_dre():
    for sql in (HIST_CONTA_SQL, REAL_CONTA_SQL, AGRUP_CONTA_SQL):
        assert "l.grupo::text || '|' || l.reduzido::text" in sql or \
               "ag.grupo::text || '|' || ag.reduzido::text" in sql
