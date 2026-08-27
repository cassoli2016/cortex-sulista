"""Leva `data/push.db` (SQLite) para o PostgreSQL local.

Mesmo molde de `migrar_antt.py`: idempotente, confere a contagem e não apaga a
origem. Aqui as duas tabelas têm chave natural (`endpoint` e `chave`), então a
carga é `ON CONFLICT DO UPDATE` — rodar duas vezes não duplica nem perde
inscrição que tenha chegado no meio.

Uso:
    uv run python scripts/migrar_push.py
    uv run python scripts/migrar_push.py --conferir
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "push.db"
# (origem no SQLite, destino no Postgres) — o prefixo do módulo entra aqui
TABELAS = (("subs", "push_subs"), ("meta", "push_meta"))


def _ler_sqlite() -> dict[str, list[dict]]:
    """Chaveado pelo nome de DESTINO, para os dois lados casarem na conferência."""
    if not ORIGEM.exists():
        return {destino: [] for _, destino in TABELAS}
    c = sqlite3.connect(ORIGEM)
    c.row_factory = sqlite3.Row
    try:
        return {destino: [dict(r) for r in c.execute(f"SELECT * FROM {origem}")]
                for origem, destino in TABELAS}
    finally:
        c.close()


def _contar_pg(esquema: str) -> dict[str, int]:
    fora = {}
    for _, destino in TABELAS:
        try:
            r = pglocal.um(f"SELECT count(*) AS n FROM {destino}", esquema=esquema)
            fora[destino] = int((r or {}).get("n") or 0)
        except Exception:  # noqa: BLE001 — tabela ainda não existe
            fora[destino] = 0
    return fora


def migrar(esquema: str | None = None) -> dict:
    alvo = esquema or pglocal.ESQUEMA_PADRAO
    migracoes.aplicar(alvo)
    dados = _ler_sqlite()
    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            for linha in dados["push_subs"]:
                cur.execute(
                    "INSERT INTO push_subs(endpoint,p256dh,auth,usuario,criado_em)"
                    " VALUES(%(endpoint)s,%(p256dh)s,%(auth)s,%(usuario)s,"
                    "        %(criado_em)s)"
                    " ON CONFLICT(endpoint) DO UPDATE SET"
                    "   p256dh=excluded.p256dh, auth=excluded.auth,"
                    "   usuario=excluded.usuario", linha)
            for linha in dados["push_meta"]:
                cur.execute(
                    "INSERT INTO push_meta(chave,valor) VALUES(%(chave)s,%(valor)s)"
                    " ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                    linha)
    depois = _contar_pg(alvo)
    return {"esquema": alvo,
            "origem": {t: len(v) for t, v in dados.items()},
            "destino": depois,
            # `>=` e não `==`: a origem é congelada, mas o destino pode ter
            # ganho inscrição nova entre a leitura e a carga — o que não é
            # divergência, é gente usando o sistema
            "confere": all(depois[d] >= len(dados[d]) for _, d in TABELAS)}


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
        for _, d in TABELAS:
            marca = "ok" if destino[d] >= origem[d] else "DIVERGE"
            print(f"{d:12s} sqlite={origem[d]:5d}  postgres={destino[d]:5d}  {marca}")
        return 0 if all(destino[d] >= origem[d] for _, d in TABELAS) else 1

    r = migrar(args.esquema)
    for _, d in TABELAS:
        print(f"{d:12s} {r['origem'][d]:5d} -> {r['destino'][d]:5d}")
    if not r["confere"]:
        print("DIVERGÊNCIA — o SQLite continua intacto.")
        return 1
    print(f"migrado para o schema {r['esquema']}. "
          "O data/push.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
