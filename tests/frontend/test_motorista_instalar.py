# -*- coding: utf-8 -*-
"""O botão "Instalar o app", NO NAVEGADOR — com o celular simulado.

O convite de instalação (`beforeinstallprompt`) é do navegador e não se
provoca num teste; o que se prova aqui é o que a PÁGINA faz com ele: segura
(senão o Chrome mostra a faixa dele e o convite se gasta), gasta uma vez só, e
cai no passo a passo quando ele não vem. O celular é o `user_agent` de um
Android e de um iPhone de verdade.
"""
from __future__ import annotations

import json

from tests.frontend.test_motorista_abas import EU, VIAGEM

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
ANDROID = ("Mozilla/5.0 (Linux; Android 14; SM-A146M) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")

#: O convite de mentira, com a forma do real: `prompt()` e `userChoice`.
CONVITE = """
window.__pediu = 0;
window.__convite = function (resposta) {
  var e = new Event('beforeinstallprompt', {cancelable: true});
  e.prompt = function () { window.__pediu += 1; return Promise.resolve(); };
  e.userChoice = Promise.resolve({outcome: resposta, platform: 'web'});
  window.dispatchEvent(e);
  return e.defaultPrevented;
};
"""

#: Aberto pelo ícone: é o `display-mode` que diz, e ele não se emula por opção.
PELO_ICONE = """
(function () {
  var orig = window.matchMedia.bind(window);
  window.matchMedia = function (q) {
    if (String(q).indexOf('display-mode: standalone') >= 0)
      return {matches: true, media: q, onchange: null,
              addListener: function () {}, removeListener: function () {},
              addEventListener: function () {}, removeEventListener: function () {},
              dispatchEvent: function () { return false; }};
    return orig(q);
  };
})();
"""

ENTRADA = "#instalar-entrada"
BOTAO = ENTRADA + " .inst-btn"


