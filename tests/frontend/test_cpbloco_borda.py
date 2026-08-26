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

# Os tres blocos que o usuario apontou, com a classe que passaram a ter.
BLOCOS = ("cpMes", "cpPassivo", "cpAvisos")


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
