"""Leva `data/extrato.db` (SQLite) para o PostgreSQL local.

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
    uv run python scripts/migrar_extrato.py            # migra
    uv run python scripts/migrar_extrato.py --conferir # só compara os dois lados
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "extrato.db"
# (origem no SQLite, destino no Postgres). A ORDEM importa: lançamento e saldo
# referenciam conta e importação.
TABELAS = (("ext_conta", "ext_conta"), ("ext_importacao", "ext_importacao"),
           ("ext_lancamento", "ext_lancamento"), ("ext_saldo", "ext_saldo"))


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

    # GUARDA: `_remigra_chaves` não veio junto na migração — a rotina que
    # recalculava chaves no formato antigo `fitid:<id>` ficou para trás porque
    # a base tinha ZERO delas. Se aparecer uma, é uma base que nunca passou
    # pela remigração, e continuar aqui faria o próximo reimport dobrar o
    # extrato: as chaves antigas e novas nunca colidem entre si.
    antigas = [x for x in dados["ext_lancamento"]
               if str(x.get("chave") or "").startswith("fitid:")]
    if antigas:
        raise SystemExit(
            f"{len(antigas)} lançamentos com chave no formato antigo "
            "('fitid:'). Rode a versão anterior do módulo para remigrar antes "
            "de trazer para o Postgres — ver docs/MIGRACAO_POSTGRES.md.")

    # id de conta e de importação são referenciados: guarda-se o de-para
    de_conta: dict[int, int] = {}
    de_imp: dict[int, int] = {}

    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            for _, destino in reversed(TABELAS):
                cur.execute(f"DELETE FROM {destino}")

            for c in sorted(dados["ext_conta"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO ext_conta(ident, rotulo, erp_banco, erp_agencia,"
                    " erp_conta, mapa_csv, criado_em)"
                    " VALUES(%(ident)s,%(rotulo)s,%(erp_banco)s,%(erp_agencia)s,"
                    "        %(erp_conta)s,%(mapa_csv)s,%(criado_em)s)"
                    " RETURNING id", c)
                de_conta[c["id"]] = int(cur.fetchone()["id"])

            for i in sorted(dados["ext_importacao"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO ext_importacao(conta_id, arquivo, formato,"
                    " dt_de, dt_ate, novas, duplicadas, ignoradas, quando)"
                    " VALUES(%(cid)s,%(arquivo)s,%(formato)s,%(dt_de)s,"
                    "        %(dt_ate)s,%(novas)s,%(duplicadas)s,%(ignoradas)s,"
                    "        %(quando)s) RETURNING id",
                    {**i, "cid": de_conta[i["conta_id"]]})
                de_imp[i["id"]] = int(cur.fetchone()["id"])

            for l in sorted(dados["ext_lancamento"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO ext_lancamento(conta_id, importacao_id, dt,"
                    " valor, tipo, historico, numerodoc, fitid, chave)"
                    " VALUES(%(cid)s,%(iid)s,%(dt)s,%(valor)s,%(tipo)s,"
                    "        %(historico)s,%(numerodoc)s,%(fitid)s,%(chave)s)",
                    {**l, "cid": de_conta[l["conta_id"]],
                     "iid": de_imp[l["importacao_id"]]})

            for sd in dados["ext_saldo"]:
                cur.execute(
                    "INSERT INTO ext_saldo(conta_id, dt, saldo, importacao_id,"
                    " origem) VALUES(%(cid)s,%(dt)s,%(saldo)s,%(iid)s,%(origem)s)",
                    {**sd, "cid": de_conta[sd["conta_id"]],
                     # âncora anterior à migração tem importacao_id NULL e
                     # continua NULL: não se inventa vínculo que nunca existiu
                     "iid": de_imp.get(sd["importacao_id"])})

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
          f"O data/extrato.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