def _pagina(pagina, ua=None, *, logado=False, init=""):
    pg0, base_url = pagina
    opcoes = {"viewport": {"width": 390, "height": 780}}
    if ua:
        opcoes["user_agent"] = ua
    pg = pg0.context.browser.new_context(**opcoes).new_page()
    pg.add_init_script(CONVITE + init)
    erros: list = []
    pg.on("pageerror", lambda e: erros.append(str(e)))

    def rota(route):
        c = route.request.url.split("?")[0]
        if c.endswith("/api/motorista/eu"):
            if logado:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(EU))
            return route.fulfill(status=401, content_type="application/json",
                                 body='{"erro": "sessao", "mensagem": "Entre de novo."}')
        if c.endswith("/api/motorista/viagem"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(VIAGEM))
        route.fulfill(status=200, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    pg.goto(base_url + "/static/motorista.html")
    pg.wait_for_selector("#tela-viagem:not([hidden])" if logado
                         else "#tela-entrar:not([hidden])", timeout=15000)
    return pg, erros


def _texto_do_botao(pg, sel=BOTAO) -> str:
    return (pg.text_content(sel) or "").strip()


def test_no_ANDROID_o_convite_do_navegador_vira_UM_toque(pagina):
    pg, erros = _pagina(pagina, ANDROID)
    # ANTES do convite, o passo a passo: o navegador pode nunca oferecer
    assert _texto_do_botao(pg) == "Pôr o app na tela inicial"
    assert pg.evaluate("window.__convite('accepted')") is True, \
        "o convite não foi segurado: o Chrome mostraria a faixa dele e o gastaria"
    assert _texto_do_botao(pg) == "Instalar o app no celular"
    pg.click(BOTAO)
    pg.wait_for_function("document.getElementById('instalar-entrada')"
                         ".textContent.includes('Pronto')", timeout=15000)
    assert pg.evaluate("window.__pediu") == 1
    assert pg.evaluate("document.documentElement.scrollWidth - "
                       "document.documentElement.clientWidth") == 0
    assert not erros, erros


def test_quem_RECUSA_o_convite_fica_com_o_passo_a_passo(pagina):
    """O convite vale UMA vez: pedir de novo com ele gasto dá erro no
    navegador, e o botão ficaria mudo."""
    pg, erros = _pagina(pagina, ANDROID)
    pg.evaluate("window.__convite('dismissed')")
    pg.click(BOTAO)
    pg.wait_for_function("document.querySelector('#instalar-entrada .inst-btn')"
                         ".textContent.includes('Pôr o app')", timeout=15000)
    pg.click(BOTAO)
    assert pg.locator(ENTRADA + " .inst-passos").is_visible()
    assert "Adicionar à tela inicial" in pg.text_content(ENTRADA + " .inst-passos")
    assert pg.evaluate("window.__pediu") == 1, "o convite gasto foi usado de novo"
    assert not erros, erros


def test_no_IPHONE_o_botao_mostra_o_caminho_do_Safari(pagina):
    pg, erros = _pagina(pagina, IPHONE)
    passos = pg.locator(ENTRADA + " .inst-passos")
    assert passos.is_hidden()
    pg.click(BOTAO)
    assert passos.is_visible()
    assert "Adicionar à Tela de Início" in passos.text_content()
    assert pg.get_attribute(BOTAO, "aria-expanded") == "true"
    # o iOS separa o armazenamento do app da Tela de Início: sem este aviso, a
    # tela de entrada no primeiro uso parece defeito
    assert "entre de novo" in pg.text_content(ENTRADA)
    assert not erros, erros


def test_aberto_PELO_ICONE_nao_oferece_de_novo(pagina):
    pg, erros = _pagina(pagina, ANDROID, init=PELO_ICONE)
    pg.evaluate("window.__convite('accepted')")
    assert pg.locator(ENTRADA).is_hidden()
    assert not erros, erros


def test_no_COMPUTADOR_sem_convite_nao_aparece(pagina):
    pg, erros = _pagina(pagina)
    assert pg.locator(ENTRADA).is_hidden()
    assert not erros, erros


def test_instalado_por_OUTRO_caminho_vira_PRONTO(pagina):
    """`appinstalled` também chega quando a pessoa instala pelo menu."""
    pg, erros = _pagina(pagina, ANDROID)
    pg.evaluate("window.dispatchEvent(new Event('appinstalled'))")
    assert "Pronto" in pg.text_content(ENTRADA)
    assert pg.locator(BOTAO).count() == 0
    assert not erros, erros


def test_o_CHROMIUM_considera_o_app_INSTALAVEL(pagina):
    """Pergunta ao PRÓPRIO navegador, pelo protocolo de depuração, e não à nossa
    leitura dos critérios dele — que mudam de versão para versão. Se ele disser
    que não, o convite nunca chega aos celulares Android e o botão de um toque
    não aparece para ninguém, sem erro em lugar nenhum.

    Medido em 12/09/2026 no Chromium 151: nenhum erro, e sem service worker com
    cache (o do app é só de notificação e nem é registrado na entrada).

    O QUE ELE NÃO COBRA: o modo app. Com `"display": "browser"` o Chromium 151
    continua dizendo "instalável" — a sabotagem passou verde aqui — e o atalho
    abriria como aba comum. Quem segura isso é `tests/motorista/test_manifesto.py`."""
    pg, erros = _pagina(pagina, ANDROID)
    cdp = pg.context.new_cdp_session(pg)
    manifesto = {}
    for _ in range(25):
        manifesto = cdp.send("Page.getAppManifest")
        if manifesto.get("url"):
            break
        pg.wait_for_timeout(200)
    r = cdp.send("Page.getInstallabilityErrors")
    assert r["installabilityErrors"] == [], r
    assert manifesto.get("url", "").endswith("/static/manifest-motorista.json")
    assert not manifesto.get("errors"), manifesto.get("errors")
    assert not erros, erros


def test_quem_JA_ENTROU_acha_o_botao_na_CONTA(pagina):
    """A sessão dura 30 dias: quem já usa o app não vê mais a tela de entrada,
    e é na Conta que o botão o alcança."""
    pg, erros = _pagina(pagina, ANDROID, logado=True)
    pg.evaluate("window.__convite('accepted')")
    pg.click("#b-conta")
    pg.wait_for_selector("#instalar-conta .inst-btn", timeout=15000)
    assert _texto_do_botao(pg, "#instalar-conta .inst-btn") == "Instalar o app no celular"
    pg.click("#instalar-conta .inst-btn")
    pg.wait_for_function("document.getElementById('instalar-conta')"
                         ".textContent.includes('Pronto')", timeout=15000)
    assert pg.evaluate("window.__pediu") == 1
    assert not erros, erros
