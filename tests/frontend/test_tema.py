"""Tema claro e escuro.

TRÊS ESTADOS, NÃO DOIS
======================
Uma escolha explícita carimba `data-theme` na raiz; o padrão — "seguir o
sistema" — NÃO carimba nada, e aí só o `prefers-color-scheme` decide. Isso
obriga a estrutura do CSS:

- a paleta CLARA completa mora no `:root` puro;
- `@media (prefers-color-scheme: dark)` redefine só os TOKENS, guardado por
  `:not([data-theme="light"])` para a escolha clara vencer um sistema escuro;
- `:root[data-theme="dark"]` redefine os mesmos tokens para a escolha escura
  vencer um sistema claro.

O defeito clássico é definir cor de COMPONENTE dentro do bloco de mídia: ela
nunca vale no estado "sistema" sem carimbo, e a página aparece com o texto de
um tema sobre o fundo do outro.

O QUE DESCOBRI ESCREVENDO ISTO
==============================
**Metade do tema escuro passava por vacuidade.** O auditor
(`scripts/auditar_tema.py`) rodava com a preferência do NAVEGADOR, ou seja só
exercitava o bloco de mídia. Sabotar o `[data-theme="dark"]` — o caminho de
quem clica no botão — não produzia achado nenhum. São dois blocos com os
mesmos tokens, e blocos duplicados divergem: é isso que
`test_os_dois_blocos_escuros_sao_IDENTICOS` existe para impedir.
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


def _tokens(bloco: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", bloco))


def _bloco(padrao: str) -> str:
    m = re.search(padrao + r"\{(.*?)\n\s*\}", HTML, re.S | re.M)
    assert m, "não achei o bloco " + padrao
    return m.group(1)


def _rgb(css: str) -> list[float]:
    """Aceita `#RRGGBB` e `rgb(r, g, b)`.

    A primeira versão deste teste procurava `[\\d.]+` em qualquer string — e num
    hex como `#E9EEF4` ela achava "9" e "4", concluindo que a cor CLARA era
    escura. Teste que interpreta mal o valor certo é indistinguível de defeito
    real na hora de ler a falha.
    """
    css = css.strip()
    if css.startswith("#"):
        v = css[1:]
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return [int(v[i:i + 2], 16) for i in (0, 2, 4)]
    return [float(x) for x in re.findall(r"[\d.]+", css)[:3]]


# -- a estrutura do CSS ------------------------------------------------------


def test_os_dois_blocos_escuros_sao_IDENTICOS():
    """O `@media` cobre quem segue o sistema; o `[data-theme="dark"]` cobre
    quem escolheu. São os mesmos tokens escritos duas vezes, e duas cópias
    divergem no dia em que alguém ajustar uma. O sintoma seria absurdo de
    diagnosticar: a mesma tela com cores diferentes conforme o caminho pelo
    qual o escuro foi ligado."""
    media = _tokens(_bloco(r':root:not\(\[data-theme="light"\]\)'))
    stamp = _tokens(_bloco(r':root\[data-theme="dark"\]'))
    assert media, "bloco de mídia sem tokens"
    assert media == stamp, {
        k: (media.get(k), stamp.get(k)) for k in set(media) | set(stamp)
        if media.get(k) != stamp.get(k)}


def test_o_bloco_de_midia_so_mexe_em_TOKEN():
    """Regra de componente ali dentro nunca valeria no estado "sistema" sem
    carimbo — é o defeito que produz texto de um tema sobre o fundo do outro.
    """
    bruto = re.search(r"@media \(prefers-color-scheme: dark\)\{(.*?)\n\}",
                      HTML, re.S)
    assert bruto, "não achei o @media do tema escuro"
    corpo = bruto.group(1)
    # dentro dele só pode haver o seletor de raiz
    seletores = re.findall(r"^\s*([^@{}\n][^{}\n]*)\{", corpo, re.M)
    assert seletores == [':root:not([data-theme="light"])'], seletores


def test_a_paleta_CLARA_completa_vive_no_root_puro():
    """Se um token só existisse dentro do bloco escuro, o tema claro cairia no
    valor herdado (ou em nada) — e o defeito só apareceria para quem está no
    claro, que é a maioria."""
    claro = _tokens(_bloco(r"^:root"))
    escuro = _tokens(_bloco(r':root\[data-theme="dark"\]'))
    faltam = sorted(set(escuro) - set(claro))
    assert not faltam, "token definido só no escuro: " + ", ".join(faltam)


def test_o_carimbo_do_tema_vem_ANTES_do_body():
    """Se o carimbo fosse feito pelo script do fim do arquivo, quem escolheu
    escuro veria a tela CLARA piscar a cada carregamento. Num painel operado
    no escuro isso é pior que não ter o tema."""
    i = HTML.index("cortex-tema")
    assert i < HTML.index("<body>"), "o tema é carimbado depois do <body>"


def test_a_MARCA_nao_virou_accent_de_UI_nem_muda_com_o_tema():
    """A marca é `#942821` — medida nos arquivos de marca do repositório em
    30/08/2026, depois de o usuário corrigir o "amarelo Sulista" que este
    projeto afirmava. Ela NÃO é o accent da casa (esse é o laranja) e NÃO se
    redefine por tema: um mesmo elemento mudando de cor de identidade entre
    temas é o oposto de um design system.

    Quem se adapta à superfície é `--brand-claro`, e por um motivo medido: o
    vermelho rende 8,12:1 no branco e 1,92:1 sobre o navy da barra lateral —
    ali ele sumiria."""
    escuro = _tokens(_bloco(r':root\[data-theme="dark"\]'))
    assert "--brand" not in escuro, "o --brand não deve ser redefinido no escuro"
    assert "--brand:#942821" in HTML.replace(" ", ""), (
        "o token da marca saiu do valor medido no símbolo")
    # `#FFD31C` ainda aparece no arquivo, e deve: o comentário do token conta
    # POR QUE ele saiu, e apagar a história faria a próxima pessoa repetir o
    # erro. O que não pode voltar é ele como VALOR — depois de dois-pontos.
    assert ":#FFD31C" not in HTML.upper().replace(" ", ""), (
        "o amarelo que não é da marca voltou como valor no CSS")


# -- o comportamento ---------------------------------------------------------


def _abrir(pg, base_url, tema=None):
    if tema:
        pg.add_init_script(
            "try{localStorage.setItem('cortex-tema','%s')}catch(e){}" % tema)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(ADMIN if "/api/auth/me" in r.request.url else {})))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#home")
    pg.wait_for_timeout(500)
    return erros


def test_o_padrao_e_SEGUIR_O_SISTEMA_e_nao_carimba_nada(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    assert pg.get_attribute("html", "data-theme") is None, (
        "sem escolha do usuário a raiz não pode ser carimbada — o carimbo "
        "congelaria o tema do dia em que a página foi aberta")
    assert pg.evaluate("() => window.temaGuardado()") == "sistema"


def test_o_botao_cicla_pelos_TRES_estados(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    vistos = [pg.evaluate("() => window.temaGuardado()")]
    for _ in range(3):
        pg.click("#btnTema")
        vistos.append(pg.evaluate("() => window.temaGuardado()"))
    assert vistos == ["sistema", "claro", "escuro", "sistema"], vistos


def test_a_escolha_ESCURA_carimba_e_muda_o_fundo(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    claro = pg.evaluate(
        "() => getComputedStyle(document.body).backgroundColor")
    pg.evaluate("() => window.temaAplicar('escuro')")
    assert pg.get_attribute("html", "data-theme") == "dark"
    escuro = pg.evaluate(
        "() => getComputedStyle(document.body).backgroundColor")
    assert claro != escuro, "o fundo do corpo não mudou com o tema"

    assert sum(_rgb(escuro)) < sum(_rgb(claro)), (claro, escuro)


def test_a_escolha_SOBREVIVE_ao_recarregamento(pagina):
    """É o ponto de guardar no `localStorage`: quem escolheu não reescolhe a
    cada abertura."""
    pg, base_url = pagina
    _abrir(pg, base_url, tema="escuro")
    assert pg.get_attribute("html", "data-theme") == "dark"
    pg.reload()
    pg.wait_for_timeout(300)
    assert pg.get_attribute("html", "data-theme") == "dark"


def test_a_PALETA_DOS_GRAFICOS_acompanha_o_tema(pagina):
    """`CC` lê os tokens do CSS uma vez e o ECharts COPIA as cores para dentro
    da `option` no desenho — nada disso se atualiza sozinho. Sem
    `ccAtualizar()`, trocar de tema deixaria barra navy escura sobre card
    escuro. Este teste é o que prova que a leitura foi refeita."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    antes = pg.evaluate("() => ({n900: CC.n900, grid: CC.grid, navy: CC.navy700})")
    pg.evaluate("() => window.temaAplicar('escuro')")
    depois = pg.evaluate("() => ({n900: CC.n900, grid: CC.grid, navy: CC.navy700})")
    assert antes != depois, (antes, depois)
    for k in ("n900", "grid", "navy"):
        assert antes[k] != depois[k], k


