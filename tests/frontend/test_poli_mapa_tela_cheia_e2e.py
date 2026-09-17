"""O mapa da permanencia na planta abre em TELA CHEIA (17/09/2026).

No molde do mapa do Milk Run: o cartao cobre a janela (nao e o fullscreen
nativo, que o Leaflet e o Safari do iPad nao aguentam), a legenda do calor vai
junto, Esc fecha, e o mapa e REENQUADRADO nos dois sentidos. So redimensionar
deixaria o zoom do cartao de 430 px numa tela inteira — o mapa "abre", o teste
de visibilidade passa, e as docas continuam pequenas no meio da planta. Por
isso o guard mede o ZOOM, nao so o tamanho.
"""
from __future__ import annotations

import json
import os

USUARIO = {"nome": "T", "email": "t@s.local", "admin": True,
           "perfil": "Administrador", "telas": []}

# Tres docas num quarteirao de Joinville: pequeno o bastante para o zoom mudar
# de forma mensuravel entre o cartao e a tela inteira.
def _quad(lat, lng, d=0.0004):
    return [[lat, lng], [lat + d, lng], [lat + d, lng + d], [lat, lng + d]]

PONTOS = [{"id": i, "nome": f"DOCA {i}", "coords": _quad(-26.2700 + i * 0.001, -48.8500),
           "total_h": 10.0 * i, "visitas": 5 * i, "mediana_min": 12.5, "placas": i}
          for i in (1, 2, 3)]
CORPO = {"kpis": {}, "periodo": {}, "fonte": {}, "avisos": [], "mensal": [],
         "ranking": [], "tabela": [],
         "mapa": {"perimetro": _quad(-26.2720, -48.8520, 0.006), "pontos": PONTOS}}

ESTADO = """() => {
  const c = document.getElementById('poliMapa').getBoundingClientRect();
  const card = document.getElementById('poliMapa').closest('.card');
  const leg = document.getElementById('poliMapaLegenda').getBoundingClientRect();
  return {w: Math.round(c.width), h: Math.round(c.height), zoom: poliMap.getZoom(),
          aberto: card.classList.contains('poli-mapa-exp'),
          legenda_visivel: leg.height > 0 && leg.bottom <= innerHeight + 1,
          botao: document.getElementById('btnPoliExp').textContent.trim(),
          expandido: document.getElementById('btnPoliExp').getAttribute('aria-expanded'),
          rola: getComputedStyle(document.body).overflow,
          vw: innerWidth, vh: innerHeight};
}"""


def _abre(pagina):
    pg, base = pagina

    def rota(r):
        u = r.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            CORPO if "/api/operacional/poligonos" in u else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.route("**/tile.openstreetmap.org/**", lambda r: r.abort())
    # 1200 de altura e nao 900: o Leaflet so usa zoom INTEIRO, e um nivel a
    # mais pede o dobro da area. Com 900 px a tela nao chega a 2x o cartao de
    # 430 px, o zoom fica igual e o guard nao distinguiria reenquadrar de so
    # redimensionar.
    pg.set_viewport_size({"width": 1600, "height": 1200})
    pg.goto(base + "/static/index.html#poli")
    pg.wait_for_function("() => typeof poliMap !== 'undefined' && poliMap && poliLimites")
    pg.wait_for_timeout(400)
    return pg


def test_o_mapa_da_planta_abre_em_tela_cheia_REENQUADRADO_e_volta(pagina):
    pg = _abre(pagina)
    antes = pg.evaluate(ESTADO)
    assert not antes["aberto"] and antes["botao"] == "Tela cheia", antes

    pg.click("#btnPoliExp")
    pg.wait_for_timeout(500)
    cheio = pg.evaluate(ESTADO)
    assert cheio["aberto"] and cheio["expandido"] == "true" and cheio["botao"] == "Recolher"
    assert cheio["w"] >= cheio["vw"] - 2 and cheio["h"] >= cheio["vh"] * 0.75, cheio
    assert cheio["legenda_visivel"], "tela cheia sem a escala de horas nao se le"
    assert cheio["zoom"] > antes["zoom"], (
        f"so redimensionou: zoom {antes['zoom']} -> {cheio['zoom']}")
    foto = os.environ.get("FOTO_POLI")
    if foto:
        pg.screenshot(path=foto)

    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    volta = pg.evaluate(ESTADO)
    assert not volta["aberto"] and volta["botao"] == "Tela cheia"
    assert volta["h"] == antes["h"] and volta["zoom"] == antes["zoom"], (antes, volta)
    assert volta["rola"] != "hidden"


def test_trocar_de_tela_com_o_mapa_aberto_nao_deixa_a_pagina_sem_rolagem(pagina):
    pg = _abre(pagina)
    pg.click("#btnPoliExp")
    pg.wait_for_timeout(300)
    pg.evaluate("() => { location.hash = '#home'; }")
    pg.wait_for_timeout(500)
    assert pg.evaluate("() => getComputedStyle(document.body).overflow") != "hidden"
    assert not pg.evaluate("() => !!document.querySelector('.poli-mapa-exp')")
