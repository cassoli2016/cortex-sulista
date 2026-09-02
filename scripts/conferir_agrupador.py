# -*- coding: utf-8 -*-
"""Conferidor do mapa conta -> agrupador gerencial (`sulista.agrupadorgerencial`).

A tabela é do ERP, mantida à mão pela Contabilidade, sem chave primária, sem
índice e sem coluna de vigência — e cinco telas dependem dela (DRE Gerencial,
Contabilidade, Orçamento, Previsão, Custos). Ninguém nos avisa quando ela muda.
Em 02/09/2026 uma recriação trocou o TIPO de `grupo` e duplicou uma conta; as
telas devolveram erro e o resultado ficou R$ 1,5 mi diferente do razão, as duas
coisas em silêncio. Este script é a régua: roda contra o banco vivo, MEDE, e sai
com código 1 quando acha o que não deveria existir.

    uv run python scripts/conferir_agrupador.py [--meses 12]

O que ele confere, cada um por ter acontecido:
  1. `grupo` que não é número      -> a conta perde o agrupador em silêncio
  2. (grupo, reduzido) duplicado   -> o lançamento entra DUAS vezes na DRE
  3. agrupador sem conta no plano  -> classificação que não alcança nada
  4. conta de BALANÇO classificada -> entra na DRE como custo pela elegibilidade
  5. agrupador que não cai em linha nenhuma do DRE_MODELO -> vira CLASSIFICAR
  6. os dois caminhos do resultado (mapa x estrutural) têm de fechar
"""
from __future__ import annotations

import io
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import agrupador_gerencial as ag  # noqa: E402
from api import db  # noqa: E402
from api.queries import DRE_MODELO  # noqa: E402

# Tolerância da reconciliação: centavos de float8, não "quase certo".
TOL = 0.01
_achados = 0


def _brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("-" if v < 0 else "") + "R$ " + s


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode()


def _linha_da_dre(agrupador: str) -> str | None:
    """Mesma alocação de api.queries.get_dre — se muda lá, muda aqui."""
    a = _norm(agrupador)
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            continue
        for s in sel:
            ns = _norm(s)
            if (tipo == "nome" and a == ns) or (tipo == "pref" and a.startswith(ns)):
                return rotulo
    return None


def achado(titulo: str, linhas: list[str]) -> None:
    global _achados
    _achados += len(linhas)
    print(f"\n  [ACHADO] {titulo} ({len(linhas)})")
    for x in linhas:
        print(f"      {x}")


def ok(titulo: str) -> None:
    print(f"\n  [ok] {titulo}")


def main() -> int:
    # O cadastro do ERP tem acento e o console do Windows sai em cp1252: sem
    # isto o conferidor morre num UnicodeEncodeError em vez de mostrar o
    # achado. Fica DENTRO do main: importar o script (o teste importa) nao
    # pode trocar o stdout de quem importou.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    meses = 12
    if "--meses" in sys.argv:
        meses = int(sys.argv[sys.argv.index("--meses") + 1])
    hoje = date.today()
    # A janela e a MESMA da Saude do Servidor (agrupador_gerencial.janela_12m):
    # regua que muda de janela entre as duas telas nao e regua.
    de, ate = ag.janela_12m(hoje, meses)
    P = {"de": de, "ate": ate}
    print(f"Conferidor do agrupador gerencial - {hoje.isoformat()}")
    print(f"Janela de movimento: {P['de']} ate {P['ate']} ({meses} meses fechados)")

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*)::int AS n FROM sulista.agrupadorgerencial")
        print(f"\n  {cur.fetchone()['n']} linhas em sulista.agrupadorgerencial")

        cur.execute(ag.GRUPO_INVALIDO_SQL)
        r = cur.fetchall()
        if r:
            achado("grupo NAO numerico (a conta perde o agrupador)",
                   [f"grupo={x['grupo']!r} em {x['linhas']} linha(s)" for x in r])
        else:
            ok("todo `grupo` e numerico")

        cur.execute(ag.DUPLICATAS_SQL)
        r = cur.fetchall()
        if r:
            achado("conta com MAIS DE UMA classificacao (apagar a antiga no ERP)",
                   [f"{x['grupo']}|{x['reduzido']}: {x['linhas']}x -> {x['descricoes']}" for x in r])
        else:
            ok("uma classificacao por conta")

        cur.execute(ag.ORFAO_SQL)
        r = cur.fetchall()
        if r:
            achado("agrupador em conta que nao existe no plano de contas",
                   [f"{x['grupo']}|{x['reduzido']}: {x['agrupador']}" for x in r])
        else:
            ok("toda classificacao alcanca uma conta do plano")

        cur.execute(ag.BALANCO_CLASSIFICADO_SQL, P)
        r = cur.fetchall()
        if r:
            total = sum(x["valor"] for x in r)
            achado(f"conta de BALANCO classificada - entra na DRE como custo ({_brl(total)} na janela)",
                   [f"{x['estrutural']} {x['grupo']}|{x['reduzido']} {x['conta'][:34]:34} "
                    f"-> {x['agrupador'][:32]:32} {_brl(x['valor'])}" for x in r])
        else:
            ok("so conta de resultado esta classificada")

        cur.execute("SELECT descricao, count(*)::int AS contas "
                    "FROM sulista.agrupadorgerencial GROUP BY 1 ORDER BY 1")
        fora = [(x["descricao"], x["contas"]) for x in cur.fetchall()
                if not _linha_da_dre(x["descricao"] or "")]
        if fora:
            achado("agrupador que nao cai em linha nenhuma do DRE_MODELO (vira CLASSIFICAR)",
                   [f"{d!r} - {n} conta(s)" for d, n in fora])
        else:
            ok("todo agrupador cai numa linha da DRE")

        print("\n  Os dois caminhos do resultado (mapa x estrutural do plano):")
        cur.execute(ag.DOIS_CAMINHOS_SQL, P)
        divergentes = []
        for x in cur.fetchall():
            marca = "  <<<" if abs(x["diferenca"]) > TOL else ""
            print(f"      {x['mes']}  mapa={x['por_agrupador']:>16,.2f}"
                  f"  estrutural={x['por_estrutural']:>16,.2f}"
                  f"  dif={x['diferenca']:>14,.2f}{marca}")
            if abs(x["diferenca"]) > TOL:
                divergentes.append(x)
        if divergentes:
            total = sum(x["diferenca"] for x in divergentes)
            achado(f"os dois caminhos NAO fecham - {_brl(total)} na janela",
                   [f"{x['mes']}: {_brl(x['diferenca'])}" for x in divergentes])
        else:
            ok("os dois caminhos fecham ao centavo")

    print("\n" + ("=" * 70))
    if _achados:
        print(f"  {_achados} achado(s) - o mapa precisa de conserto NO ERP "
              f"(sulista.agrupadorgerencial).")
        return 1
    print("  Nenhum achado.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        db.fechar_pool()
