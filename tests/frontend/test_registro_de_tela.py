"""Uma tela nova precisa entrar em SEIS lugares. Estes testes cobrem os dois
que ninguem verificava - e que foram justamente os dois que eu errei.

Registrar uma tela no CORTEX exige: o link na barra lateral, o link na gaveta
do celular, `VIEW_GROUP`, `LOADMAP`, o RBAC (`api/auth.TELAS` + `ROTA_TELAS`)
e o registro `VIEWS`. Ja havia teste para a gaveta e para o VIEW_GROUP.

Faltavam estes dois, e o modo de falhar dos dois e SILENCIOSO:

- fora de `VIEWS`, o router faz `VIEWS[h] ? h : 'home'` e o clique cai calado
  na Visao Geral - a tela existe, tem dado, tem rota, e simplesmente nao abre;
- um `data-ic` sem chave em `ICONS` nao levanta erro nenhum, so deixa o espaco
  do icone vazio no menu.
"""
import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def _views(html: str) -> set[str]:
    i = html.index("const VIEWS = {")
    bloco = html[i:html.index("};", i)]
    return set(re.findall(r"(?:^|[{,\s])([a-zA-Z0-9_]+)\s*:", bloco))


def _da_barra(html: str) -> set[str]:
    return set(re.findall(r'data-view="([a-zA-Z0-9_]+)"', html))


def test_toda_tela_da_barra_lateral_esta_em_VIEWS(html):
    """Sem isto o clique cai na Visao Geral SEM erro nenhum: o router usa
    `VIEWS[h] ? h : 'home'`, entao uma tela ausente do registro fica
    inalcancavel mesmo tendo link, rota, dado e permissao."""
    falta = sorted(_da_barra(html) - _views(html))
    assert not falta, ("telas com link na barra lateral e FORA do registro "
                       "VIEWS (o router nao abre): " + ", ".join(falta))


def test_toda_tela_de_VIEWS_tem_secao_no_html(html):
    """O caminho inverso: registro sem <section class="view" id="view-X">
    deixa a tela abrir em branco."""
    secoes = set(re.findall(r'<section class="view[^"]*" id="view-([a-zA-Z0-9_]+)"',
                            html))
    falta = sorted(v for v in _views(html) if v not in secoes)
    assert not falta, ("telas em VIEWS e sem <section> no HTML: "
                       + ", ".join(falta))


def test_todo_data_ic_tem_chave_em_ICONS(html):
    """`data-ic` desconhecido nao da erro - so deixa o menu sem icone."""
    i = html.index("const ICONS = {")
    chaves = set(re.findall(r"(?m)^\s*([a-zA-Z0-9_]+)\s*:", html[i:i + 40000]))
    usados = set(re.findall(r'data-ic="([a-zA-Z0-9_]+)"', html))
    falta = sorted(usados - chaves)
    assert not falta, ("data-ic sem chave correspondente em ICONS (o icone "
                       "some do menu, sem erro): " + ", ".join(falta))


def test_toda_tela_do_menu_tem_loader(html):
    """LOADMAP e quem chama a consulta; sem entrada, a tela abre vazia."""
    i = html.index("const LOADMAP={")
    bloco = html[i:html.index("};", i)]
    mapeadas = set(re.findall(r"([a-zA-Z0-9_]+)\s*:", bloco))
    # O lookup e LOADMAP[viewKey(v)], nao LOADMAP[v]: `viewKey` colapsa varias
    # telas numa chave so (fluxo/receber/pagar dividem o mesmo endpoint e o
    # mesmo loader `fin`). O teste tem de aplicar a mesma reducao, senao acusa
    # tela que esta certa - lido do proprio arquivo para nao virar uma segunda
    # lista escrita a mao, que era o defeito que este teste existe para pegar.
    m = re.search(r"const viewKey = v => \((.*?)\) \? '([a-zA-Z0-9_]+)'", html)
    assert m, "viewKey mudou de forma - reveja este teste"
    colapsadas = set(re.findall(r"v==='([a-zA-Z0-9_]+)'", m.group(1)))
    assert m.group(2) in mapeadas, "a chave para onde viewKey colapsa sumiu do LOADMAP"
    falta = sorted(_da_barra(html) - mapeadas - colapsadas)
    assert not falta, ("telas no menu e fora do LOADMAP (abrem vazias): "
                       + ", ".join(falta))


def test_tela_com_filtro_proprio_esconde_o_carimbo_global(html):
    """`#meta` (o "Atualizado HH:MM" do cabecalho) e preenchido pelos loaders
    das telas SEM filtro proprio. Tela com filtro proprio precisa entrar na
    lista que o esconde - senao ele fica em "carregando..." para sempre, e o
    usuario le isso como tela travada. Aconteceu com poli e ctecp.
    """
    i = html.index("const metaEl=document.getElementById('meta')")
    linha = html[i:i + 900]
    # telas com barra de filtros propria (as que escondem a filterbar global)
    j = html.index("v==='pneus'||v==='people'")
    proprias = set(re.findall(r"v==='([a-zA-Z0-9_]+)'", html[j - 700:j + 120]))
    escondem = set(re.findall(r"v==='([a-zA-Z0-9_]+)'", linha))
    falta = sorted(v for v in ("poli", "ctecp") if v not in escondem)
    assert not falta, ("telas com filtro proprio que nao escondem o #meta "
                       "(fica 'carregando...' para sempre): " + ", ".join(falta))
