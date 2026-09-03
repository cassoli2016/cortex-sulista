# -*- coding: utf-8 -*-
"""O drill-down da DRE: conta → centro de custo → lançamento.

O guard principal é um só, e é o que decide se a tela serve para conferir ou
só para olhar: a soma dos centros TEM de fechar com o total da conta. Se não
fechar, o drill-down vira uma segunda opinião sobre o mesmo número — que é
pior do que não existir.
"""
from __future__ import annotations

import datetime as dt

import pytest

from api import dre_drill as dd


def _stub(monkeypatch, linhas):
    class _Cur:
        def execute(self, sql, params=None):
            self._sql = sql
            self._params = params

        def fetchall(self):
            return linhas

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

    monkeypatch.setattr(dd.db, "get_conn", lambda: _Conn())


# ------------------------------------------------- o balde "sem centro"

def test_sem_centro_de_custo_e_uma_LINHA_e_nao_um_resto(monkeypatch):
    """14% dos lançamentos não têm rateio — 68.451 em 12 meses, valendo
    R$ 15,76 milhões (medido em 03/09/2026). Um JOIN ingênuo os perderia e a
    soma dos centros não fecharia com a conta; o buraco teria cara de "esse
    centro custa menos do que eu pensava"."""
    _stub(monkeypatch, [
        {"centro": 2102, "descricao": "CCO", "valor": -100.0, "lancamentos": 3},
        {"centro": None, "descricao": dd.SEM_CENTRO, "valor": -40.0,
         "lancamentos": 2}])
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    d = dd.centros(1, 411101, "2026-08-01", "2026-09-01")
    rotulos = [x["descricao"] for x in d["linhas"]]
    assert dd.SEM_CENTRO in rotulos
    # a SOMA fecha: é isso que faz o drill-down ser conferência
    assert d["total"] == pytest.approx(-140.0)


def test_a_ordem_e_por_TAMANHO_e_nao_por_codigo(monkeypatch):
    _stub(monkeypatch, [
        {"centro": 1, "descricao": "A", "valor": -10.0, "lancamentos": 1},
        {"centro": 2, "descricao": "B", "valor": -900.0, "lancamentos": 1},
        {"centro": 3, "descricao": "C", "valor": -50.0, "lancamentos": 1}])
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    d = dd.centros(1, 411101, "2026-08-01", "2026-09-01")
    assert [x["descricao"] for x in d["linhas"]] == ["B", "C", "A"]


# ----------------------------------------------------- a exclusão vale aqui

def test_o_drill_down_RESPEITA_a_exclusao(monkeypatch):
    """A exclusão vale aqui também. Se um lançamento foi tirado do resultado,
    ele não pode reaparecer três cliques abaixo — o total de cima deixaria de
    bater com a soma de baixo, e a tela perderia o direito de ser conferida."""
    vistos = {}

    class _Cur:
        def execute(self, sql, params=None):
            vistos["sql"] = sql
            vistos["params"] = params

        def fetchall(self):
            return []

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

    monkeypatch.setattr(dd.db, "get_conn", lambda: _Conn())
    monkeypatch.setattr(dd.dre_exclusoes, "chaves",
                        lambda *a, **k: [(1, 1, 411101, 999, dt.date(2026, 8, 1))])
    dd.centros(1, 411101, "2026-08-01", "2026-09-01")
    assert "dre_excluidos" in vistos["sql"]
    assert "dre_excluidos" in vistos["params"]

    dd.lancamentos(1, 411101, "2026-08-01", "2026-09-01", centro=2102)
    assert "dre_excluidos" in vistos["sql"]


def test_sem_exclusao_a_consulta_nao_ganha_clausula(monkeypatch):
    """Cláusula com lista vazia é erro de sintaxe — e a conta de quem nunca
    excluiu nada é o caso mais comum."""
    vistos = {}

    class _Cur:
        def execute(self, sql, params=None):
            vistos["sql"] = sql

        def fetchall(self):
            return []

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

    monkeypatch.setattr(dd.db, "get_conn", lambda: _Conn())
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    dd.centros(1, 411101, "2026-08-01", "2026-09-01")
    assert "dre_excluidos" not in vistos["sql"]


# ------------------------------------------------------------- o teto

def test_o_teto_de_lancamentos_SE_DECLARA(monkeypatch):
    """Lista cortada em silêncio faz a soma da tela não bater com o total de
    cima — e quem confere culpa o número certo."""
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    _stub(monkeypatch, [{"sequencia": i} for i in range(dd.LIMITE_LANC + 1)])
    d = dd.lancamentos(1, 411101, "2026-08-01", "2026-09-01")
    assert d["truncou"] is True
    assert len(d["linhas"]) == dd.LIMITE_LANC
    assert d["limite"] == dd.LIMITE_LANC

    _stub(monkeypatch, [{"sequencia": i} for i in range(10)])
    assert dd.lancamentos(1, 411101, "2026-08-01", "2026-09-01")["truncou"] is False


# ------------------------------------------------ só conta de resultado

def test_o_drill_so_abre_conta_de_RESULTADO():
    """Mostrar aqui um lançamento que a DRE já ignora seria oferecer o
    detalhe de algo que não está no número de cima."""
    import inspect

    for fn in (dd.centros, dd.lancamentos):
        assert "p.estrutural ~ '^[34]'" in inspect.getsource(fn), fn.__name__


def test_o_sem_rateio_usa_NOT_EXISTS_e_nao_left_join():
    """O rateio divide o mesmo lançamento em até 21 partes: um
    `LEFT JOIN … IS NULL` multiplicaria a linha antes de filtrar."""
    import inspect

    fonte = inspect.getsource(dd.centros)
    assert "NOT EXISTS" in fonte


# ------------------------------------------------------------- a tela

def test_a_tela_tem_os_dois_niveis():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert "function dreDrill(" in html
    assert "function dreDrillLanc(" in html
    # a linha da conta CARREGA a chave, senão o drill não sabe o que abrir
    assert 'data-g="${c.grupo}" data-r="${c.reduzido}"' in html
    # e o botão CHAMA o drill (não basta existir a função)
    assert 'onclick="dreDrill(this)"' in html
    # a faixa usa colspan: a tabela tem 15 colunas e célula a mais desalinha
    assert 'colspan="15"' in html


def test_a_rota_do_drill_esta_no_rbac():
    from api import auth

    rotas = dict(auth.ROTA_TELAS)
    assert "dre" in rotas["/api/dre/centros"]
    assert "dre" in rotas["/api/dre/conta-lancamentos"]
