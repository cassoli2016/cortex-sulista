"""Gera a logo da Sulista para os e-mails (PNG) a partir do SVG do repositório.

POR QUE PNG, E NÃO O SVG QUE JÁ EXISTE: o Outlook para Windows renderiza e-mail
com o motor do Word e não desenha SVG — a logo sairia como um quadrado vazio
justamente no cliente da diretoria. PNG embutido (`cid:`) é o que todos mostram.

A IMAGEM É O SVG OFICIAL (`api/static/sulista-logo-branco.svg`) rasterizado
pelo Chromium, e não um redesenho: marca redesenhada à mão envelhece separada
da marca do produto. É a mesma regra do selo do CÓRTEX, que é um quadro do
próprio `anel.js`. Mudou o SVG, roda-se isto de novo.

BRANCA E COM FUNDO TRANSPARENTE: ela mora na faixa tijolo do cabeçalho
(`painel.cabecalho`). Em 3× a altura de exibição (24 px → 72 px), para ficar
nítida em tela de alta densidade sem pesar na mensagem.

Uso:
  uv run --no-sync python scripts/gerar_logo_sulista_email.py
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SVG = RAIZ / "api" / "static" / "sulista-logo-branco.svg"
PNG = RAIZ / "api" / "static" / "sulista-logo-email.png"
ALTURA_CSS = 24      # a altura em que o e-mail a exibe (`painel.SULISTA_ALTURA`)
ESCALA = 3


def proporcao() -> float:
    """Largura ÷ altura do `viewBox` do SVG oficial."""
    vb = re.search(r'viewBox="([^"]+)"', SVG.read_text(encoding="utf-8")).group(1).split()
    return float(vb[2]) / float(vb[3])


def main() -> int:
    from playwright.sync_api import sync_playwright

    largura = round(ALTURA_CSS * proporcao(), 2)
    dados = base64.b64encode(SVG.read_bytes()).decode()
    html = ('<html><body style="margin:0;background:transparent">'
            f'<img id="l" src="data:image/svg+xml;base64,{dados}" '
            f'style="display:block;width:{largura}px;height:{ALTURA_CSS}px">'
            '</body></html>')
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(device_scale_factor=ESCALA,
                          viewport={"width": 400, "height": 100})
        pg.set_content(html)
        pg.wait_for_function("document.getElementById('l').complete")
        pg.locator("#l").screenshot(path=str(PNG), omit_background=True)
        nav.close()
    print(f"{PNG.relative_to(RAIZ)}: {PNG.stat().st_size} bytes "
          f"(exibida em {largura:.0f}x{ALTURA_CSS} px, gerada em {ESCALA}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
