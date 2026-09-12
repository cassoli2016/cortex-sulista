# -*- coding: utf-8 -*-
"""Os avisos do app do motorista, NO NAVEGADOR: o sino, a lista e o "lido".

O que só o navegador prova:

1. **O NÚMERO DO SINO É O DO SERVIDOR** (`avisos.novos` do `/eu`), e o boot NÃO
   busca a lista — a regra "cada aba carrega sozinha" vale para ela também.
2. **LIDO É QUANDO A PESSOA ABRE.** Tocar na aba (ou no aviso, ou na
   notificação) marca; a aba que o app abre sozinho ao entrar, não.
3. **O ACESSO MESTRE NÃO LIGA NOTIFICAÇÃO NEM MARCA NADA** — quem confere não
   pode apagar o "novo" de outra pessoa nem passar a receber os avisos dela.
"""
from __future__ import annotations

import json

from tests.frontend.test_motorista_abas import EU, MULTAS, VIAGEM

LIDOS = "/api/motorista/avisos/lidos"

#: O formato que `avisos.meus` devolve — conferido contra o módulo, não
#: inventado: `itens`, `nao_lidos` e o bloco `push`.
AVISOS = {
    "itens": [{"id": 11, "tipo": "multa", "rotulo": "Multa",
               "titulo": "Há uma nova multa no seu app.",
               "detalhe": "VELOCIDADE ATE 20% · 04/08", "aba": "multas",
               "quando": "2026-09-11T14:03:00-03:00", "lido": False},
              {"id": 10, "tipo": "mural", "rotulo": "Recado do RH",
               "titulo": "Há um novo recado do RH.",
               "detalhe": "Convenção coletiva", "aba": "rh",
               "quando": "2026-09-10T09:00:00-03:00", "lido": True}],
    "nao_lidos": 1,
    "push": {"habilitado": True, "chave": "BAAA", "aparelhos": 0, "mestre": False}}


def _eu(novos=1, **extra):
    return {**EU, "avisos": {"conversas": 0, "novos": novos}, **extra}


def _abrir(pg, base_url, eu, avisos=AVISOS, *, hash_="", espera="viagem",
           largura=390):
    corpos = {"/api/motorista/eu": eu, "/api/motorista/viagem": VIAGEM,
              "/api/motorista/multas": MULTAS, "/api/motorista/avisos": avisos,
              LIDOS: {"ok": True, "marcados": 1},
              "/api/motorista/avisos/novos": {"novos": 0}}
    pedidas: list = []

    def rota(route):
        req = route.request
        caminho = req.url.split("?")[0]
        # A MAIS COMPRIDA PRIMEIRO: `/avisos` é sufixo de nada, mas a ordem
        # explícita não depende disso.
        for chave in sorted(corpos, key=len, reverse=True):
            if caminho.endswith(chave):
                pedidas.append((req.method, chave))
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(corpos[chave]))
        pedidas.append((req.method, caminho))
        route.fulfill(status=200, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    erros: list = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": largura, "height": 780})
    pg.goto("%s/static/motorista.html%s" % (base_url, hash_))
    pg.wait_for_selector("#tela-%s:not([hidden])" % espera, timeout=15000)
    return pedidas, erros


def _lidos(pg, acao) -> dict:
    """Executa a ação e devolve o corpo do POST de "lido" que ela disparou."""
    with pg.expect_request(lambda r: r.url.endswith(LIDOS) and r.method == "POST",
                           timeout=15000) as info:
        acao()
    return json.loads(info.value.post_data or "{}")


def test_o_sino_mostra_o_numero_que_o_SERVIDOR_manda(pagina):
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url, _eu(3))
    num = pg.locator("#num-avisos")
    assert num.is_visible() and num.text_content() == "3"
    assert pg.get_attribute("#b-avisos", "aria-label") == "Avisos: 3 novos"
    assert not erros, erros


def test_sem_novidade_o_sino_fica_SEM_numero(pagina):
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url, _eu(0))
    assert not pg.locator("#num-avisos").is_visible()
    assert not erros, erros


def test_o_boot_nao_busca_a_lista_nem_marca_nada_e_o_TOQUE_marca(pagina):
    pg, base_url = pagina
    pedidas, erros = _abrir(pg, base_url, _eu(3))
    pg.wait_for_load_state("networkidle")
    assert ("GET", "/api/motorista/avisos") not in pedidas, \
        "o boot buscou a lista de avisos que ninguém abriu"
    assert ("POST", LIDOS) not in pedidas, \
        "a aba que o app abre sozinho marcou como lido"

    corpo = _lidos(pg, lambda: pg.click("#navbar button[data-aba='multas']"))
    assert corpo == {"aba": "multas"}
    # 3 novos − 1 marcado (o que o servidor respondeu), sem esperar a recarga
    pg.wait_for_function("document.getElementById('num-avisos').textContent === '2'",
                         timeout=15000)
    assert not erros, erros


