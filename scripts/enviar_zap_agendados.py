"""Percorre a agenda de WhatsApp e envia o que está na hora.

Irmão do `enviar_agendados.py` (e-mail), com o mesmo desenho: o agendador do
Windows NÃO decide nada — ele dispara de tempos em tempos e pergunta ao CÓRTEX
se já passou a hora, lendo o horário configurado na tela. Assim mudar horário
ou destinatário vale na hora, sem reinstalar tarefa.

A diferença que importa em relação ao e-mail: aqui, **dado ruim não vira
mensagem**. Se os números não vierem completos, a rotina registra o motivo e
não envia — uma automação que manda "Faturamento de hoje: R$ 0,00" para a
diretoria às 8h assusta na primeira vez e, na segunda, vira um remetente que
ninguém lê.

Uso:
  uv run --no-sync python scripts/enviar_zap_agendados.py            # de verdade
  uv run --no-sync python scripts/enviar_zap_agendados.py --ensaio   # não envia
  uv run --no-sync python scripts/enviar_zap_agendados.py --forcar 3 # agora, id 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.whatsapp import agenda  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true",
                    help="percorre tudo e NÃO envia")
    ap.add_argument("--forcar", type=int, metavar="ID",
                    help="envia esta rotina agora, fora do horário")
    a = ap.parse_args()

    try:
        itens = agenda.listar()
    except Exception as exc:  # noqa: BLE001
        print(f"nao foi possivel ler a agenda: {type(exc).__name__}: {exc}")
        return 1

    if a.forcar:
        alvo = [x for x in itens if int(x["id"]) == a.forcar]
        if not alvo:
            print(f"rotina {a.forcar} nao existe")
            return 1
        print(agenda.executar(alvo[0], ensaio=a.ensaio, forcado=True))
        return 0

    if not itens:
        print("nenhuma rotina cadastrada")
        return 0

    enviados = falhas = 0
    for ag in itens:
        pode, porque = agenda.deve_rodar(ag)
        if not pode:
            print(f" --   #{ag['id']} {ag['modelo']}: {porque}")
            continue
        linha = agenda.executar(ag, ensaio=a.ensaio)
        print(linha)
        if linha.startswith("OK"):
            enviados += 1
        elif linha.startswith("FALHA"):
            falhas += 1

    print(f"\n{len(itens)} rotina(s) · {enviados} enviada(s) · {falhas} falha(s)")
    # Sai com erro só quando houve FALHA de envio: "não era hora" é o caso
    # normal, e marcá-lo como falha encheria o histórico do agendador do
    # Windows de vermelho a cada disparo.
    return 2 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
