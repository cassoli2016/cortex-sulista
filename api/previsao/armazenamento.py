"""Persistência local da previsão de fechamento (SQLite).

O AVA é réplica somente-leitura; ajuste manual e snapshot diário são dado
nosso. Padrão de api/orcamento/armazenamento.py: conexão curta com commit
automático e WAL.

Regra central (herdada do orçamento): recalcular a previsão NUNCA apaga o
ajuste manual — o efetivo é previsto_calculado + delta (ou o valor absoluto),
resolvido no motor (motor.aplicar_ajustes), não aqui.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "previsao.db"

TIPOS_AJUSTE = ("delta", "valor")


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path = DB_PATH) -> None:
    with _conn(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS prev_ajuste(
            mes       TEXT NOT NULL,
            linha     TEXT NOT NULL,
            tipo      TEXT NOT NULL CHECK (tipo IN ('delta','valor')),
            valor     REAL NOT NULL,
            motivo    TEXT NOT NULL,
            autor     TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (mes, linha)
        );
        CREATE TABLE IF NOT EXISTS prev_snapshot(
            data               TEXT NOT NULL,
            mes                TEXT NOT NULL,
            linha              TEXT NOT NULL,
            previsto_base      REAL NOT NULL,
            previsto_otim      REAL,
            previsto_pess      REAL,
            realizado_contabil REAL,
            estrategia         TEXT,
            PRIMARY KEY (data, mes, linha)
        );
        CREATE TABLE IF NOT EXISTS prev_log(
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            quando  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            autor   TEXT,
            acao    TEXT NOT NULL,
            detalhe TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_prev_snap_mes ON prev_snapshot(mes, data);
        """)


def ler_ajustes_prev(path: Path, mes: str) -> dict[str, dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT linha, tipo, valor, motivo, autor, criado_em "
            "FROM prev_ajuste WHERE mes=?", (mes,)).fetchall()
        return {r["linha"]: {k: r[k] for k in
                             ("tipo", "valor", "motivo", "autor", "criado_em")}
                for r in rows}


def salvar_ajuste_prev(path: Path, mes: str, linha: str, tipo: str,
                       valor: float, motivo: str, autor: str) -> None:
    if tipo not in TIPOS_AJUSTE:
        raise ValueError(f"tipo deve ser um de {TIPOS_AJUSTE}")
    if not (motivo or "").strip():
        raise ValueError("motivo é obrigatório")
    with _conn(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO prev_ajuste(mes, linha, tipo, valor, motivo, autor) "
            "VALUES(?,?,?,?,?,?)", (mes, linha, tipo, float(valor), motivo.strip(), autor))
        c.execute("INSERT INTO prev_log(autor, acao, detalhe) VALUES(?,?,?)",
                  (autor, "ajuste", f"{mes} {linha} {tipo}={valor} ({motivo.strip()})"))


def remover_ajuste_prev(path: Path, mes: str, linha: str) -> bool:
    with _conn(path) as c:
        cur = c.execute("DELETE FROM prev_ajuste WHERE mes=? AND linha=?", (mes, linha))
        if cur.rowcount:
            c.execute("INSERT INTO prev_log(autor, acao, detalhe) VALUES(?,?,?)",
                      (None, "ajuste_removido", f"{mes} {linha}"))
        return bool(cur.rowcount)


def gravar_snapshot(path: Path, data_foto: str, mes: str, linhas: list[dict]) -> None:
    with _conn(path) as c:
        c.executemany(
            "INSERT OR REPLACE INTO prev_snapshot"
            "(data, mes, linha, previsto_base, previsto_otim, previsto_pess,"
            " realizado_contabil, estrategia) VALUES(?,?,?,?,?,?,?,?)",
            [(data_foto, mes, ln["linha"], ln["previsto_base"], ln.get("previsto_otim"),
              ln.get("previsto_pess"), ln.get("realizado_contabil"), ln.get("estrategia"))
             for ln in linhas])


def ler_snapshots(path: Path, mes: str) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT data, mes, linha, previsto_base, previsto_otim, previsto_pess,"
            "       realizado_contabil, estrategia "
            "FROM prev_snapshot WHERE mes=? ORDER BY data, linha", (mes,)).fetchall()
        return [dict(r) for r in rows]


def registrar_log(path: Path, autor: str | None, acao: str, detalhe: str) -> None:
    with _conn(path) as c:
        c.execute("INSERT INTO prev_log(autor, acao, detalhe) VALUES(?,?,?)",
                  (autor, acao, detalhe))
