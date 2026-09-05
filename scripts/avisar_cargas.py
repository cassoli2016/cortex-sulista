# -*- coding: utf-8 -*-
"""Aviso horario das cargas acompanhadas, por WhatsApp.

Roda de hora em hora pela tarefa agendada do Windows. NUNCA levanta: a tarefa
que morre com excecao some do radar, e o sintoma dela e identico ao de "nao ha
nada para avisar" — que e exatamente o estado que ela deveria distinguir.

ENSAIO: `--ensaio` monta as mensagens e NAO envia. E como se confere o texto
antes de ele sair para o numero de um cliente, e e o primeiro comando a rodar
depois de mexer no `api/rastreio/aviso.py`.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)

ensaio = "--ensaio" in sys.argv

try:
    from api.rastreio import aviso
except Exception as exc:  # noqa: BLE001
    print("FALHOU ao carregar o modulo: %s: %s" % (type(exc).__name__, exc))
    raise SystemExit(1)

try:
    r = aviso.rodar(ensaio=ensaio)
except Exception as exc:  # noqa: BLE001
    print("FALHOU: %s: %s" % (type(exc).__name__, str(exc)[:200]))
    raise SystemExit(2)

marca = " [ENSAIO — nada enviado]" if ensaio else ""
print("OK%s" % marca)
print("  %s inscricao(oes) ativa(s)" % r["inscricoes"])
print("  enviadas: %s | iguais a anterior (nao reenviadas): %s"
      % (r["enviados"], r["iguais"]))
print("  sem novidade para contar: %s | encerradas por entrega: %s"
      % (r["sem_texto"], r["encerradas"]))
if r["falhas"]:
    print("  ATENCAO: %s envio(s) recusado(s) — ver o log da API" % r["falhas"])
for a in r.get("amostra") or []:
    print("  exemplo (…%s): %s" % (a["telefone"], a["texto"][:110]))
