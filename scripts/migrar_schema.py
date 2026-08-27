"""Aplica as migrations do banco local (CLI de `api/migracoes.py`).

Uso:
    uv run python scripts/migrar_schema.py             # schema cortex
    uv run python scripts/migrar_schema.py --conferir  # só diz o que falta
    uv run python scripts/migrar_schema.py --esquema teste_x

Rodar duas vezes é seguro: o que já foi aplicado não roda de novo. É o comando
normal depois de um `git pull` que traga migration nova.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--esquema", default=pglocal.ESQUEMA_PADRAO)
    ap.add_argument("--conferir", action="store_true",
                    help="lista o que falta, sem aplicar")
    args = ap.parse_args()

    if not pglocal.configurado():
        print("banco local não configurado — falta CORTEX_PG_PASSWORD no .env.\n"
              "Ver docs/MIGRACAO_POSTGRES.md, seção 2.")
        return 1
    d = pglocal.diagnostico()
    if not d["conectado"]:
        print(f"sem conexão com {d['onde']} ({d['erro']}).\n"
              "O serviço do PostgreSQL está de pé? A role foi criada?")
        return 1

    falta = migracoes.pendentes(args.esquema)
    if args.conferir:
        print("\n".join(f"pendente {v:04d} — {p.name}" for v, p in falta)
              or f"nada pendente (versão {migracoes.versao_atual(args.esquema)})")
        return 0
    if not falta:
        print(f"nada a aplicar — schema {args.esquema} já está na versão "
              f"{migracoes.versao_atual(args.esquema)}")
        return 0
    migracoes.aplicar(args.esquema, falar=print)
    print(f"schema {args.esquema} na versão {migracoes.versao_atual(args.esquema)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
