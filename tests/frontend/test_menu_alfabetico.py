"""O menu fica em ordem alfabetica — e continua ficando.

Os dois EXTREMOS sao posicionais e o miolo e alfabetico. No topo, Visao Geral e
Copiloto Cortex — a porta de entrada, e procura-los na letra V e na C seria
pior. No fim, Administracao — e configuracao, nao trabalho do dia, e abrir o
menu com ela em cima empurra para baixo tudo o que a pessoa usa.

Este teste existe porque menu e o lugar onde tela nova entra "no fim" por
inercia. Sem ele, em tres telas a ordem alfabetica vira ordem de chegada.
"""
import re
import unicodedata
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"

RE_GRUPO_BARRA = re.compile(
    r'<button class="group" id="grp(\w+)"[^>]*>\r?\n.*?'
    r'<span>([^<]+)</span><span class="ic chev".*?'
    r'(<div class="subs[^"]*" id="subs\1">)', re.S)

RE_SUBGRUPO = re.compile(
    r'<button class="subgrupo" id="(\w+)"[^>]*>\r?\n.*?<span>([^<]+)</span>.*?'
    r'(<div class="subs2[^"]*" id="\w+">)', re.S)

RE_GRUPO_GAVETA = re.compile(
    r'<div class="dgrp" data-grp="\w+">\r?\n[ \t]*'
    r'<button class="dgrp-h"[^>]*><span>([^<]+)</span>.*?'
    r'<div class="dgrp-b">\r?\n(.*?)[ \t]*</div>', re.S)


def chave(txt: str) -> str:
    """Ordem de dicionario: sem acento, minusculo. Comparar por byte poria
    'Operacao' depois de 'Paineis TV' e 'ANTT' no fim."""
    n = unicodedata.normalize("NFD", txt)
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip().lower()


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def _ate_fechar(html: str, ini: int) -> str:
    """Corpo do `<div>` que ABRE em `ini`, contando os aninhados.

    O corte era "ate o primeiro `</div>`", e com submenu dentro do grupo ele
    parava no fim do PRIMEIRO submenu: quando os paineis de TV viraram tres
    submenus por tema, dois deles ficariam fora de toda checagem deste arquivo.
    """
    prof = 0
    for m in re.finditer(r"<div\b|</div>", html[ini:]):
        prof += 1 if m.group(0) == "<div" else -1
        if prof == 0:
            corpo = html[ini:ini + m.start()]
            return corpo[corpo.index(">") + 1:]
    raise AssertionError("div sem fechamento no menu")


def _grupos(html: str) -> list[tuple[str, str]]:
    """(nome do grupo, corpo dos subitens) na ordem em que aparecem."""
    return [(m.group(2), _ate_fechar(html, m.start(3)))
            for m in RE_GRUPO_BARRA.finditer(html)]


def _subgrupos(corpo: str) -> list[tuple[str, str, str]]:
    """(id do botao, rotulo, corpo) de cada submenu de terceiro nivel."""
    return [(m.group(1), m.group(2), _ate_fechar(corpo, m.start(3)))
            for m in RE_SUBGRUPO.finditer(corpo)]


def _grupos_gaveta(html: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in RE_GRUPO_GAVETA.finditer(html)]


# ------------------------------------------------------------------- ordem
def test_os_grupos_estao_em_ordem_com_administracao_no_fim(html):
    nomes = [g for g, _ in _grupos(html)]
    assert nomes, "nenhum grupo encontrado"
    assert nomes[-1].startswith("Administra"), (
        f"Administracao tem de ser o ultimo grupo, e o ultimo e {nomes[-1]!r}")
    miolo = nomes[:-1]
    assert miolo == sorted(miolo, key=chave), (
        "grupos fora de ordem: " + " · ".join(miolo))


