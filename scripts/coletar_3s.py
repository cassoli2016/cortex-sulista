"""Coleta da 3S: cadastro de veículos e última posição de cada um.

Roda a cada 30 minutos pela tarefa do Windows. É barata (duas chamadas, ~1 s,
250 KB) e IDEMPOTENTE — repetir não duplica, e o agendador repete quando a
máquina acorda.

POR QUE 30 MINUTOS e não uma vez por dia: a régua diária pergunta "comunicou
NAQUELE dia", e quem responde isso é o registro do dia de cada posição. Uma
coleta diária só veria a última posição no instante em que rodasse e perderia
todo mundo que falou entre uma e outra.

Uso:
  uv run --no-sync python scripts/coletar_3s.py
  uv run --no-sync python scripts/coletar_3s.py --estado   # só mostra, não coleta
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.tress import armazenamento, cliente, coleta  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--estado", action="store_true",
                   help="mostra o espelho e sai")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.estado:
        for k, v in armazenamento.estado().items():
            print("  %-18s %s" % (k, v))
        return 0

    if not cliente.configurado():
        # SEM CREDENCIAL NÃO É FALHA: é instalação incompleta. Sair com erro
        # aqui encheria o log do agendador de vermelho todo dia numa máquina
        # onde a integração simplesmente não foi ligada.
        print("3S sem credencial — nada a coletar (Gestão › Integrações › 3S)")
        return 0

    try:
        r = coleta.coletar()
    except cliente.TressIndisponivel as exc:
        print("FALHA na coleta da 3S: %s" % exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        print("FALHA inesperada na coleta da 3S: %s" % type(exc).__name__)
        return 1
    print("OK  %d veículos · %d posições · %d dias marcados · %d sumiram · %.1fs"
          % (r["veiculos"], r["posicoes"], r["dias_marcados"], r["sumiram"],
             r["segundos"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
