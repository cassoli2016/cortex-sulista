# scripts/cancelar_cte.py
"""Cancela um CT-e de contrapartida JA AUTORIZADO.

Ato fiscal com PRAZO: passado o prazo da UF, o documento nao se cancela mais -
resolve-se por outros meios, mais caros. Justificativa tem minimo de 15
caracteres, e ela fica no evento para quem ler daqui a um ano.

NAO exige a liberacao de producao. Liberar existe para impedir que se EMITA
sem querer; exigi-la para CANCELAR seria pedir para destravar a emissao a fim
de corrigir uma emissao. Desfazer tem de ser mais facil que fazer.

Uso:
  uv run --no-sync python scripts/cancelar_cte.py <CHAVE> \\
      --justificativa "..." --quem voce@sulista.com.br
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.contrapartida import emissao  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chave")
    ap.add_argument("--justificativa", required=True)
    ap.add_argument("--quem", required=True)
    a = ap.parse_args()

    limpa = "".join(c for c in a.chave if c.isdigit())
    print(f"CANCELAMENTO de {limpa}")
    print(f"  justificativa: {a.justificativa}")
    print(f"  por          : {a.quem}\n")

    try:
        r = emissao.cancelar(limpa, a.justificativa, quem=a.quem)
    except Exception as exc:  # noqa: BLE001
        print(f"FALHOU: {type(exc).__name__}: {str(exc)[:400]}")
        return 1

    print(f"  ambiente  {emissao.AMBIENTES.get(r['ambiente'], r['ambiente'])}")
    print(f"  retorno   {r['cStat']} {r['xMotivo']}")
    print(f"  protocolo {r['protocolo']}")
    print("  CANCELADO" if r["cancelado"] else "  NAO cancelado")
    return 0 if r["cancelado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
