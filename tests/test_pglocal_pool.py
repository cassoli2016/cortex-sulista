"""O banco da casa tem pool — e o pool nao pode furar o isolamento por schema.

POR QUE O POOL ENTROU (medido em 06/09/2026):

`auth.sessao_atual()` roda em TODA requisicao autenticada e abria uma conexao
NOVA no PostgreSQL local. Abrir era 99% do custo — a consulta em si mede
0,07 ms — e piorava justamente sob carga, porque no Windows cada conexao nova
e um processo novo do lado do servidor:

    sessao_atual()          antes 24,70 ms (p95 143,10)  ->  0,40 ms (p95 0,61)
    60 requisicoes juntas   antes  165 ms mediana        ->  10,5 ms

O `api/pglocal.py` ja previa isto por escrito: "o pool entra quando o `auth`
migrar — e ai com medicao, nao por suposicao".

O QUE ESTE ARQUIVO GUARDA e a ressalva que vinha na MESMA frase daquele
comentario: pool traz `search_path` grudado de outra chamada. Schema de teste e
schema de producao convivem no mesmo servidor, e uma conexao reusada que
mantivesse o `search_path` anterior gravaria dado de producao dentro do schema
de um teste — ou o contrario, que e pior. Por isso o `SET search_path` e refeito
A CADA RETIRADA, e por isso o primeiro teste daqui e o do isolamento.
"""
from __future__ import annotations

import uuid

import pytest

from api import pglocal


# ------------------------------------------------------- o que o pool nao pode quebrar

def test_o_search_path_nao_gruda_de_uma_chamada_para_a_outra(pg_disponivel):
    """O RISCO CENTRAL do pool, e o unico que corromperia dado.

    Dois schemas com uma tabela de mesmo nome. Se a conexao reusada trouxesse o
    `search_path` da chamada anterior, a segunda linha cairia na primeira
    tabela — sem erro nenhum, que e o que torna isso caro.
    """
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    a = "teste_pool_a_" + uuid.uuid4().hex[:10]
    b = "teste_pool_b_" + uuid.uuid4().hex[:10]
    try:
        for nome in (a, b):
            pglocal.criar_esquema(nome)
            pglocal.executar("CREATE TABLE caixa (v text)", esquema=nome)

        # muitas idas no A: e o que faria a conexao "se acostumar" com ele
        for i in range(10):
            pglocal.executar("INSERT INTO caixa (v) VALUES (%s)", (f"a{i}",), esquema=a)
        pglocal.executar("INSERT INTO caixa (v) VALUES (%s)", ("b0",), esquema=b)

        assert len(pglocal.query("SELECT v FROM caixa", esquema=a)) == 10
        assert [r["v"] for r in pglocal.query("SELECT v FROM caixa", esquema=b)] == ["b0"]
    finally:
        for nome in (a, b):
            try:
                pglocal.apagar_esquema(nome)
            except Exception:  # noqa: BLE001
                pass
        # SE O MECANISMO ESTIVER QUEBRADO, A ESCRITA CAI EM PRODUCAO -- e foi o
        # que aconteceu em 06/09/2026 ao SABOTAR este guard para conferir que
        # ele acende: sem o `SET search_path`, o `CREATE TABLE caixa` foi para o
        # schema `cortex`, e so apareceu horas depois, no teste de restauracao
        # de backup, como "tabela ausente no restaurado".
        #
        # O teste nao pode qualificar o schema no DDL (e justamente o
        # `search_path` que ele existe para provar), entao ele LIMPA e ACUSA:
        # contaminacao silenciosa vira falha que se nomeia.
        vazou = pglocal.query(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = %s AND tablename = 'caixa'",
            (pglocal.ESQUEMA_PADRAO,))
        if vazou:
            pglocal.executar(
                'DROP TABLE IF EXISTS "%s".caixa' % pglocal.ESQUEMA_PADRAO)
            pytest.fail(
                "a tabela do teste foi parar no schema de PRODUCAO "
                f"({pglocal.ESQUEMA_PADRAO}) -- o `SET search_path` do "
                "`get_conn` nao esta valendo. Foi apagada, mas o isolamento "
                "esta furado.")


