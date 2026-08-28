"""Os blocos da tela de CT-e de Contrapartida nao podem encostar na borda.

`.card` nao tem padding proprio — cada bloco de conteudo poe o seu. Era a
mesma armadilha ja documentada no arquivo para `.ges-cfg`: "Volume por mes",
"Passivo acumulado" e "Ler com atencao" entravam no cartao como div CRU, e as
barras corriam de borda a borda.

O teste carrega o index.html real e le a folha de estilo pelo navegador, em vez
de procurar a regra por texto: o que importa e o valor COMPUTADO, que depende
da especificidade do seletor `>` e de quem mais casa com o elemento.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"

# Os blocos que entram no cartao como div cru e precisam do proprio
# espacamento. `cpPassivo` saiu da tela (o acumulado nao vira trabalho) e deu
# lugar a `cpPront`, a prontidao da fila; `cpAvisos` saiu em 28/08/2026 - o
# cartao "Ler com atencao" era uma lista corrida de frases competindo com os
# cartoes e com a fila. Os avisos continuam vindo do servidor, porque o
# relatorio de e-mail da contrapartida os consome.
BLOCOS = ("cpMes", "cpPront")


def test_os_tres_blocos_declaram_a_classe():
    """Sem a classe no HTML a regra de CSS nao alcanca nada — e o defeito
    volta calado, porque a folha de estilo continua correta."""
    s = HTML.read_text(encoding="utf-8")
    for ident in BLOCOS:
        m = re.search(r'<div id="' + ident + r'"([^>]*)>', s)
        assert m, f"#{ident} sumiu da tela"
        assert "cpbloco" in m.group(1), f"#{ident} voltou a ser div cru"


def test_o_padding_computado_afasta_o_conteudo_da_borda(pagina):
    pg, base = pagina
    pg.goto(f"{base}/static/index.html")
    medido = pg.evaluate(
        """() => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = '<div class="head"><h2>t</h2></div>'
          + '<div class="cpbloco"><div style="margin:0 0 10px">a</div>'
          + '<div style="margin:0 0 10px">b</div></div>';
        document.body.appendChild(card);
        const bloco = card.querySelector('.cpbloco');
        const s = getComputedStyle(bloco);
        const cab = getComputedStyle(card.querySelector('.head'));
        const ult = getComputedStyle(bloco.lastElementChild);
        return {left: s.paddingLeft, right: s.paddingRight,
                top: s.paddingTop, bottom: s.paddingBottom,
                cabLeft: cab.paddingLeft, ultimaMargem: ult.marginBottom};
        }""")

    assert medido["left"] != "0px" and medido["right"] != "0px", (
        "o bloco voltou a encostar na borda lateral do cartao")
    assert medido["top"] != "0px" and medido["bottom"] != "0px"


def test_alinha_com_o_titulo_do_cartao(pagina):
    """Barra que comeca antes do titulo que a nomeia faz o cartao parecer
    torto mesmo com a borda intacta."""
    pg, base = pagina
    pg.goto(f"{base}/static/index.html")
    medido = pg.evaluate(
        """() => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = '<div class="head"><h2>t</h2></div>'
          + '<div class="cpbloco"><div>a</div></div>';
        document.body.appendChild(card);
        return {bloco: getComputedStyle(card.querySelector('.cpbloco')).paddingLeft,
                cab: getComputedStyle(card.querySelector('.head')).paddingLeft};
        }""")
    assert medido["bloco"] == medido["cab"]


def test_o_espacamento_entre_barras_e_gap_e_nao_margem(pagina):
    """As barras nascem com `style=` inline vindo do JS, e estilo inline vence
    folha de estilo: um `:last-child{margin-bottom:0}` seria ignorado em
    silencio. Com `gap` a ultima barra nao pendura margem — que era o que
    deixava o vao ate a borda de baixo diferente em cada cartao."""
    pg, base = pagina
    pg.goto(f"{base}/static/index.html")
    medido = pg.evaluate(
        """() => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = '<div class="cpbloco"><div>a</div><div>b</div></div>';
        document.body.appendChild(card);
        const b = card.querySelector('.cpbloco');
        const s = getComputedStyle(b);
        return {gap: s.rowGap, display: s.display,
                ultimo: getComputedStyle(b.lastElementChild).marginBottom};
        }""")
    assert medido["display"] == "flex"
    assert medido["gap"] != "normal" and medido["gap"] != "0px", (
        "sem gap as barras se encostam")
    assert medido["ultimo"] == "0px"


def test_o_js_nao_devolve_mais_margem_inline_nos_blocos():
    """Se o JS voltar a emitir `margin` inline, o `gap` continua valendo mas a
    ultima barra pendura margem de novo — e o defeito volta calado."""
    s = HTML.read_text(encoding="utf-8")
    trecho = s[s.index("document.getElementById('cpMes')"):
               s.index("document.getElementById('hintCp')")]
    assert "margin:0 0" not in trecho, (
        "voltou margem inline em cpMes/cpPassivo — use o gap do .cpbloco")


def test_grade_de_indicadores_dentro_de_cartao_tem_espacamento():
    """`.kpis` solta na pagina nao tem espacamento proprio, e esta certo: ela
    fica ENTRE cartoes. Dentro de UM cartao isso vira conteudo encostado nas
    quatro bordas - o mesmo defeito que os blocos da contrapartida ja tinham
    tido, repetido em sete cartoes do painel."""
    import pathlib
    import re

    html = (pathlib.Path(__file__).resolve().parents[2]
            / "api" / "static" / "index.html").read_text(encoding="utf-8")
    regra = re.search(r'\.card>\.kpis\{([^}]*)\}', html)
    assert regra, "sem regra de espacamento para .kpis dentro de .card"
    assert "padding" in regra.group(1)
    # o horizontal casa com o do titulo do cartao (.card .head usa 18px):
    # conteudo que comeca antes do titulo que o nomeia deixa o cartao torto
    assert "18px" in regra.group(1)


def test_blocos_da_portaria_nao_encostam_na_borda():
    """A Portaria repetia, intocada, o mesmo defeito que a contrapartida ja
    tinha corrigido: blocos entrando no cartao como div cru."""
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[2]
            / "api" / "static" / "index.html").read_text(encoding="utf-8")
    for ident in ("poliRank", "poliDec", "poliAvisos"):
        assert f'<div id="{ident}" class="cpbloco">' in html, ident


def test_a_tela_de_contrapartida_nao_declara_display_no_id():
    """Guarda de um defeito que foi ao ar: para dar respiro entre os cartoes,
    um `display:flex` foi declarado em `#view-ctecp`. Seletor de ID vence o
    `.view{display:none}` que liga e desliga cada tela, e a contrapartida
    passou a ser desenhada POR CIMA de todas as outras.

    Quem manda no `display` de uma tela e `.view` / `.view.on`. Regra de tela
    especifica pode mudar `gap`, `padding`, cor - nunca `display`."""
    import re
    s = HTML.read_text(encoding="utf-8")
    for m in re.finditer(r"#view-[a-z]+\s*\{([^}]*)\}", s):
        assert "display" not in m.group(1), (
            "regra de #view-* declarando display vence o .view{display:none} e "
            "faz a tela aparecer em todas as outras: " + m.group(0)[:120])


def test_os_paineis_das_abas_separam_os_cartoes():
    """O `gap` da tela nao alcanca os cartoes: eles sao filhos dos PAINEIS das
    abas. Sem gap no painel, os cartoes ficam colados (medido: 0px)."""
    s = HTML.read_text(encoding="utf-8")
    regra = "#cpAbaDespacho,#cpAbaImplantacao,#cpAbaTransmitidos{"
    assert regra in s, "os paineis das abas voltaram a ficar sem espacamento"
    corpo = s[s.index(regra):s.index("}", s.index(regra))]
    assert "gap" in corpo and "flex" in corpo
