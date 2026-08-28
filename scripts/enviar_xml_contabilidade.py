# scripts/enviar_xml_contabilidade.py
"""Manda para a contabilidade os XML de PRODUCAO que ainda nao sairam.

A rotina normal nao precisa deste script: ela roda pendurada no lote de
emissao (`api/contrapartida/lote.py`), logo depois de cada rodada. Isto aqui e
para as tres situacoes em que alguem precisa agir:

  - CONFERIR sem mandar nada (--ensaio), que e como se olha a fila;
  - MANDAR AGORA, quando a contabilidade pede e nao se quer esperar a proxima
    rodada do lote;
  - REENFILEIRAR o que ficou parado depois de bater o teto de tentativas, uma
    vez consertada a causa (endereco errado, SMTP fora do ar).

O interruptor continua sendo o da tela: com o envio DESLIGADO em Gestao >
Integracoes, o script sai sem mandar nada e diz isso. Um atalho de linha de
comando que ignorasse o interruptor tornaria o interruptor decorativo.

Uso:
  uv run --no-sync python scripts/enviar_xml_contabilidade.py --ensaio
  uv run --no-sync python scripts/enviar_xml_contabilidade.py
  uv run --no-sync python scripts/enviar_xml_contabilidade.py --reenfileirar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.contrapartida import xml_email  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true",
                    help="percorre a fila e NAO manda")
    ap.add_argument("--limite", type=int, default=xml_email.MAX_POR_EXECUCAO)
    ap.add_argument("--quem", default="scripts/enviar_xml_contabilidade.py",
                    help="quem aparece na trilha")
    ap.add_argument("--reenfileirar", action="store_true",
                    help="devolve a fila o que estava PARADO e sai")
    a = ap.parse_args()

    if a.reenfileirar:
        r = xml_email.reenfileirar(a.quem)
        print(f"reenfileirados: {r['reenfileirados']}")
        return 0

    st = xml_email.estado()
    print(f"envio      : {'LIGADO' if st['ativo'] else 'DESLIGADO'}")
    print(f"destino    : {st['destinatarios']}")
    print(f"corte      : {st['corte']}")
    print(f"ja enviados: {st['enviados']}")
    if st["parados"]:
        # Numero grande sempre acompanhado do que fazer com ele: parado nao
        # sai da fila sozinho, e sem esta linha ele some da vista.
        print(f"PARADOS    : {st['parados']} (bateram {st['max_tentativas']} "
              f"tentativas — use --reenfileirar depois de consertar a causa)")

    r = xml_email.enviar_pendentes(a.quem, limite=a.limite, ensaio=a.ensaio)
    print(f"\npendentes  : {r['pendentes']}")
    print(f"resultado  : {r['motivo']}")
    if r["enviados"]:
        print(f"enviados   : {r['enviados']} em {r['mensagens']} mensagem(ns)")
    for e in r["erros"]:
        print(f"  ERRO: {e}")

    # Sai com erro so quando houve FALHA de envio. "Desligado" e "nada novo"
    # sao o caso normal, e marca-los como falha encheria de vermelho o
    # historico de quem roda isto num agendador.
    return 2 if not r["ok"] and r["falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
