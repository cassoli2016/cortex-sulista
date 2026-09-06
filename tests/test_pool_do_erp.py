"""O pool do ERP confere a conexao, mas nao a cada consulta.

O QUE ESTE ARQUIVO GUARDA, medido nesta bancada em 06/09/2026:

`SELECT 1` numa conexao presa custa ~15 ms (o ida-e-volta ate o ERP, e o
piso). O mesmo `SELECT 1` pelo pool custava ~60 ms. Os ~45 ms de diferenca
eram duas idas e voltas extras: o `check` na retirada e o `rollback` da
devolucao.

O `check` existia por causa do tunel SSH que podia cair no meio — e o tunel
nao existe mais, mas a rede publica tem os proprios motivos para derrubar
conexao parada. A garantia fica; o que sai e conferir uma conexao que acabou
de responder uma consulta, que e pagar uma ida e volta para saber o que ja se
sabe. Medido alternando em 4 voltas: 61,3 ms -> 46,7 ms.

E FICA REGISTRADO O QUE NAO SE FEZ: `autocommit=True` tiraria os outros 30 ms
(o rollback da devolucao). Foi MEDIDO E RECUSADO — com ele a Visao Geral saiu
de ~1,9 s para o `statement_timeout` de 60 s, cinco vezes em cinco — e a causa
e conhecida: **`SET LOCAL` fora de transacao e no-op**, e o `api/queries.py`
protege a consulta de OC com `SET LOCAL enable_mergejoin = off` (sem a dica, o
9.3 escolhe um merge join degenerado). Com autocommit a dica evapora antes da
consulta. Ha um teste aqui para a ideia nao voltar antes de os `SET LOCAL`
serem convertidos.
"""
from __future__ import annotations

import time

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from api import db


class ConexaoFalsa:
    """So precisa aceitar um atributo — e o que o relogio usa."""


@pytest.fixture
def conferencias(monkeypatch):
    """Conta quantas vezes a conferencia de verdade seria disparada."""
    feitas: list = []
    monkeypatch.setattr(ConnectionPool, "check_connection",
                        lambda conn: feitas.append(conn))
    return feitas


# ------------------------------------------------- o relogio da conferencia

def test_rajada_de_retiradas_confere_uma_vez_so(conferencias):
    """O caminho quente. Era uma ida ao ERP por retirada."""
    conn = ConexaoFalsa()
    for _ in range(20):
        db._conferir_se_parada(conn)
    assert len(conferencias) == 1, (
        f"conferiu {len(conferencias)} vezes em 20 retiradas — "
        "cada uma custa um ida-e-volta ate o ERP")


def test_conexao_que_ficou_parada_e_conferida_de_novo(conferencias):
    """A GARANTIA. Sem isto, a economia acima viraria conexao morta entregue."""
    conn = ConexaoFalsa()
    db._conferir_se_parada(conn)
    assert len(conferencias) == 1

    # envelhece o carimbo em vez de dormir: teste que espera relogio de verdade
    # fica lento e instavel sem afirmar nada a mais
    conn._cortex_conferida_em = time.monotonic() - (db.INTERVALO_CONFERIR + 1)
    db._conferir_se_parada(conn)
    assert len(conferencias) == 2


def test_o_relogio_e_de_cada_conexao_e_nao_do_pool(conferencias):
    """Um contador global isentaria a conexao errada: o pool entrega qualquer
    uma das 16, e a que dormiu nao e a que trabalhou."""
    a, b = ConexaoFalsa(), ConexaoFalsa()
    db._conferir_se_parada(a)
    db._conferir_se_parada(b)
    assert len(conferencias) == 2


def test_conexao_morta_continua_derrubando_a_retirada(monkeypatch):
    def caiu(conn):
        raise psycopg.OperationalError("a conexao esta fechada")
    monkeypatch.setattr(ConnectionPool, "check_connection", caiu)
    with pytest.raises(psycopg.OperationalError):
        db._conferir_se_parada(ConexaoFalsa())


def test_conferencia_que_falhou_nao_carimba_a_conexao(monkeypatch):
    """Se o carimbo viesse antes da conferencia, uma conexao que falhou ficaria
    marcada como conferida e passaria livre pelo minuto seguinte."""
    tentativas = {"n": 0}

    def caiu(conn):
        tentativas["n"] += 1
        raise psycopg.OperationalError("a conexao esta fechada")

    monkeypatch.setattr(ConnectionPool, "check_connection", caiu)
    conn = ConexaoFalsa()
    for _ in range(3):
        with pytest.raises(psycopg.OperationalError):
            db._conferir_se_parada(conn)
    assert tentativas["n"] == 3, "conexao ruim ficou carimbada como boa"


# ------------------------------------------------------- contra o ERP de verdade

@pytest.fixture
def pool_do_erp():
    """Pula quando o ERP nao responde: ausencia de infraestrutura nao e falha
    de codigo, e uma suite vermelha por isso treina todo mundo a ignorar
    vermelho."""
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ERP inacessivel ({type(exc).__name__})")
    yield db._get_pool()


def test_o_pool_do_erp_nao_usa_autocommit(pool_do_erp):
    """MEDIDO E RECUSADO em 06/09/2026, e a causa e CONHECIDA.

    `autocommit=True` tira o rollback da devolucao (~30 ms por consulta) e
    parece dinheiro no chao. Com ele a Visao Geral saiu de ~1,9 s para o
    `statement_timeout` de 60 s, em 5 de 5 execucoes.

    O motivo nao e o pool: **`SET LOCAL` fora de transacao e no-op**. O
    `api/queries.py` abre o grupo de OC com `SET LOCAL enable_mergejoin = off`
    (sem a dica o 9.3 escolhe um merge join degenerado) e
    `SET LOCAL statement_timeout = 12000`. Com autocommit os dois evaporam
    antes da consulta.

    Os 30 ms sao recuperaveis, mas so depois de converter cada `SET LOCAL` da
    casa. Ate la este teste segura a ideia.
    """
    with db.get_conn() as conn:
        assert conn.autocommit is False


def test_consultar_em_rajada_nao_confere_toda_vez(pool_do_erp, monkeypatch):
    """O mesmo do primeiro teste, mas pelo caminho real do `db.query`."""
    feitas: list = []
    original = ConnectionPool.check_connection
    monkeypatch.setattr(ConnectionPool, "check_connection",
                        lambda conn: (feitas.append(conn), original(conn))[1])
    for _ in range(10):
        db.query("SELECT 1 AS ok")
    assert len(feitas) <= 2, (
        f"conferiu {len(feitas)} vezes em 10 consultas seguidas "
        "(o pool tem no maximo 2 conexoes ociosas para estrear)")
