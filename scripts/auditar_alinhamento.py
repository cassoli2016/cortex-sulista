# -*- coding: utf-8 -*-
"""Linha IRREGULAR: dois cartões lado a lado terminando em alturas diferentes.

O QUE ESTE AUDITOR MEDE, E POR QUE O DE ESPAÇOS NÃO O SUBSTITUI
==============================================================
`auditar_espacos.py` cuida do vão VERTICAL entre componentes — a escala de três
degraus da casa (9/18/25px). Ele não vê nada de errado numa linha em que o
cartão da esquerda tem 323px e o da direita 73: os dois estão a 18px do
vizinho de cima, cada um na sua coluna.

Mas é exatamente isso que se vê como "desalinhado". Dois cartões na mesma
linha, um terminando 250px acima do outro, deixam um rasgo branco no meio do
painel.

O QUE ESTAVA ERRADO, E ERA UMA LINHA
====================================
`.grid2` tinha `align-items:start`. Com ele, cada cartão se dimensiona pelo
próprio conteúdo e encosta no topo, então a linha fica com o fundo irregular.
`stretch` — que é o PADRÃO do CSS grid — faz os dois ocuparem a altura da
linha, e a linha é a altura do maior dos dois de qualquer forma.

Medido em 31/08/2026, nas 69 telas e em todas as sub-abas:

    antes  ...  17 de 57 linhas irregulares (30%), a pior com 250px
    depois ...   0

E NÃO AUMENTA A ALTURA DE TELA NENHUMA, que era o risco: a altura da linha já
era a do cartão mais alto, então esticar o menor não muda o total. Conferido —
`test_nenhuma_aba_passa_da_altura_de_uma_tela` continua verde nas 69.

A TOLERÂNCIA É DE 2px de propósito: arredondamento de subpixel em borda e
sombra produz diferenças de 1px que não são visíveis e que fariam o relatório
acusar quase toda linha — relatório com falso positivo é relatório desligado.
"""
from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import medir_paineis  # noqa: E402

# Abaixo disto é subpixel de borda e sombra, não desalinhamento que se enxergue.
TOLERANCIA = 2

_SONDA = """() => {
  const out = [];
  document.querySelectorAll('.view').forEach(v => {
    if (v.offsetParent === null) return;
    v.querySelectorAll('.grid2, .grid3').forEach(g => {
      if (g.offsetParent === null) return;
      const hs = Array.from(g.children)
        .filter(c => c.offsetParent !== null)
        .map(c => Math.round(c.getBoundingClientRect().height));
      if (hs.length > 1) out.push({tela: v.id, alturas: hs,
                                   delta: Math.max(...hs) - Math.min(...hs)});
    });
  });
  return out;
}"""


def medir(telas=None) -> list[dict]:
    """Uma entrada por LINHA de cartões, em toda tela e em toda sub-aba."""
    from playwright.sync_api import sync_playwright

    hd = functools.partial(http.server.SimpleHTTPRequestHandler,
                           directory=str(RAIZ / "api"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), hd)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    achados: list[dict] = []
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            pg = nav.new_page(viewport={"width": 1500, "height": 1000})
            pg.route("**/api/**", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(medir_paineis.USUARIO
                                if "/api/auth/me" in r.request.url else {})))
            for tela in (telas or medir_paineis._telas()):
                pg.goto(f"{base}/static/index.html#{tela}")
                pg.wait_for_timeout(300)
                abas = pg.evaluate(
                    "(t) => Array.from(document.querySelectorAll("
                    " '#view-'+t+' .subtabs button')).map(b => "
                    " [b.closest('.subtabs').dataset.abas, b.dataset.aba])", tela)
                for grupo, qual in (abas or [(None, None)]):
                    if grupo:
                        pg.evaluate("([g,q]) => abaTrocar(g,q)", [grupo, qual])
                        pg.wait_for_timeout(90)
                    for a in pg.evaluate(_SONDA):
                        achados.append({**a, "aba": qual})
            nav.close()
    finally:
        srv.shutdown()
    return achados


def main() -> int:
    achados = medir()
    ruins = sorted((a for a in achados if a["delta"] > TOLERANCIA),
                   key=lambda a: -a["delta"])
    print("linhas de cartões medidas : %d" % len(achados))
    print("IRREGULARES (> %dpx)       : %d" % (TOLERANCIA, len(ruins)))
    for a in ruins[:20]:
        print("   %-16s aba %-8s %s  -> %d px de diferença"
              % (a["tela"], a["aba"] or "-", a["alturas"], a["delta"]))
    return 1 if ruins else 0


if __name__ == "__main__":
    raise SystemExit(main())
