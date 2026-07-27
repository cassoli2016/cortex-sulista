"""Persistência local do orçamento (SQLite).

O ERP AVA é réplica somente-leitura, então o orçamento é dado nosso. Segue o
padrão de `api/auth.py`: conexão curta com commit automático e WAL.

Regra central: `valor_efetivo = coalesce(valor_ajustado, valor_baseline)`.
Regerar o baseline recalcula APENAS `valor_baseline` — o ajuste manual sobrevive,
senão recalcular jogaria fora o trabalho da controladoria.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "orcamento.db"


@contextmanager
def _conn(path: Path):
    Path(path).parent.mkdir(exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db(path: Path = DB_PATH) -> None:
    with _conn(path) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS orc_versao(
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ano             INTEGER NOT NULL,
            rotulo          TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'rascunho',
            fator_tendencia REAL    NOT NULL DEFAULT 0,
            criado_em       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            criado_por      TEXT
        );
        CREATE TABLE IF NOT EXISTS orc_linha(
            versao_id      INTEGER NOT NULL REFERENCES orc_versao(id) ON DELETE CASCADE,
            conta          TEXT    NOT NULL,
            mes            INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
            valor_baseline REAL    NOT NULL DEFAULT 0,
            valor_ajustado REAL,
            origem         TEXT    NOT NULL DEFAULT 'sem_base',
            meses_com_dado INTEGER NOT NULL DEFAULT 0,
            ajustado_em    TEXT,
            ajustado_por   TEXT,
            PRIMARY KEY (versao_id, conta, mes)
        );
        CREATE TABLE IF NOT EXISTS orc_log(
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            versao_id  INTEGER NOT NULL,
            conta      TEXT    NOT NULL,
            mes        INTEGER NOT NULL,
            valor_de   REAL,
            valor_para REAL,
            quem       TEXT,
            quando     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS ix_orc_linha_versao ON orc_linha(versao_id);
        CREATE INDEX IF NOT EXISTS ix_orc_log_versao   ON orc_log(versao_id, id DESC);
        """)


def criar_versao(path: Path, ano: int, rotulo: str, fator: float, quem: str) -> int:
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO orc_versao(ano, rotulo, fator_tendencia, criado_por) "
            "VALUES (?,?,?,?)", (ano, rotulo, fator, quem))
        return int(cur.lastrowid)


def atualizar_versao(path: Path, versao_id: int, fator: float) -> None:
    """Regeração troca o fator da versão; ano e rótulo continuam os mesmos."""
    with _conn(path) as c:
        cur = c.execute("UPDATE orc_versao SET fator_tendencia=? WHERE id=?",
                        (fator, versao_id))
        if cur.rowcount == 0:
            raise KeyError(f"versão inexistente: {versao_id}")


def zerar_fora_do_conjunto(path: Path, versao_id: int,
                           chaves: set[tuple[str, int]]) -> int:
    """Zera o baseline das células que a nova derivação não produziu.

    A linha NÃO é apagada: se a controladoria ajustou aquela célula, o ajuste
    sobrevive à regeração — é a mesma regra do `coalesce`. Sem isso, um baseline
    velho de conta que sumiu do histórico continuaria somando no orçado.
    """
    with _conn(path) as c:
        atuais = c.execute(
            "SELECT conta, mes FROM orc_linha WHERE versao_id=?", (versao_id,)).fetchall()
        sobrando = [(versao_id, r["conta"], r["mes"]) for r in atuais
                    if (r["conta"], r["mes"]) not in chaves]
        if sobrando:
            c.executemany(
                "UPDATE orc_linha SET valor_baseline=0, origem='sem_base', meses_com_dado=0 "
                "WHERE versao_id=? AND conta=? AND mes=?", sobrando)
        return len(sobrando)


def gravar_baseline(path: Path, versao_id: int, linhas: list[dict]) -> int:
    """Insere ou atualiza o baseline. NÃO toca em valor_ajustado."""
    with _conn(path) as c:
        c.executemany("""
            INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline, origem, meses_com_dado)
            VALUES (:v, :conta, :mes, :valor_baseline, :origem, :meses_com_dado)
            ON CONFLICT(versao_id, conta, mes) DO UPDATE SET
                valor_baseline = excluded.valor_baseline,
                origem         = excluded.origem,
                meses_com_dado = excluded.meses_com_dado
        """, [{**l, "v": versao_id} for l in linhas])
        return len(linhas)


def ajustar(path: Path, versao_id: int, conta: str, mes: int,
            valor: float | None, quem: str) -> None:
    """Grava (ou limpa, com valor=None) o ajuste manual de uma célula."""
    with _conn(path) as c:
        row = c.execute(
            "SELECT valor_baseline, valor_ajustado FROM orc_linha "
            "WHERE versao_id=? AND conta=? AND mes=?", (versao_id, conta, mes)).fetchone()
        if row is None:
            raise KeyError(f"linha inexistente: versao={versao_id} conta={conta} mes={mes}")
        de = row["valor_ajustado"] if row["valor_ajustado"] is not None else row["valor_baseline"]
        c.execute(
            "UPDATE orc_linha SET valor_ajustado=?, "
            "ajustado_em=datetime('now','localtime'), ajustado_por=? "
            "WHERE versao_id=? AND conta=? AND mes=?", (valor, quem, versao_id, conta, mes))
        c.execute(
            "INSERT INTO orc_log(versao_id, conta, mes, valor_de, valor_para, quem) "
            "VALUES (?,?,?,?,?,?)", (versao_id, conta, mes, de, valor, quem))


def ler_linhas(path: Path, versao_id: int) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute("""
            SELECT conta, mes, valor_baseline, valor_ajustado, origem, meses_com_dado,
                   ajustado_em, ajustado_por,
                   coalesce(valor_ajustado, valor_baseline) AS valor_efetivo
            FROM orc_linha WHERE versao_id=? ORDER BY conta, mes
        """, (versao_id,)).fetchall()
        return [dict(r) for r in rows]


def listar_versoes(path: Path, ano: int | None = None) -> list[dict]:
    sql = "SELECT * FROM orc_versao"
    par: tuple = ()
    if ano is not None:
        sql += " WHERE ano=?"
        par = (ano,)
    sql += " ORDER BY ano DESC, id DESC"
    with _conn(path) as c:
        return [dict(r) for r in c.execute(sql, par).fetchall()]


def ler_log(path: Path, versao_id: int, limite: int = 200) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT * FROM orc_log WHERE versao_id=? ORDER BY id DESC LIMIT ?",
            (versao_id, limite)).fetchall()
        return [dict(r) for r in rows]
