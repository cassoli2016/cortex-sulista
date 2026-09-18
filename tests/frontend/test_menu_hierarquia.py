# -*- coding: utf-8 -*-
"""A hierarquia do menu, medida no NAVEGADOR.

POR QUE ESTE ARQUIVO EXISTE
===========================
O terceiro nível do menu passou meses sem recuo nenhum, com o CSS dizendo o
contrário. `nav a.sub2{padding-left:46px}` e `nav a.sub{padding-left:22px}` têm
a MESMA especificidade (0,2,1), e a de `.sub` vinha depois no arquivo — vencia.
Os cinco itens de terceiro nível ficavam exatamente onde os de segundo, e o
comentário do CSS até explicava o salto de 12px que nunca aconteceu.

"A regra de CSS pode existir, estar certa e NÃO VALER": só o navegador diz
quem venceu a especificidade. Por isso todo teste aqui lê `getComputedStyle` e
posição na tela, nunca o texto do CSS.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

MEDIR = r"""() => {
  const nav = document.querySelector('aside nav');
  nav.querySelectorAll('.subs, .subs2').forEach(s => s.classList.remove('closed'));
  const x = sel => { const e = nav.querySelector(sel);
    if(!e) return null;
    const t = [...e.querySelectorAll('span')].find(
        s => !s.classList.contains('ic') && s.textContent.trim());
    return Math.round((t||e).getBoundingClientRect().left); };
  const hs = [...nav.querySelectorAll('a[data-view]')]
      .map(a => a.getBoundingClientRect().height);
  const med = hs.slice().sort((a,b)=>a-b)[Math.floor(hs.length/2)];
  return {
    x_grupo: x('.group'),
    x_item: x('.subs a.sub'),
    x_item3: x('a.sub.sub2'),
    guia_item: getComputedStyle(nav.querySelector('.subs')).borderLeftWidth,
    guia_item3: getComputedStyle(nav.querySelector('.subs2')).borderLeftWidth,
    largura_item: Math.round(nav.querySelector('.subs a.sub').getBoundingClientRect().width),
    quebram: [...nav.querySelectorAll('a[data-view]')]
        .filter(a => a.getBoundingClientRect().height > med * 1.5).length,
  };
}"""


def _abrir(pagina, hash_tela="prem"):
    pg, base_url = pagina
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(USUARIO if "/auth/me" in r.request.url else {})))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#{hash_tela}")
    pg.wait_for_selector("nav a.active", timeout=20000)
    return pg, erros


def test_os_tres_niveis_tem_recuos_DIFERENTES(pagina):
    """O defeito que este arquivo existe para não deixar voltar.

    Não basta o CSS declarar o recuo: `nav a.sub` e `nav a.sub2` empatam em
    especificidade, e quem vence é quem vier depois. Trocar a ordem das duas
    linhas reintroduz o defeito sem mudar um valor.
    """
    pg, _ = _abrir(pagina)
    m = pg.evaluate(MEDIR)

    # DEGRAU MINIMO, e nao "maior que". A primeira versao deste guard so pedia
    # `x_item3 > x_item`, e passou nas DUAS sabotagens: com o recuo zerado, a
    # borda de 1px da guia ja satisfazia a comparacao. Um degrau de 1px nao e
    # hierarquia -- e o guard aprovava exatamente o defeito que existe para
    # pegar. Verde que nunca ficaria vermelho nao conferiu nada.
    PASSO = 6

    assert m["x_item"] - m["x_grupo"] >= PASSO, (
        f"o item quase nao recua do grupo: {m['x_grupo']} -> {m['x_item']}")
    assert m["x_item3"] - m["x_item"] >= PASSO, (
        f"o TERCEIRO nivel quase nao recua do segundo: {m['x_item']} -> "
        f"{m['x_item3']} — a regra de CSS provavelmente perdeu a briga")


def test_a_hierarquia_tem_guia_e_nao_so_recuo(pagina):
    """A barra tem 228px e rótulos longos.

    A guia diz a hierarquia com 1px; recuo grande diria a mesma coisa comendo
    a largura do rótulo. A primeira versão desta mudança usou recuo de 21px e
    DOBROU os itens que quebram em duas linhas (8 → 17).
    """
    pg, _ = _abrir(pagina)
    m = pg.evaluate(MEDIR)
    assert m["guia_item"] != "0px", "o segundo nivel perdeu a guia"
    assert m["guia_item3"] != "0px", "o terceiro nivel perdeu a guia"


def test_o_menu_NAO_piora_a_quebra_de_linha(pagina):
    """Régua contra regressão de largura.

    Oito itens já quebravam antes desta mudança (rótulos longos numa barra de
    228px). O número não pode subir: cada quebra a mais é uma linha a mais num
    menu que já tem 86 itens.
    """
    pg, _ = _abrir(pagina)
    m = pg.evaluate(MEDIR)
    assert m["quebram"] <= 8, (
        f"{m['quebram']} itens quebram em duas linhas (o teto e 8): a largura "
        f"util do item caiu para {m['largura_item']}px")


def test_o_grupo_DIZ_que_a_tela_atual_esta_dentro_dele(pagina):
    """Com 14 grupos e 86 itens, o item destacado não basta.

    Antes, o botão do grupo que continha a tela ativa era idêntico ao de
    qualquer outro — mesma cor, mesmo fundo, mesmo peso. Bastava rolar a barra
    para o menu parar de dizer onde você está.
    """
    pg, _ = _abrir(pagina)
    m = pg.evaluate(r"""() => {
      const nav = document.querySelector('aside nav');
      const at = [...nav.querySelectorAll('.group')].find(g => g.classList.contains('tem-ativa'));
      const outro = [...nav.querySelectorAll('.group')].find(g => !g.classList.contains('tem-ativa'));
      const cs = g => { const c = getComputedStyle(g);
        return c.backgroundColor + '|' + c.borderLeftColor; };
      return {rot: at ? at.textContent.trim() : null,
              ativo: at ? cs(at) : null, outro: outro ? cs(outro) : null};
    }""")
    assert m["rot"], "nenhum grupo foi marcado como contendo a tela atual"
    assert m["ativo"] != m["outro"], (
        "o grupo da tela atual esta pintado igual aos outros")


def test_a_marca_do_grupo_SOBREVIVE_ao_grupo_fechado(pagina):
    """É fechado que ela mais importa: com o grupo aberto, o item destacado já
    diz onde você está; fechado, ela é o único sinal que resta."""
    pg, _ = _abrir(pagina)
    m = pg.evaluate(r"""() => {
      const nav = document.querySelector('aside nav');
      const at = [...nav.querySelectorAll('.group')].find(g => g.classList.contains('tem-ativa'));
      const subs = document.getElementById(at.getAttribute('aria-controls'));
      subs.classList.add('closed');
      const c = getComputedStyle(at);
      return {bg: c.backgroundColor, borda: c.borderLeftColor,
              item_visivel: !!nav.querySelector('a.active').offsetParent};
    }""")
    assert not m["item_visivel"], "o teste nao chegou a fechar o grupo"
    assert m["borda"] != "rgba(0, 0, 0, 0)", (
        "com o grupo fechado nao sobra sinal nenhum de onde voce esta")


def test_a_trilha_do_cabecalho_diz_o_GRUPO(pagina):
    """"Premiação de Motoristas" não situa; "Telemetria › Premiação" situa."""
    pg, _ = _abrir(pagina)
    m = pg.evaluate(r"""() => {
      const t = document.querySelector('#viewTitle .trilha');
      return {texto: t ? t.textContent.trim() : null,
              sep: t ? getComputedStyle(t, '::after').content : null,
              titulo: document.getElementById('viewTitle').textContent};
    }""")
    assert m["texto"] == "Telemetria", m
    assert "›" in (m["sep"] or ""), f"a trilha ficou sem separador: {m['sep']}"
    assert "Premiação de Motoristas" in m["titulo"]


def test_a_trilha_NAO_quebra_quando_a_tela_esta_fora_de_grupo(pagina):
    """Visão Geral e Copiloto são atalhos de topo, sem grupo.

    O título tem de sair inteiro mesmo assim — uma trilha que exige grupo
    deixaria a home sem título, e a home é a tela mais aberta da casa.
    """
    pg, erros = _abrir(pagina, "home")
    m = pg.evaluate(r"""() => ({
      titulo: document.getElementById('viewTitle').textContent.trim(),
      tem_trilha: !!document.querySelector('#viewTitle .trilha')})""")
    assert not erros, erros
    assert m["titulo"] == "Visão Geral", m


def test_o_painel_de_tv_abre_o_submenu_do_TEMA_dele_e_so_ele(pagina):
    """Os paineis de TV em tres submenus por tema (16/09/2026).

    O grupo Business Intelligence abrir nao basta: com o submenu do tema
    fechado, o painel ativo fica escondido e o menu nao diz onde voce esta.
    E abrir TODOS os submenus devolveria a lista comprida que motivou a
    divisao.
    """
    # a TV esconde a barra lateral: o item ativo existe, so nao esta VISIVEL
    pg, _base = pagina
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(USUARIO if "/auth/me" in r.request.url else {})))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{_base}/static/index.html#tvfat")
    pg.wait_for_selector('nav a.active[data-view="tvfat"]', state="attached", timeout=20000)
    m = pg.evaluate(r"""() => Object.fromEntries(['Cli','Ges','Ope'].map(k => {
      const b = document.getElementById('sgTv'+k), s = document.getElementById('subsTv'+k);
      return [k, {aberto: b.getAttribute('aria-expanded') === 'true' && !s.classList.contains('closed'),
                  marcado: b.classList.contains('tem-ativa')}];
    }))""")
    assert not erros, erros
    assert m["Ges"] == {"aberto": True, "marcado": True}, m
    assert m["Ope"] == {"aberto": False, "marcado": False}, m
    assert m["Cli"] == {"aberto": False, "marcado": False}, m


def test_o_acordeao_fecha_TODO_grupo_aberto(pagina):
    """Abrir um grupo fecha os outros — inclusive os que a lista escrita a mao
    do JS nao conhecia (ANTT, Gestao, Telemetria, TMS e WMS ficaram de fora
    dela, e com um deles aberto o menu ficava com DOIS grupos abertos).

    Mede o menu inteiro, grupo a grupo: lista de nomes aqui seria a mesma
    lista escrita a mao que causou o defeito.
    """
    pg, erros = _abrir(pagina)
    ids = pg.evaluate("() => [...document.querySelectorAll('aside nav button.group[aria-controls]')]"
                      ".map(b => b.id)")
    assert len(ids) >= 15, ids
    abertos = []
    for gid in ids:
        pg.click("#" + gid)
        abertos.append(pg.evaluate(
            """(gid) => { const a = [...document.querySelectorAll(
                    'aside nav button.group[aria-expanded="true"]')].map(b => b.id);
                return {clicado: gid, abertos: a}; }""", gid))
    assert not erros, erros
    fora = [a for a in abertos if a["abertos"] != [a["clicado"]]]
    assert not fora, fora


def test_suporte_e_o_ULTIMO_grupo_da_barra_e_da_gaveta(pagina):
    """Administracao e depois Suporte, no fim dos dois menus (quem opera,
    18/09/2026). Medido pela POSICAO na tela, nao pela ordem do texto: e a
    ordem visual que a decisao trata."""
    pg, erros = _abrir(pagina)
    m = pg.evaluate(r"""() => {
      const y = el => Math.round(el.getBoundingClientRect().top);
      const barra = [...document.querySelectorAll('aside nav button.group')]
          .sort((a,b) => y(a)-y(b))
          .map(b => [...b.querySelectorAll('span')].find(s => !s.classList.contains('ic')).textContent.trim());
      document.getElementById('drawer').classList.add('aberto');
      const gav = [...document.querySelectorAll('#drawer .dgrp')]
          .sort((a,b) => y(a)-y(b))
          .map(d => d.querySelector('.dgrp-h span').textContent.trim());
      document.getElementById('drawer').classList.remove('aberto');
      return {barra: barra.slice(-2), gaveta: gav.slice(-2)}; }""")
    assert not erros, erros
    assert m == {"barra": ["Administração", "Suporte"],
                 "gaveta": ["Administração", "Suporte"]}, m
