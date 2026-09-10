# -*- coding: utf-8 -*-
"""Que testes esta mudanca exige? Monta a selecao a partir do DIFF.

POR QUE ISTO EXISTE
===================
A regra da casa pede a suite COMPLETA para TELA NOVA, e o motivo e especifico:
os onze registros de uma tela tem guards espalhados por arquivos que nao falam
do assunto, e a falha e ausencia silenciosa. Em 09/09/2026 eu apliquei essa
regra a coisas que nao eram tela — um modulo de fornecedor e uma sub-aba — e
gastei duas horas de relogio em quatro rodadas de 50 minutos, das quais duas
nao eram exigidas por regra nenhuma.

O julgamento "isto pede tudo ou pede pouco?" e o problema: ele se refaz a cada
entrega, cansa, e erra para o lado caro. Aqui ele vira uma linha.

O QUE ELE FAZ, E O QUE NAO FAZ
==============================
Ele MONTA a selecao; nao decide sozinho o que basta. Sao tres fontes:

  1. As PASTAS espelho dos arquivos tocados (`api/pneus/x.py` -> `tests/pneus`).
  2. Os testes que CITAM os simbolos alterados — e e esta que pega o guard que
     mora longe. A regra da casa e explicita: "ache os guards dela pelo
     ASSUNTO, nao pela pasta"; a faixa da marca no e-mail quebrou 8 testes, um
     em `tests/correio/` e outro na raiz.
  3. Os GATILHOS DE SUITE COMPLETA. Alguns arquivos nao tem selecao possivel:
     mexer em `auth.py` ou no roteador do `index.html` toca RBAC e registro de
     tela, e ai o barato sai caro.

Uso:
    uv run python scripts/testes_afetados.py            # contra o HEAD
    uv run python scripts/testes_afetados.py --ref main # contra outro ponto
    uv run python scripts/testes_afetados.py --rodar    # ja executa o pytest
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: Tocar nestes NAO tem selecao possivel: o que eles quebram mora em qualquer
#: lugar. `auth.py` e RBAC e registro de tela; o `index.html` so entra aqui
#: quando a mudanca mexe no ROTEADOR (VIEWS/VIEW_GROUP/ROTA), o que se detecta
#: pelo simbolo, nao pelo nome do arquivo.
SUITE_COMPLETA = {
    "api/auth.py",
    "conftest.py",
    "tests/conftest.py",
}

#: Arquivos que so sao gatilho quando a mudanca toca CERTAS partes deles.
#:
#: A PRIMEIRA VERSAO DISTO ERRAVA, e o erro apareceu no primeiro uso: eu tinha
#: posto `pyproject.toml` e `api/main.py` na lista de cima, e os dois mudam em
#: QUASE TODA entrega — o bump de versao e a rota nova. O veredito saia "suite
#: completa" sempre, e uma ferramenta que responde sempre a mesma coisa nao e
#: ferramenta, e cerimonia.
#:
#: O que importa em cada um:
#:   - `pyproject.toml`: dependencia ou config de teste, nao a linha `version`.
#:   - `api/main.py`: middleware, startup e RBAC — nao um `@app.get` a mais.
GATILHOS_PARCIAIS = {
    "pyproject.toml": ("dependencies", "dependency-groups", "[tool.pytest",
                       "[tool.uv"),
    "api/main.py": ("middleware", "on_event", "ROTA_TELAS", "_ROTAS_SEM_TELA",
                    "sessao_atual", "HTTP_RECUSA", "def _servir"),
}

#: Simbolos que, alterados no `index.html`, significam tela nova ou mexida no
#: roteador — e ai a suite inteira e a resposta certa.
GATILHOS_HTML = ("const VIEWS", "VIEW_GROUP", "ROTA_TELAS", "semFilterbar",
                 "function router", "podeVer")

#: Simbolo digno de busca. Nome curto casa com tudo e a selecao vira a suite.
MIN_SIMBOLO = 6

#: Simbolo que aparece em MAIS de tantos arquivos de teste nao esta apontando
#: para nada: e palavra comum. Medido no primeiro uso: `idade` casou com tres
#: suites de antecipacoes que nao tinham relacao nenhuma com a mudanca. O corte
#: nao e sobre o tamanho do nome, e sobre o quanto ele DISTINGUE.
MAX_ARQUIVOS_POR_SIMBOLO = 8

DECL = re.compile(
    r"^\+\s*(?:async\s+)?(?:def|class|function|const|let|var)\s+(\w+)|"
    r"^\+\s*(\w+)\s*[:=]\s|"
    r'^\+.*?"([A-Z_]{5,})"', re.M)


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(RAIZ), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def arquivos_tocados(ref: str) -> list[str]:
    saida = _git("diff", "--name-only", ref)
    nao_commitados = _git("status", "--porcelain")
    novos = [l[3:].strip() for l in nao_commitados.splitlines()
             if l.startswith("?? ")]
    tocados = [l.strip() for l in saida.splitlines() if l.strip()]
    for n in novos:
        p = RAIZ / n
        if p.is_dir():
            tocados += [str(x.relative_to(RAIZ)).replace("\\", "/")
                        for x in p.rglob("*.py")]
        elif n.endswith((".py", ".html", ".sql", ".ps1", ".yaml")):
            tocados.append(n)
    return sorted({t.replace("\\", "/") for t in tocados})


def simbolos_alterados(ref: str, arquivos: list[str]) -> set[str]:
    """Nomes que APARECERAM no diff — e que um guard distante pode citar."""
    alvo = [a for a in arquivos if a.endswith((".py", ".html"))]
    if not alvo:
        return set()
    diff = _git("diff", "-U0", ref, "--", *alvo)
    nomes = set()
    for m in DECL.finditer(diff):
        for g in m.groups():
            if g and len(g) >= MIN_SIMBOLO and not g.startswith("_"):
                nomes.add(g)
    return nomes


def testes_que_citam(nomes: set[str]) -> dict[str, set[str]]:
    """Onde cada nome aparece dentro de `tests/` — a busca por ASSUNTO."""
    achados: dict[str, set[str]] = {}
    for nome in sorted(nomes):
        saida = _git("grep", "-l", "--fixed-strings", nome, "--", "tests/")
        arquivos = {l.strip() for l in saida.splitlines() if l.strip()}
        # Palavra comum nao seleciona nada: ela SO alarga.
        if arquivos and len(arquivos) <= MAX_ARQUIVOS_POR_SIMBOLO:
            achados[nome] = arquivos
    return achados


def pastas_espelho(arquivos: list[str]) -> set[str]:
    """`api/pneus/x.py` -> `tests/pneus`; `scripts/y.py` -> `tests`."""
    pastas = set()
    for a in arquivos:
        p = Path(a)
        if p.parts and p.parts[0] == "tests":
            # ARQUIVO DE TESTE SELECIONA O ARQUIVO, nao a pasta dele. Subir
            # para a pasta parece inofensivo e nao e: um teste na RAIZ de
            # `tests/` faria a selecao virar `tests`, que e a suite inteira —
            # exatamente o que esta ferramenta existe para evitar. Visto no
            # primeiro uso real, com `tests/test_rota_mapeada.py`.
            if p.name.startswith("test_") and p.suffix == ".py":
                pastas.add(a)
            else:
                pastas.add(str(p.parent).replace("\\", "/"))
            continue
        if len(p.parts) >= 2 and p.parts[0] == "api":
            cand = RAIZ / "tests" / p.parts[1]
            if cand.is_dir():
                pastas.add(f"tests/{p.parts[1]}")
        if a.endswith(".html"):
            pastas.add("tests/frontend")
    return pastas


def decidir(ref: str) -> dict:
    arquivos = arquivos_tocados(ref)
    motivos: list[str] = []

    for c in sorted(set(arquivos) & SUITE_COMPLETA):
        motivos.append(f"{c} muda RBAC ou o arranjo dos testes")

    for arq, pedacos in GATILHOS_PARCIAIS.items():
        if arq not in arquivos:
            continue
        diff = _git("diff", "-U0", ref, "--", arq)
        for pedaco in pedacos:
            if re.search(r"^[+-].*" + re.escape(pedaco), diff, re.M):
                motivos.append(f"{arq} mexeu em `{pedaco}`")
                break

    if "api/static/index.html" in arquivos:
        diff = _git("diff", "-U0", ref, "--", "api/static/index.html")
        for g in GATILHOS_HTML:
            if re.search(r"^\+.*" + re.escape(g), diff, re.M):
                motivos.append(f"o index.html mexeu em `{g}` — tela nova ou roteador")
                break

    nomes = simbolos_alterados(ref, arquivos)
    citam = testes_que_citam(nomes)
    pastas = pastas_espelho(arquivos)
    alvos = sorted(pastas | {a for s in citam.values() for a in s})

    return {"arquivos": arquivos, "simbolos": sorted(nomes), "citam": citam,
            "pastas": sorted(pastas), "alvos": alvos,
            "completa": bool(motivos), "motivos": motivos}


def main() -> int:
    p = argparse.ArgumentParser(description="Seleciona os testes que a mudanca exige.")
    p.add_argument("--ref", default="HEAD", help="ponto de comparacao (padrao: HEAD)")
    p.add_argument("--rodar", action="store_true", help="executa o pytest com a selecao")
    p.add_argument("--quieto", action="store_true", help="so a linha de comando")
    args = p.parse_args()

    d = decidir(args.ref)

    if not args.quieto:
        print(f"arquivos tocados: {len(d['arquivos'])}")
        for a in d["arquivos"][:20]:
            print("   ", a)
        if len(d["arquivos"]) > 20:
            print(f"    ... (+{len(d['arquivos']) - 20})")
        if d["simbolos"]:
            print(f"\nsimbolos novos/alterados: {len(d['simbolos'])}")
            print("   ", ", ".join(d["simbolos"][:14])
                  + (" ..." if len(d["simbolos"]) > 14 else ""))
        if d["citam"]:
            print("\nguards que CITAM esses nomes (a busca por assunto):")
            for nome, arqs in list(d["citam"].items())[:12]:
                print(f"    {nome:28} -> {', '.join(sorted(arqs)[:3])}"
                      + (" ..." if len(arqs) > 3 else ""))
        print()

    if d["completa"]:
        print("VEREDITO: SUITE COMPLETA")
        for m in d["motivos"]:
            print("   porque", m)
        cmd = ["pytest", "-q"]
    elif d["alvos"]:
        print("VEREDITO: selecao dirigida")
        cmd = ["pytest", "-q", *d["alvos"]]
    else:
        print("VEREDITO: nada a rodar (nenhum teste espelha o que mudou)")
        print("   ATENCAO: isso costuma significar que a mudanca NAO TEM GUARD.")
        return 0

    print("\n  uv run " + " ".join(cmd))

    if args.rodar:
        print()
        return subprocess.call([sys.executable, "-m", *cmd], cwd=RAIZ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