def _itens(corpo: str) -> list[str]:
    """Rotulos dos itens de um grupo, INCLUSIVE os de terceiro nivel.

    `class="sub"` casava so o nivel 2. Com Business Intelligence > Paineis TV
    o menu ganhou um terceiro (`class="sub sub2"`), e sem `[^"]*` aqui os
    painteis ficavam de fora da checagem: o grupo aparecia com ZERO itens e o
    teste passava sem olhar nada.
    """
    return re.findall(
        r'<a href="#\w+" class="sub[^"]*"[^>]*>.*?<span>([^<]+)</span></a>', corpo)


def test_os_itens_de_cada_grupo_estao_em_ordem(html):
    """Cada NIVEL em ordem por si: os submenus entre si, os itens soltos do
    grupo entre si e os itens de cada submenu entre si. Achatar tudo numa
    lista so reprovaria o menu por tema (Cliente · Diretoria · Coletas)."""
    fora = []
    for nome, corpo in _grupos(html):
        subs = _subgrupos(corpo)
        soltos = corpo
        for _id, _rot, sc in subs:
            soltos = soltos.replace(sc, "")
        listas = [(nome, _itens(soltos)),
                  (nome + " (submenus)", [r for _i, r, _c in subs])]
        listas += [(f"{nome} > {r}", _itens(sc)) for _i, r, sc in subs]
        for rot, itens in listas:
            if itens != sorted(itens, key=chave):
                fora.append(f"{rot}: {' · '.join(itens)}")
    assert not fora, "itens fora de ordem -> " + " | ".join(fora)


def test_todo_grupo_da_barra_tem_ao_menos_um_item(html):
    """Grupo vazio e sintoma de extrator cego, nao de menu vazio: foi assim
    que os Paineis TV sumiram da checagem de ordem ao virarem submenu."""
    vazios = [nome for nome, corpo in _grupos(html) if not _itens(corpo)]
    assert not vazios, "grupos sem item reconhecido: " + " · ".join(vazios)


def _subgrupos_bi(html: str) -> list[tuple[str, str, str]]:
    corpo = dict(_grupos(html))["Business Intelligence"]
    subs = _subgrupos(corpo)
    assert subs, "Business Intelligence sem submenu reconhecido"
    return subs


def test_os_submenus_de_paineis_tv_nascem_RECOLHIDOS(html):
    """Business Intelligence e uma area que vai receber varios paineis; os de
    TV sao familias dentro dela e nao podem ocupar a altura do grupo inteiro
    por padrao."""
    for bid, rotulo, _corpo in _subgrupos_bi(html):
        i = html.index(f'id="{bid}"')
        assert 'aria-expanded="false"' in html[i - 200:i + 200], f"{rotulo} nasce aberto"
        sid = "subs" + bid[2:]
        assert f'<div class="subs2 closed" id="{sid}">' in html, f"{rotulo}: o corpo nasce aberto"


def test_os_paineis_de_tv_estao_nos_submenus_por_tema(html):
    """Os tres temas (quem opera, 16/09/2026). Se um painel novo entrar solto
    no grupo, ele fica fora da familia e o submenu deixa de descrever o que
    tem dentro."""
    tema = {r: set(re.findall(r'data-view="(\w+)"', c)) for _b, r, c in _subgrupos_bi(html)}
    assert tema == {
        "TV — Cliente": {"tvcli"},
        "TV — Gestão": {"tvdir", "tvfat", "tvrh"},
        "TV — Operação": {"tvcco", "tvcom", "tvjor", "tvope", "tvprod"},
    }, tema


def test_todo_submenu_esta_no_SUBGRUPOS_do_js(html):
    """Submenu fora do `SUBGRUPOS` nao abre sozinho ao navegar para a tela
    dele: o grupo abre e o painel fica escondido atras do submenu fechado."""
    js = html[html.index("const SUBGRUPOS"):]
    js = js[:js.index(";")]
    for bid, rotulo, _c in _subgrupos_bi(html):
        assert f"['{bid}','subs{bid[2:]}','grpBi']" in js, f"{rotulo} fora do SUBGRUPOS"


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


