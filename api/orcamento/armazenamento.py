"""Persistência local do orçamento (SQLite).

O ERP AVA é réplica somente-leitura, então o orçamento é dado nosso. Segue o
padrão de `api/auth.py`: conexão curta com commit automático e WAL.

Regra central: `valor_efetivo = coalesce(valor_ajustado, valor_baseline)`.
Regerar o baseline recalcula APENAS `valor_baseline` — o ajuste manual sobrevive,
senão recalcular jogaria fora o trabalho da controladoria.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
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
        # migração: bancos criados antes não têm a coluna (CREATE IF NOT EXISTS
        # não altera tabela existente). meses_base = JSON com os 'YYYY-MM' usados
        # na derivação — é o que permite ao comparativo saber quais meses do ano
        # orçado estavam DENTRO da base (espelho de si mesmos, comparação circular)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(orc_versao)")}
        if "meses_base" not in cols:
            c.execute("ALTER TABLE orc_versao ADD COLUMN meses_base TEXT")
        # metodo = qual derivação gerou a versão ('espelho' ou 'semestre'). Regerar
        # tem de saber o método ORIGINAL sem depender do que o body da requisição
        # manda — por isso vive na versão, não é parâmetro solto do regerar.
        if "metodo" not in cols:
            c.execute(
                "ALTER TABLE orc_versao ADD COLUMN metodo TEXT NOT NULL DEFAULT 'espelho'")
        # aprovado_em/aprovado_por: quem travou a versão e quando. Só existem
        # preenchidas em status='aprovado' — reabrir limpa as duas de volta a NULL.
        if "aprovado_em" not in cols:
            c.execute("ALTER TABLE orc_versao ADD COLUMN aprovado_em TEXT")
        if "aprovado_por" not in cols:
            c.execute("ALTER TABLE orc_versao ADD COLUMN aprovado_por TEXT")


def criar_versao(path: Path, ano: int, rotulo: str, fator: float, quem: str,
                 meses_base: list[str] | None = None, metodo: str = "espelho") -> int:
    with _conn(path) as c:
        cur = c.execute(
            "INSERT INTO orc_versao(ano, rotulo, fator_tendencia, criado_por, meses_base, metodo) "
            "VALUES (?,?,?,?,?,?)",
            (ano, rotulo, fator, quem, json.dumps(meses_base) if meses_base else None, metodo))
        return int(cur.lastrowid)


def atualizar_versao(path: Path, versao_id: int, fator: float,
                     meses_base: list[str] | None = None,
                     metodo: str | None = None) -> None:
    """Regeração troca fator e base da versão; ano e rótulo continuam os mesmos.

    `metodo=None` NÃO altera o método gravado — regerar sempre re-deriva pelo
    método ORIGINAL da versão, não pelo que a requisição de regerar mandar.
    """
    with _conn(path) as c:
        cur = c.execute(
            "UPDATE orc_versao SET fator_tendencia=?, meses_base=?, "
            "metodo=coalesce(?, metodo) WHERE id=?",
            (fator, json.dumps(meses_base) if meses_base else None, metodo, versao_id))
        if cur.rowcount == 0:
            raise KeyError(f"versão inexistente: {versao_id}")


def aprovar(path: Path, versao_id: int, quem: str, agora: datetime | None = None) -> None:
    """Aprova a versão — a partir daqui `ajustar` fica bloqueado até reabrir.

    Reaprovar uma versão já aprovada é idempotente: regrava quem/quando (não
    é erro reforçar a aprovação, só é vedado aprovar uma arquivada).
    """
    with _conn(path) as c:
        row = c.execute("SELECT status FROM orc_versao WHERE id=?", (versao_id,)).fetchone()
        if row is None:
            raise KeyError(f"versão inexistente: {versao_id}")
        if row["status"] == "arquivada":
            raise ValueError(
                "Versão arquivada não pode ser aprovada — gere ou regenere uma versão rascunho.")
        quando = (agora or datetime.now()).strftime("%Y-%m-%d %H:%M")
        c.execute(
            "UPDATE orc_versao SET status='aprovado', aprovado_em=?, aprovado_por=? "
            "WHERE id=?", (quando, quem, versao_id))


def reabrir(path: Path, versao_id: int) -> None:
    """Volta a versão para rascunho e limpa quem/quando aprovou.

    Arquivada é registro histórico e não reabre — para corrigir uma versão
    aprovada, reabra ANTES de arquivar (ou arquive uma cópia da rascunho nova).
    """
    with _conn(path) as c:
        row = c.execute("SELECT status FROM orc_versao WHERE id=?", (versao_id,)).fetchone()
        if row is None:
            raise KeyError(f"versão inexistente: {versao_id}")
        if row["status"] == "arquivada":
            raise ValueError(
                "Versão arquivada é registro histórico — não pode ser reaberta.")
        c.execute(
            "UPDATE orc_versao SET status='rascunho', aprovado_em=NULL, aprovado_por=NULL "
            "WHERE id=?", (versao_id,))


def arquivar_copia(path: Path, versao_id: int, rotulo_novo: str) -> int:
    """Congela a versão atual numa cópia histórica com status='arquivada'.

    A original não é tocada (segue podendo ser aprovada/reaberta normalmente);
    a cópia nasce arquivada e imutável. Cabeçalho e todas as linhas (baseline
    E ajuste, fielmente) copiam numa única transação — devolve o id novo.
    """
    with _conn(path) as c:
        original = c.execute(
            "SELECT ano, fator_tendencia, metodo, meses_base, criado_por FROM orc_versao "
            "WHERE id=?", (versao_id,)).fetchone()
        if original is None:
            raise KeyError(f"versão inexistente: {versao_id}")
        cur = c.execute(
            "INSERT INTO orc_versao(ano, rotulo, status, fator_tendencia, metodo, "
            "meses_base, criado_por) VALUES (?,?,'arquivada',?,?,?,?)",
            (original["ano"], rotulo_novo, original["fator_tendencia"],
             original["metodo"], original["meses_base"], original["criado_por"]))
        novo_id = int(cur.lastrowid)
        c.execute(
            "INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline, valor_ajustado, "
            "origem, meses_com_dado, ajustado_em, ajustado_por) "
            "SELECT ?, conta, mes, valor_baseline, valor_ajustado, origem, meses_com_dado, "
            "ajustado_em, ajustado_por FROM orc_linha WHERE versao_id=?",
            (novo_id, versao_id))
        return novo_id


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
    """Grava (ou limpa, com valor=None) o ajuste manual de uma célula.

    Versão aprovada ou arquivada é imutável: reabra antes de ajustar. Versão
    inexistente segue para o KeyError de linha inexistente, como antes.
    """
    with _conn(path) as c:
        versao = c.execute(
            "SELECT status FROM orc_versao WHERE id=?", (versao_id,)).fetchone()
        if versao is not None and versao["status"] != "rascunho":
            raise ValueError(
                "Versão aprovada/arquivada é imutável — reabra antes de ajustar.")
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


def versao_vigente(path: Path, ano: int | None = None) -> dict | None:
    """Escolhe a versão "em uso" dentre `listar_versoes(path, ano)`.

    Regra única, compartilhada por quem precisa de UM default (o painel de
    Fluxo em `caixa.provisao_do_ano` e o endpoint de comparativo sem
    `versao_id`): aprovada tem prioridade sobre rascunho — regerar não pode
    fazer quem lê "a versão atual" saltar silenciosamente para o snapshot
    congelado que o regerar acabou de criar. Arquivada NUNCA é escolhida (é
    histórico, não o orçamento vigente). Versão sem `status` gravado (banco
    de antes desta coluna) é tratada como rascunho.

    `ano=None` varre TODAS as versões (mesmo comportamento de
    `listar_versoes`), útil para "a versão mais recente de qualquer ano".
    """
    versoes = listar_versoes(path, ano)
    if not versoes:
        return None
    aprovada = next((v for v in versoes if v.get("status") == "aprovado"), None)
    if aprovada is not None:
        return aprovada
    return next((v for v in versoes if v.get("status") in (None, "", "rascunho")), None)


def ler_log(path: Path, versao_id: int, limite: int = 200) -> list[dict]:
    with _conn(path) as c:
        rows = c.execute(
            "SELECT * FROM orc_log WHERE versao_id=? ORDER BY id DESC LIMIT ?",
            (versao_id, limite)).fetchall()
        return [dict(r) for r in rows]
