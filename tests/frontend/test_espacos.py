"""A distância entre componentes é uma ESCALA, não uma decisão por tela.

O QUE ACONTECEU (30/08/2026)
============================
Ao dividir 29 telas em sub-abas, os cartões deixaram de ser filhos do `.view`
— que é uma coluna flex com `gap:18px` — e passaram a ser filhos de um
`<div class="aba">` que não tinha regra nenhuma. Vão ZERO: cartão colado em
cartão, em todas as telas divididas, sem uma linha de erro no console.

A medição achou mais três famílias que ninguém tinha visto:

  - a barra de sub-abas somava a `margin` dela ao `gap` da coluna e ficava a
    32px do painel, o dobro de todo o resto;
  - um `<div id="…-avisos"></div>` VAZIO tem altura zero mas continua sendo um
    item da coluna flex, então os vizinhos ficavam a 18 + 18 = 36px — um buraco
    visível sem nada dentro dele;
  - o `.banner-inline` traz recuo lateral de 18px para viver DENTRO de um card;
    como filho direto da tela, ele saía desalinhado dos cartões ao lado.

Antes: 62 pares colados e 123 fora da escala. Depois: zero e zero.

A ESCALA, E O PORQUÊ DE CADA DEGRAU
===================================
   9px  rótulo da banda → grade de indicadores. DENTRO de um grupo respira
        menos que ENTRE grupos — é isso que faz a banda ser lida como um grupo.
  18px  entre cartões de uma tela. O degrau padrão.
  25px  entre BANDAS de indicadores (18 + 7). Duas bandas são dois assuntos, e
        pedem mais ar que dois cartões do mesmo assunto.

Dentro do card a régua é outra — lá o respiro vem do `padding` de cada bloco, e
o vão entre as caixas é zero mesmo havendo 16px de ar visível. Por isso o
auditor não desce no `.card`: medir ali acusaria defeito onde não há, que é o
jeito de ensinar a ignorar o relatório.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

pytest.importorskip("playwright.sync_api")
import auditar_espacos  # noqa: E402


@pytest.fixture(scope="module")
def vaos():
    return [a for a in auditar_espacos.medir()
            if a["tela"] not in auditar_espacos.E_TV]


def test_nenhum_componente_fica_colado_no_vizinho(vaos):
    """Vão zero entre dois cartões é sempre defeito: ou o container perdeu o
    `gap`, ou alguém embrulhou os filhos num `<div>` sem regra."""
    colados = [(a["tela"], a["pai"], a["de"], a["para"]) for a in vaos
               if a["vao"] == 0]
    assert not colados, "componentes colados: %s" % colados[:12]


def test_toda_distancia_esta_na_escala_da_casa(vaos):
    """Um degrau novo tem de ser uma DECISÃO, com motivo — não a soma acidental
    de uma `margin` esquecida com o `gap` do container. Foi assim que
    apareceram o 32px das sub-abas, o 36px do placeholder vazio e o 26px do
    seletor de escopo do RH."""
    fora = Counter((a["tela"], a["vao"]) for a in vaos
                   if a["vao"] not in auditar_espacos.ESPERADOS)
    assert not fora, (
        "distância fora da escala %s: %s — se o degrau novo é deliberado, "
        "declare-o em ESPERADOS com o motivo"
        % (sorted(auditar_espacos.ESPERADOS), dict(fora)))
