# -*- coding: utf-8 -*-
"""Mede o VAO VERTICAL entre componentes vizinhos, em todas as telas.

POR QUE MEDIR NO NAVEGADOR E NAO LER O CSS
==========================================
O vao entre dois cartoes nao esta escrito em lugar nenhum: ele e o `gap` do
container, ou uma `margin` que sobrou, ou zero porque o container deixou de ser
flex quando alguem embrulhou os cartoes num `<div>`. Ler o CSS diz o que foi
DECLARADO; so o navegador diz o que SAIU.

E foi assim que o aperto apareceu: `.view` e uma coluna flex com `gap:18px`, e
ao dividir as telas em sub-abas os cartoes deixaram de ser filhos dela — cada
`.aba` virou UM filho, e la dentro nao havia gap nenhum. Cartao colado em
cartao, em 29 telas, sem uma linha de erro.

O RELATORIO
===========
Para cada par de vizinhos visiveis dentro de um mesmo pai, o vao em px, com o
pai identificado. O que interessa sao os EXTREMOS: vao 0 (colado) e vao acima
de 30 (buraco). O meio da distribuicao e a escala da casa.

Uso:
    uv run --no-sync python scripts/auditar_espacos.py
    uv run --no-sync python scripts/auditar_espacos.py --tela torre
    uv run --no-sync python scripts/auditar_espacos.py --detalhe
"""
from __future__ import annotations

import functools
import http.server
import json
import re
import sys
import threading
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_API = RAIZ / "api"

USUARIO = {"nome": "Medição", "email": "medir@sulista.local",
           "perfil": "Administrador", "admin": True, "telas": []}

# A ESCALA DA CASA, com o porque de cada degrau. Vao fora disto e desvio a
# explicar, nao gosto:
#
#    0  dentro de um cartao (cabecalho colado no corpo, por padding do card)
#    9  rotulo da banda -> grade de indicadores (`.kband{gap:9px}`): DENTRO de
#       um grupo respira menos que ENTRE grupos, e e isso que faz a banda ser
#       lida como um grupo
#   16  entre indicadores da mesma grade (`.kpis{gap:16px}`)
#   18  entre cartoes de uma tela (`.view` e `.aba`) — o degrau padrao
#   25  entre BANDAS de indicadores (18 + `margin-top:7px`): duas bandas sao
#       dois assuntos, e precisam de mais ar que dois cartoes do mesmo assunto
ESPERADOS = {0, 9, 16, 18, 25}

# PAINEL DE TV TEM ESCALA PROPRIA, e nao e desleixo: e lido a metros de
# distancia, em tela cheia, sem ponteiro. Os degraus dele (24, 26, 29, 40)
# saem do `tv-grid`, e compara-los com a escala de uma tela de trabalho a
# 60 cm nao diz nada sobre nenhuma das duas.
E_TV = ("tvope", "tvfat", "tvdir")

JS_VAOS = """(vid) => {
  const v = document.getElementById(vid); if(!v) return [];
  const out = [];
  const visivel = e => e.offsetParent !== null
                    && e.getBoundingClientRect().height > 2;
  const anda = (pai, caminho) => {
    const fs = Array.from(pai.children).filter(visivel);
    for(let i = 1; i < fs.length; i++){
      const a = fs[i-1].getBoundingClientRect(), b = fs[i].getBoundingClientRect();
      // so compara quem esta EMPILHADO: dois cartoes lado a lado num grid tem
      // vao vertical negativo, e ele nao diz nada sobre respiro.
      if(b.top < a.bottom - 2) continue;
      out.push({pai: caminho, de: (fs[i-1].className||'').toString().split(' ')[0],
                para: (fs[i].className||'').toString().split(' ')[0],
                vao: Math.round(b.top - a.bottom)});
    }
    for(const f of fs){
      // NAO desce dentro do `.card`: la o respiro vem do `padding` de cada
      // bloco, e o vao entre as CAIXAS e zero mesmo quando ha 16px de ar
      // visivel. Medir ali acusaria defeito onde nao ha, que e o jeito de
      // ensinar a ignorar o relatorio.
      if(f.matches('.aba, .grid2, .grid3, .kband, .view')
         && f.children.length > 1)
        anda(f, caminho + ' > ' + ((f.className||'').toString().split(' ')[0]
                                   || f.tagName.toLowerCase()));
    }
  };
  anda(v, vid);
  return out;
}"""


def _telas() -> list[str]:
    html = (DIR_API / "static" / "index.html").read_text(encoding="utf-8")
    bloco = re.search(r"const VIEWS = \{(.*?)\};", html, re.S).group(1)
    return re.findall(r"(\w+):", bloco)


def medir(telas=None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    achados = []
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pg = nav.new_page(viewport={"width": 1500, "height": 1000})
        pg.route("**/api/**", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(USUARIO if "/api/auth/me" in r.request.url else {})))
        for tela in (telas or _telas()):
            pg.goto(f"{base}/static/index.html#{tela}")
            pg.wait_for_timeout(300)
            abas = pg.evaluate(
                "(t) => Array.from(document.querySelectorAll("
                " '#view-'+t+' .subtabs button[data-aba]')).map(b => "
                " [b.closest('.subtabs').dataset.abas, b.dataset.aba])", tela)
            for g, q in abas or [(None, None)]:
                if g:
                    pg.evaluate("([g,q]) => abaTrocar(g,q)", [g, q])
                    pg.wait_for_timeout(60)
                for v in pg.evaluate(JS_VAOS, "view-" + tela):
                    v["tela"] = tela
                    achados.append(v)
        nav.close()
    srv.shutdown()
    return achados


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    telas = None
    if "--tela" in sys.argv:
        telas = [sys.argv[sys.argv.index("--tela") + 1]]
    achados = medir(telas)
    achados = [a for a in achados if a["tela"] not in E_TV]
    dist = Counter(a["vao"] for a in achados)
    print("distribuição dos vãos (px → quantos pares):")
    for v, n in sorted(dist.items()):
        marca = "" if v in ESPERADOS else "   ← fora da escala"
        print("  %4d  %4d%s" % (v, n, marca))
    fora = [a for a in achados if a["vao"] not in ESPERADOS]
    colados = [a for a in achados if a["vao"] == 0
               and a["de"] in ("card", "kpis", "grid2", "aba", "kband")]
    print("\n%d pares medidos · %d fora da escala · %d cartões COLADOS"
          % (len(achados), len(fora), len(colados)))
    if "--detalhe" in sys.argv:
        for a in sorted(fora + colados, key=lambda x: (x["tela"], x["vao"]))[:120]:
            print("  %-10s %-34s %-12s → %-12s %4dpx"
                  % (a["tela"], a["pai"][:34], a["de"], a["para"], a["vao"]))
    else:
        piores = Counter((a["tela"], a["vao"]) for a in fora + colados)
        for (t, v), n in piores.most_common(25):
            print("  %-10s vão %4dpx  ×%d" % (t, v, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
