# -*- coding: utf-8 -*-
"""Coleta do Gerenciamento de Risco (RasterIntegra) — viagens e km.

POR QUE EXISTE: a aba "Risco por viagem" lê o BANCO, não a Raster — a tela
abre em milissegundos e não cai junto com o fornecedor. O preço é este: sem
coleta o banco envelhece e a aba mostra o risco de anteontem como se fosse
o de hoje. A tarefa agendada roda de madrugada; a trilha fica em gr_carga e
a Saúde do Servidor mede o frescor dali.

A coleta é POR PLACA (o único filtro que o servidor respeita — medido em
01/09/2026) e respeita o rate-limit com pausa entre chamadas: ~80 placas
por noite ≈ 20 minutos. O --backfill puxa até 12 meses de histórico, uma
chamada por placa da frota GR (~300 placas ≈ 75 min — rodar UMA vez).

Uso:
  uv run --no-sync python scripts/coletar_gr.py            # viagens D-8 + km D-1/D-2
  uv run --no-sync python scripts/coletar_gr.py --so-km
  uv run --no-sync python scripts/coletar_gr.py --backfill # histórico 12m
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.rasterintegra import cliente, coleta  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-km", action="store_true",
                    help="só o km diário (getKMRodado)")
    ap.add_argument("--backfill", action="store_true",
                    help="histórico de até 12 meses, uma chamada por placa")
    a = ap.parse_args()

    # SEM CREDENCIAL NÃO É FALHA, é instalação incompleta. Sair com 0 evita
    # que o agendador marque a tarefa como quebrada onde a integração ainda
    # não foi ligada.
    if not cliente.configurado():
        print("rasterintegra: credencial nao configurada (Gestao > "
              "Integracoes > RasterIntegra) - nada a fazer")
        return 0

    if a.backfill:
        r = coleta.backfill_viagens()
        print(f"backfill: {r['placas']} placas, {r['gravadas']} viagens finalizadas")
        return 0

    if not a.so_km:
        r = coleta.coletar_viagens()
        print(f"viagens: {r['placas']} placas ({r['janela']}), "
              f"{r['gravadas']} finalizadas gravadas")
    r = coleta.coletar_km()
    print(f"km: {r['dias']} dias, {r['gravadas']} linhas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
