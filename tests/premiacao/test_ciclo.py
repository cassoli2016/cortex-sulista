# -*- coding: utf-8 -*-
"""O ciclo 16→15 da premiação.

O ciclo NÃO é o mês do calendário (decisão de quem opera, 18/09/2026): uma
ocorrência do dia 16 em diante conta para o ciclo do mês seguinte. Errar isso
não dá erro nenhum — só move dinheiro de um mês para o outro, e ninguém
percebe até alguém conferir uma ocorrência específica.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.premiacao import ciclo


@pytest.mark.parametrize("dia, esperado", [
    ("2026-09-01", "2026-09"),   # começo do mês: ciclo do próprio mês
    ("2026-09-15", "2026-09"),   # o dia 15 ainda é o ciclo que fecha
    ("2026-09-16", "2026-10"),   # a virada
    ("2026-09-30", "2026-10"),
    ("2026-12-16", "2027-01"),   # dezembro vira janeiro do ano seguinte
    ("2026-01-15", "2026-01"),
])
def test_a_data_cai_no_ciclo_certo(dia, esperado):
    assert ciclo.de_data(dia) == esperado
    assert ciclo.de_data(date.fromisoformat(dia)) == esperado


def test_o_ciclo_cobre_do_16_do_mes_anterior_ao_15():
    ini, fim = ciclo.periodo("2026-09")
    assert (ini, fim) == (date(2026, 8, 16), date(2026, 9, 15))


def test_janeiro_puxa_dezembro_do_ano_anterior():
    assert ciclo.periodo("2026-01") == (date(2025, 12, 16), date(2026, 1, 15))


def test_os_limites_da_consulta_sao_meia_abertos():
    """`>= de` e `< ate`: o dia 15 inteiro entra, o 16 não. Com `<=` na ponta,
    uma ocorrência às 10h do dia 16 cairia nos DOIS ciclos."""
    de, ate = ciclo.limites("2026-09")
    assert (de, ate) == ("2026-08-16", "2026-09-16")


def test_todo_ciclo_tem_dia_15_e_nenhum_depende_do_dia_31():
    """A armadilha do mês civil (fevereiro, 30 × 31) não existe aqui — mas só
    porque o corte é no 15. Vale conferir que nenhum mês reclama."""
    for mes in range(1, 13):
        ini, fim = ciclo.periodo(f"2026-{mes:02d}")
        assert fim.day == 15 and ini.day == 16


def test_a_janela_da_reputacao_termina_no_ciclo_pedido():
    assert ciclo.janela("2026-09", 6) == ["2026-04", "2026-05", "2026-06",
                                          "2026-07", "2026-08", "2026-09"]
    assert ciclo.janela("2026-01", 3) == ["2025-11", "2025-12", "2026-01"]


def test_a_nota_da_gobrax_vem_do_mes_que_responde_pela_MAIOR_parte_do_ciclo():
    """A Gobrax fecha por mês civil. O ciclo 09 tem 16 dias de agosto contra 15
    de setembro — e a tela diz de que mês é a nota, em vez de fingir que tudo
    veio da mesma janela."""
    assert ciclo.mes_da_gobrax("2026-09") == "2026-08"
    assert ciclo.mes_da_gobrax("2026-01") == "2025-12"


def test_o_rotulo_diz_o_periodo_em_portugues():
    assert ciclo.rotulo("2026-09") == "16/08 a 15/09 de 2026"
    assert ciclo.rotulo("2026-01") == "16/12/2025 a 15/01/2026"


@pytest.mark.parametrize("ruim", ["", "2026", "2026-13", "setembro", None, "26-09"])
def test_ciclo_invalido_e_RECUSADO_e_nao_vira_periodo_estranho(ruim):
    assert ciclo.valido(ruim) is False
    with pytest.raises(ValueError, match="Ciclo inválido"):
        ciclo.periodo(ruim)


def test_somar_atravessa_o_ano_nos_dois_sentidos():
    assert ciclo.somar("2026-12", 1) == "2027-01"
    assert ciclo.somar("2026-01", -1) == "2025-12"
    assert ciclo.somar("2026-09", 0) == "2026-09"
    assert ciclo.somar("2026-09", -12) == "2025-09"
