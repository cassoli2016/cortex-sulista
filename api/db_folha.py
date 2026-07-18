"""Acesso ao banco da FOLHA (Oracle) — SOMENTE LEITURA.

Espelha o padrão do api/db.py, mas para Oracle via python-oracledb em modo
THIN (Python puro, sem Oracle Instant Client). As credenciais vêm do .env na
raiz — NUNCA no código. O módulo é "desligado por padrão": se as variáveis
ORACLE_FOLHA_* não estiverem definidas, `configured()` devolve False e nenhuma
conexão é aberta (o resto do painel segue funcionando normalmente).

.env esperado (na máquina de produção, mesma rede do servidor Oracle):
    ORACLE_FOLHA_HOST=...          # IP/hostname do Oracle
    ORACLE_FOLHA_PORT=1521         # padrão 1521
    ORACLE_FOLHA_SERVICE=...       # service name  (OU ORACLE_FOLHA_SID=...)
    ORACLE_FOLHA_USER=...          # usuário read-only dedicado
    ORACLE_FOLHA_PASSWORD=...      # só no .env

Segurança: use um usuário Oracle com apenas SELECT no schema da folha. Ainda
assim só executamos SELECT, e cada consulta abre a transação como READ ONLY.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

try:
    import oracledb  # type: ignore
except ImportError:  # pragma: no cover — dependência ainda não sincronizada
    oracledb = None

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


def configured() -> bool:
    """True se há credenciais da folha no ambiente (host + user + senha)."""
    return bool(
        oracledb
        and os.environ.get("ORACLE_FOLHA_HOST")
        and os.environ.get("ORACLE_FOLHA_USER")
        and os.environ.get("ORACLE_FOLHA_PASSWORD")
        and (os.environ.get("ORACLE_FOLHA_SERVICE") or os.environ.get("ORACLE_FOLHA_SID"))
    )


def _dsn() -> str:
    host = os.environ["ORACLE_FOLHA_HOST"]
    port = os.environ.get("ORACLE_FOLHA_PORT", "1521")
    service = os.environ.get("ORACLE_FOLHA_SERVICE")
    sid = os.environ.get("ORACLE_FOLHA_SID")
    if service:
        return f"{host}:{port}/{service}"          # formato "easy connect"
    return oracledb.makedsn(host, port, sid=sid)   # SID clássico


_pool = None


def _get_pool():
    """Pool de conexões Oracle (thin). Criado sob demanda."""
    global _pool
    if not configured():
        raise RuntimeError(
            "Folha (Oracle) não configurada: defina ORACLE_FOLHA_HOST/USER/PASSWORD/"
            "SERVICE (ou SID) no .env.")
    if _pool is None:
        _pool = oracledb.create_pool(
            user=os.environ["ORACLE_FOLHA_USER"],
            password=os.environ["ORACLE_FOLHA_PASSWORD"],
            dsn=_dsn(), min=1, max=4, increment=1, timeout=300,
            getmode=oracledb.POOL_GETMODE_WAIT,
        )
    return _pool


@contextmanager
def get_conn():
    conn = _get_pool().acquire()
    try:
        conn.call_timeout = 60000        # 60s de teto por chamada (ms)
        yield conn
    finally:
        _get_pool().release(conn)


def query(sql: str, params: dict | list | None = None) -> list[dict]:
    """Executa um SELECT e devolve list[dict] (nomes de coluna em minúsculo).

    Abre a transação como READ ONLY antes do SELECT — camada extra de proteção
    além do usuário read-only."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql, params or {})
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def ping() -> dict:
    """Teste de conectividade: SELECT 1 FROM dual + versão do banco."""
    import time
    t0 = time.perf_counter()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM dual")
        cur.fetchone()
        ver = getattr(conn, "version", None)
    return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "versao": ver}
