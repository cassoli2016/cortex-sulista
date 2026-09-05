# -*- coding: utf-8 -*-
"""Tira de `pne_inspecao` as fotos que nao dizem nada.

O QUE ACONTECEU. A semeadura da Prolog roda de 20 em 20 minutos e gravava o
instantaneo INTEIRO a cada rodada: 7.865 linhas por vez, 566 mil por dia. O
sulco de um pneu nao muda em vinte minutos — medido, 100% dos pares
consecutivos eram IDENTICOS ao anterior. Eram 267 mil linhas com zero
informacao, a caminho de 200 milhoes por ano.

A causa foi consertada em `api/pneus/replica.py` (a foto so vira linha quando a
medicao MUDA). Este script limpa o que ja entrou.

O QUE ELE APAGA, e so isso: linha de FOTO (`prolog_id` comecando em `snap:`)
cujo valor e igual ao da linha anterior do MESMO pneu. A primeira ocorrencia de
cada valor FICA — e ela que marca o momento em que o sulco mudou, e e dela que
a serie de desgaste e feita.

O QUE ELE NUNCA TOCA: as medicoes vindas de movimentacao (`rel:`), que sao
leituras de verdade feitas no patio, com data propria.

  uv run python scripts/limpar_inspecoes_repetidas.py --ensaio   # so mede
  uv run python scripts/limpar_inspecoes_repetidas.py            # apaga
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)

from api import pglocal  # noqa: E402

# A COMPARACAO E COM A LINHA ANTERIOR DO MESMO PNEU, em ordem de tempo — e ela
# considera TODAS as linhas, inclusive as de movimentacao. Uma foto que repete
# uma medicao de patio tambem nao acrescenta nada.
ALVO_SQL = """
WITH s AS (
  SELECT id, pneu_id, prolog_id,
         sulcos_mm::text  AS v,
         pressao_psi::text AS p,
         lag(sulcos_mm::text)  OVER (PARTITION BY pneu_id ORDER BY medido_em, id) AS v_ant,
         lag(pressao_psi::text) OVER (PARTITION BY pneu_id ORDER BY medido_em, id) AS p_ant
  FROM pne_inspecao
)
SELECT id FROM s
WHERE strpos(coalesce(prolog_id,''), 'snap:') = 1
  AND v_ant IS NOT NULL
  AND v IS NOT DISTINCT FROM v_ant
  AND p IS NOT DISTINCT FROM p_ant
"""


def main() -> int:
    ensaio = "--ensaio" in sys.argv
    total = pglocal.query("SELECT count(*) AS n FROM pne_inspecao")[0]["n"]
    alvo = pglocal.query("SELECT count(*) AS n FROM (%s) t" % ALVO_SQL)[0]["n"]
    reais = pglocal.query(
        "SELECT count(*) AS n FROM pne_inspecao "
        "WHERE strpos(coalesce(prolog_id,''), 'rel:') = 1")[0]["n"]

    print("linhas hoje                 : %s" % format(total, ","))
    print("  medicoes de movimentacao  : %s (intocadas)" % format(reais, ","))
    print("  fotos repetidas a apagar  : %s" % format(alvo, ","))
    print("  ficam                     : %s" % format(total - alvo, ","))
    if not alvo:
        print("\nNada a fazer.")
        return 0
    if ensaio:
        print("\n[ENSAIO — nada foi apagado]")
        return 0

    # EM LOTES: um DELETE de 267 mil linhas segura a tabela inteira, e esta
    # tabela e escrita pela coleta a cada 20 minutos.
    apagadas = 0
    while True:
        n = pglocal.executar(
            "DELETE FROM pne_inspecao WHERE id IN "
            "(SELECT id FROM (%s) t LIMIT 20000)" % ALVO_SQL)
        apagadas += n or 0
        print("  apagadas %s…" % format(apagadas, ","))
        if not n:
            break
    print("\nOK: %s linhas apagadas." % format(apagadas, ","))
    print("A causa esta consertada em api/pneus/replica.py — a foto so vira "
          "linha quando a medicao muda.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
