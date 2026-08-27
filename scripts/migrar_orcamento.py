"""Leva `data/orcamento.db` (SQLite) para o PostgreSQL local.

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
    uv run python scripts/migrar_orcamento.py            # migra
    uv run python scripts/migrar_orcamento.py --conferir # só compara os dois lados
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "orcamento.db"
# (origem no SQLite, destino no Postgres). A ORDEM importa: linha e log
# referenciam a versão.
TABELAS = (("orc_versao", "orc_versao"), ("orc_linha", "orc_linha"),
           ("orc_log", "orc_log"))


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

    # o id da versão é IDENTITY e é REFERENCIADO por linha e log: guarda-se o
    # de-para. 21.696 linhas apontando para o id errado seria um orçamento
    # inteiro no lugar errado, com o total continuando a fechar.
    de_versao: dict[int, int] = {}

    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            for _, destino in reversed(TABELAS):
                cur.execute(f"DELETE FROM {destino}")

            for v in sorted(dados["orc_versao"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO orc_versao(ano, rotulo, status, fator_tendencia,"
                    " criado_em, criado_por, meses_base, metodo, aprovado_em,"
                    " aprovado_por)"
                    " VALUES(%(ano)s,%(rotulo)s,%(status)s,%(fator_tendencia)s,"
                    "        %(criado_em)s,%(criado_por)s,%(meses_base)s,"
                    "        %(metodo)s,%(aprovado_em)s,%(aprovado_por)s)"
                    " RETURNING id", v)
                de_versao[v["id"]] = int(cur.fetchone()["id"])

            # executemany nas 21.696 linhas: uma a uma seriam 21.696 idas ao
            # banco, e o script levaria minutos em vez de segundos
            cur.executemany(
                "INSERT INTO orc_linha(versao_id, conta, mes, valor_baseline,"
                " valor_ajustado, origem, meses_com_dado, ajustado_em, ajustado_por)"
                " VALUES(%(vid)s,%(conta)s,%(mes)s,%(valor_baseline)s,"
                "        %(valor_ajustado)s,%(origem)s,%(meses_com_dado)s,"
                "        %(ajustado_em)s,%(ajustado_por)s)",
                [{**l, "vid": de_versao[l["versao_id"]]}
                 for l in dados["orc_linha"] if l["versao_id"] in de_versao])

            cur.executemany(
                "INSERT INTO orc_log(versao_id, conta, mes, valor_de, valor_para,"
                " quem, quando)"
                " VALUES(%(vid)s,%(conta)s,%(mes)s,%(valor_de)s,%(valor_para)s,"
                "        %(quem)s,%(quando)s)",
                [{**g, "vid": de_versao.get(g["versao_id"], g["versao_id"])}
                 for g in sorted(dados["orc_log"], key=lambda r: r["id"])])

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
          f"O data/orcamento.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
