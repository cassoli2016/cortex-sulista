"""Leva `data/contrapartida.db` (SQLite) para o PostgreSQL local.

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
    uv run python scripts/migrar_contrapartida.py            # migra
    uv run python scripts/migrar_contrapartida.py --conferir # só compara os dois lados
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import migracoes, pglocal  # noqa: E402

ORIGEM = ROOT / "data" / "contrapartida.db"
# Nenhuma referência entre elas: a ordem aqui é só de leitura.
TABELAS = (("autorizacao", "autorizacao"), ("certificado", "certificado"),
           ("auditoria", "auditoria"), ("emissao", "emissao"),
           ("lote_config", "lote_config"))


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

    # GUARDA: a tabela se chamou `procuracao` antes de `autorizacao`, e o
    # módulo carregava um `INSERT ... SELECT` que copiava de uma para a outra a
    # cada conexão. Essa rotina NÃO veio para o Postgres. Se a origem ainda
    # tiver `procuracao`, há autorização que nunca foi copiada — e autorização
    # perdida é justamente o registro que permite emitir em nome de alguém.
    if ORIGEM.exists():
        c = sqlite3.connect(ORIGEM)
        try:
            achou = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table'"
                " AND name='procuracao'").fetchone()
        finally:
            c.close()
        if achou:
            raise SystemExit(
                "a origem ainda tem a tabela `procuracao`, anterior ao rename "
                "para `autorizacao`. Rode a versão anterior do módulo uma vez "
                "para ela migrar, e só então traga para o Postgres — aqui essa "
                "rotina não existe mais.")

    dados = _ler_sqlite()

    with pglocal.get_conn(alvo) as conn:
        with conn.cursor() as cur:
            for _, destino in reversed(TABELAS):
                cur.execute(f"DELETE FROM {destino}")

            for a in dados["autorizacao"]:
                cur.execute(
                    "INSERT INTO autorizacao(cnpj, escopo, valida_de,"
                    " valida_ate, observacao, criado_em, criado_por)"
                    " VALUES(%(cnpj)s,%(escopo)s,%(valida_de)s,%(valida_ate)s,"
                    "        %(observacao)s,%(criado_em)s,%(criado_por)s)", a)

            for c_ in dados["certificado"]:
                cur.execute(
                    "INSERT INTO certificado(cnpj, tipo, arquivo, valida_ate,"
                    " titular, criado_em, criado_por)"
                    " VALUES(%(cnpj)s,%(tipo)s,%(arquivo)s,%(valida_ate)s,"
                    "        %(titular)s,%(criado_em)s,%(criado_por)s)", c_)

            # id é IDENTITY nas duas: leva-se a ORDEM, não o número. Em trilha
            # de auditoria a sequência é o que importa.
            for a in sorted(dados["auditoria"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO auditoria(quando, quem, acao, cnpj, detalhe)"
                    " VALUES(%(quando)s,%(quem)s,%(acao)s,%(cnpj)s,%(detalhe)s)",
                    a)

            for e in sorted(dados["emissao"], key=lambda r: r["id"]):
                cur.execute(
                    "INSERT INTO emissao(quando, quem, ambiente, cnpj_emitente,"
                    " serie, numero, chave, chave_origem, cstat, xmotivo,"
                    " protocolo, xml, xml_prot)"
                    " VALUES(%(quando)s,%(quem)s,%(ambiente)s,"
                    "        %(cnpj_emitente)s,%(serie)s,%(numero)s,%(chave)s,"
                    "        %(chave_origem)s,%(cstat)s,%(xmotivo)s,"
                    "        %(protocolo)s,%(xml)s,%(xml_prot)s)", e)

            for k in dados["lote_config"]:
                cur.execute(
                    "INSERT INTO lote_config(chave, valor, quem, quando)"
                    " VALUES(%(chave)s,%(valor)s,%(quem)s,%(quando)s)", k)

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
          f"O data/contrapartida.db continua no disco, como desfazer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
