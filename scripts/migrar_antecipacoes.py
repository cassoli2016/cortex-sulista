"""Leva `data/antecipacoes.db` (SQLite) para o PostgreSQL local.

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
    uv run python scripts/migrar_antecipacoes.py            # migra
    uv run python scripts/migrar_antecipacoes.py --conferir # só compara os dois lados
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "antecipacoes.db"
# (origem no SQLite, destino no Postgres). A ORDEM importa: `ant_titulos`
# referencia `ant_envios`, então envios entra antes e sai depois.
TABELAS = (("envios", "ant_envios"), ("titulos", "ant_titulos"),
           ("sacados", "ant_sacados"))


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

    # O id do envio é IDENTITY no destino, mas `ant_titulos.envio_id` APONTA
    # para ele: não dá para "levar a ordem" como nos outros stores. Guarda-se
    # o de-para id_antigo -> id_novo e os títulos entram já traduzidos. Perder
    # esse vínculo faria a posição de cada portal apontar para o envio errado.
    de_para: dict[int, int] = {}

    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ant_titulos")
            cur.execute("DELETE FROM ant_envios")
            cur.execute("DELETE FROM ant_sacados")

            for e in sorted(dados["ant_envios"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO ant_envios (ts,usuario,arquivo,portal,"
                    " portal_rotulo,titulos,valor_nominal,valor_saldo,"
                    " total_declarado,divergencia,rejeitadas,impressao,vigente,"
                    " origem)"
                    " VALUES (%(ts)s,%(usuario)s,%(arquivo)s,%(portal)s,"
                    "         %(portal_rotulo)s,%(titulos)s,%(valor_nominal)s,"
                    "         %(valor_saldo)s,%(total_declarado)s,"
                    "         %(divergencia)s,%(rejeitadas)s,%(impressao)s,"
                    "         %(vigente)s,%(origem)s) RETURNING id", e)
                de_para[e["id"]] = int(cur.fetchone()["id"])

            for t in dados["ant_titulos"]:
                novo = de_para.get(t["envio_id"])
                if novo is None:
                    # título órfão: o envio dele já não existe. Não se inventa
                    # vínculo — conta como divergência e a conferência acusa.
                    continue
                cur.execute(
                    "INSERT INTO ant_titulos (envio_id,titulo,documento,emissao,"
                    " vencimento,valor_nominal,valor_saldo,antecipavel,situacao,"
                    " cnpj_cedente,nome_cedente,cnpj_sacado,nome_sacado,chave,"
                    " id_portal)"
                    " VALUES (%(envio_id_novo)s,%(titulo)s,%(documento)s,"
                    "         %(emissao)s,%(vencimento)s,%(valor_nominal)s,"
                    "         %(valor_saldo)s,%(antecipavel)s,%(situacao)s,"
                    "         %(cnpj_cedente)s,%(nome_cedente)s,%(cnpj_sacado)s,"
                    "         %(nome_sacado)s,%(chave)s,%(id_portal)s)",
                    {**t, "envio_id_novo": novo})

            for s_ in dados["ant_sacados"]:
                cur.execute(
                    "INSERT INTO ant_sacados"
                    " (cnpj,nome,portal,elegivel,origem,atualizado_em,observacao)"
                    " VALUES (%(cnpj)s,%(nome)s,%(portal)s,%(elegivel)s,"
                    "         %(origem)s,%(atualizado_em)s,%(observacao)s)", s_)

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
          f"O data/antecipacoes.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
