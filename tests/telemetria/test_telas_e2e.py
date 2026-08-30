"""As três telas de Telemetria contra o index.html real."""
from __future__ import annotations

import json
from pathlib import Path

from api.gobrax import consumo
from tests.frontend.conftest import USUARIO

HTML = Path(__file__).resolve().parent.parent.parent / "api" / "static" / "index.html"
S = HTML.read_text(encoding="utf-8")

TEL = [
    {"placa": "AAA1A11", "km": 4000.0, "litros": 1000.0, "km_l": 4.0,
     "vel_media": 62.0, "odometro": 500000.0, "freadas": 30, "freadas_alta": 3},
    {"placa": "BBB2B22", "km": 3000.0, "litros": 1000.0, "km_l": 3.0,
     "vel_media": 58.0, "odometro": 700000.0, "freadas": 10, "freadas_alta": 1},
    {"placa": "CCC3C33", "km": 32.95, "litros": 6.56, "km_l": 5.03,
     "vel_media": 40.0, "odometro": 995126.0, "freadas": 2, "freadas_alta": 0},
]
AVA = [
    {"placa": "AAA1A11", "litros_ava": 800.0, "km_ava": 4100.0, "abastecimentos": 9},
    {"placa": "BBB2B22", "litros_ava": 1000.0, "km_ava": 3050.0, "abastecimentos": 7},
    {"placa": "CCC3C33", "litros_ava": 3310.0, "km_ava": 6644.0, "abastecimentos": 12},
]


def _consumo():
    linhas = consumo.cruzar(TEL, AVA)
    return {"competencia": "2026-07", "kpis": consumo.resumir(linhas),
            "linhas": linhas,
            "sync": {"competencia": "2026-07", "quando": "2026-08-19 16:00:00",
                     "registros": 3},
            "fonte": "teste"}


HODOMETRO = {"competencia": "2026-07",
             "kpis": {"veiculos": 3, "com_leitura": 2, "sem_leitura": 1},
             "linhas": [{"placa": "AAA1A11", "odometro": 500000.0,
                         "lido_em": "2026-07-31 23:59:35+0000"},
                        {"placa": "ZZZ9Z99", "odometro": None, "lido_em": None}],
             "sync": {"competencia": "2026-07", "quando": "2026-08-19 16:00:00",
                      "registros": 3},
             "fonte": "teste"}

CONDUCAO = {"placa": "AAA1A11", "competencia": "2026-07",
            "motoristas": [{"nome": "3169 - CIRSO", "de": "2026-07-01",
                            "ate": "2026-07-15"}],
            "indicadores": [
                {"chave": "economicRange", "rotulo": "Faixa econômica",
                 "duracao_h": 1022.12, "percentual": 9.15, "nota": 0.0},
                {"chave": "cruiseControl", "rotulo": "Piloto automático",
                 "duracao_h": 0.0, "percentual": 0.0, "nota": 100.0},
                {"chave": "ecoRoll", "rotulo": "Eco-roll (embalo)",
                 "duracao_h": 919.78, "percentual": 8.23, "nota": 8.0}]}


def _abrir(pg, base_url, view):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = USUARIO
        elif "telemetria/consumo" in u:
            corpo = _consumo()
        elif "telemetria/hodometro" in u:
            corpo = HODOMETRO
        elif "telemetria/conducao" in u:
            corpo = CONDUCAO
        elif "telemetria/rastro" in u:
            corpo = {"dia": "2026-07-15", "placa": "AAA1A11", "pontos": 2,
                     "veiculos": [{"placa": "AAA1A11", "pontos": [
                         {"quando": "2026-07-15 10:00:00", "lat": -23.6, "lon": -46.5,
                          "velocidade": 60.0},
                         {"quando": "2026-07-15 10:10:00", "lat": -23.7, "lon": -46.6,
                          "velocidade": None}]}]}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#{view}")
    return erros


def test_as_tres_views_estao_no_roteador():
    bloco = S.split("const VIEWS = {", 1)[1].split("};", 1)[0]
    for v in ("telcon", "telcond", "telhod"):
        assert f"{v}:" in bloco
        assert f"{v}:load" in S
        assert f'data-view="{v}"' in S


def test_as_tres_estao_na_gaveta_mobile():
    drawer = S.split('<div class="drawer"', 1)[1]
    for v in ("telcon", "telcond", "telhod"):
        assert f'href="#{v}"' in drawer


def test_consumo_abre_sem_erro_e_mostra_os_kpis(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, "telcon")
    pg.wait_for_selector("#kpis-telcon .kpi", timeout=20000)
    assert erros == []
    assert pg.eval_on_selector_all("#kpis-telcon .kpi", "e=>e.length") == 4
    assert "Km/l da frota" in pg.inner_text("#kpis-telcon")


def test_consumo_marca_telemetria_incompleta_em_vez_de_divergencia(pagina):
    """CCC3C33 tem 32,95 km de telemetria contra 6.644 do AVA: rastreador mudo,
    não divergência de consumo."""
    pg, base = pagina
    _abrir(pg, base, "telcon")
    pg.wait_for_selector("#telcon-lista tr", timeout=20000)
    lista = pg.inner_text("#telcon-lista")
    assert "CCC3C33" in lista
    assert "telemetria incompleta" in lista


def test_consumo_mostra_a_idade_da_coleta(pagina):
    pg, base = pagina
    _abrir(pg, base, "telcon")
    pg.wait_for_selector("#telcon-lista tr", timeout=20000)
    assert "coletado em" in pg.inner_text("#telcon-sync")


def test_conducao_sem_placa_explica_em_vez_de_chamar_a_api(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, "telcond")
    # A tela virou três abas em 30/08/2026 (painel que se lê sem rolar) e a
    # condução econômica é a terceira. Aba escondida não é visível — abrir a
    # aba é o caminho de quem usa.
    pg.evaluate("abaTrocar('telcond','eco')")
    pg.wait_for_selector("#telcond-conteudo", timeout=20000)
    assert erros == []
    assert "Escolha um veículo" in pg.inner_text("#telcond-conteudo")


def test_hodometro_separa_quem_tem_leitura(pagina):
    pg, base = pagina
    erros = _abrir(pg, base, "telhod")
    pg.wait_for_selector("#telhod-lista tr", timeout=20000)
    assert erros == []
    lista = pg.inner_text("#telhod-lista")
    assert "com leitura" in lista and "sem leitura no período" in lista
    assert "rastreador mudo" in pg.inner_text("#kpis-telhod")


def test_hodometro_abre_o_mapa_do_trajeto(pagina):
    pg, base = pagina
    _abrir(pg, base, "telhod")
    pg.wait_for_selector("#telhod-lista tr", timeout=20000)
    pg.click("#telhod-lista button.ghost")
    pg.wait_for_selector("#telhod-mapa-card", state="visible", timeout=10000)
    assert "Trajeto de" in pg.inner_text("#telhod-mapa-titulo")
