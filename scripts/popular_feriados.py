"""Busca os feriados nacionais na web (BrasilAPI) e grava no calendário da casa.

A rotina dos relatórios por e-mail já faz isto sozinha quando falta um ano
(`calendario.garantir`); este script é para a primeira carga e para rebuscar
um ano de propósito. Ver `api/calendario.py`.

Uso:
  uv run --no-sync python scripts/popular_feriados.py            # ano corrente e o próximo
  uv run --no-sync python scripts/popular_feriados.py 2026 2027
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import calendario  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("anos", nargs="*", type=int)
    a = ap.parse_args()
    anos = a.anos or [date.today().year, date.today().year + 1]
    falhas = 0
    for ano in anos:
        try:
            r = calendario.popular(ano)
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            print(f"{ano}: FALHOU — {type(exc).__name__}: {exc} (vale a lista da lei)")
            continue
        print(f"{ano}: {r['itens']} datas, {r['folgas']} contam como folga")
        for d in r["divergencias"]:
            print(f"   a conferir: {d}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
