# -*- coding: utf-8 -*-
"""Superfície CLARA sem contraparte no tema escuro.

O QUE ISTO PEGA, E POR QUE A OUTRA AUDITORIA NÃO PEGA
=====================================================
`scripts/auditar_tema.py` varre o que está NA TELA. Superfície que só aparece
depois de um clique — modal, menu do avatar, card de login — não está lá no
momento da varredura, e foi exatamente ali que passou, em 30/08/2026, um
`background:#fff` que no tema escuro punha texto `#E9EEF4` sobre branco:
contraste 1,06:1, ilegível, em TODO modal do sistema.

POR QUE LER `document.styleSheets` E NÃO O TEXTO DO CSS
=======================================================
A primeira tentativa foi um parser próprio por regex sobre o `<style>`. Ele
devolvia ZERO com o defeito reposto de propósito — inclusive num CSS sintético
de cinco linhas —, e conferência que passa por vacuidade é pior que conferência
nenhuma. Foi jogada fora em vez de ficar dando falso verde.

Aqui quem responde "esta regra está dentro de um bloco de tema?" é o MESMO
motor que renderiza a página: o CSSOM já separou `@media`, já resolveu
`@import` e já sabe o que é seletor. Não há regex de chaves para errar.

Uso:
    uv run --no-sync python scripts/auditar_superficies.py
    uv run --no-sync python scripts/auditar_superficies.py --detalhe
"""
from __future__ import annotations

import functools
import http.server
import json
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_API = RAIZ / "api"

USUARIO = {"nome": "Medição", "email": "medir@sulista.local",
           "perfil": "Administrador", "admin": True, "telas": []}

# Superfície clara que é branca NOS DOIS temas de propósito. Declarada, não
# descoberta caso a caso: marcador sobre ladrilho de mapa e a chapa da logo no
# botão de report — os dois existem para se destacar do que está ATRÁS deles,
# que é o mapa e a pílula escura, não a página.
DELIBERADAS = ("milk-truck", "milk-leg", "#btnReport img", "tv-", "tvw",
               "tvmode", "#view-tv")

SONDA = r"""(deliberadas) => {
  /* O CSSOM NORMALIZA A COR. `background:#fff` escrito no arquivo volta daqui
     como `rgb(255, 255, 255)` — procurar hexadecimal na saída do navegador não
     acha nada, e foi assim que a primeira versão desta sonda devolveu ZERO com
     o defeito reposto de propósito. Ler as duas formas. */
  const rgbDe = v => {
    v = String(v || '');
    let m = v.match(/rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,/\s]+([\d.]+))?/);
    if(m){
      if(m[4] !== undefined && parseFloat(m[4]) < .5) return null;  // translúcido tinge
      return [+m[1], +m[2], +m[3]];
    }
    m = v.match(/#([0-9A-Fa-f]{3,8})/);
    if(!m) return null;
    let h = m[1];
    if(h.length === 3) h = h.split('').map(c=>c+c).join('');
    if(h.length < 6) return null;
    return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16),
            parseInt(h.slice(4,6),16)];
  };
  const claro = c => (.2126*c[0] + .7152*c[1] + .0722*c[2]) > 200;
  /* Percorre o CSSOM. `parentRule` diz se a regra mora dentro de um `@media`,
     e `conditionText` diz QUAL — é assim que se sabe, sem adivinhar, que uma
     cor literal está num bloco de tema (onde ela é legítima). */
  const daTema = r => {
    for(let p = r.parentRule; p; p = p.parentRule){
      const c = (p.conditionText || p.media?.mediaText || '');
      if(/prefers-color-scheme|print/.test(c)) return true;
    }
    return /\[data-theme/.test(r.selectorText || '');
  };
  const emTema = [], suspeitas = [];
  let lidas = 0;
  /* `CSSRuleList` NAO e iteravel com `for...of` no Chrome — e objeto legado,
     indexado. O `for...of` lanca, e o `try/catch` de fora engolia: a sonda
     lia ZERO regra e reportava verde. `Array.from` resolve, e o contador
     `lidas` existe para essa falha nunca mais ser silenciosa. */
  const anda = regras => {
    for(const r of Array.from(regras || [])){
      lidas++;
      /* `CSSStyleRule` TAMBEM tem `cssRules` no Chrome (CSS aninhado): vazio,
         mas TRUTHY. `if(r.cssRules) continue` pulava as 1.003 regras de estilo
         do arquivo e a sonda dizia "0 achados" com o defeito na tela. Recursao
         so quando ha filho DE VERDADE, e a regra segue sendo examinada. */
      if(r.cssRules && r.cssRules.length){ anda(r.cssRules); continue; }
      if(!r.selectorText) continue;
      if(daTema(r)){ emTema.push(r.selectorText); continue; }
      const bg = r.style && (r.style.backgroundColor || r.style.background);
      if(!bg) continue;
      /* `var(--n0)` também chega aqui, e é justamente o que está CERTO: quem
         usa token vira com o tema. Só cor literal interessa. */
      if(String(bg).includes('var(')) continue;
      const c = rgbDe(bg);
      if(!c || !claro(c)) continue;
      suspeitas.push({sel: r.selectorText,
                      cor: 'rgb(' + c.join(',') + ')'});
    }
  };
  const falhas = [];
  for(const folha of document.styleSheets){
    try{ anda(folha.cssRules); }
    catch(e){ falhas.push((folha.href || '<style>') + ': ' + e.name); }
  }
  const txtTema = emTema.join(' ');
  if(!lidas) return [{sel: '(A SONDA NAO LEU REGRA NENHUMA — resultado sem valor)',
                      cor: falhas.join(' | ') || 'sem folha'}];
  return suspeitas.filter(s => {
    if(deliberadas.some(d => s.sel.includes(d))) return false;
    const chaves = [...s.sel.matchAll(/[.#]([A-Za-z][\w-]*)/g)].map(x=>x[1]);
    /* LIMITE DE PALAVRA: sem ele `.modal` casaria com `.modal-bg`, que o bloco
       de tema declara, e a caixa branca de todo modal passaria como coberta. */
    return !chaves.some(c =>
      new RegExp('[.#]' + c.replace(/[-]/g,'\\-') + '(?![\\w-])').test(txtTema));
  });
}"""


def medir():
    from playwright.sync_api import sync_playwright
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pg = nav.new_page()
        pg.route("**/api/**", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(USUARIO if "/api/auth/me" in r.request.url else {})))
        pg.goto(f"{base}/static/index.html")
        pg.wait_for_timeout(400)
        achados = pg.evaluate(SONDA, list(DELIBERADAS))
        nav.close()
    srv.shutdown()
    return achados


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    achados = medir()
    for a in achados:
        print("   %-60s %s" % (a["sel"][:60], a["cor"]))
    print("\n%d superfície(s) clara(s) sem contraparte no tema escuro" % len(achados))
    return 1 if achados else 0


if __name__ == "__main__":
    raise SystemExit(main())
