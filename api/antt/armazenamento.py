"""Base local da situação do RNTRC — SQLite, como todo dado nosso.

Guarda SÓ os transportadores que a Sulista contrata (222 hoje), não a base
nacional: o casamento é por número de registro, então não há razão para trazer
1,16 milhão de linhas para dentro. Nenhum documento de pessoa é gravado aqui.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "antt.db"

_SO_DIGITOS = re.compile(r"\D")


class BaseVazia(Exception):
    """Sync que não trouxe nenhuma linha. Nunca sobrescreve o que está gravado."""


def normalizar_rntrc(valor: str | None) -> str:
    """Chave de casamento: só dígitos, sem zeros à esquerda.

    O AVA guarda 8 dígitos ('07600540') e a ANTT publica 9 ('007600540'). Os
    dois lados passam por aqui — normalizar só um deles cria falso 'não
    encontrado', que num módulo de compliance acusa quem está em ordem.
    """
    if not valor:
        return ""
    return _SO_DIGITOS.sub("", str(valor)).lstrip("0")


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


def init_db(path: Path | None = None) -> None:
    with _conn(path or DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS rntrc_transportador(
            rntrc         TEXT PRIMARY KEY,
            nome          TEXT,
            situacao      TEXT NOT NULL,
            categoria     TEXT,
            uf            TEXT,
            municipio     TEXT,
            data_situacao TEXT
        );
        CREATE TABLE IF NOT EXISTS rntrc_sync(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            competencia TEXT NOT NULL,
            quando      TEXT NOT NULL,
            linhas      INTEGER NOT NULL
        );
        """)


def gravar_lote(linhas: list[dict], competencia: str,
                path: Path | None = None) -> int:
    if not linhas:
        raise BaseVazia(f"sync de {competencia} não trouxe nenhuma linha")
    p = path or DB_PATH
    init_db(p)
    with _conn(p) as c:
        c.execute("DELETE FROM rntrc_transportador")
        c.executemany(
            """INSERT OR REPLACE INTO rntrc_transportador
               (rntrc, nome, situacao, categoria, uf, municipio, data_situacao)
               VALUES(:rntrc, :nome, :situacao, :categoria, :uf, :municipio,
                      :data_situacao)""",
            [{**l, "rntrc": normalizar_rntrc(l["rntrc"])} for l in linhas])
        c.execute("INSERT INTO rntrc_sync(competencia, quando, linhas) VALUES(?,?,?)",
                  (competencia, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   len(linhas)))
    return len(linhas)


def situacao(rntrc: str, path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute("SELECT * FROM rntrc_transportador WHERE rntrc=?",
                        (normalizar_rntrc(rntrc),)).fetchone()
    return dict(row) if row else None


def todas(path: Path | None = None) -> dict[str, dict]:
    p = path or DB_PATH
    if not Path(p).exists():
        return {}
    with _conn(p) as c:
        return {r["rntrc"]: dict(r)
                for r in c.execute("SELECT * FROM rntrc_transportador")}


def ultima_sync(path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute("SELECT competencia, quando, linhas FROM rntrc_sync "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
