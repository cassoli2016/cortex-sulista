# -*- coding: utf-8 -*-
"""Percorre as telas no tema ESCURO e acha o que ficou com cor de tema claro.

POR QUE UM AUDITOR E NÃO UMA VARREDURA NO CSS
=============================================
O `index.html` tem ~205 literais de cor fora do `:root` e ~98 atributos
`style=` com cor. Trocar todos às cegas é o caminho para quebrar o tema CLARO
(que estava certo) tentando consertar o escuro — e a maior parte deles está
sobre a barra lateral navy ou nos painéis de TV, superfícies que já são
escuras nos dois temas e não devem mudar nada.

O que interessa não é onde há literal: é onde o resultado FICA ILEGÍVEL. Então
a pergunta é feita ao navegador, com a página montada: para cada elemento com
texto, qual a cor computada, qual o fundo atrás dele, e qual o contraste.

O que ele reporta:
  - texto com contraste abaixo de 4,5:1 (3:1 para texto grande);
  - "ilha clara": elemento com fundo claro no meio de uma página escura, que é
    a assinatura de um `background:#fff` que ficou para trás.

Uso:
    uv run --no-sync python scripts/auditar_tema.py            # tudo
    uv run --no-sync python scripts/auditar_tema.py home prem  # só estas
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

USUARIO = {"nome": "Auditoria", "email": "audit@sulista.local",
           "perfil": "Administrador", "admin": True, "telas": []}

# O JS roda NA PÁGINA. Sobe a árvore atrás do primeiro ancestral com fundo
# opaco — `background-color` de um elemento sem fundo próprio é
# `rgba(0,0,0,0)`, e comparar texto contra transparente não diz nada.
SONDA = r"""
() => {
  const lum = c => {
    const [r,g,b] = c;
    const f = v => { v/=255; return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); };
    return .2126*f(r) + .7152*f(g) + .0722*f(b);
  };
  const rgb = s => {
    const m = String(s).match(/rgba?\(([^)]+)\)/);
    if(!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return {c:[p[0],p[1],p[2]], a: p.length > 3 ? p[3] : 1};
  };
  const contraste = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la,lb) + .05) / (Math.min(la,lb) + .05);
  };
  const fundoDe = el => {
    let n = el;
    while(n && n !== document.documentElement){
      const b = rgb(getComputedStyle(n).backgroundColor);
      if(b && b.a > .5) return b.c;
      n = n.parentElement;
    }
    const b = rgb(getComputedStyle(document.body).backgroundColor);
    return b ? b.c : [255,255,255];
  };
  const visivel = el => {
    const r = el.getBoundingClientRect();
    if(r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
  };
  const caminho = el => {
    const p = [];
    for(let n = el; n && n !== document.body && p.length < 4; n = n.parentElement){
      let s = n.tagName.toLowerCase();
      if(n.id) s += '#' + n.id;
      else if(n.className && typeof n.className === 'string' && n.className.trim())
        s += '.' + n.className.trim().split(/\s+/).slice(0,2).join('.');
      p.unshift(s);
    }
    return p.join(' > ');
  };

  const achados = [];
  const vistos = new Set();
  const fundoPagina = fundoDe(document.body);
  const paginaEscura = lum(fundoPagina) < .2;
  /* No tema CLARO a "ilha" que interessa e a ESCURA: um card que ficou com
     fundo de tema escuro no meio da pagina branca. Mesma regra, sinal
     invertido. */
  const ilhaErrada = b => paginaEscura ? lum(b) > .5 : lum(b) < .2;

  document.querySelectorAll('*').forEach(el => {
    if(!visivel(el)) return;
    /* PAINEL DE TV é escuro DE PROPÓSITO nos dois temas — auditá-lo produziria
       achado sobre uma decisão deliberada. */
    if(el.closest('#view-tvfat, #view-tvope, aside, #drawer, #loginOverlay')) return;

    const cs = getComputedStyle(el);
    const propio = rgb(cs.backgroundColor);

    /* ILHA CLARA: fundo claro dentro de página escura.
       SÓ SUPERFÍCIE, não amostra de cor. A primeira versão acusava os
       quadradinhos de 14px da legenda -- que são o VERDE DO SEMÁFORO, ou seja
       exatamente o que tem de ficar claro. Chip, bolinha e swatch carregam a
       cor como informação; superfície é o que tem tamanho de superfície. */
    const cx = el.getBoundingClientRect();
    /* A REGRA E ASSIMETRICA PORQUE O DESIGN E. No tema CLARO, controle com
       fundo escuro e o botao primario da casa (navy solido) -- desenho
       deliberado, e acusa-lo produziu 146 achados de um so padrao, ou seja um
       relatorio que ninguem leria. No tema ESCURO nao existe padrao de
       controle com fundo claro: um `select` branco ali e literal esquecido, e
       foi assim que os campos de filtro apareceram. Entao controle so entra
       na conta quando a pagina e escura.
       Em ambos os temas, o TEXTO de qualquer elemento continua sendo medido
       pela regra de contraste -- que e a que diz se da para ler. */
    const controle = el.matches('button, a, input, select, textarea, .badge, .chip')
                     || !!el.closest('button, a');
    if(propio && propio.a > .5 && ilhaErrada(propio.c)
       && (paginaEscura || !controle)
       && cx.width >= 60 && cx.height >= 26){
      const ch = caminho(el);
      if(!vistos.has('ilha|' + ch)){
        vistos.add('ilha|' + ch);
        achados.push({tipo: paginaEscura ? 'ilha-clara' : 'ilha-escura', onde: ch,
                      fundo: cs.backgroundColor, texto: cs.color});
      }
    }

    // TEXTO: só nós com texto próprio
    const temTexto = Array.from(el.childNodes).some(
      n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if(!temTexto) return;
    const cor = rgb(cs.color);
    if(!cor || cor.a < .5) return;
    const fundo = fundoDe(el);
    const r = contraste(cor.c, fundo);
    const px = parseFloat(cs.fontSize) || 14;
    const negrito = (parseInt(cs.fontWeight, 10) || 400) >= 700;
    const minimo = (px >= 24 || (px >= 18.66 && negrito)) ? 3 : 4.5;
    if(r < minimo){
      const ch = caminho(el);
      if(!vistos.has('txt|' + ch)){
        vistos.add('txt|' + ch);
        achados.push({tipo:'contraste', onde: ch, razao: Math.round(r*100)/100,
                      minimo, texto: cs.color, fundo: 'rgb(' + fundo.join(',') + ')',
                      amostra: (el.textContent || '').trim().slice(0, 40)});
      }
    }
  });
  return achados;
}
"""


def _telas() -> list[str]:
    html = (DIR_API / "static" / "index.html").read_text(encoding="utf-8")
    bloco = re.search(r"const VIEWS = \{(.*?)\};", html, re.S).group(1)
    return re.findall(r"(\w+):", bloco)


def main() -> int:
    # O console do Windows e cp1252: uma amostra de texto com acento estoura
    # o print e derruba a auditoria no meio -- perdendo os achados que ja
    # tinham sido encontrados.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from playwright.sync_api import sync_playwright

    pedidas = [a for a in sys.argv[1:] if not a.startswith("-")]
    telas = pedidas or _telas()
    # `--claro` audita o tema CLARO. Serve para provar que o escuro nao foi
    # comprado a custa do que ja funcionava -- e o claro e o tema da maioria.
    esquema = "light" if "--claro" in sys.argv else "dark"
    # `--fixo` prova o OUTRO caminho, que nao estava sendo testado: existem
    # DOIS blocos de tema escuro -- o `@media (prefers-color-scheme)` e o
    # `:root[data-theme="dark"]` da escolha explicita. Sabotar o segundo nao
    # produzia achado nenhum, ou seja metade do tema passava por vacuidade.
    # Com `--fixo` a preferencia do NAVEGADOR e a OPOSTA da escolhida, o que
    # de quebra prova que o carimbo vence o sistema nos dois sentidos.
    fixo = "--fixo" in sys.argv
    if fixo:
        esquema = "light" if esquema == "dark" else "dark"

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DIR_API))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    total = 0
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        # `color_scheme` DO NAVEGADOR, não o nosso atributo: é o caminho que a
        # maioria dos usuários percorre (a preferência do sistema, sem escolha
        # explícita), e é justamente o que um `[data-theme]` mal escrito não
        # cobre.
        pg = nav.new_page(color_scheme=esquema, viewport={"width": 1500,
                                                         "height": 1000})
        if fixo:
            # o caminho REAL do usuario: a escolha fica no localStorage e o
            # script do `<head>` a carimba antes do primeiro pixel.
            pg.add_init_script(
                "try{localStorage.setItem('cortex-tema','%s')}catch(e){}"
                % ("claro" if esquema == "dark" else "escuro"))
        pg.route("**/api/**", lambda rota: rota.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(USUARIO if "/api/auth/me" in rota.request.url else {})))
        erros: list[str] = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        for tela in telas:
            pg.goto(f"{base}/static/index.html#{tela}")
            pg.wait_for_timeout(450)
            for a in pg.evaluate(SONDA):
                total += 1
                if a["tipo"].startswith("ilha"):
                    print(f"[{tela:9}] {a['tipo'].upper():12} {a['onde']}  fundo={a['fundo']}")
                else:
                    print(f"[{tela:9}] CONTRASTE {a['razao']:>5}  (min {a['minimo']})"
                          f"  {a['onde']}  \"{a['amostra']}\"")
        nav.close()
    srv.shutdown()
    # Com `--fixo`, `esquema` e a preferencia do NAVEGADOR e o tema que
    # de fato foi auditado e o OPOSTO dela -- e a escolha carimbada que
    # vence. Reportar `esquema` ali dizia "dark" numa auditoria do claro.
    efetivo = ("light" if esquema == "dark" else "dark") if fixo else esquema
    print(f"\n{total} achado(s) em {len(telas)} tela(s) - tema {efetivo}"
          f" - {'escolha explicita, sistema no oposto' if fixo else 'preferencia do sistema'}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
