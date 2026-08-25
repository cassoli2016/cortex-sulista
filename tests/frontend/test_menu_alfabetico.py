"""O menu fica em ordem alfabetica — e continua ficando.

Visao Geral e Copiloto Cortex sao os pontos de entrada e ficam no topo, fora da
ordenacao: procura-los na letra V e na C seria pior.

Este teste existe porque menu e o lugar onde tela nova entra "no fim" por
inercia. Sem ele, em tres telas a ordem alfabetica vira ordem de chegada.
"""
import re
import unicodedata
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


def chave(txt: str) -> str:
    """Ordem de dicionario: sem acento, minusculo. Comparar por byte poria
    'Operacao' depois de 'Paineis TV' e 'ANTT' no fim."""
    n = unicodedata.normalize("NFD", txt)
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip().lower()


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def _grupos(html: str) -> list[tuple[str, str]]:
    """(nome do grupo, corpo dos subitens) na ordem em que aparecem."""
    return [(m.group(2), m.group(3)) for m in re.finditer(
        r'<button class="group" id="grp(\w+)"[^>]*>\r?\n.*?'
        r'<span>([^<]+)</span><span class="ic chev".*?'
        r'<div class="subs[^"]*" id="subs\1">\r?\n(.*?)[ \t]*</div>\r?\n',
        html, re.S)]


def test_os_grupos_estao_em_ordem(html):
    nomes = [g for g, _ in _grupos(html)]
    assert nomes and nomes == sorted(nomes, key=chave), (
        "grupos fora de ordem: " + " · ".join(nomes))


def test_os_itens_de_cada_grupo_estao_em_ordem(html):
    fora = []
    for nome, corpo in _grupos(html):
        itens = re.findall(
            r'<a href="#\w+" class="sub"[^>]*>.*?<span>([^<]+)</span></a>', corpo)
        if itens != sorted(itens, key=chave):
            fora.append(f"{nome}: {' · '.join(itens)}")
    assert not fora, "itens fora de ordem -> " + " | ".join(fora)


def test_nao_ha_mais_subsecoes_de_tema(html):
    """O Financeiro era dividido por tema (Caixa, A receber, A pagar, Bancos).
    Com a lista alfabetica esses cabecalhos so atrapalhariam a busca visual."""
    assert 'class="subsec"' not in html


def test_visao_geral_e_copiloto_seguem_no_topo(html):
    """Fora da ordenacao de proposito: sao a porta de entrada."""
    i_home = html.index('data-view="home"')
    i_cop = html.index('data-view="cop"')
    i_1o_grupo = html.index('<button class="group"')
    assert i_home < i_cop < i_1o_grupo


def test_a_gaveta_do_celular_segue_a_mesma_ordem(html):
    """Lista escrita a mao e separada da barra lateral: se ficar na ordem
    antiga, a mesma pessoa ve dois menus diferentes no computador e no
    celular."""
    fora = []
    for m in re.finditer(r'<div class="dgrp-b">\r?\n(.*?)[ \t]*</div>\r?\n',
                         html, re.S):
        itens = [re.sub(r"<[^>]+>", "", a).strip()
                 for a in re.findall(r'<a href="#\w+"[^>]*>.*?</a>', m.group(1))]
        if len(itens) > 1 and itens != sorted(itens, key=chave):
            fora.append(" · ".join(itens))
    assert not fora, "gaveta fora de ordem -> " + " | ".join(fora)
