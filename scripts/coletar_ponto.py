# -*- coding: utf-8 -*-
"""Coleta as batidas do Ponto Certificado. Uma execução, sem relógio próprio.

QUEM CHAMA
==========
Uma tarefa agendada do Windows, a cada 10 minutos. O relógio é DELA e não
daqui: script que agenda a si mesmo vira um segundo relógio ao lado do
primeiro, e ninguém sabe qual está valendo.

A cadência de 10 min não é para "tempo real" — a batida chega ao fornecedor em
12 segundos. Ela existe para que uma queda de uma hora custe seis execuções
perdidas e não um dia inteiro de apuração.

O WEBHOOK FICA DE FORA, e é DECISÃO de quem opera (11/09/2026), não pendência.
A API do fornecedor expõe `WebhookSubscription`, e é natural quem reencontrar
isso propor a troca — dez minutos de atraso não incomodam ninguém aqui, e o
push traz porta aberta, segredo de assinatura e uma fila que só falha quando
já falhou. A coleta por cursor é idempotente e se recupera sozinha; o webhook
seria mais peça para manter, resolvendo um problema que a casa não tem.

PRIMEIRA EXECUÇÃO
=================
Sem cursor, ele SEMEIA pelos últimos 7 dias: o cursor do fornecedor não parte
de zero (`ultIdImportado=0` devolve vazio), então alguém precisa dar o ponto
de partida. Depois disso é só cursor.

    uv run python scripts/coletar_ponto.py            # coleta
    uv run python scripts/coletar_ponto.py --semear   # força a semeadura
    uv run python scripts/coletar_ponto.py --dias 30  # janela da semeadura
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta as batidas do Ponto Certificado.")
    p.add_argument("--semear", action="store_true",
                   help="faz a primeira carga por período, mesmo já havendo cursor")
    p.add_argument("--dias", type=int, default=7,
                   help="janela da semeadura, em dias (padrão: 7)")
    p.add_argument("--paginas", type=int, default=None,
                   help="teto de páginas nesta execução")
    args = p.parse_args()

    from api.pontocertificado import cliente, coleta

    if not cliente.configurado():
        # Sem credencial NÃO é falha: é instalação incompleta. Sair com erro
        # aqui encheria o log do agendador de vermelho todo dia numa máquina
        # onde a integração simplesmente não foi contratada.
        print("ponto certificado: " + cliente.o_que_falta())
        return 0

    origem = (cliente.credencial() or {}).get("origem")
    if origem == "globus":
        print("aviso: usando a credencial EMPRESTADA do ERP — cadastre a própria "
              "em Integrações › Ponto Certificado")

    if args.semear or not coleta.cursor():
        fim = date.today()
        ini = fim - timedelta(days=max(1, args.dias))
        r = coleta.semear(ini.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y"))
        print("semeadura:", r)
        if not r.get("semeado") and not coleta.cursor():
            return 1

    cercas = coleta.sincronizar_cercas()
    print("cercas:", cercas)

    r = coleta.coletar(**({"max_paginas": args.paginas} if args.paginas else {}))
    print("coleta:", r)

    e = coleta.estado()
    print("estado:", {"ultima_batida": e.get("ultima_batida"),
                      "por_situacao": e.get("por_situacao"),
                      "cercas": e.get("cercas")})
    # Falha de rede NÃO é falha da tarefa: o cursor ficou no lugar certo e a
    # próxima execução continua. Sair 1 aqui faria o agendador marcar erro a
    # cada tropeço do fornecedor.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
