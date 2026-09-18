# -*- coding: utf-8 -*-
"""O corte do ciclo existe em DOIS sotaques — e eles têm de concordar.

`ciclo.de_data` decide em Python; `pilares._CICLO_SQL` decide dentro da
consulta, porque ler seis ciclos em seis consultas custa seis idas ao banco.
Duas implementações da mesma regra divergem em silêncio — é a lição do
freetime, e lá o guard que resolveu foi o que EXECUTA as duas lado a lado
contra entrada real, em vez de comparar o código lendo.

A borda que este teste existe para pegar: o atalho `data + 15 dias` erra em
mês de 31 dias (16 + 15 = 31, ainda o mesmo mês) e `+ 16 dias` erra em mês de
30 (15 + 16 = 31, que vira o mês seguinte). Só um dia de diferença — e ele
move a ocorrência, o desvio e o dinheiro de um ciclo para o outro.
"""
from __future__ import annotations

from datetime import date, timedelta

from api import pglocal
from api.premiacao import ciclo as ciclo_mod
from api.premiacao import pilares


def test_o_corte_do_SQL_e_o_do_PYTHON_concordam_em_todo_dia_de_dois_anos(esquema_pg):
    sql = (
        "SELECT d::date AS dia, "
        + pilares._CICLO_SQL.format(col="d")
        + " AS ciclo FROM generate_series(%(de)s::timestamp, %(ate)s::timestamp,"
          " interval '1 day') d")
    linhas = pglocal.query(sql, {"de": "2025-01-01", "ate": "2026-12-31"},
                           esquema=esquema_pg)
    assert len(linhas) == 730, "a série não cobriu os dois anos"
    divergentes = [(r["dia"].isoformat(), r["ciclo"], ciclo_mod.de_data(r["dia"]))
                   for r in linhas if r["ciclo"] != ciclo_mod.de_data(r["dia"])]
    assert not divergentes, (
        "SQL e Python discordam sobre o ciclo (dia, SQL, Python): "
        + str(divergentes[:8]))


def test_as_bordas_do_mes_caem_no_ciclo_certo_nos_dois(esquema_pg):
    """Os dias que os atalhos erram: 15 e 16 de um mês de 30 e de um de 31."""
    alvos = [date(2026, 1, 15), date(2026, 1, 16),   # janeiro tem 31
             date(2026, 4, 15), date(2026, 4, 16),   # abril tem 30
             date(2026, 2, 15), date(2026, 2, 16),   # fevereiro tem 28
             date(2026, 12, 16)]                     # e a virada do ano
    sql = ("SELECT d::date AS dia, " + pilares._CICLO_SQL.format(col="d")
           + " AS ciclo FROM unnest(%(dias)s::timestamp[]) d")
    linhas = pglocal.query(sql, {"dias": [d.isoformat() for d in alvos]},
                           esquema=esquema_pg)
    por_dia = {r["dia"]: r["ciclo"] for r in linhas}
    assert por_dia[date(2026, 1, 15)] == "2026-01" == ciclo_mod.de_data("2026-01-15")
    assert por_dia[date(2026, 1, 16)] == "2026-02" == ciclo_mod.de_data("2026-01-16")
    assert por_dia[date(2026, 4, 15)] == "2026-04"
    assert por_dia[date(2026, 4, 16)] == "2026-05"
    assert por_dia[date(2026, 2, 16)] == "2026-03"
    assert por_dia[date(2026, 12, 16)] == "2027-01"


def test_a_janela_do_SQL_cobre_exatamente_os_ciclos_pedidos(esquema_pg):
    """O primeiro dia da janela é o 16 do mês anterior ao ciclo mais antigo, e
    o último é o 15 do ciclo mais novo. Um dia a mais em qualquer ponta puxa
    ocorrência de outro ciclo para dentro da conta."""
    de, ate = pilares._janela_limites("2026-09", 6)
    assert de == "2026-03-16"
    assert ate == "2026-09-16"          # exclusivo: o dia 15 inteiro entra
    dias = (date.fromisoformat(ate) - date.fromisoformat(de)).days
    assert dias == sum(
        (date.fromisoformat(ciclo_mod.limites(c)[1])
         - date.fromisoformat(ciclo_mod.limites(c)[0])).days
        for c in ciclo_mod.janela("2026-09", 6))


def test_uma_ocorrencia_do_dia_16_entra_no_ciclo_SEGUINTE(esquema_pg, monkeypatch):
    """Ponta a ponta, com o corte do SQL: o dia 16 não pode cair no ciclo que
    fecha — é o dia em que o dinheiro muda de mês."""
    linhas = [
        {"cpf": "11111111111", "codigo": 1, "data": "2026-08-15",
         "descricao": "X", "ciclo": "2026-08"},
        {"cpf": "11111111111", "codigo": 1, "data": "2026-08-16",
         "descricao": "X", "ciclo": "2026-09"},
    ]
    monkeypatch.setattr(pilares.erp, "query", lambda sql, p=None: linhas)
    r = pilares.comportamento_janela("2026-09", 6, depara={1: "D01"})
    assert r["por_ciclo"]["2026-08"]["11111111111"]["pontos"] == 12
    assert r["por_ciclo"]["2026-09"]["11111111111"]["pontos"] == 12
    assert len(r["por_ciclo"]) == 2
