# tests/previsao/test_sql.py
"""Guardas de compatibilidade do SQL (PG 9.3 / LATIN-1 / convencoes da DRE)."""
from __future__ import annotations

from datetime import date

from api.previsao.sql import (ATING_HIST_SQL, CAP_MES_SQL, COMPLETUDE_SQL,
                              CTAPLUS_MTD_SQL, RAZAO_ASOF_SQL, VFC_MTD_SQL,
                              meses_fechados_prev)

TODAS = (COMPLETUDE_SQL, RAZAO_ASOF_SQL, ATING_HIST_SQL, VFC_MTD_SQL,
         CTAPLUS_MTD_SQL, CAP_MES_SQL)


def test_sem_recursos_ausentes_no_pg93():
    for sql in TODAS:
        assert "FILTER (WHERE" not in sql.upper()
        assert "LATERAL" not in sql.upper()


def test_somente_latin1():
    for sql in TODAS:
        sql.encode("latin-1")  # explode se houver travessao/setas


def test_razao_trata_lado_nulo_e_historico_18():
    for sql in (COMPLETUDE_SQL, RAZAO_ASOF_SQL):
        assert "coalesce(l.valorcredito,0)" in sql
        assert "coalesce(l.valordebito,0)" in sql
        assert "coalesce(l.historico, 0) <> 18" in sql


def test_asof_filtra_por_dtinc():
    assert "l.dtinc <= %(asof)s::date" in RAZAO_ASOF_SQL


def test_filtros_fiscais_canonicos_no_atingimento():
    assert "situacaocte = 3" in ATING_HIST_SQL
    assert "tipo IN (1,4)" in ATING_HIST_SQL
    assert "numero < 1000000" in ATING_HIST_SQL
    assert "tipo = 1" in ATING_HIST_SQL  # meta


def test_viagens_com_filtros_canonicos():
    assert "dtcancelamento IS NULL" in VFC_MTD_SQL
    assert "semaforo = 1" in VFC_MTD_SQL


def test_ctaplus_placa_nao_casada_fora_do_proprio():
    # Convencao canonica (api/queries.py ~2002/2047): propria exige placa
    # casada no veiculo. Placa nao casada (v.placa IS NULL) NUNCA pode virar
    # "propria" por default - tem de ficar de fora do filtro NOT IN.
    assert "v.placa IS NOT NULL" in CTAPLUS_MTD_SQL
    assert "coalesce(v.utilizacaoveiculo, '') NOT IN ('AGR', 'TER')" in CTAPLUS_MTD_SQL


def test_meses_fechados_reexportado():
    assert meses_fechados_prev(date(2026, 8, 2), 6)[-1] == "2026-07"
