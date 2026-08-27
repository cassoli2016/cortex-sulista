"""Leva `data/antt.db` (SQLite) para o PostgreSQL local — piloto da migração.

É o molde dos próximos: cada store da Fase 2 ganha um script deste feitio.
Três regras que valem para todos (ver `docs/MIGRACAO_POSTGRES.md`):

1. **Idempotente.** Rodar duas vezes não duplica: a carga é substituição
   completa, dentro de uma transação.
2. **Confere a contagem.** Ler 223 e gravar 222 é o defeito que ninguém percebe
   na hora e todo mundo descobre um mês depois. O script compara linha a linha
   e sai com código 1 se divergir.
3. **Não apaga a origem.** O `.db` fica onde está. Desfazer é `git revert` do
   módulo, e o dado antigo continua lá.

Uso:
    uv run python scripts/migrar_antt.py            # migra
    uv run python scripts/migrar_antt.py --conferir # só compara os dois lados
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "antt.db"
TABELAS = ("rntrc_transportador", "rntrc_sync")


def _ler_sqlite() -> dict[str, list[dict]]:
    if not ORIGEM.exists():
        return {t: [] for t in TABELAS}
    c = sqlite3.connect(ORIGEM)
    c.row_factory = sqlite3.Row
    try:
        return {t: [dict(r) for r in c.execute(f"SELECT * FROM {t}")]
                for t in TABELAS}
    finally:
        c.close()


def _contar_pg(esquema: str) -> dict[str, int]:
    fora = {}
    for t in TABELAS:
        try:
            r = pglocal.um(f"SELECT count(*) AS n FROM {t}", esquema=esquema)
            fora[t] = int((r or {}).get("n") or 0)
        except Exception:  # noqa: BLE001 — tabela ainda não existe
            fora[t] = 0
    return fora


def migrar(esquema: str | None = None) -> dict:
    alvo = esquema or pglocal.ESQUEMA_PADRAO
    migracoes.aplicar(alvo)
    dados = _ler_sqlite()

    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            # tudo numa transação: se o segundo insert falhar, não fica meia
            # base migrada com a outra metade ainda no SQLite
            cur.execute("DELETE FROM rntrc_transportador")
            if dados["rntrc_transportador"]:
                cur.executemany(
                    """INSERT INTO rntrc_transportador
                       (rntrc, nome, situacao, categoria, uf, municipio,
                        data_situacao)
                       VALUES(%(rntrc)s, %(nome)s, %(situacao)s, %(categoria)s,
                              %(uf)s, %(municipio)s, %(data_situacao)s)""",
                    dados["rntrc_transportador"])
            # o id do sync é IDENTITY no Postgres: não se leva o id da origem,
            # leva-se a ORDEM. O que a tela usa é o mais recente, e a ordem por
            # id da origem é a mesma ordem de inserção aqui.
            cur.execute("DELETE FROM rntrc_sync")
            for linha in sorted(dados["rntrc_sync"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO rntrc_sync(competencia, quando, linhas)"
                    " VALUES(%s,%s,%s)",
                    (linha["competencia"], linha["quando"], linha["linhas"]))

    depois = _contar_pg(alvo)
    return {
        "esquema": alvo,
        "origem": {t: len(v) for t, v in dados.items()},
        "destino": depois,
        "confere": all(len(dados[t]) == depois[t] for t in TABELAS),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--esquema", default=pglocal.ESQUEMA_PADRAO)
    ap.add_argument("--conferir", action="store_true")
    args = ap.parse_args()

    if not pglocal.configurado():
        print("banco local não configurado — ver docs/MIGRACAO_POSTGRES.md")
        return 1
    d = pglocal.diagnostico()
    if not d["conectado"]:
        print(f"sem conexão com {d['onde']} ({d['erro']})")
        return 1

    if args.conferir:
        origem = {t: len(v) for t, v in _ler_sqlite().items()}
        destino = _contar_pg(args.esquema)
        for t in TABELAS:
            marca = "ok" if origem[t] == destino[t] else "DIVERGE"
            print(f"{t:24s} sqlite={origem[t]:6d}  postgres={destino[t]:6d}  {marca}")
        return 0 if origem == destino else 1

    r = migrar(args.esquema)
    for t in TABELAS:
        print(f"{t:24s} {r['origem'][t]:6d} -> {r['destino'][t]:6d}")
    if not r["confere"]:
        print("DIVERGÊNCIA na contagem — o SQLite continua intacto, "
              "não troque o módulo até entender.")
        return 1
    print(f"migrado para o schema {r['esquema']}. "
          f"O data/antt.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
