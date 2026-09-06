# -*- coding: utf-8 -*-
"""A página pública de rastreio em várias larguras.

POR QUE ESTES GUARDS LEEM O NAVEGADOR, e não o texto do CSS: uma regra pode
existir, estar certa e NÃO VALER — quem decide especificidade e layout é o
navegador. Um teste que procurasse `grid-template-columns` na folha de estilo
ficaria verde com a grade perdendo para qualquer regra mais específica.

O QUE ELES PROTEGEM:

1. **O celular não pode mudar.** A página chega por link de WhatsApp: o celular
   é o caso normal e o monitor é a exceção. O rearranjo de duas colunas usa
   `display:contents` justamente para que, abaixo do ponto de corte, os blocos
   sigam sendo filhos diretos do cartão, na mesma ordem — e é isso que o guard
   mede: a ORDEM VISUAL dos blocos num 390px.
2. **A página não anda para o lado.** `scrollWidth > clientWidth` é o defeito
   que nasce sem erro nenhum, e já pôs um card inteiro fora da tela nesta casa.
3. **No monitor há duas colunas de verdade** — o mapa à direita do conteúdo, e
   não uma tira de 560px no meio do vazio.
"""
from __future__ import annotations

import json

import pytest

CARGA = {
    "ok": True,
    "carga": {
        "documento": "CT-e 1234", "origem": "Joinville/SC",
        "destino": "Sao Leopoldo/RS", "estado": "em_viagem",
        "estado_rotulo": "Em viagem", "destinatario": "Cliente Exemplo SA",
        "previsao": "2026-09-08T14:00:00", "entregue_em": None,
        "notas": ["111", "222"],
        "transporte": {"cliente": "Cliente Exemplo SA", "pagador": None,
                       "pagador_igual_cliente": True,
                       "motorista": "Motorista Exemplo",
                       "cavalo": "AAA1A11", "carreta": "BBB2B22"},
        "andamento": {"tem_posicao": True, "progresso_pct": 42,
                      "falta_km": 380, "km_rota": 662, "por_rota": True,
                      "percorrido_km": 282, "atualizado_ha_min": 3,
                      "transito": {"estado": "livre", "rotulo": "Fluxo livre"},
                      "area": {"lat": -26.3, "lng": -48.8, "raio_km": 11}},
        "mapa": {"origem": {"lat": -26.30, "lng": -48.84},
                 "destino": {"lat": -29.76, "lng": -51.15}},
        "etapas": [
            {"chave": "emitido", "rotulo": "Documento emitido",
             "em": "2026-09-05T08:00:00", "feito": True},
            {"chave": "transito", "rotulo": "Em viagem",
             "em": "2026-09-05T09:30:00", "feito": True},
            {"chave": "entregue", "rotulo": "Entregue", "em": None,
             "feito": False},
        ],
    },
}

LISTA = {"ok": True, "cargas": [
    {"id": "a1", "documento": "CT-e 1234", "origem": "Joinville/SC",
     "destino": "Sao Leopoldo/RS", "estado": "em_viagem",
     "estado_rotulo": "Em viagem"},
    {"id": "b2", "documento": "CT-e 5678", "origem": "Curitiba/PR",
     "destino": "Santos/SP", "estado": "entregue",
     "estado_rotulo": "Entregue"},
]}


