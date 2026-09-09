# -*- coding: utf-8 -*-
"""TELA NOVA TEM ONZE REGISTROS — e este guard varre o DISCO em vez de listar.

POR QUE ELE EXISTE
==================
O guard que já havia (`tests/frontend/test_registro_de_tela.py`) confere DUAS
telas nomeadas à mão, `poli` e `ctecp`, e não varre. É lista escrita à mão para
proteger contra o defeito de lista escrita à mão — e ela falhou exatamente como
se esperava: `integ` e `apps` nasceram depois dela, ficaram fora da barra de
filtros e do carimbo do `#meta`, e ninguém soube até alguém reparar que a tela
dizia "carregando…" para sempre.

Esta classe de defeito NÃO TEM SINTOMA, só ausência: o ícone some, a tela não
aparece no celular, a busca não acha. Nada quebra, nada fica vermelho.

O QUE ESTE GUARD COBRE, E O QUE NÃO
====================================
Cobre os cinco registros VERIFICÁVEIS por varredura, que são os que somem sem
alarme: `VIEWS`, `VIEW_GROUP`, a `<section>`, o link da barra lateral e a
entrada da gaveta do celular.

NÃO cobre `semFilterbar()` nem a lista do `#meta`: as duas são DECISÃO por
tela (a de filtros depende de a rota receber parâmetro; a do carimbo, de a tela
responder "e agora?" ou ser registro estático), e um guard que exigisse
presença nas duas transformaria escolha em obrigação. Essas seguem por leitura.

A VARREDURA SAI DO DISCO e leva `assert` contra o vazio: varredura que não acha
nada passa por vacuidade, e um `VIEWS` que a regex deixasse de casar aprovaria
o repositório inteiro em silêncio.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from api import auth

RAIZ = Path(__file__).resolve().parents[2]
HTML = io.open(RAIZ / "api" / "static" / "index.html", encoding="utf-8").read()

# ── entradas de TELAS que NÃO são tela navegável ────────────────────────────
#
# São PERMISSÃO: habilitam uma ação ou uma aba DENTRO de outra tela, e por isso
# não têm hash, nem seção, nem lugar no menu. `desrh` libera a administração de
# ciclos dentro de `des`; `dreexc` libera excluir lançamento dentro da DRE.
#
# A lista é escrita à mão — e por isso ela mesma é conferida contra o disco no
# primeiro teste. Lista errada aqui não teria sintoma: bastaria alguém pôr uma
# tela de verdade aqui para o guard parar de olhar para ela.
PERMISSOES = {"desrh", "dreexc"}


def _views() -> set[str]:
    m = re.search(r"const VIEWS = \{(.*?)\};", HTML, re.S)
    assert m, "o objeto VIEWS não foi encontrado — a regex desta varredura envelheceu"
    return set(re.findall(r"(\w+)\s*:", m.group(1)))


def _view_group() -> set[str]:
    m = re.search(r"const VIEW_GROUP\s*=\s*\{(.*?)\};", HTML, re.S)
    assert m, "o objeto VIEW_GROUP não foi encontrado — a regex envelheceu"
    return set(re.findall(r"(\w+)\s*:", m.group(1)))


NAVEGAVEIS = sorted(set(auth.TELAS) - PERMISSOES)


def test_a_varredura_nao_passa_por_vacuidade():
    """Se a regex parar de casar, tudo aqui vira verde-para-sempre."""
    assert len(NAVEGAVEIS) > 50, "auth.TELAS encolheu demais — confira o import"
    assert len(_views()) > 50, "VIEWS veio quase vazio: a regex não está casando"
    assert len(_view_group()) > 50, "VIEW_GROUP veio quase vazio"


def test_toda_entrada_de_PERMISSOES_e_mesmo_uma_permissao():
    """A lista de exceções descreve o CÓDIGO, então se confere contra ele.

    Uma permissão de verdade não tem seção no HTML e é consultada por
    `podeVer(...)` ou aparece em `ROTA_TELAS`. Se alguém puser aqui uma tela
    navegável para calar o guard, este teste acusa.
    """
    rotas = {t for _, telas in auth.ROTA_TELAS for t in telas}
    for p in sorted(PERMISSOES):
        assert p in auth.TELAS, f"{p} não está em auth.TELAS — exceção obsoleta"
        assert f'id="view-{p}"' not in HTML, (
            f"{p} TEM seção no HTML: é tela navegável, não pode estar em PERMISSOES")
        assert f"podeVer('{p}')" in HTML or p in rotas, (
            f"{p} não é consultada como permissão em lugar nenhum — exceção sem lastro")


@pytest.mark.parametrize("tela", NAVEGAVEIS)
def test_tela_esta_registrada_nos_cinco_pontos(tela):
    """Cada parâmetro é um guard próprio: um `freq` que entrasse só no VIEWS
    ficaria fora do menu do celular sem nada quebrar."""
    faltando = []
    if tela not in _views():
        faltando.append("VIEWS (o roteador não conhece a tela)")
    if tela not in _view_group():
        faltando.append("VIEW_GROUP (a tela fica sem grupo no menu)")
    if f'id="view-{tela}"' not in HTML:
        faltando.append("<section class=\"view\" id=\"view-%s\">" % tela)
    if f'data-view="{tela}"' not in HTML:
        faltando.append("link na barra lateral (data-view)")
    if f'href="#{tela}" onclick="fecharDrawer()"' not in HTML:
        faltando.append("entrada na gaveta do celular")
    assert not faltando, (
        "a tela '%s' (%s) não está registrada em: %s"
        % (tela, auth.TELAS[tela][0], "; ".join(faltando)))


def test_o_menu_do_celular_tem_o_mesmo_grupo_da_barra_lateral():
    """A gaveta é o menu de quem está na rua. Tela que existe na barra lateral
    e não na gaveta some para o celular inteiro, e ninguém do escritório vê."""
    na_barra = set(re.findall(r'data-view="(\w+)"', HTML))
    na_gaveta = set(re.findall(r'href="#(\w+)" onclick="fecharDrawer\(\)"', HTML))
    so_na_barra = {t for t in na_barra if t in auth.TELAS} - na_gaveta
    assert not so_na_barra, f"telas fora da gaveta do celular: {sorted(so_na_barra)}"
