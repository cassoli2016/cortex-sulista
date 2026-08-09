"""Integracao da barra de carregamento contra o index.html real.

Nao sobe a API nem toca no AVA: um http.server serve api/ como raiz (para
/static/index.html e /static/carga.js resolverem) e o Playwright intercepta
TODA rota /api/**, respondendo com atraso controlado. Assim os limiares de
150ms e 3s sao testados sem depender do banco.

A visibilidade da barra e observada por um MutationObserver injetado antes do
documento: checar `#loadbar` por polling seria uma corrida perdida contra uma
transicao de 150ms.
"""
from __future__ import annotations

import json
import time

from tests.frontend.conftest import USUARIO


def _mockar(pg, atraso_ms: int):
    """Toda rota /api/** responde {} depois de `atraso_ms`; /auth/me devolve sessao.

    O atraso e time.sleep e nao page.wait_for_timeout: chamar um metodo de
    espera da propria page de DENTRO de um route handler da API sincrona do
    Playwright e reentrante e trava.
    """
    def rota(route):
        if "/api/auth/me" in route.request.url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(USUARIO))
            return
        if atraso_ms:
            time.sleep(atraso_ms / 1000)
        route.fulfill(status=200, content_type="application/json", body="{}")
    pg.route("**/api/**", rota)


QUIETUDE_S = 1.5


def _estabilizar(pg):
    """Espera o boot sossegar de verdade e zera o espia.

    Exige QUIETUDE (nenhuma chamada /api/ por 1,5s) e nao apenas um instante de
    CARGA.ativas()==0: o boot tem fases (auth/me -> entrar -> router -> tela) e,
    com respostas rapidas, o contador toca zero ENTRE elas. Medindo o instante,
    os testes de 'nao acende' pegavam a rajada seguinte do boot em vez da
    chamada sob teste e falhavam com [True, False, True, False].
    """
    ultimo = {"t": time.time()}

    def marca(req):
        if "/api/" in req.url:
            ultimo["t"] = time.time()

    pg.on("request", marca)
    try:
        limite = time.time() + 40
        while time.time() < limite:
            quieto = (time.time() - ultimo["t"]) > QUIETUDE_S
            if quieto and pg.evaluate("typeof CARGA !== 'undefined' && CARGA.ativas() === 0"):
                break
            pg.wait_for_timeout(200)
        else:
            raise AssertionError("o painel nunca parou de chamar a API")
    finally:
        pg.remove_listener("request", marca)
    pg.evaluate("window.__barraLog = []")


def test_carga_rapida_nao_pisca_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 30)
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("void fetch('/api/financeiro/overview')")   # 30ms, abaixo dos 150
    pg.wait_for_timeout(1000)
    assert True not in pg.evaluate("window.__barraLog"), "barra apareceu numa carga de 30ms"


def test_carga_lenta_mostra_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 800)
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_selector("#loadbar:not([hidden])", timeout=5000)


def test_barra_some_ao_terminar(pagina):
    pg, base = pagina
    _mockar(pg, 800)
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_selector("#loadbar:not([hidden])", timeout=5000)
    # state="hidden" e obrigatorio: wait_for_selector espera VISIBILIDADE por
    # padrao, e "#loadbar[hidden]" tem display:none -- a condicao seria
    # impossivel de satisfazer e o teste so daria timeout.
    pg.wait_for_selector("#loadbar", state="hidden", timeout=30000)
    assert pg.evaluate("CARGA.ativas()") == 0


def test_erro_de_rede_tambem_apaga_a_barra(pagina):
    """O caso que mais gera spinner eterno na vida real: a Promise rejeita e o
    finally e a unica coisa que ainda roda."""
    pg, base = pagina
    # ORDEM IMPORTA: no Playwright a rota registrada POR ULTIMO e avaliada
    # primeiro. O catch-all vai antes; o mock da sessao depois, para vencer.
    pg.route("**/api/**", lambda r: r.abort())
    pg.route("**/api/auth/me", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_timeout(3000)
    assert pg.evaluate("CARGA.ativas()") == 0, "contador vazou quando o fetch falhou"
    assert pg.is_hidden("#loadbar")


def test_contador_de_tempo_aparece_aos_3s(pagina):
    pg, base = pagina
    _mockar(pg, 6000)
    pg.goto(f"{base}/static/index.html")
    pg.wait_for_selector("#loadtempo:not([hidden])", timeout=8000)
    texto = pg.inner_text("#loadtempo")
    assert texto.startswith("consultando o banco… "), texto
    assert texto.endswith("s"), texto


def test_recarga_de_fundo_nao_acende_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 800)          # bem acima dos 150ms: se contasse, acenderia
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("void fetch('/api/gestao/servidor',{headers:{'X-Carga-Fundo':'1'}})")
    pg.wait_for_timeout(2000)
    assert True not in pg.evaluate("window.__barraLog"), "chamada de fundo acendeu a barra"


def test_clique_manual_na_mesma_rota_acende_a_barra(pagina):
    """Contraprova do teste acima: sem o header, a MESMA rota tem de acender.
    Sem esta, um bug que desligasse a barra por completo passaria despercebido."""
    pg, base = pagina
    _mockar(pg, 800)
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("void fetch('/api/gestao/servidor')")
    pg.wait_for_selector("#loadbar:not([hidden])", timeout=5000)
    assert True in pg.evaluate("window.__barraLog")


def test_chamada_externa_nao_acende_a_barra(pagina):
    pg, base = pagina
    _mockar(pg, 800)
    pg.route("**open-meteo**", lambda r: (time.sleep(0.8), r.fulfill(
        status=200, content_type="application/json", body="{}")))
    pg.goto(f"{base}/static/index.html")
    _estabilizar(pg)
    pg.evaluate("void fetch('https://api.open-meteo.com/v1/forecast?latitude=-27&longitude=-48')")
    pg.wait_for_timeout(2000)
    assert True not in pg.evaluate("window.__barraLog"), "fetch externo acendeu a barra"
