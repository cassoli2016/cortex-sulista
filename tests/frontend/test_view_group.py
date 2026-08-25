"""VIEW_GROUP tem de concordar com a barra lateral.

O mapa `VIEW_GROUP` diz qual grupo do acordeao abrir ao navegar para cada tela,
e e escrito a mao — ou seja, duplica a organizacao que ja existe no HTML da
barra lateral. Duplicata escrita a mao diverge: a Premiacao de Motoristas
estava marcada como 'Fro' e o link dela mora em 'Tel', entao clicar nela abria
o grupo Frota e a pessoa ficava vendo o menu de outra area.
"""
import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def _view_group(html: str) -> dict[str, str]:
    m = re.search(r"const VIEW_GROUP *= *\{(.*?)\};", html, re.S)
    assert m, "VIEW_GROUP nao encontrado"
    corpo = re.sub(r"//.*", "", m.group(1))
    return {k: v for k, v in re.findall(r"(\w+) *: *'([^']*)'", corpo)}


def _grupo_na_sidebar(html: str) -> dict[str, str]:
    """Para cada link da barra lateral, o sufixo do `subs<X>` que o contem."""
    fora: dict[str, str] = {}
    for bloco in re.finditer(
            r'<div class="subs[^"]*" id="subs(\w+)">(.*?)</div>', html, re.S):
        grupo, dentro = bloco.group(1), bloco.group(2)
        for v in re.findall(r'data-view="(\w+)"', dentro):
            fora[v] = grupo
    return fora


def test_cada_tela_abre_o_grupo_em_que_ela_realmente_esta(html):
    mapa, real = _view_group(html), _grupo_na_sidebar(html)
    erros = []
    for view, grupo in mapa.items():
        if not grupo:            # home e copiloto nao tem grupo, de proposito
            continue
        if view not in real:
            continue             # tela sem link na barra (mobile-only etc.)
        if real[view] != grupo:
            erros.append(f"{view}: VIEW_GROUP diz '{grupo}', "
                         f"mas o link esta em '{real[view]}'")
    assert not erros, "acordeao abriria o grupo errado -> " + " · ".join(erros)


def test_toda_tela_da_barra_lateral_esta_no_mapa(html):
    """Tela fora do mapa nao abre grupo nenhum ao ser aberta pela busca global
    — foi o caso dos Portais de Antecipacao e do Milk Run."""
    mapa, real = _view_group(html), _grupo_na_sidebar(html)
    faltando = sorted(v for v in real if v not in mapa)
    assert not faltando, ("telas na barra lateral e fora de VIEW_GROUP: "
                          + ", ".join(faltando))
