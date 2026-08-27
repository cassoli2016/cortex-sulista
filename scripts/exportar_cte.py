# scripts/exportar_cte.py
"""Grava em disco os CT-e de contrapartida AUTORIZADOS, para importar no ERP.

Sai um arquivo por documento, no formato `cteProc` - o XML assinado MAIS o
protocolo de autorizacao. E esse o arquivo que um importador de CT-e espera:
o documento sozinho, sem o protocolo, nao prova que foi autorizado.

Nomeado pela CHAVE, que e como todo importador procura, e separado por
ambiente. Misturar homologacao com producao na mesma pasta e o caminho mais
curto para alguem importar documento de teste como se valesse.

Uso:
  uv run --no-sync python scripts/exportar_cte.py
  uv run --no-sync python scripts/exportar_cte.py --producao
  uv run --no-sync python scripts/exportar_cte.py --desde 2026-08-01 --destino D:\\cte
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.contrapartida import emissao  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--destino", default=None,
                    help="pasta de saida (padrao: data/cte_contrapartida)")
    ap.add_argument("--producao", action="store_true")
    ap.add_argument("--desde", default=None, help="AAAA-MM-DD")
    a = ap.parse_args()
    ambiente = emissao.PRODUCAO if a.producao else emissao.HOMOLOGACAO

    r = emissao.exportar(a.destino, ambiente=ambiente, desde=a.desde)
    print(f"ambiente : {emissao.AMBIENTES[ambiente]}")
    print(f"pasta    : {r['pasta']}")
    print(f"exportados: {r['exportados']}")
    if r["autorizados_sem_arquivo"]:
        # Numero grande sempre acompanhado do que o desarma: estes foram
        # autorizados ANTES de o sistema passar a guardar o XML, entao nao ha
        # arquivo para gerar. Nao e falha da exportacao.
        print(f"sem arquivo guardado: {r['autorizados_sem_arquivo']}"
              f"  (autorizados antes de o XML passar a ser guardado)")
    for f in r["falhas"]:
        print(f"  FALHOU {f['chave']}: {f['erro']}")
    return 1 if r["falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