# ------------------------------------------------- barra x gaveta do celular
def test_a_gaveta_do_celular_segue_a_mesma_ordem(html):
    """Lista escrita a mao e separada da barra lateral: ficando na ordem
    antiga, a mesma pessoa ve dois menus diferentes no computador e no
    celular."""
    fora = []
    for nome, corpo in _grupos_gaveta(html):
        itens = [re.sub(r"<[^>]+>", "", a).strip()
                 for a in re.findall(r'<a href="#\w+"[^>]*>.*?</a>', corpo)]
        if len(itens) > 1 and itens != sorted(itens, key=chave):
            fora.append(f"{nome}: {' · '.join(itens)}")
    assert not fora, "gaveta fora de ordem -> " + " | ".join(fora)


def test_a_gaveta_tem_os_MESMOS_grupos_que_a_barra(html):
    """A ANTT era grupo proprio na barra e vivia dentro de Operacao na gaveta.
    A mesma tela em grupos diferentes conforme o aparelho e o defeito que
    ninguem reporta e todo mundo tropeca: quem aprendeu "ANTT > Piso Minimo"
    no computador procura ANTT no celular e nao acha."""
    barra = [g for g, _ in _grupos(html)]
    gaveta = [g for g, _ in _grupos_gaveta(html)]
    # a gaveta abre com um grupo "Geral" que na barra sao os dois itens do topo
    assert gaveta and gaveta[0] == "Geral"
    assert gaveta[1:] == barra, (
        "grupos divergem.\n  barra : " + " · ".join(barra)
        + "\n  gaveta: " + " · ".join(gaveta[1:]))


def test_toda_tela_esta_no_MESMO_grupo_nos_dois_menus(html):
    """Nao basta o grupo existir dos dois lados: a tela tem de estar no mesmo."""
    barra = {v: nome for nome, corpo in _grupos(html)
             for v in re.findall(r'<a href="#(\w+)" class="sub"', corpo)}
    gaveta = {v: nome for nome, corpo in _grupos_gaveta(html)
              for v in re.findall(r'href="#(\w+)"', corpo)}
    divergem = [f"{v}: barra={barra[v]} gaveta={gaveta[v]}"
                for v in sorted(barra) if v in gaveta and barra[v] != gaveta[v]]
    assert not divergem, "telas em grupos diferentes -> " + " | ".join(divergem)


def test_nenhuma_tela_aparece_DUAS_VEZES_no_mesmo_menu(html):
    """O buraco que deixou o CT-e de Contrapartida em dois grupos da gaveta.

    O guard acima (`test_toda_tela_esta_no_MESMO_grupo_nos_dois_menus`) existia
    e passava: ele monta a gaveta com uma COMPREENSAO DE DICIONARIO, e a
    segunda ocorrencia de `ctecp` sobrescrevia a primeira. Sobrava o par
    Tms/Tms, que confere -- e a entrada duplicada em Controladoria ficava
    invisivel para o teste e visivel para quem abre o celular.

    A tela mudou de grupo em algum momento: foi acrescentada no destino e nao
    foi tirada da origem. Contar em vez de indexar e o que separa "esta no
    grupo certo" de "esta SO no grupo certo".
    """
    from collections import Counter
    for rotulo, grupos in (("barra", _grupos(html)), ("gaveta", _grupos_gaveta(html))):
        vistas = Counter(v for _nome, corpo in grupos
                         for v in re.findall(r'href="#(\w+)"', corpo))
        assert vistas, f"{rotulo}: nenhum item lido — a varredura passaria por vacuidade"
        repetidas = {v: n for v, n in vistas.items() if n > 1}
        assert not repetidas, (
            f"{rotulo}: tela em mais de um lugar -> " + ", ".join(
                f"{v} ({n}x, em {[nome for nome, corpo in grupos if f'href=\"#{v}\"' in corpo]})"
                for v, n in sorted(repetidas.items())))
