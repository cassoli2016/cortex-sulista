"""A tela de Premiação com a regra nova, contra o index.html real."""
from __future__ import annotations

import json

from api.premiacao import calculo
from tests.frontend.conftest import USUARIO

PARAMS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}
DRIVERS = [
    {"driverId": 1, "driverName": "3797 - GABRIEL ITALO", "km": 10850.0, "nota": 78.0},
    {"driverId": 2, "driverName": "3472 - FERNANDO FREITAS", "km": 8870.0, "nota": 88.0},
    {"driverId": 3, "driverName": "9999 - POUCO KM", "km": 200.0, "nota": 95.0},
    {"driverId": 4, "driverName": "8888 - NOTA BAIXA", "km": 6000.0, "nota": 40.0},
]


def _payload(regra="nota_km"):
    calc = calculo.calcular(DRIVERS, PARAMS)
    return {"configurado": True, "month": "2026-04", "parcial": False,
            "coletado_em": "2026-05-02T10:00:00", "aviso": None, "regra": regra,
            "index": [{"mes": "2026-04"}], "params": PARAMS,
            "linhas": calc["linhas"],
            "kpis": {"motoristas": calc["motoristas"], "premiados": calc["premiados"],
                     "premio_total": calc["premio_total"], "km_total": calc["km_total"]},
            "referencias": {"preco_diesel_interno": 5.9}}


def _abrir(pg, base_url, regra="nota_km"):
    dados = _payload(regra)

    def rota(route):
        u = route.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            dados if "premiacao" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#prem")
    pg.wait_for_selector("#kpis-prem .kpi", timeout=20000)
    return dados, erros


def test_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == []


def test_kpis_mostram_a_regra_nova(pagina):
    pg, base = pagina
    dados, _ = _abrir(pg, base)
    texto = pg.inner_text("#kpis-prem")
    assert "nota da Gobrax × km rodado" in texto
    assert "Km rodado" in texto
    assert "Litros" not in texto      # vocabulário da regra antiga sumiu


def test_mes_antigo_avisa_que_usa_a_regra_com_que_foi_pago(pagina):
    """Sem isso a mesma tela mostraria dois critérios sem avisar."""
    pg, base = pagina
    _abrir(pg, base, regra="litros_economizados")
    assert "regra antiga" in pg.inner_text("#kpis-prem")


def test_quem_ficou_de_fora_aparece_com_o_motivo(pagina):
    pg, base = pagina
    _abrir(pg, base)
    lista = pg.inner_text("#prem-rank")
    assert "POUCO KM" in lista and "km abaixo do mínimo" in lista
    assert "NOTA BAIXA" in lista and "nota abaixo da mínima" in lista


def test_detalhe_explica_a_conta_do_premio(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#prem-rank tr.forn-row")
    det = pg.inner_text("#prem-det-0")
    assert "km ×" in det and "nota" in det


def test_parametros_da_regra_nova_estao_no_formulario(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.input_value("#fPremValorKm") != ""
    assert pg.input_value("#fPremNotaMin") != ""
    assert pg.is_visible("#fPremKmMin")


def test_premiacao_aparece_sob_telemetria_no_menu(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.is_visible("#grpTel")
