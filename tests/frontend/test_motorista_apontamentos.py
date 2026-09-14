# -*- coding: utf-8 -*-
"""Chegada e saída no app do motorista, NO NAVEGADOR (14/09/2026).

A regra da cerca é do servidor (`tests/motorista/test_apontamento.py`); aqui se
prova o que só existe depois de o navegador executar a página:

- a EXPLICAÇÃO vem ANTES da permissão do navegador — quem nunca autorizou lê o
  que é enviado e quando, e só então o celular pergunta;
- com a autorização, o toque manda a posição do celular e a linha redesenha
  com o veredito que o servidor gravou;
- localização bloqueada diz COMO liberar, e nada é enviado;
- o acesso mestre não tem botão e não manda posição;
- o app aberto manda a posição sozinho, e a aba Conta retira a autorização.

A geolocalização é a do PLAYWRIGHT (`set_geolocation`): o navegador de verdade
responde, com permissão concedida ou negada — dublê de `navigator` provaria o
dublê, não a página.
"""
from __future__ import annotations

import json

from tests.frontend.test_motorista_abas import EU, VIAGEM

LAT, LON = -26.3000, -48.8000

APONT = [
    {"tipo": "chegou_coleta", "rotulo": "Cheguei para carregar", "feito": True,
     "em": "2026-09-14 07:10", "cerca": "fora", "referencia": "poligono",
     "distancia_m": 1234},
    {"tipo": "saiu_coleta", "rotulo": "Saí carregado", "feito": False},
    {"tipo": "chegou_entrega", "rotulo": "Cheguei para descarregar", "feito": False},
    {"tipo": "saiu_entrega", "rotulo": "Terminei a descarga", "feito": False},
]


def _abrir(pg, base_url, aceita=True, mestre=False, geo=True, vazio=False):
    estado = {"aceita": aceita, "apont": json.loads(json.dumps(APONT)), "posts": []}
    loc = lambda: {"aceita": estado["aceita"],
                   "em": "2026-09-14T08:00:00-03:00" if estado["aceita"] else None}

    def rota(route):
        req = route.request
        caminho = req.url.split("?")[0]
        corpo = None
        if req.method == "POST":
            try:
                corpo = req.post_data_json
            except Exception:  # noqa: BLE001
                corpo = None
            estado["posts"].append((caminho.split("/api/motorista/")[-1], corpo))
        if caminho.endswith("/api/motorista/eu"):
            r = {**EU, "mestre": mestre, "localizacao": loc()}
        elif caminho.endswith("/api/motorista/viagem"):
            v = {**VIAGEM["viagem"], "vazio": vazio}
            r = {"viagem": v, "apontamentos": [] if vazio else estado["apont"],
                 "localizacao": loc()}
        elif caminho.endswith("/api/motorista/localizacao"):
            estado["aceita"] = bool((corpo or {}).get("aceito"))
            r = loc()
        elif caminho.endswith("/api/motorista/apontamento"):
            t = (corpo or {}).get("tipo")
            for a in estado["apont"]:
                if a["tipo"] == t:
                    a.update({"feito": True, "em": "2026-09-14 09:30",
                              "cerca": "dentro", "referencia": "poligono",
                              "distancia_m": 0})
            r = {"tipo": t, "cerca": "dentro", "distancia_m": 0}
        elif caminho.endswith("/api/motorista/posicao"):
            r = {"viagem": True, "proxima_s": 300}
        else:
            r = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(r))

    if geo:
        pg.context.grant_permissions(["geolocation"], origin=base_url)
        pg.context.set_geolocation({"latitude": LAT, "longitude": LON, "accuracy": 12})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": 390, "height": 780})
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#card-viagem h1", timeout=15000)
    return estado, erros


def _posts(estado, rota):
    return [c for r, c in estado["posts"] if r == rota]


