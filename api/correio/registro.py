"""Trilha dos e-mails enviados — data/email.db (SQLite local).

Existe separado do `audit_log` do auth.db de propósito: o audit responde
"quem mexeu no sistema", e aqui é "o que saiu para fora da empresa", com o
corpo da mensagem. São perguntas diferentes, retenções diferentes, e o
volume de um não pode empurrar o outro para fora da tela.

Toda tentativa é gravada — inclusive a que FALHOU. Registro só de sucesso
esconde justamente o caso que se precisa investigar ("o cliente diz que não
recebeu").
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "email.db"

# corpo é guardado truncado: a trilha serve para conferir O QUE foi dito, não
# para virar arquivo de anexos — relatório grande encheria o SQLite à toa.
MAX_CORPO = 4000


@contextmanager
def _conn(path: Path | None = None):
    caminho = path or DB_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(caminho, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path | None = None) -> None:
    with _conn(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS envios(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            usuario TEXT NOT NULL DEFAULT '',
            destinatarios TEXT NOT NULL,
            assunto TEXT NOT NULL DEFAULT '',
            corpo TEXT NOT NULL DEFAULT '',
            origem TEXT NOT NULL DEFAULT '',
            ok INTEGER NOT NULL DEFAULT 0,
            erro TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_envios_ts ON envios(ts);
        """)


def gravar(destinatarios: list[str], assunto: str, corpo: str, *,
           usuario: str = "", origem: str = "", ok: bool = False,
           erro: str = "", path: Path | None = None) -> int:
    init_db(path)
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO envios(ts, usuario, destinatarios, assunto, corpo, origem, ok, erro)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), usuario or "",
             ", ".join(destinatarios), assunto or "", (corpo or "")[:MAX_CORPO],
             origem or "", 1 if ok else 0, erro or ""))
        return int(cur.lastrowid)


def listar(limite: int = 100, path: Path | None = None) -> list[dict]:
    init_db(path)
    with _conn(path) as c:
        rows = c.execute(
            "SELECT id, ts, usuario, destinatarios, assunto, origem, ok, erro"
            " FROM envios ORDER BY id DESC LIMIT ?", (int(limite),)).fetchall()
    return [dict(r) for r in rows]


def resumo(path: Path | None = None) -> dict:
    init_db(path)
    with _conn(path) as c:
        r = c.execute(
            "SELECT count(*) AS total,"
            " sum(CASE WHEN ok=1 THEN 1 ELSE 0 END) AS ok,"
            " sum(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS falha,"
            " max(ts) AS ultimo FROM envios").fetchone()
    return {"total": r["total"] or 0, "ok": r["ok"] or 0,
            "falha": r["falha"] or 0, "ultimo": r["ultimo"]}
