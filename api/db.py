"""Acesso ao banco legado AVA (PostgreSQL 9.3) — SOMENTE LEITURA.

Conecta em 127.0.0.1:15432 (porta local do túnel SSH). As credenciais vêm do
.env na raiz. Toda sessão é read-only e com statement_timeout para não travar.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

try:  # pool é opcional: se a dependência ainda não foi sincronizada, conecta direto
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover
    ConnectionPool = None

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for raw in env.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_env()


def _conninfo() -> str:
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "15432"),
        dbname=os.environ.get("POSTGRES_DB", "sulista"),
        user=os.environ.get("POSTGRES_USER", "consulta_sulista"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        connect_timeout=8,
        # O servidor é UTF8, mas o libpq no Windows deriva o client_encoding da
        # codepage do sistema e escolhe LATIN1. Aí o SERVIDOR passa a converter
        # UTF8 -> LATIN1 na saída, e um caractere fora do Latin-1 derruba a
        # CONSULTA INTEIRA com UntranslatableCharacter -- não a linha, a
        # consulta. São poucas linhas (4 praças de pedágio, 20 CT-e, 12 coletas
        # com o travessão "–"), e é justamente isso que torna a armadilha ruim:
        # a tela funciona por meses e quebra no dia em que alguém cadastra um
        # nome com travessão. Pedindo UTF8 não há conversão nenhuma.
        client_encoding="UTF8",
        # read-only + timeout de segurança (o banco é de produção de terceiros)
        options="-c statement_timeout=60000 -c default_transaction_read_only=on",
    )


# Pool de conexões: o banco fica atrás de um túnel SSH e o handshake de uma
# conexão nova custa vários round-trips — reusar conexões corta esse custo em
# todas as rotas. `check` descarta conexões mortas (ex.: túnel reiniciado).
_pool: "ConnectionPool | None" = None


def _get_pool() -> "ConnectionPool":
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            _conninfo(), kwargs={"row_factory": dict_row},
            min_size=1, max_size=6, max_idle=300, timeout=15,
            check=ConnectionPool.check_connection, name="ava", open=True)
    return _pool


def fechar_pool() -> None:
    """Encerra o pool de propósito — para SCRIPT, não para a API.

    A API vive com o pool aberto até o processo morrer. Já um script de linha
    de comando (conferir_numeros) que termina sem fechar deixa o worker do
    pool vivo e o psycopg imprime "couldn't stop thread 'ava-worker-0'" no
    stderr depois do veredito — aviso que se lê como problema onde não há.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn():
    if ConnectionPool is None:
        with psycopg.connect(_conninfo(), row_factory=dict_row) as conn:
            yield conn
        return
    with _get_pool().connection() as conn:
        yield conn


def query(sql: str, params: tuple | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()
