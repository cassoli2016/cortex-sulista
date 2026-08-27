"""Migrations do banco local — aplica `sql/cortex/NNNN_*.sql`.

Trinta linhas em vez do Alembic de propósito: o Alembic deste repositório está
apontado para o schema DA ARQUITETURA (`migrations/versions/0001..0006`, que
nunca rodou), com a tabela de versão dele. Enfiar duas cadeias na mesma
ferramenta confunde justamente na hora em que se está com o banco na mão.

Regras:

- ordem pelo NÚMERO do arquivo, sempre;
- cada migration roda na sua transação: a que falha não deixa metade aplicada,
  e o registro em `schema_versao` entra na MESMA transação do DDL — senão um
  erro no meio deixaria o schema alterado e o runner achando que não aplicou;
- o que já está registrado não roda de novo, então chamar duas vezes é seguro
  e é o modo normal de usar depois de um `git pull`;
- funciona em QUALQUER schema, que é como o teste aplica este mesmo schema num
  universo isolado (ver `docs/MIGRACAO_POSTGRES.md`).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import pglocal

ROOT = Path(__file__).resolve().parent.parent
DIR_SQL = ROOT / "sql" / "cortex"
_NUM = re.compile(r"^(\d{4})_")


def _arquivos() -> list[tuple[int, Path]]:
    return sorted(((int(m.group(1)), p) for p in DIR_SQL.glob("*.sql")
                   if (m := _NUM.match(p.name))), key=lambda x: x[0])


def versao_atual(esquema: str | None = None) -> int | None:
    try:
        r = pglocal.um("SELECT max(versao) AS v FROM schema_versao",
                       esquema=esquema)
    except Exception:  # noqa: BLE001 — schema novo não tem a tabela ainda
        return None
    return (r or {}).get("v")


def pendentes(esquema: str | None = None) -> list[tuple[int, Path]]:
    """O que falta, na ordem. Schema sem `schema_versao` é schema novo: tudo
    está pendente, inclusive a migration que cria a própria tabela."""
    try:
        feitas = {r["versao"] for r in pglocal.query(
            "SELECT versao FROM schema_versao", esquema=esquema)}
    except Exception:  # noqa: BLE001
        feitas = set()
    return [(v, p) for v, p in _arquivos() if v not in feitas]


def aplicar(esquema: str | None = None, falar=None) -> list[int]:
    """Aplica o que falta. Devolve as versões aplicadas NESTA chamada."""
    alvo = esquema or pglocal.ESQUEMA_PADRAO
    pglocal.criar_esquema(alvo)
    feitas: list[int] = []
    for versao, arquivo in pendentes(alvo):
        with pglocal.get_conn(alvo) as conn:
            with conn.cursor() as cur:
                cur.execute(arquivo.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_versao(versao, arquivo) VALUES(%s, %s)",
                    (versao, arquivo.name))
        feitas.append(versao)
        if falar:
            falar(f"aplicada {versao:04d} — {arquivo.name}")
    return feitas
