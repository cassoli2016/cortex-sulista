"""Coleta da jornada da RasterJOR para o banco local do CÓRTEX.

Uso:
    uv run python scripts/coletar_jornada.py              # últimos 7 dias
    uv run python scripts/coletar_jornada.py --dias 30
    uv run python scripts/coletar_jornada.py --de 2026-01-01 --ate 2026-01-31
    uv run python scripts/coletar_jornada.py --carga-ava  # histórico, uma vez

É este o comando da tarefa agendada do Windows. Rodar duas vezes é seguro e é
o modo NORMAL de usar: a API devolve o dia inteiro a cada chamada e o dia só
fecha à noite, então toda gravação é `ON CONFLICT … DO UPDATE` sobre a chave
natural.

SAI COM CÓDIGO 1 QUANDO ALGUM RECURSO FALHA, para o agendador registrar. Mas
grava a trilha em `jor_carga` de qualquer jeito — é dela que a Saúde do
Servidor tira o alarme, e um agendador que só olha o código de saída não conta
a ninguém o que aconteceu.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import pglocal  # noqa: E402
from api.jornada import cliente, coleta  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--de", help="data inicial (aaaa-mm-dd)")
    ap.add_argument("--ate", help="data final (aaaa-mm-dd)")
    ap.add_argument("--dias", type=int, default=None,
                    help=f"janela em dias (padrão {coleta.JANELA_DIAS})")
    ap.add_argument("--recurso", action="append",
                    choices=list(cliente.RECURSOS),
                    help="só este recurso; pode repetir")
    ap.add_argument("--carga-ava", action="store_true",
                    help="carga inicial do histórico de sulista.rasterjor_*")
    args = ap.parse_args()

    if not pglocal.configurado():
        print("banco local não configurado — falta CORTEX_PG_PASSWORD no .env.")
        return 1

    recursos = tuple(args.recurso) if args.recurso else None

    if args.carga_ava:
        print("carga inicial a partir do AVA (sulista.rasterjor_*)…")
        r = coleta.carga_ava(recursos=recursos)
        for nome, v in r["recursos"].items():
            marca = "ok " if v["ok"] else "FALHOU"
            print(f"  {marca} {nome:<18} lidos {v['lidos']:>7,} · "
                  f"gravados {v['gravados']:>7,}"
                  + (f" · {v.get('erro','')}" if not v["ok"] else ""))
        return 0 if r["ok"] else 1

    de, ate = args.de, args.ate
    if args.dias and not de:
        de = (date.today() - timedelta(days=args.dias)).isoformat()

    r = coleta.coletar(de=de, ate=ate, recursos=recursos)
    if not r["ok"] and not r["recursos"]:
        # não configurado: a mensagem já diz o que falta e onde preencher
        print(r["erro"])
        return 1
    # ASCII no que vai para o console: a tarefa agendada do Windows roda em
    # cp1252 e uma seta unicode derruba o script DEPOIS de a coleta ter dado
    # certo — falha que não é falha, e que o agendador registra como erro.
    print(f"janela {r['de']} ate {r['ate']}")
    for nome, v in r["recursos"].items():
        marca = "ok " if v["ok"] else "FALHOU"
        print(f"  {marca} {nome:<18} lidos {v['lidos']:>7,} · "
              f"gravados {v['gravados']:>7,}"
              + (f" · {v['erro']}" if not v["ok"] else ""))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
