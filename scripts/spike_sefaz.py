# scripts/spike_sefaz.py
"""Consulta se a SEFAZ da UF do agregado esta no ar. NAO emite nada.

Usa a camada de compatibilidade em api/contrapartida/sefaz.py, onde moram as
quatro correcoes que a biblioteca exigiu no caminho de CT-e. Serve para
conferir um certificado novo antes de confiar nele, e para saber se a SEFAZ
esta fora antes de culpar o codigo.

Uso:  uv run python scripts/spike_sefaz.py <CNPJ> [UF]
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from api.contrapartida.sefaz import status_servico  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: spike_sefaz.py <CNPJ> [UF]")
        return 2
    cnpj = "".join(c for c in sys.argv[1] if c.isdigit())
    uf = (sys.argv[2] if len(sys.argv) > 2 else "").upper()
    if not uf:
        # a UF e a do EMITENTE: cada SEFAZ so atende os seus contribuintes,
        # entao usar a da Sulista mandaria o pedido para o lugar errado
        from api import db
        linha = db.query("SELECT uf FROM cadastro WHERE codigo = %(c)s",
                         {"c": cnpj})
        uf = ((linha[0]["uf"] if linha else "") or "").strip().upper()
        if not uf:
            print("UF do emitente ausente no cadastro — informe na linha de comando.")
            return 2
    try:
        r = status_servico(cnpj, uf)
    except Exception as exc:  # noqa: BLE001
        print(f"FALHOU: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    print(f"SEFAZ {uf} — homologacao")
    for k, v in r.items():
        print(f"  {k:12} {v}")
    return 0 if r.get("em_operacao") else 1


if __name__ == "__main__":
    raise SystemExit(main())
