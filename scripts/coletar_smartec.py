"""Coleta da Smartec — infrações, notificações, licenças, ANTT e acessos.

POR QUE ESTA ROTINA EXISTE SEPARADA DO ENVIO
============================================
O aviso de prazo de indicação lê o BANCO, não a Smartec. Isso é de propósito
(a tela abre em milissegundos e não cai junto se o fornecedor estiver fora),
mas cria uma dependência que só se enxerga quando quebra: **sem coleta, o
banco envelhece e o aviso silencia** — e silêncio, ali, é indistinguível de
"está tudo indicado".

O provedor do WhatsApp recusa dado velho (`HORAS_FRESCOR`), então a falha
aparece como recusa explícita em vez de silêncio. Mas quem impede a recusa é
esta rotina rodar.

CADÊNCIA: duas vezes ao dia, antes dos horários em que o aviso costuma sair.
A varredura inteira leva ~20 s e faz ~265 chamadas — todas de LEITURA, e todas
contra o banco de dados da Smartec (não contra o DETRAN), então não há custo
por consulta a órgão.

Uso:
  uv run --no-sync python scripts/coletar_smartec.py
  uv run --no-sync python scripts/coletar_smartec.py --so-infracoes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.smartec import cliente, coleta  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-infracoes", action="store_true",
                    help="só multas e notificações (o que muda todo dia)")
    a = ap.parse_args()

    # SEM TOKEN NÃO É FALHA, é instalação incompleta. Sair com 0 evita que o
    # agendador do Windows marque a tarefa como quebrada num servidor em que a
    # integração simplesmente ainda não foi ligada.
    if not cliente.configurado():
        print("smartec: token nao configurado (Gestao > Credenciais > "
              "SMARTEC_TOKEN) - nada a fazer")
        return 0

    if a.so_infracoes:
        passos = (("multas", coleta.coletar_multas),
                  ("notificacoes", coleta.coletar_notificacoes))
        r = {"ok": True, "recursos": {}, "erros": {}}
        for nome, fn in passos:
            try:
                r["recursos"][nome] = fn()
            except Exception as exc:  # noqa: BLE001
                r["erros"][nome] = f"{type(exc).__name__}: {exc}"
                r["ok"] = False
    else:
        r = coleta.coletar_tudo()

    if r.get("erro") == "sem_token":
        print("smartec: " + r.get("mensagem", ""))
        return 0

    for nome, d in (r.get("recursos") or {}).items():
        extra = ""
        if "veiculos" in d:
            extra = (f" | {d['veiculos']} veiculos"
                     f"{'' if d.get('completa') else ' (COLETA INCOMPLETA)'}")
        print(f"  {nome:14} {d.get('itens', 0):>6} itens"
              f" em {d.get('chamadas', 0):>4} chamadas{extra}")
    for nome, e in (r.get("erros") or {}).items():
        print(f"  ERRO {nome:10} {e[:180]}")

    # Falha de UM recurso não derruba a rotina inteira: os outros sete
    # coletaram, e o que falhou já está em `smt_carga` e no cartão da Saúde.
    # Sair diferente de zero aqui faria o agendador do Windows pintar de
    # vermelho uma passagem que trouxe 95% do dado.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
