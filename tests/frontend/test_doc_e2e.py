"""A tela de Documentacao (#doc) contra o index.html real.

O payload servido e o de verdade (documentacao.montar()), entao o teste cobre a
ponta a ponta: extracao do painel -> API -> render -> busca local.
"""
from __future__ import annotations

import json

from api import documentacao
from tests.frontend.conftest import USUARIO


def _mockar(pg):
    doc = documentacao.montar()

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = USUARIO
        elif "/api/documentacao" in u:
            corpo = doc
        elif "/api/versao" in u:
            corpo = {"versao": doc["versao"], "rotulo": doc["rotulo"], "data": "2026-08-08"}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    return doc


def _abrir(pg, base, viewport=None):
    if viewport:
        pg.set_viewport_size(viewport)
    doc = _mockar(pg)
    pg.goto(f"{base}/static/index.html#doc")
    pg.wait_for_selector("#doc-grupos .doc-grupo", timeout=20000)
    return doc


def test_renderiza_grupos_glossario_e_versoes(pagina):
    pg, base = pagina
    doc = _abrir(pg, base)
    assert pg.eval_on_selector_all("#doc-grupos .doc-grupo", "e=>e.length") == len(doc["grupos"])
    assert pg.eval_on_selector_all(".doc-glo dt", "e=>e.length") == len(doc["glossario"])
    assert pg.eval_on_selector_all(".doc-ver", "e=>e.length") == len(doc["versoes"])


def test_mostra_a_procedencia_extraida_do_painel(pagina):
    """O texto do ⓘ tem de chegar ate a tela — e o que faz a documentacao
    dizer de qual tabela cada numero saiu."""
    pg, base = pagina
    _abrir(pg, base)
    texto = pg.inner_text("#doc-grupos")
    assert "CT-e" in texto
    assert "programacaoembarque" in texto


def test_rotulo_cx_no_cabecalho_e_no_rodape(pagina):
    pg, base = pagina
    doc = _abrir(pg, base)
    assert pg.inner_text("#doc-rotulo") == doc["rotulo"]
    assert pg.inner_text("#appVersao") == doc["rotulo"]
    assert doc["rotulo"].startswith("CX-")


def test_busca_local_filtra_e_conta(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.fill("#doc-q", "retorno vazio")
    pg.wait_for_timeout(300)
    assert "resultado" in pg.inner_text("#doc-cont")
    visiveis = pg.eval_on_selector_all(
        "#doc-grupos .doc-grupo", "es=>es.filter(e=>e.style.display!=='none').length")
    assert 0 < visiveis < 10, visiveis          # filtrou, mas nao zerou


def test_busca_sem_resultado_avisa(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.fill("#doc-q", "zzzzzznaoexiste")
    pg.wait_for_timeout(300)
    assert pg.is_visible("#doc-vazio")


def test_limpar_a_busca_devolve_tudo(pagina):
    pg, base = pagina
    doc = _abrir(pg, base)
    pg.fill("#doc-q", "zzzzzznaoexiste")
    pg.wait_for_timeout(300)
    pg.fill("#doc-q", "")
    pg.wait_for_timeout(300)
    assert pg.is_hidden("#doc-vazio")
    visiveis = pg.eval_on_selector_all(
        "#doc-grupos .doc-grupo", "es=>es.filter(e=>e.style.display!=='none').length")
    assert visiveis == len(doc["grupos"])


def test_no_mobile_nao_rola_na_horizontal(pagina):
    pg, base = pagina
    _abrir(pg, base, viewport={"width": 390, "height": 760})
    largura = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert largura[0] <= largura[1], f"pagina rola na horizontal: {largura}"


def test_no_mobile_a_versao_e_a_doc_sao_VISIVEIS_na_gaveta(pagina):
    """Assertar existencia no DOM nao basta e foi o que deixou o defeito passar:
    a versao morava so no rodape da sidebar, que e display:none no celular, e a
    Documentacao ficava dentro do grupo Administracao, que abre FECHADO."""
    pg, base = pagina
    doc = _abrir(pg, base, viewport={"width": 390, "height": 760})

    assert pg.eval_on_selector("#sidebar", "e=>getComputedStyle(e).display") == "none"

    pg.evaluate("document.getElementById('drawer').classList.add('aberto')")
    pg.wait_for_timeout(300)

    # a versao aparece de fato, sem depender de abrir nenhum acordeao
    assert pg.is_visible("#appVersaoMob"), "rotulo da versao invisivel no celular"
    assert pg.inner_text("#appVersaoMob") == doc["rotulo"]

    # e a Documentacao esta no rodape fixo da gaveta, nao so dentro do acordeao
    assert pg.is_visible('.dconta a[href="#doc"]'), "Documentacao so achavel dentro do acordeao"


def test_documentacao_nao_fica_dentro_do_grupo_administracao(pagina):
    """Documentacao nao e assunto de Administracao, e no rodape ja existe o
    atalho: dentro do acordeao ela aparecia DUAS vezes na mesma gaveta."""
    pg, base = pagina
    _abrir(pg, base, viewport={"width": 390, "height": 860})
    pg.evaluate("""
      document.getElementById('drawer').classList.add('aberto');
      document.querySelector('#drawer .dgrp[data-grp="Adm"]').classList.add('aberto');
    """)
    pg.wait_for_timeout(300)
    dentro = pg.eval_on_selector_all('#drawer .dgrp[data-grp="Adm"] a[href="#doc"]', "e=>e.length")
    assert dentro == 0, "Documentacao duplicada dentro do grupo Administracao"
    assert pg.eval_on_selector_all('.dconta a[href="#doc"]', "e=>e.length") == 1


def test_a_versao_no_rodape_nao_vira_botao_de_menu(pagina):
    """`.drawer a` estiliza todo link da gaveta como tile e `.drawer a.ativo`
    pintava a borda laranja -- a assinatura de versao ganhava moldura de botao
    pisado sempre que a tela aberta era a #doc, e colava nos botoes acima."""
    pg, base = pagina
    _abrir(pg, base, viewport={"width": 390, "height": 860})
    pg.evaluate("document.getElementById('drawer').classList.add('aberto')")
    pg.wait_for_timeout(300)
    est = pg.eval_on_selector("#appVersaoMob", """e=>{
      const s = getComputedStyle(e);
      return {ativo: e.classList.contains('ativo'),
              margem: parseFloat(s.marginTop),
              fundo: s.backgroundColor,
              borda: parseFloat(s.borderLeftWidth)};
    }""")
    assert est["ativo"] is False, "versao marcada como item de menu ativo"
    assert est["margem"] >= 12, f"versao colada nos botoes: margin-top {est['margem']}px"
    assert est["borda"] == 0, "versao com moldura de botao"
    assert est["fundo"] in ("rgba(0, 0, 0, 0)", "transparent"), est["fundo"]


def test_no_mobile_a_versao_leva_para_a_documentacao(pagina):
    pg, base = pagina
    _abrir(pg, base, viewport={"width": 390, "height": 760})
    pg.evaluate("document.getElementById('drawer').classList.add('aberto')")
    pg.wait_for_timeout(300)
    pg.click("#appVersaoMob")
    pg.wait_for_timeout(500)
    assert pg.evaluate("location.hash") == "#doc"