def test_o_ink_dos_graficos_DERIVA_do_token(pagina):
    """Era o literal #1E1E1E — texto quase preto, invisível sobre card escuro.
    E `--ink` sequer existia como variável CSS: as cinco regras que a usavam
    caíam no literal do fallback, o que no claro dava a cor certa por
    acidente."""
    pg, base_url = pagina
    _abrir(pg, base_url, tema="escuro")
    ink = pg.evaluate("() => CC.ink")
    assert sum(_rgb(ink)) / 3 > 128, (
        "o ink do gráfico continua escuro no tema escuro: " + ink)


def test_nao_ha_var_ink_fantasma_no_css():
    """`var(--ink, #1E2833)` parecia um token e era um literal com disfarce.
    Fallback de variável inexistente é a forma mais silenciosa de hard-code."""
    assert "var(--ink" not in HTML


@pytest.mark.parametrize("tema", ["claro", "escuro"])
def test_o_botao_DIZ_em_que_estado_esta(pagina, tema):
    """"Seguir o sistema" seria um estado invisível — indistinguível daquele
    que por acaso coincide com ele agora."""
    pg, base_url = pagina
    _abrir(pg, base_url, tema=tema)
    titulo = pg.get_attribute("#btnTema", "title") or ""
    assert "fixo em " + tema in titulo, titulo
