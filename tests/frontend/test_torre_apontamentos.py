# -*- coding: utf-8 -*-
"""A Torre com o app do motorista: o celular no mapa e a aba Apontamentos.

Dois guards do que só o navegador mostra:

- **O CELULAR NÃO SOBREPÕE O RASTREADOR MAIS NOVO.** O tracejado aparece quando
  a placa não tem posição de rastreador mais recente que a do celular — é o que
  mostra o agregado sem rastreador integrado sem duplicar o caminhão que o
  rastreador já vê.
- **O APONTAMENTO APARECE AO LADO DO ERP**, com a cerca do cliente e a
  diferença em minutos; com o ERP fora, a coluna diz "não sei", nunca "sem
  registro".
"""
from __future__ import annotations

import json

from tests.frontend.test_torre_mapa import ADMIN, TORRE

CELULAR = [
    # DEF4G56: rastreador às 15:40, celular às 16:02 — o celular é mais novo
    {"placa": "DEF4G56", "lat": -25.90, "lng": -49.00, "posicao_em": "2026-08-30 16:02",
     "idade_min": 3, "precisao_m": 20, "fonte": "celular do motorista"},
    # ABC1D23: rastreador às 16:00, celular às 15:00 — o rastreador vence
    {"placa": "ABC1D23", "lat": -26.50, "lng": -48.90, "posicao_em": "2026-08-30 15:00",
     "idade_min": 65, "precisao_m": 15, "fonte": "celular do motorista"},
]

APONT = {
    "itens": [
        {"em": "2026-09-14 09:30", "motorista": "ANA MOTORISTA", "placa": "DEF4G56",
         "viagem": "178010", "tipo": "chegou_coleta", "rotulo": "Cheguei para carregar",
         "cerca": "dentro", "referencia": "poligono", "distancia_m": 0, "precisao_m": 12,
         "aparelho_dif_min": 0, "erp_em": "2026-09-14 09:18", "erp_dif_min": 12},
        {"em": "2026-09-14 08:00", "motorista": "BRUNO MOTORISTA", "placa": "ABC1D23",
         "viagem": "178011", "tipo": "chegou_entrega",
         "rotulo": "Cheguei para descarregar", "cerca": "fora", "referencia": "coordenada",
         "distancia_m": 1234, "precisao_m": 30, "aparelho_dif_min": -4,
         "erp_em": None, "erp_dif_min": None},
    ],
    "janela_dias": 7, "limite": 500, "erp_ok": True, "raio_coordenada_m": 500,
    "resumo": {"total": 2, "dentro": 1, "fora": 1, "sem_cerca": 0,
               "nao_conferida": 0, "com_erp": 1},
    "fonte": "t",
}


def _abrir(pg, base_url, apont=APONT):
    torre = {**TORRE, "posicoes_celular": CELULAR}

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/operacao/torre/apontamentos" in u:
            corpo = apont
        elif "/api/operacao/torre/estradas" in u:
            corpo = {"configurado": True, "trechos": [], "resumo": {}}
        elif "/api/operacao/torre" in u:
            corpo = torre
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#torre")
    pg.wait_for_selector("#mapaTorre .leaflet-tile-pane", state="attached", timeout=25000)
    pg.wait_for_timeout(600)
    return erros


def test_o_celular_aparece_TRACEJADO_so_onde_e_mais_novo_que_o_rastreador(pagina):
    pg, base = pagina
    erros = _abrir(pg, base)
    tracejados = pg.evaluate(
        "() => document.querySelectorAll('#mapaTorre path[stroke-dasharray]').length")
    assert tracejados == 1, tracejados
    assert not erros, erros


def test_a_aba_poe_o_apontamento_AO_LADO_do_ERP(pagina):
    pg, base = pagina
    erros = _abrir(pg, base)
    pg.click("#tabtorre-apont")
    pg.wait_for_selector("#torre-apont tr", timeout=10000)
    linhas = pg.locator("#torre-apont tr")
    assert linhas.count() == 2
    a = linhas.nth(0).inner_text()
    assert "ANA MOTORISTA" in a and "Cheguei para carregar" in a
    assert "no cliente" in a and "09:18" in a and "+12 min" in a
    b = linhas.nth(1).inner_text()
    assert "fora · 1,2 km" in b and "pelo endereço" in b
    assert "2 apontamentos" in pg.inner_text("#hintTorreApont")
    assert not erros, erros


def test_com_o_ERP_fora_a_coluna_diz_NAO_SEI(pagina):
    pg, base = pagina
    _abrir(pg, base, apont={**APONT, "erp_ok": False,
                           "itens": [{**i, "erp_em": None, "erp_dif_min": None}
                                     for i in APONT["itens"]]})
    pg.click("#tabtorre-apont")
    pg.wait_for_selector("#torre-apont tr", timeout=10000)
    assert "ERP não respondeu" in pg.inner_text("#hintTorreApont")
    assert "sem lançamento" not in pg.inner_text("#torre-apont")
