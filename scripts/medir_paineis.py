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

  altura  — o que já ocupa sem dado nenhum, medido na aba MAIS ALTA (ter aba
            não é cumprir a regra: quem se lê é a aba aberta, e dividir 1.400px
            numa aba de 1.300 e outra de 100 não resolveu nada);
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

# PAINEL DE TV TEM OUTRA REGUA, e nao e indulgencia. Ele roda em tela cheia
# numa TV de corredor: nao ha barra do navegador para descontar, e sobretudo
# NAO HA QUEM CLIQUE — dividir em aba um painel que ninguem opera esconde
# metade do que ele existe para mostrar. Entao ele nao cabe em aba nenhuma: o
# que ele tem de fazer e caber em 1080 inteiros.
ALTURA_TV = 1050
E_TV = ("tvope", "tvfat")


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
        # `max(0, ...)`: `tabroll` aparece tambem em wrapper que nao envolve
        # tabela nenhuma, e a subtracao ficava NEGATIVA — o que virava um
        # CREDITO de altura no veredito e escondia telas de 1.000px+ atras de
        # um "cabe". Foi assim que `orc` (966) e `hc` (1.030) passaram.
        fora[m.group(1)] = max(0, len(re.findall(r"<table", corpo))
                               - len(re.findall(r"tabroll", corpo)))
    return fora


def medir() -> list[tuple[str, int, int, bool]]:
    """(tela, altura da aba mais alta, tabelas soltas, tem aba) para as 68.

    Separado do `main` para o teste poder cobrar a regra sem repetir o arranjo
    — regra sem teste volta, e esta ja voltou uma vez em forma de tela de
    16.000px.
    """
    from playwright.sync_api import sync_playwright

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
            # O BANNER DE ERRO NAO ENTRA NA REGUA. A API aqui e dublada e
            # devolve `{}`, entao TODA tela abre com o banner vermelho — 98px
            # mais o vao, em 68 telas, empurrando cada uma para o vermelho e
            # cobrando divisao de quem ja cabia. Ele e estado de excecao, nao
            # o estado em que a tela e lida.
            alt = ("() => { const c = document.getElementById('content');"
                   " if(!c) return 0;"
                   " const b = c.querySelector('#banner');"
                   " const fora = (b && b.offsetParent !== null)"
                   "   ? Math.round(b.getBoundingClientRect().height) + 14 : 0;"
                   " return Math.round(c.scrollHeight) - fora; }")
            h = pg.evaluate(alt)
            # TER ABA NAO E CUMPRIR A REGRA. A regra e "se le sem rolar", e
            # quem se le e a aba ABERTA — dividir uma tela de 1.400px em uma
            # aba de 1.300 e outra de 100 nao resolveu nada. Entao mede-se
            # CADA aba, e o que vale e a mais alta.
            chaves = pg.evaluate(
                "(t) => Array.from(document.querySelectorAll("
                " '#view-'+t+' .subtabs button')).map(b => "
                " [b.closest('.subtabs').dataset.abas, b.dataset.aba])", tela)
            for grupo, qual in chaves:
                pg.evaluate("([g,q]) => abaTrocar(g,q)", [grupo, qual])
                pg.wait_for_timeout(120)
                h = max(h, pg.evaluate(alt))
            medidas.append((tela, h, soltas.get(tela, 0), bool(chaves)))
        nav.close()
    srv.shutdown()
    return medidas


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    limite = ALTURA_UTIL
    if "--altura" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--altura") + 1])
    medidas = medir()
    medidas.sort(key=lambda m: -(m[1] + m[2] * 400))
    print(f"{'tela':10}{'altura':>8}{'soltas':>8}  aba   veredito")
    print("-" * 64)
    acima = 0
    for tela, h, sol, aba in medidas:
        # Uma tabela solta vale ~400px de crescimento provável — é a ordem de
        # grandeza de 20 linhas, e 20 linhas é pouco para as tabelas da casa.
        # A TABELA DO PAINEL DE TV NAO E "SOLTA": quem limita ali e o
        # RENDERIZADOR (`slice(0,10)`), nao o CSS — e tem de ser assim, porque
        # rolagem dentro do card e inutil numa TV que ninguem toca.
        estimado = h + (0 if tela in E_TV else sol * 400)
        regua = ALTURA_TV if tela in E_TV else limite
        ruim = estimado > regua
        acima += 1 if ruim else 0
        veredito = ("cabe na TV" if tela in E_TV and not ruim else
                    "cabe" if not ruim else
                    "ABA ALTA DEMAIS" if aba else "PASSA DA TELA")
        print(f"{tela:10}{h:8}{sol:8}  {'sim' if aba else '   '}   {veredito}")
    print(f"\n{acima} tela(s) acima de {limite}px sem aba — "
          f"régua: painel de BI se lê sem rolar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
