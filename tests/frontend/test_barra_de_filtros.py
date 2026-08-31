# -*- coding: utf-8 -*-
"""A barra de filtros alinha input e select — e so o NAVEGADOR responde isso.

O DEFEITO, E POR QUE ELE SOBREVIVEU A UMA CORRECAO
==================================================
Numa barra com `<input>` e `<select>` lado a lado, os inputs mediam 42px e os
selects 34px. Como `.milk-filtros` alinha pelo FUNDO, a diferenca sobe para o
topo: os rotulos de metade dos campos ficavam oito pixels acima dos da outra
metade.

Ja existia uma regra escrita para consertar exatamente isso, com comentario e
tudo -- e ela funcionava so metade:

    .milk-filtros input, .milk-filtros select{height:34px;min-height:0}   (0,1,1)
    .view input:not([type=checkbox]):not([type=radio]):not([type=file])   (0,4,1)
      { ... min-height:42px }

No SELECT a regra global pontua (0,1,1), EMPATA, e a ordem no arquivo decide a
favor da barra. No INPUT os tres `:not()` levam a global a (0,4,1) e ela vence:
o `height:34px` era aplicado e o `min-height:42px` o sobrepunha.

A LICAO E DE METODO, e ja esta escrita nesta casa: **ler o texto do CSS nao diz
se a regra chegou**. Quem sabe se ela venceu a briga de especificidade e o
motor que renderiza. Por isso este teste MEDE, em vez de procurar o seletor no
arquivo -- procurar o seletor teria passado o tempo todo, porque ele estava la.

Vale para as tres telas que misturam os dois tipos na mesma barra. Uma lista
escrita a mao envelheceria calada (foi assim que o teste de abas perdeu a
Jornada), entao a lista sai do proprio HTML.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HTML = (Path(__file__).resolve().parents[2] / "api" / "static"
        / "index.html").read_text(encoding="utf-8")


def _telas_com_barra_mista() -> list[str]:
    """Telas cuja `.milk-filtros` tem input E select — as unicas em que a
    diferenca de altura aparece."""
    achadas = []
    for m in re.finditer(r'<section class="view[^"]*" id="view-(\w+)">', HTML):
        corpo = HTML[m.end():HTML.index("</section>", m.end())]
        for bm in re.finditer(r'<div class="milk-filtros">(.*?)</div>\s*</div>',
                              corpo, re.S):
            b = bm.group(1)
            if re.search(r"<input", b) and re.search(r"<select", b):
                achadas.append(m.group(1))
                break
    return achadas


def test_existe_pelo_menos_uma_barra_mista():
    """Guarda contra o teste perder o alvo: se a marcacao mudar de forma e o
    regex parar de casar, os testes abaixo passariam por VACUIDADE, varrendo
    uma lista vazia e reportando verde sem medir nada."""
    assert _telas_com_barra_mista(), "nenhuma barra com input e select — alvo perdido"


@pytest.mark.parametrize("tela", _telas_com_barra_mista())
def test_input_e_select_tem_a_MESMA_altura_na_barra(pagina, tela):
    pg, base_url = pagina
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(ADMIN if "/api/auth/me" in r.request.url else {})))
    pg.goto(base_url + "/static/index.html#" + tela)
    pg.wait_for_selector("#view-" + tela + " .milk-filtros", timeout=20000)
    alturas = pg.eval_on_selector_all(
        "#view-" + tela + " .milk-filtros input, #view-" + tela + " .milk-filtros select",
        "els => [...new Set(els.map(e => Math.round(e.getBoundingClientRect().height)))]")
    assert len(alturas) == 1, (
        "campos de alturas diferentes na barra de %s: %s — a barra alinha pelo "
        "FUNDO, entao a diferenca vira rotulo desalinhado no topo" % (tela, alturas))


@pytest.mark.parametrize("tela", _telas_com_barra_mista())
def test_os_rotulos_da_barra_ficam_na_MESMA_linha(pagina, tela):
    """O sintoma que o usuario ve nao e a altura do campo: e o rotulo fora de
    linha. Medir o sintoma, e nao so a causa, e o que impede a regressao de
    voltar por outro caminho (um `padding` novo, por exemplo)."""
    pg, base_url = pagina
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(ADMIN if "/api/auth/me" in r.request.url else {})))
    pg.goto(base_url + "/static/index.html#" + tela)
    pg.wait_for_selector("#view-" + tela + " .milk-filtros", timeout=20000)
    # so a PRIMEIRA linha da barra: com muitos campos ela quebra, e ai topos
    # diferentes sao o layout funcionando, nao o defeito.
    topos = pg.eval_on_selector_all(
        "#view-" + tela + " .milk-filtros label",
        """els => { const t = els.map(e => Math.round(e.getBoundingClientRect().top));
                    const primeira = Math.min(...t);
                    return [...new Set(t.filter(x => x < primeira + 30))]; }""")
    assert len(topos) == 1, (
        "rotulos desalinhados na mesma linha em %s: %s" % (tela, topos))
