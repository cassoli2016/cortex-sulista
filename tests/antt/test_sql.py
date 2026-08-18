"""Guardas do SQL do piso: PG 9.3, LATIN-1 e a fonte canônica correta."""
from __future__ import annotations

from api.antt.sql import PISO_VIAGENS_SQL


def test_sem_recursos_ausentes_no_pg93():
    assert "FILTER (WHERE" not in PISO_VIAGENS_SQL.upper()


def test_somente_latin1():
    PISO_VIAGENS_SQL.encode("latin-1")


def test_usa_a_fonte_canonica_do_frete_de_compra():
    s = PISO_VIAGENS_SQL
    assert "programacaoembarque" in s
    assert "p.semaforo = 1" in s
    assert "p.dtcancelamento IS NULL" in s
    assert "v.utilizacaoveiculo IN ('AGR','TER')" in s


def test_traz_os_campos_que_o_piso_precisa():
    s = PISO_VIAGENS_SQL
    for campo in ("kmfretecompra", "valorfretecompra", "veic_tipo",
                  "veic_carroceria", "veic_bitrem", "veic_tipocarga"):
        assert campo in s


def test_marca_deslocamento_vazio_pelo_tipo_3():
    assert "(p.tipo = 3)" in PISO_VIAGENS_SQL


def test_aceita_os_filtros_da_tela():
    for p in ("%(dt_de)s", "%(dt_ate)s", "%(filial)s", "%(modalidade)s",
              "%(transportador)s"):
        assert p in PISO_VIAGENS_SQL


def test_exclui_manifesto_fora_da_faixa_como_a_tela_agregados():
    # mesma guarda de _agr_base: numero < 1000000 descarta lançamentos técnicos
    assert "p.numero < 1000000" in PISO_VIAGENS_SQL
