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
        {"centro": 2102, "descricao": "CCO", "mes": "2026-08", "valor": -100.0,
         "lancamentos": 3},
        {"centro": None, "descricao": dd.SEM_CENTRO, "mes": "2026-08",
         "valor": -40.0, "lancamentos": 2}])
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    d = dd.centros(1, 411101, "2026-08-01", "2026-09-01")
    rotulos = [x["descricao"] for x in d["linhas"]]
    assert dd.SEM_CENTRO in rotulos
    # a SOMA fecha: é isso que faz o drill-down ser conferência
    assert d["total"] == pytest.approx(-140.0)


def test_a_ordem_e_por_TAMANHO_e_nao_por_codigo(monkeypatch):
    _stub(monkeypatch, [
        {"centro": 1, "descricao": "A", "mes": "2026-08", "valor": -10.0,
         "lancamentos": 1},
        {"centro": 2, "descricao": "B", "mes": "2026-08", "valor": -900.0,
         "lancamentos": 1},
        {"centro": 3, "descricao": "C", "mes": "2026-08", "valor": -50.0,
         "lancamentos": 1}])
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


# ------------------------------------------------------ o pivô mês a mês
#
# O centro de custo era o ÚNICO nível com um número só do período inteiro,
# entre níveis que a tela mostra mês a mês. Quem via "R$ 2,3 mi" num centro
# não sabia se era um mês fora da curva ou doze meses iguais — que é
# justamente a pergunta que traz alguém até este nível.


def test_o_intervalo_de_meses_e_GERADO_e_nao_colhido(monkeypatch):
    """`GROUP BY` não devolve o mês SEM lançamento. Colhendo os meses do
    resultado, uma conta parada em maio e junho emendaria abril em julho, e a
    linha diria "não mudou nada" onde houve dois meses de nada."""
    _stub(monkeypatch, [
        {"centro": 1, "descricao": "A", "mes": "2026-04", "valor": -10.0,
         "lancamentos": 1},
        {"centro": 1, "descricao": "A", "mes": "2026-07", "valor": -30.0,
         "lancamentos": 1}])
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    d = dd.centros(1, 411101, "2026-04-01", "2026-08-01")
    assert d["meses"] == ["2026-04", "2026-05", "2026-06", "2026-07"]
    linha = d["linhas"][0]
    assert linha["meses"]["2026-05"] == 0.0 and linha["meses"]["2026-06"] == 0.0
    assert linha["meses"]["2026-04"] == pytest.approx(-10.0)
    assert linha["meses"]["2026-07"] == pytest.approx(-30.0)


def test_o_total_do_centro_e_a_soma_dos_meses(monkeypatch):
    """Total desnormalizado discorda das próprias linhas no primeiro edit."""
    _stub(monkeypatch, [
        {"centro": 1, "descricao": "A", "mes": "2026-06", "valor": -10.0,
         "lancamentos": 2},
        {"centro": 1, "descricao": "A", "mes": "2026-07", "valor": -30.0,
         "lancamentos": 5}])
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    d = dd.centros(1, 411101, "2026-06-01", "2026-08-01")
    linha = d["linhas"][0]
    assert linha["valor"] == pytest.approx(sum(linha["meses"].values()))
    assert linha["valor"] == pytest.approx(-40.0)
    assert linha["lancamentos"] == 7, "a contagem tem de somar os meses também"


def test_mes_fora_do_periodo_nao_entra_pela_janela(monkeypatch):
    """Um mês que o filtro não pediu não pode aparecer na linha só porque a
    consulta o devolveu — e também não pode sumir da SOMA sem aviso."""
    _stub(monkeypatch, [
        {"centro": 1, "descricao": "A", "mes": "2026-06", "valor": -10.0,
         "lancamentos": 1}])
    monkeypatch.setattr(dd.dre_exclusoes, "chaves", lambda *a, **k: [])
    d = dd.centros(1, 411101, "2026-07-01", "2026-08-01")
    assert d["meses"] == ["2026-07"]
    assert "2026-06" not in d["linhas"][0]["meses"]


def test_a_virada_de_ano_nao_perde_dezembro():
    assert dd._meses_do_periodo("2025-11-01", "2026-02-01") == [
        "2025-11", "2025-12", "2026-01"]
