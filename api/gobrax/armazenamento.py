"""Cache local das coletas lentas da Gobrax — data/telemetria.db.

vehicle-statistics leva 73 s para a frota e vehicle-odometer 66 s. Nenhuma tela
pode pagar isso no carregamento, então o resultado é coletado em segundo plano e
lido daqui. O registro vai como JSON: o formato da API muda com o tempo e não
vale criar coluna para cada campo.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "telemetria.db"


class ColetaVazia(Exception):
    """Coleta sem registros. Nunca substitui o que já está gravado."""


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
        CREATE TABLE IF NOT EXISTS coleta(
            colecao     TEXT NOT NULL,
            competencia TEXT NOT NULL,
            registro    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_coleta ON coleta(colecao, competencia);
        CREATE TABLE IF NOT EXISTS coleta_log(
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            colecao     TEXT NOT NULL,
            competencia TEXT NOT NULL,
            quando      TEXT NOT NULL,
            registros   INTEGER NOT NULL
        );
        """)


def gravar(colecao: str, competencia: str, registros: list[dict],
           path: Path | None = None) -> int:
    if not registros:
        raise ColetaVazia(f"coleta de {colecao}/{competencia} veio vazia")
    p = path or DB_PATH
    init_db(p)
    with _conn(p) as c:
        c.execute("DELETE FROM coleta WHERE colecao=? AND competencia=?",
                  (colecao, competencia))
        c.executemany(
            "INSERT INTO coleta(colecao, competencia, registro) VALUES(?,?,?)",
            [(colecao, competencia, json.dumps(r, ensure_ascii=False))
             for r in registros])
        c.execute("INSERT INTO coleta_log(colecao, competencia, quando, registros)"
                  " VALUES(?,?,?,?)",
                  (colecao, competencia,
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(registros)))
    return len(registros)


def ler(colecao: str, competencia: str, path: Path | None = None) -> list[dict]:
    p = path or DB_PATH
    if not Path(p).exists():
        return []
    with _conn(p) as c:
        return [json.loads(r["registro"]) for r in c.execute(
            "SELECT registro FROM coleta WHERE colecao=? AND competencia=?",
            (colecao, competencia))]


def competencia_atual(colecao: str, path: Path | None = None) -> dict | None:
    """Coleta da MAIOR competência, não a última gravada.

    `ultima()` ordena por `id DESC`, isto é, pela ordem de INSERÇÃO. Isso
    basta enquanto se coleta um mês só, mas quebra na hora em que alguém
    recoleta um mês antigo: a coleta de julho, feita depois da de agosto,
    passaria a ser "a última" e a Torre voltaria a mostrar julho como se
    fosse a posição de hoje. Aconteceu na primeira execução do coletor
    agendado, que busca o mês corrente e o anterior.

    Como a competência é 'AAAA-MM', a ordenação alfabética é cronológica.
    """
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute(
            "SELECT competencia, quando, registros FROM coleta_log"
            " WHERE colecao=? ORDER BY competencia DESC, id DESC LIMIT 1",
            (colecao,)).fetchone()
    return dict(row) if row else None


def ultima(colecao: str, path: Path | None = None) -> dict | None:
    p = path or DB_PATH
    if not Path(p).exists():
        return None
    with _conn(p) as c:
        row = c.execute(
            "SELECT competencia, quando, registros FROM coleta_log"
            " WHERE colecao=? ORDER BY id DESC LIMIT 1", (colecao,)).fetchone()
    return dict(row) if row else None