def _rotas(pg):
    """O ERP e o Leaflet ficam de fora: aqui se mede LAYOUT.

    O mapa é abortado de propósito — o `desenharMapa` remove o contêiner
    quando o Leaflet não carrega, e é o pior caso para a coluna da direita:
    se as duas colunas sobrevivem sem o mapa, sobrevivem com ele.
    """
    pg.route("**/api/rastreio/buscar*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(LISTA)))
    pg.route("**/api/rastreio/carga*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(CARGA)))
    pg.route("**/vendor/leaflet/**", lambda r: r.abort())


def _abrir_detalhe(pg, base, largura, altura=900):
    pg.set_viewport_size({"width": largura, "height": altura})
    _rotas(pg)
    pg.goto(f"{base}/static/rastreio.html")
    pg.fill("#doc", "1234")
    pg.fill("#cnpj", "0051")
    pg.click("#btn")
    pg.wait_for_selector(".carga")
    pg.click(".carga")
    pg.wait_for_selector(".det-a1")
    pg.wait_for_timeout(150)


def _fora_da_tela(pg) -> list:
    """Blocos cuja borda direita passou da janela.

    NÃO SE MEDE POR `scrollWidth`, e a primeira versão deste guard media — e
    passava com um `width:1160px` fixo num viewport de 360px, que é o defeito
    inteiro. A causa: a página declara `html,body{overflow-x:hidden}`, então o
    transbordo é CLIPADO. Não há barra de rolagem, `scrollWidth` nunca cresce,
    e o conteúdo simplesmente fica inalcançável — o pior dos dois mundos, e
    invisível para a régua óbvia.

    Medir a borda direita de cada bloco estrutural responde a pergunta certa:
    "isto está dentro da tela?". Só os contêineres de layout entram; o que vive
    dentro de uma caixa que rola por conta própria (o mapa) é problema dela.
    """
    return pg.evaluate("""() => {
      const seletores = ['.wrap', '.card', '.card-in', '.det>div', '.quem',
                         '.nums', '.num', '.etapas', '.zap', '.zap .linha',
                         '.trans', '.notas', '.legenda', '.barra', '#mapa',
                         '.voltar', '.carga'];
      const larg = window.innerWidth, fora = [];
      for (const s of seletores) {
        document.querySelectorAll(s).forEach(el => {
          const b = el.getBoundingClientRect();
          if (b.width > 0 && (b.right > larg + 1 || b.left < -1))
            fora.push({sel: s, esq: Math.round(b.left),
                       dir: Math.round(b.right), janela: larg});
        });
      }
      return fora;
    }""")


# --------------------------------------------------------------------------
# o celular não muda
# --------------------------------------------------------------------------
def test_no_celular_a_ordem_visual_dos_blocos_e_a_de_sempre(pagina):
    """`display:contents` existe para isto: abaixo do corte, o rearranjo do
    monitor não deve deixar rastro nenhum na página que a maioria vê."""
    pg, base = pagina
    _abrir_detalhe(pg, base, 390, 844)

    topos = pg.evaluate("""() => {
      const alvo = {
        cabecalho: '.det-a1 .doc',
        quem: '.quem',
        progresso: '.barra',
        numeros: '.nums',
        transito: '.trans',
        notas: '.notas',
        etapas: '.etapas',
        zap: '.zap'
      };
      const fora = {};
      for (const [nome, sel] of Object.entries(alvo)) {
        const el = document.querySelector(sel);
        if (el) fora[nome] = el.getBoundingClientRect().top + window.scrollY;
      }
      return fora;
    }""")

    esperada = ["cabecalho", "quem", "progresso", "numeros", "transito",
                "notas", "etapas", "zap"]
    presentes = [n for n in esperada if n in topos]
    assert len(presentes) >= 6, f"o dublê não montou a tela: {topos}"
    lida = sorted(presentes, key=lambda n: topos[n])
    assert lida == presentes, (
        f"a ordem no celular mudou.\nesperada: {presentes}\nlida:     {lida}")


def test_no_celular_continua_UMA_coluna(pagina):
    """Duas colunas num 390px espremeriam o mapa e a tabela de números."""
    pg, base = pagina
    _abrir_detalhe(pg, base, 390, 844)
    colunas = pg.evaluate(
        "() => getComputedStyle(document.querySelector('.det'))"
        ".gridTemplateColumns")
    # `display:contents` não gera caixa: a grade nem existe aqui.
    assert colunas in ("none", "", "auto"), colunas
    assert pg.evaluate(
        "() => getComputedStyle(document.querySelector('.det')).display"
    ) == "contents"


# --------------------------------------------------------------------------
# a página não anda para o lado
# --------------------------------------------------------------------------
@pytest.mark.parametrize("largura", [360, 390, 414, 768, 1024, 1280, 1920])
def test_nada_nasce_FORA_da_tela(pagina, largura):
    """O defeito que nasce sem erro nenhum: um bloco largo empurra o vizinho
    para fora da janela. Aqui ele é mais traiçoeiro que o normal, porque a
    página clipa o transbordo (`overflow-x:hidden`) — não há barra de rolagem
    para denunciar, o conteúdo só fica inacessível."""
    pg, base = pagina
    _abrir_detalhe(pg, base, largura)
    fora = _fora_da_tela(pg)
    assert not fora, f"blocos fora da tela em {largura}px: {fora}"


# --------------------------------------------------------------------------
# o monitor ganha duas colunas
# --------------------------------------------------------------------------
def test_no_monitor_o_mapa_fica_AO_LADO_do_conteudo(pagina):
    """A tira de 560px no meio do monitor era o pedido: no desktop o mapa é a
    resposta visual da página e merece a altura e a largura que existem."""
    pg, base = pagina
    _abrir_detalhe(pg, base, 1440, 900)

    caixas = pg.evaluate("""() => {
      const r = s => {
        const el = document.querySelector(s);
        if (!el) return null;
        const b = el.getBoundingClientRect();
        return {esq: b.left, dir: b.right, topo: b.top, alt: b.height};
      };
      return {a1: r('.det-a1'), b: r('.det-b'), a2: r('.det-a2')};
    }""")

    assert caixas["a1"] and caixas["b"], caixas
    # A COLUNA DA DIREITA COMECA DEPOIS QUE A ESQUERDA TERMINA — é isto que
    # significa "ao lado", e não a mera existência de uma regra de grade.
    assert caixas["b"]["esq"] >= caixas["a1"]["dir"] - 1, (
        f"as colunas se sobrepõem: {caixas}")
    # E AS DUAS DIVIDEM A MESMA FAIXA VERTICAL: uma coluna que começa abaixo da
    # outra é a pilha de sempre com nome novo.
    assert abs(caixas["b"]["topo"] - caixas["a1"]["topo"]) < 40, (
        f"a coluna da direita não está na mesma altura: {caixas}")
    # As etapas seguem na coluna DA ESQUERDA, embaixo do que veio antes.
    if caixas["a2"]:
        assert caixas["a2"]["esq"] < caixas["b"]["esq"], caixas
        assert caixas["a2"]["topo"] > caixas["a1"]["topo"], caixas


def test_no_monitor_o_detalhe_usa_mais_que_a_coluna_da_busca(pagina):
    """A busca continua estreita — dois campos e um botão numa faixa de 1160px
    seriam um formulário perdido — e o detalhe é que alarga."""
    pg, base = pagina
    pg.set_viewport_size({"width": 1440, "height": 900})
    _rotas(pg)
    pg.goto(f"{base}/static/rastreio.html")
    busca = pg.evaluate(
        "() => document.querySelector('.wrap').getBoundingClientRect().width")
    assert busca <= 580, f"a busca alargou junto: {busca}"

    pg.fill("#doc", "1234")
    pg.fill("#cnpj", "0051")
    pg.click("#btn")
    pg.wait_for_selector(".carga")
    pg.click(".carga")
    pg.wait_for_selector(".det-a1")
    detalhe = pg.evaluate(
        "() => document.querySelector('.wrap').getBoundingClientRect().width")
    assert detalhe > busca + 200, (
        f"o detalhe não alargou: busca={busca} detalhe={detalhe}")


# --------------------------------------------------------------------------
# voltar volta
# --------------------------------------------------------------------------
def test_voltar_devolve_a_LISTA_e_nao_o_formulario_vazio(pagina):
    """Quem achou duas cargas e abriu a errada precisava buscar tudo de novo,
    com o documento e o CNPJ na mão. O botão dizia "Outra busca" e era honesto
    — o problema era não haver caminho de volta nenhum."""
    pg, base = pagina
    _abrir_detalhe(pg, base, 1024)
    assert "Voltar para a lista" in pg.inner_text(".voltar")

    pg.click(".voltar")
    pg.wait_for_selector(".carga")
    assert len(pg.query_selector_all(".carga")) == 2
    assert pg.query_selector(".det-a1") is None


def test_o_formulario_NAO_fica_no_topo_do_detalhe(pagina):
    """Quem acabou de achar a carga via primeiro os dois campos que já
    preencheu. No monitor, com o detalhe alargado, era um formulário vazio de
    1160px antes da resposta.

    O GUARD MEDE O QUE O NAVEGADOR PINTA, e a primeira versão media
    `element.hidden` — a propriedade — e passava com o formulário BEM VISÍVEL
    na tela. A causa é a lição de sempre desta casa: `form{display:grid}` é
    regra de AUTOR e `[hidden]{display:none}` vem da folha do NAVEGADOR; autor
    vence, e o atributo virava decoração. `abrirPorLink` mandava esconder o
    formulário desde o primeiro dia e nunca escondeu.
    """
    pg, base = pagina
    _abrir_detalhe(pg, base, 1440, 900)
    caixa = pg.evaluate("""() => {
      const f = document.getElementById('form');
      const s = document.getElementById('secBusca');
      return {display: getComputedStyle(f).display,
              alt_form: f.getBoundingClientRect().height,
              alt_secao: s.getBoundingClientRect().height};
    }""")
    assert caixa["display"] == "none", caixa
    assert caixa["alt_form"] == 0, caixa
    # A MOLDURA DO CARTAO TAMBEM: só esconder o <form> deixava uma faixa branca
    # vazia de 1160px no topo — pior que o formulário, porque não se explica.
    assert caixa["alt_secao"] == 0, caixa

    # E VOLTA NA LISTA, onde ele serve.
    pg.click(".voltar")
    pg.wait_for_selector(".carga")
    assert pg.evaluate(
        "() => getComputedStyle(document.getElementById('form')).display"
    ) != "none"


def test_quem_chega_pelo_LINK_nao_ve_o_formulario(pagina):
    """O caminho do WhatsApp: a pessoa clica no link e a carga abre sozinha.
    O formulário de busca acima dela nunca fez sentido ali — e estava lá."""
    pg, base = pagina
    pg.set_viewport_size({"width": 390, "height": 844})
    _rotas(pg)
    pg.route("**/api/rastreio/link*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(CARGA)))
    pg.goto(f"{base}/static/rastreio.html#c=umtokenqualquer")
    pg.wait_for_selector(".det-a1")
    assert pg.evaluate(
        "() => getComputedStyle(document.getElementById('form')).display"
    ) == "none"
    # E o token sai da barra de endereços — a regra que já existia.
    assert "#c=" not in pg.url


def test_o_botao_VOLTAR_DO_APARELHO_nao_sai_da_pagina(pagina):
    """No celular a pessoa aperta voltar por reflexo. Sem entrada de histórico
    ela perdia a consulta inteira e caía fora da página."""
    pg, base = pagina
    _abrir_detalhe(pg, base, 390, 844)
    pg.go_back()
    pg.wait_for_selector(".carga")
    assert pg.query_selector(".det-a1") is None, (
        "o voltar do aparelho não desfez a abertura da carga")
    assert "rastreio.html" in pg.url


def test_o_voltar_da_TELA_e_o_do_APARELHO_nao_se_somam(pagina):
    """Se o botão da tela restaurasse a lista por conta própria, a entrada
    empilhada ficaria lá — e o voltar seguinte, o do aparelho, sairia da página
    com a pessoa achando que ia para a busca."""
    pg, base = pagina
    _abrir_detalhe(pg, base, 390, 844)
    pg.click(".voltar")
    pg.wait_for_selector(".carga")
    pg.go_back()
    pg.wait_for_timeout(200)
    # Voltou para ANTES da página (about:blank do harness) ou continua nela —
    # o que não pode é ter ficado uma entrada órfã que reabre o detalhe.
    assert pg.query_selector(".det-a1") is None