def test_erro_no_bloco_continua_desfazendo_a_transacao(esquema_pg):
    """A conexao volta para o pool, mas a transacao tem de morrer junto com o
    erro — senao um `INSERT` de um pedido que falhou no meio ficaria gravado."""
    pglocal.executar("CREATE TABLE t (v text)", esquema=esquema_pg)
    with pytest.raises(RuntimeError):
        with pglocal.get_conn(esquema_pg) as conn:
            conn.execute("INSERT INTO t (v) VALUES ('nao devia ficar')")
            raise RuntimeError("o chamador explodiu no meio")
    assert pglocal.query("SELECT v FROM t", esquema=esquema_pg) == []


def test_o_que_deu_certo_continua_sendo_gravado(esquema_pg):
    """O par do teste acima: sem ele, um `rollback` sempre passaria os dois."""
    pglocal.executar("CREATE TABLE t (v text)", esquema=esquema_pg)
    with pglocal.get_conn(esquema_pg) as conn:
        conn.execute("INSERT INTO t (v) VALUES ('fica')")
    assert [r["v"] for r in pglocal.query("SELECT v FROM t", esquema=esquema_pg)] == ["fica"]


# ---------------------------------------------------------------- o pool reusa

def test_as_conexoes_sao_reusadas(esquema_pg):
    """O ganho, afirmado pelo que o BANCO ve: era um processo novo por chamada.

    `pg_backend_pid()` e o processo do lado do servidor — a evidencia de que a
    conexao e a mesma nao vem do nosso codigo, vem do PostgreSQL.
    """
    processos = set()
    for _ in range(30):
        with pglocal.get_conn(esquema_pg) as conn:
            processos.add(conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"])
    assert len(processos) <= 3, (
        f"{len(processos)} conexoes distintas em 30 chamadas sequenciais — "
        "o pool nao esta reusando nada")


# --------------------------------------------------- a saude nao pode ser enganada

def test_o_diagnostico_nao_passa_pelo_pool(pg_disponivel, monkeypatch):
    """A tela de Saude responde "o banco aceita conexao AGORA?".

    Com o pool no caminho, um banco que parou de aceitar conexao nova (o
    `max_connections` esgotado, o servico recusando) continuaria sendo atendido
    pelas conexoes ja abertas, e o cartao diria "conectado" enquanto ninguem
    mais consegue entrar. Este teste aquece o pool DE PROPOSITO antes de
    quebrar o `connect`.
    """
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    with pglocal.get_conn() as conn:          # pool quente e funcionando
        conn.execute("SELECT 1")

    def recusa(*a, **kw):
        raise RuntimeError("o banco nao aceita conexao nova")

    monkeypatch.setattr(pglocal.psycopg, "connect", recusa)
    d = pglocal.diagnostico()
    assert d["conectado"] is False, (
        "a Saude disse 'conectado' com o banco recusando conexao nova — "
        "ela estava respondendo pelo pool")
    assert d["erro"] == "RuntimeError"


# ------------------------------------------- trocar a configuracao refaz o pool

def test_trocar_a_configuracao_refaz_o_pool(pg_disponivel, monkeypatch):
    """`tests/test_pglocal.py` troca `CORTEX_PG_*` no meio da suite. Um pool
    preso ao DSN antigo responderia apontando para o lugar errado, calado."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    with pglocal.get_conn() as conn:
        conn.execute("SELECT 1")
    antigo = pglocal._get_pool()

    monkeypatch.setenv("CORTEX_PG_DB", "um_banco_que_nao_existe")
    novo = pglocal._get_pool()
    try:
        assert novo is not antigo, "o pool continuou o mesmo com outro banco no .env"
    finally:
        novo.close()
        pglocal.fechar_pool()


def test_sem_configuracao_continua_recusando_antes_de_tocar_no_pool(monkeypatch):
    monkeypatch.delenv("CORTEX_PG_PASSWORD", raising=False)
    with pytest.raises(pglocal.NaoConfigurado):
        with pglocal.get_conn():
            pass
