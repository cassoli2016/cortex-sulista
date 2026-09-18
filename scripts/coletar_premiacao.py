# -*- coding: utf-8 -*-
"""Coleta a nota da Gobrax do mês — o pilar de CONDUÇÃO da Gestão de Motoristas.

POR QUE ESTE SCRIPT NASCEU EM 18/09/2026: até hoje a coleta da Gobrax era um
EFEITO COLATERAL de alguém abrir a tela da premiação antiga — `servico.obter()`
recoleta quando não há snapshot do mês ou quando o do mês corrente passou de
uma hora. Com as abas do modelo antigo fora da tela, ninguém mais chama aquela
rota, e o pilar de condução da régua nova congelaria no último snapshot que
alguém pediu por acaso.

A FALHA SERIA MUDA, que é o que a torna cara: a nota não some da tela — ela
simplesmente para de mudar, ou o ciclo novo nasce "sem leitura da Gobrax" e a
nota composta se renormaliza entre os outros dois pilares, em silêncio, para a
frota inteira. Quem lê o ranking não tem como desconfiar.

A coleta é IDEMPOTENTE (o snapshot do mês é regravado) e o mês FECHADO nunca é
recoletado sem `--force`: reescrever um mês já pago é o defeito que o
fechamento existe para impedir.

Uso:
  uv run --no-sync python scripts/coletar_premiacao.py            # mês corrente
  uv run --no-sync python scripts/coletar_premiacao.py --mes 2026-08
  uv run --no-sync python scripts/coletar_premiacao.py --force    # recoleta mesmo fresco
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.premiacao import servico  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta a nota da Gobrax do mês.")
    p.add_argument("--mes", help="competência AAAA-MM (padrão: o mês corrente)")
    p.add_argument("--force", action="store_true",
                   help="recoleta mesmo com snapshot fresco")
    a = p.parse_args()
    mes = a.mes or date.today().strftime("%Y-%m")

    try:
        d = servico.obter(mes, force=a.force)
    except Exception as exc:  # noqa: BLE001
        # SEM CREDENCIAL NÃO É FALHA, É INSTALAÇÃO INCOMPLETA — e a diferença
        # importa para o agendador do Windows: sair com erro encheria o
        # histórico de vermelho numa casa que simplesmente não contratou o
        # recurso. Quem diz isso de verdade é o cartão da Saúde.
        nome = type(exc).__name__
        print(f"{mes}: nao coletou ({nome}: {exc})")
        return 0 if "NaoConfigurado" in nome else 2

    if not d.get("configurado"):
        print(f"{mes}: Gobrax nao configurada — nada a coletar")
        return 0
    k = d.get("kpis") or {}
    print(f"{mes}: {k.get('motoristas', 0)} motorista(s) · "
          f"{k.get('km_total', 0):.0f} km · coletado em {d.get('coletado_em')}"
          + (f" · AVISO: {d['aviso']}" if d.get("aviso") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