def test_a_viagem_mostra_os_QUATRO_e_o_proximo_em_destaque(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    linhas = pg.locator("#card-viagem .ap-linha")
    assert linhas.count() == 4
    assert "fora da cerca · 1,2 km" in linhas.nth(0).inner_text()
    assert pg.locator("#card-viagem .ap-btn.ap-prox").get_attribute("data-tipo") == "saiu_coleta"
    assert not erros, erros


def test_sem_autorizacao_o_toque_EXPLICA_antes_de_pedir(pagina):
    pg, base = pagina
    estado, erros = _abrir(pg, base, aceita=False)
    pg.click("#card-viagem .ap-linha .ap-btn[data-tipo='saiu_coleta']")
    caixa = pg.locator("#ap-msg .aceite")
    assert caixa.is_visible()
    txt = caixa.inner_text()
    assert "a cada 5 minutos" in txt and "apagada quando a viagem termina" in txt
    assert "Com o app fechado, nada é enviado" in txt
    assert not _posts(estado, "apontamento"), "enviou antes de a pessoa autorizar"

    pg.click("#ap-msg [data-aceite='sim']")
    pg.wait_for_timeout(1200)
    assert _posts(estado, "localizacao") == [{"aceito": True}]
    enviados = _posts(estado, "apontamento")
    assert enviados and enviados[0]["tipo"] == "saiu_coleta"
    assert abs(enviados[0]["lat"] - LAT) < 1e-6 and abs(enviados[0]["lon"] - LON) < 1e-6
    assert enviados[0]["em_aparelho"], "a hora do aparelho vai junto"
    assert not erros, erros


def test_com_autorizacao_registra_DIRETO_e_redesenha_com_o_veredito(pagina):
    pg, base = pagina
    estado, erros = _abrir(pg, base)
    pg.click("#card-viagem .ap-linha .ap-btn[data-tipo='saiu_coleta']")
    pg.wait_for_function(
        "() => document.querySelectorAll('#card-viagem .ap-linha')[1]"
        ".innerText.includes('no cliente')", timeout=8000)
    assert len(_posts(estado, "apontamento")) == 1
    assert not pg.locator("#card-viagem .ap-btn[data-tipo='saiu_coleta']").count()
    assert not erros, erros


def test_localizacao_BLOQUEADA_diz_como_liberar_e_nao_envia(pagina):
    pg, base = pagina
    estado, _ = _abrir(pg, base, geo=False)
    pg.click("#card-viagem .ap-linha .ap-btn[data-tipo='saiu_coleta']")
    pg.wait_for_selector("#ap-msg.erro", timeout=8000)
    assert "bloqueada" in pg.inner_text("#ap-msg")
    assert not _posts(estado, "apontamento")
    assert pg.locator("#card-viagem .ap-btn[data-tipo='saiu_coleta']").is_enabled()


def test_o_acesso_MESTRE_nao_tem_botao_nem_manda_posicao(pagina):
    pg, base = pagina
    estado, _ = _abrir(pg, base, mestre=True)
    assert pg.locator("#card-viagem .ap-btn").count() == 0
    assert "conferência" in pg.inner_text("#card-viagem .ap-nota")
    pg.wait_for_timeout(3500)
    assert not _posts(estado, "posicao"), "o acesso mestre enviou a posição de quem administra"


def test_o_app_ABERTO_manda_a_posicao_sozinho(pagina):
    pg, base = pagina
    estado, _ = _abrir(pg, base)
    pg.wait_for_timeout(4000)
    enviadas = _posts(estado, "posicao")
    assert len(enviadas) == 1, "no boot sai UMA posição, e a próxima em 5 min"
    assert abs(enviadas[0]["lat"] - LAT) < 1e-6 and enviadas[0]["precisao"] == 12


def test_sem_autorizacao_o_app_NAO_manda_posicao(pagina):
    pg, base = pagina
    estado, _ = _abrir(pg, base, aceita=False)
    pg.wait_for_timeout(3500)
    assert not _posts(estado, "posicao")


def test_a_conta_mostra_e_RETIRA_a_autorizacao(pagina):
    pg, base = pagina
    estado, erros = _abrir(pg, base)
    pg.click("#b-conta")
    pg.wait_for_selector("#tela-conta:not([hidden])", timeout=5000)
    assert "autorizada em 14/09/2026" in pg.inner_text("#linhas-conta")
    pg.click("#b-loc")
    pg.wait_for_timeout(600)
    assert _posts(estado, "localizacao") == [{"aceito": False}]
    assert "não autorizada" in pg.inner_text("#linhas-conta")
    assert not pg.locator("#b-loc").count()
    assert not erros, erros


def test_viagem_VAZIA_nao_tem_chegada_nem_saida(pagina):
    pg, base = pagina
    _abrir(pg, base, vazio=True)
    assert pg.locator("#card-viagem .ap").count() == 0


def test_a_explicacao_aberta_NAO_empurra_a_pagina_para_o_lado(pagina):
    pg, base = pagina
    _abrir(pg, base, aceita=False)
    pg.click("#card-viagem .ap-linha .ap-btn[data-tipo='saiu_coleta']")
    pg.wait_for_selector("#ap-msg .aceite", timeout=5000)
    assert pg.evaluate("() => document.documentElement.scrollWidth - "
                       "document.documentElement.clientWidth") == 0
