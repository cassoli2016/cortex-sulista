"""Guardas do SQL dos transportadores contratados."""
from __future__ import annotations

from api.antt.sql import RNTRC_TRANSPORTADORES_SQL as S


def test_sem_recursos_ausentes_no_pg93():
    assert "FILTER (WHERE" not in S.upper()


def test_somente_latin1():
    S.encode("latin-1")


def test_le_o_rntrc_do_proprio_cadastro():
    """A cobertura é de 100% em produção; não há por que descobrir o registro
    na base aberta."""
    assert "numerorntrc" in S
    assert "cadastro" in S


def test_usa_a_fonte_canonica_do_frete_de_compra():
    assert "programacaoembarque" in S
    assert "v.utilizacaoveiculo IN ('AGR','TER')" in S
    assert "p.semaforo = 1" in S


def test_classifica_pessoa_sem_expor_documento():
    """Só o COMPRIMENTO do documento sai do banco, para distinguir empresa de
    autônomo. O documento em si não é selecionado."""
    assert "length(regexp_replace" in S
    assert "AS pessoa" in S


def test_traz_valor_e_contagem_para_dimensionar_o_risco():
    for campo in ("viagens", "pago", "ultima_viagem"):
        assert campo in S
