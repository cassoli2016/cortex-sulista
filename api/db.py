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
