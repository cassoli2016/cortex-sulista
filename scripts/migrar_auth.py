"""Leva `data/auth.db` (SQLite) para o PostgreSQL local.

Mesmo molde de `migrar_antt.py`. Três regras que valem para todos
(ver `docs/MIGRACAO_POSTGRES.md`):

1. **Idempotente.** Rodar duas vezes não duplica: a carga é substituição
   completa, dentro de uma transação.
2. **Confere a contagem.** Ler 223 e gravar 222 é o defeito que ninguém percebe
   na hora e todo mundo descobre um mês depois. O script compara linha a linha
   e sai com código 1 se divergir.
3. **Não apaga a origem.** O `.db` fica onde está. Desfazer é `git revert` do
   módulo, e o dado antigo continua lá.

Uso:
    uv run python scripts/migrar_auth.py            # migra
    uv run python scripts/migrar_auth.py --conferir # só compara os dois lados
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "auth.db"
# A ORDEM importa: `usuarios` e `perfil_telas` referenciam `perfis`.
TABELAS = (("perfis", "perfis"), ("perfil_telas", "perfil_telas"),
           ("usuarios", "usuarios"), ("audit_log", "audit_log"),
           ("config", "config"))


def _ler_sqlite() -> dict[str, list[dict]]:
    """Chaveado pelo nome de DESTINO, para os dois lados casarem na conferência."""
    if not ORIGEM.exists():
        return {d: [] for _, d in TABELAS}
    c = sqlite3.connect(ORIGEM)
    c.row_factory = sqlite3.Row
    try:
        return {d: [dict(r) for r in c.execute(f"SELECT * FROM {o}")]
                for o, d in TABELAS}
    finally:
        c.close()


def _contar_pg(esquema: str) -> dict[str, int]:
    fora = {}
    for _, d in TABELAS:
        try:
            r = pglocal.um(f"SELECT count(*) AS n FROM {d}", esquema=esquema)
            fora[d] = int((r or {}).get("n") or 0)
        except Exception:  # noqa: BLE001 — tabela ainda não existe
            fora[d] = 0
    return fora


def migrar(esquema: str | None = None) -> dict:
    alvo = esquema or pglocal.ESQUEMA_PADRAO
    migracoes.aplicar(alvo)
    dados = _ler_sqlite()

    # o id do perfil é IDENTITY e é REFERENCIADO por usuarios e perfil_telas:
    # perder o vínculo daria usuário no perfil errado — que num sistema de
    # ACESSO significa alguém enxergando tela que não devia.
    de_perfil: dict[int, int] = {}

    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            for _, destino in reversed(TABELAS):
                cur.execute(f"DELETE FROM {destino}")

            for p_ in sorted(dados["perfis"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO perfis(nome, descricao, admin, criado_em)"
                    " VALUES(%(nome)s,%(descricao)s,%(admin)s,%(criado_em)s)"
                    " RETURNING id", p_)
                de_perfil[p_["id"]] = int(cur.fetchone()["id"])

            for t in dados["perfil_telas"]:
                cur.execute(
                    "INSERT INTO perfil_telas(perfil_id, tela)"
                    " VALUES(%(pid)s,%(tela)s) ON CONFLICT DO NOTHING",
                    {**t, "pid": de_perfil[t["perfil_id"]]})

            for u in sorted(dados["usuarios"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO usuarios(nome, email, senha_hash, perfil_id,"
                    " ativo, deve_trocar_senha, token_ver, falhas,"
                    " bloqueado_ate, criado_em, ultimo_login)"
                    " VALUES(%(nome)s,%(email)s,%(senha_hash)s,%(pid)s,"
                    "        %(ativo)s,%(deve_trocar_senha)s,%(token_ver)s,"
                    "        %(falhas)s,%(bloqueado_ate)s,%(criado_em)s,"
                    "        %(ultimo_login)s)",
                    {**u, "pid": de_perfil[u["perfil_id"]]})

            for a in sorted(dados["audit_log"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip)"
                    " VALUES(%(ts)s,%(usuario)s,%(acao)s,%(alvo)s,%(detalhe)s,"
                    "        %(ip)s)", a)

            for k in dados["config"]:
                cur.execute(
                    "INSERT INTO config(chave, valor)"
                    " VALUES(%(chave)s,%(valor)s)", k)

    depois = _contar_pg(alvo)
    return {
        "esquema": alvo,
        "origem": {d: len(v) for d, v in dados.items()},
        "destino": depois,
        "confere": all(len(dados[d]) == depois[d] for _, d in TABELAS),
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
        origem = _ler_sqlite()
        destino = _contar_pg(args.esquema)
        for _, d in TABELAS:
            marca = "ok" if len(origem[d]) == destino[d] else "DIVERGE"
            print(f"{d:18s} sqlite={len(origem[d]):6d}  postgres={destino[d]:6d}  {marca}")
        return 0 if all(len(origem[d]) == destino[d] for _, d in TABELAS) else 1

    r = migrar(args.esquema)
    for _, d in TABELAS:
        print(f"{d:18s} {r['origem'][d]:6d} -> {r['destino'][d]:6d}")
    if not r["confere"]:
        print("DIVERGÊNCIA na contagem — o SQLite continua intacto, "
              "não troque o módulo até entender.")
        return 1
    print(f"migrado para o schema {r['esquema']}. "
          f"O data/auth.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
