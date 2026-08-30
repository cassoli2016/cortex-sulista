# -*- coding: utf-8 -*-
"""Mede a ALTURA de cada tela e diz quais não cabem em uma tela só.

POR QUE MEDIR E NÃO CONTAR CARD
===============================
Contar marcador no HTML já subestimou trabalho nesta casa — o lote da conversão
para ECharts foi dimensionado por um `grep` de `<svg id="chart…">` e deixou três
gráficos de fora, porque eles eram montados como string. Card também engana: um
card com um número e um card com uma tabela de 200 linhas contam igual.

O QUE ELE MEDE, E O QUE ELE NÃO CONSEGUE MEDIR
==============================================
As tabelas saem VAZIAS (a API é dublada), então a altura aqui é o **piso**: a
tela real é sempre mais alta. Por isso o relatório traz duas colunas:

  altura  — o que já ocupa sem dado nenhum;
  soltas  — tabelas SEM `.tabroll`, que são as que crescem sem limite quando o
            dado chega. É esta coluna que explica a página de 16.000px do CRM.

Uma tela com 900px de piso e três tabelas soltas é pior que uma com 1.400px e
nenhuma — e só a segunda coluna revela isso.

Uso:
    uv run --no-sync python scripts/medir_paineis.py
    uv run --no-sync python scripts/medir_paineis.py --altura 900
"""
from __future__ import annotations

import functools
import http.server
import json
import re
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_API = RAIZ / "api"

USUARIO = {"nome": "Medição", "email": "medir@sulista.local",
           "perfil": "Administrador", "admin": True, "telas": []}

# Altura útil de uma tela 1080p com a barra do navegador. É a régua da casa:
# "painel de BI se lê SEM ROLAR".
ALTURA_UTIL = 900


def _telas() -> list[str]:
    html = (DIR_API / "static" / "index.html").read_text(encoding="utf-8")
    bloco = re.search(r"const VIEWS = \{(.*?)\};", html, re.S).group(1)
    return re.findall(r"(\w+):", bloco)


def _tabelas_soltas() -> dict[str, int]:
    """Tabelas sem `.tabroll` por tela — as que crescem sem limite com o dado.

    O limite da seção é o `</section>`, e NÃO o começo da próxima: a última
    view do arquivo engoliria todo o JavaScript e apareceria com 92 tabelas.
    """
    html = (DIR_API / "static" / "index.html").read_text(encoding="utf-8")
    fora: dict[str, int] = {}
    for m in re.finditer(r'<section class="view[^"]*" id="view-(\w+)">', html):
        ini = m.end()
        corpo = html[ini:html.index("</section>", ini)]
        fora[m.group(1)] = (len(re.findall(r"<table", corpo))
                            - len(re.findall(r"tabroll", corpo)))
    return fora


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from playwright.sync_api import sync_playwright

    limite = ALTURA_UTIL
    if "--altura" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--altura") + 1])

    soltas = _tabelas_soltas()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    medidas = []
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pg = nav.new_page(viewport={"width": 1500, "height": 1000})
        pg.route("**/api/**", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(USUARIO if "/api/auth/me" in r.request.url else {})))
        for tela in _telas():
            pg.goto(f"{base}/static/index.html#{tela}")
            pg.wait_for_timeout(400)
            h = pg.evaluate(
                "() => { const c = document.getElementById('content');"
                " return c ? Math.round(c.scrollHeight) : 0; }")
            temAba = pg.evaluate(
                "(t) => !!document.querySelector('#view-'+t+' .subtabs')", tela)
            medidas.append((tela, h, soltas.get(tela, 0), temAba))
        nav.close()
    srv.shutdown()

    medidas.sort(key=lambda m: -(m[1] + m[2] * 400))
    print(f"{'tela':10}{'altura':>8}{'soltas':>8}  aba   veredito")
    print("-" * 64)
    acima = 0
    for tela, h, sol, aba in medidas:
        # Uma tabela solta vale ~400px de crescimento provável — é a ordem de
        # grandeza de 20 linhas, e 20 linhas é pouco para as tabelas da casa.
        estimado = h + sol * 400
        ruim = estimado > limite
        acima += 1 if ruim and not aba else 0
        veredito = ("cabe" if not ruim else
                    "JÁ TEM ABA" if aba else "PASSA DA TELA")
        print(f"{tela:10}{h:8}{sol:8}  {'sim' if aba else '   '}   {veredito}")
    print(f"\n{acima} tela(s) acima de {limite}px sem aba — "
          f"régua: painel de BI se lê sem rolar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