def test_a_lista_abre_pelo_sino_e_o_toque_leva_a_ABA_do_aviso(pagina):
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url, _eu(1))
    pg.click("#b-avisos")
    pg.wait_for_selector("#tela-avisos .av-item", timeout=15000)
    lista = "#tela-avisos .av-item"
    itens = pg.locator("#tela-avisos .av-item")
    assert itens.count() == 2
    assert "novo" in (itens.nth(0).get_attribute("class") or "")
    assert "novo" not in (itens.nth(1).get_attribute("class") or "")
    assert "VELOCIDADE" in (itens.nth(0).text_content() or "")
    assert pg.locator("#av-todos").count() == 1
    assert pg.get_attribute("#b-avisos", "aria-current") == "page"

    corpo = _lidos(pg, lambda: itens.nth(0).click())
    assert corpo == {"aba": "multas"}
    pg.wait_for_selector("#tela-multas:not([hidden])", timeout=15000)
    assert pg.locator("#tela-avisos").is_hidden()

    # E A LISTA NÃO SE GUARDA: reabrir busca de novo. Guardada, ela mostraria
    # como "novo" o aviso que o motorista acabou de ler — cada outra aba do app
    # fica em cache, e esta é a exceção.
    with pg.expect_request(lambda r: r.url.split("?")[0].endswith("/api/motorista/avisos")
                           and r.method == "GET", timeout=15000):
        pg.click("#b-avisos")
    pg.wait_for_selector(lista, timeout=15000)
    assert not erros, erros


def test_o_toque_na_NOTIFICACAO_abre_a_aba_do_aviso_e_marca(pagina):
    """`/motorista#multas` é a URL que o push leva (`avisos.despachar`)."""
    pg, base_url = pagina
    corpo = _lidos(pg, lambda: _abrir(pg, base_url, _eu(1), hash_="#multas",
                                      espera="multas"))
    assert corpo == {"aba": "multas"}
    assert pg.locator("#tela-viagem").is_hidden()
    assert pg.evaluate("location.hash") == "", \
        "o hash ficou na barra: recarregar abriria e marcaria de novo"


def test_hash_que_NAO_e_aba_do_app_e_ignorado(pagina):
    pg, base_url = pagina
    pedidas, erros = _abrir(pg, base_url, _eu(1), hash_="#<script>")
    pg.wait_for_load_state("networkidle")
    assert ("POST", LIDOS) not in pedidas
    assert not erros, erros


def test_o_acesso_MESTRE_nao_liga_notificacao_nem_marca(pagina):
    pg, base_url = pagina
    avisos = {**AVISOS, "push": {**AVISOS["push"], "mestre": True}}
    pedidas, erros = _abrir(pg, base_url, _eu(2, mestre=True), avisos)
    pg.click("#b-avisos")
    pg.wait_for_selector("#av-push .nota", timeout=15000)
    assert "administração" in pg.text_content("#av-push")
    assert pg.locator("#av-ligar").count() == 0
    assert pg.locator("#av-todos").count() == 0

    pg.click("#navbar button[data-aba='multas']")
    pg.wait_for_selector("#tela-multas .card:not(.carregando)", timeout=15000)
    pg.wait_for_load_state("networkidle")
    assert ("POST", LIDOS) not in pedidas, "o acesso mestre marcou como lido"
    assert not erros, erros


def test_com_o_push_DESLIGADO_no_servidor_a_tela_DIZ(pagina):
    pg, base_url = pagina
    avisos = {**AVISOS, "push": {**AVISOS["push"], "habilitado": False, "chave": ""}}
    _, erros = _abrir(pg, base_url, _eu(1), avisos)
    pg.click("#b-avisos")
    pg.wait_for_selector("#av-push .nota", timeout=15000)
    assert "ainda não estão ligadas" in pg.text_content("#av-push")
    assert pg.locator("#av-ligar").count() == 0
    assert not erros, erros


def test_o_sino_NAO_empurra_a_pagina_para_o_lado(pagina):
    """Um botão a mais na faixa, num celular de 360 px: nada pode nascer fora
    da tela — nem o sino, nem a conta, nem a página inteira.

    E A LOGO CONTINUA INTEIRA, que é a parte que a régua de largura não vê. A
    faixa absorve o que sobra ENCOLHENDO A LOGO (`min-width:0`, para um SVG
    largo não fazer a página rolar): com botões largos demais nada transborda
    — a logo da Sulista é que vira um risco de zero pixel, sem erro nenhum.
    Medido em 11/09/2026 com o sino: 67,7 px a 360 px, a largura natural dela.
    """
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url, _eu(12), largura=360)
    assert pg.evaluate("document.documentElement.scrollWidth - "
                       "document.documentElement.clientWidth") == 0
    for sel in ("#b-avisos", "#b-conta", "#num-avisos"):
        caixa = pg.locator(sel).bounding_box()
        assert caixa and caixa["x"] + caixa["width"] <= 360, (sel, caixa)
    pg.wait_for_function("document.querySelector('.appbar .sulista').complete",
                         timeout=15000)
    natural = pg.evaluate("(() => { const i = document.querySelector('.appbar .sulista');"
                          " return i.getBoundingClientRect().height * i.naturalWidth"
                          " / i.naturalHeight; })()")
    logo = pg.locator(".appbar .sulista").bounding_box()
    assert natural > 30 and logo["width"] >= 0.95 * natural, (logo, natural)
    assert pg.text_content("#num-avisos") == "9+"
    assert not erros, erros
