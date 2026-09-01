# -*- coding: utf-8 -*-
"""Coleta da Monkey Exchange — a posição de antecipação da Tupy.

POR QUE EXISTE: o painel de Antecipações lê o BANCO (ant_envios/ant_titulos),
não a Monkey. Sem coleta, a posição da Tupy envelhece calada — e posição de
antecipação velha é oferta perdida: o título ACTIVE de hoje pode estar SOLD
amanhã.

A varredura é COMPLETA de propósito (todas as páginas de cada seller, ~500
chamadas): o search da Monkey se invalida com paginação e uma busca que
voltasse vazia por mudança do lado deles gravaria posição vazia em cima de
posição real, em silêncio. A varredura completa é autoverificável — 48 mil
linhas de histórico provam que ela enxergou tudo. Só a POSIÇÃO (em aberto)
vira envio; se nada mudou, nenhum envio novo é criado (hash do conteúdo).

Uso:
  uv run --no-sync python scripts/coletar_monkey.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.monkey import cliente, servico  # noqa: E402


def main() -> int:
    # SEM CREDENCIAL NÃO É FALHA, é instalação incompleta — sair com 0 evita
    # que o agendador marque a tarefa como quebrada onde a integração ainda
    # não foi ligada.
    if not cliente.configurado():
        print("monkey: credencial nao configurada (Gestao > Integracoes > "
              "Monkey Exchange) - nada a fazer")
        return 0

    r = servico.coletar(usuario="coleta agendada")
    print(f"monkey [{r['ambiente']}]: {r['sellers']} sellers, "
          f"{r['recebidos']} recebiveis varridos, "
          f"{r['gravados']} na posicao ({r['fora_da_posicao']} historicos), "
          f"{r['antecipaveis']} antecipaveis"
          + (" - posicao IGUAL, nenhum envio novo" if r["sem_mudanca"] else
             f" - envio {r['envio_id']}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
