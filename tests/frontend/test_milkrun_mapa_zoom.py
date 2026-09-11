"""O ENQUADRAMENTO do mapa do Milk Run, medido na tela.

O DEFEITO, medido em 10/09/2026 e relatado por quem opera ("ajuste o zoom do
mapa da Operação MWM"):

A aba Mapa nasce ESCONDIDA — quem nasce aberta é o Resumo por dia — e
`milkMapa()` roda no carregamento da tela. Com a aba escondida o contêiner mede
0x0, o Leaflet não tem como calcular escala, e `fitBounds` devolve ZOOM 0: o
planeta inteiro. Ao abrir a aba, `mapasRemedir()` chama `invalidateSize()`, que
conserta o TAMANHO e não o ZOOM — o mapa ganhava 1322x300 px e continuava no
zoom 0, com as cinco paradas do ABC a cinco pixels uma da outra.

    com a aba escondida   zoom 0 · container 0x0
    ao abrir a aba        zoom 0 · container 1322x300 · norte 85,6 sul -88,1

NADA DISSO LEVANTA ERRO. O mapa aparece, os pinos estão lá, e um teste que
contasse pinos passaria — eles estão todos "dentro da área visível" porque a
área visível é o mundo. Só medindo o ZOOM e os LIMITES o defeito aparece.

Enquadrar é medir, e não dá para medir o que não tem tamanho.
"""
from __future__ import annotations

import json

import pytest

USUARIO = {"nome": "T", "email": "t@s.local", "admin": True,
           "perfil": "Administrador", "telas": []}

# Paradas REAIS de uma operação MWM: fornecedores no ABC mais uma em Campinas.
# A distância entre as pontas (~100 km) é o que torna o zoom observável — com
# tudo no mesmo quarteirão, zoom 0 e zoom 13 dariam a mesma contagem de pinos.
_PTS = [
    ("FORN A", "SAO BERNARDO DO CAMPO", -23.6939, -46.5650, 1, "coletada"),
    ("FORN B", "DIADEMA", -23.6860, -46.6200, 2, "coletada"),
    ("FORN C", "SANTO ANDRE", -23.6639, -46.5383, 3, "no_local"),
    ("FORN D", "SAO PAULO", -23.5505, -46.6333, 4, "aguardando"),
    ("FORN E", "CAMPINAS", -22.9099, -47.0626, 5, "aguardando"),
]
PONTOS = [{"ponto": n, "cidade": c, "uf": "SP", "lat": la, "lng": lo,
           "sequencia": sq, "estado": es, "coleta": 900 + sq,
           "previsto": "2026-09-10 08:00", "chegada": None, "placa": "ABC1D23"}
          for n, c, la, lo, sq, es in _PTS]

CORPO = {
    "kpis": {"solicitacoes": 5, "coletas": 1, "coletadas": 2, "frustradas": 0,
             "pendentes": 3, "realizado": 66.7},
    "dias": [], "coletas": [{"coleta": 901, "pontos": PONTOS}],
    "veiculos_pos": {"ABC1D23": {"lat": -23.65, "lng": -46.60, "recente": True,
                                 "velocidade": 42,
                                 "posicao_em": "2026-09-10 09:10"}},
    "fornecedores": [], "tipos": [],
}

_ESTADO = """() => {
  if(typeof milkMap === 'undefined' || !milkMap) return null;
  const c = milkMap.getContainer().getBoundingClientRect();
  const b = milkMap.getBounds();
  return {zoom: milkMap.getZoom(), w: Math.round(c.width), h: Math.round(c.height),
          norte: b.getNorth(), sul: b.getSouth(),
          leste: b.getEast(), oeste: b.getWest()};
}"""


@pytest.fixture
def mapa(pagina):
    pg, base = pagina

    def rota(r):
        u = r.request.url
        corpo = USUARIO if "/api/auth/me" in u else (
            CORPO if "/api/operacao/milkrun" in u else {})
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.goto(base + "/static/index.html#milkrun")
    pg.wait_for_timeout(2000)
    return pg


def test_abrir_a_aba_ENQUADRA_a_operacao_e_nao_o_planeta(mapa):
    """O guard do defeito. Zoom 0 é o mundo; a operação está em ~100 km."""
    pg = mapa
    pg.evaluate("() => abaTrocar('milkrun','mapa')")
    pg.wait_for_timeout(1200)
    e = pg.evaluate(_ESTADO)
    assert e, "o mapa nem foi criado"
    assert e["w"] > 200 and e["h"] > 100, ("o container nao ganhou tamanho: %r" % e)
    assert e["zoom"] >= 7, (
        "o mapa abriu no zoom %s — com 0 ele mostra o planeta inteiro, que foi "
        "exatamente o defeito de 10/09/2026" % e["zoom"])
    # E O ENQUADRAMENTO TEM DE SER APERTADO, nao apenas conter os pontos.
    #
    # A primeira versao deste guard exigia so que a janela fosse menor que 6
    # graus, e ele PASSOU COM A CORRECAO SABOTADA: sem enquadrar, o mapa fica
    # no zoom 7 do `setView` inicial, centrado em -23,6/-46,7 — que por acaso
    # cobre esta operacao. Verde que nunca ficaria vermelho nao conferiu nada.
    #
    # O que discrimina e o APERTO: enquadrado, a janela e ~2x o tamanho da
    # operacao; no zoom inicial ela e ~4x. A regua e relativa aos pontos, e nao
    # um numero absoluto que eu teria escolhido a olho.
    lat = [p[2] for p in _PTS]
    alcance = max(lat) - min(lat)
    janela = e["norte"] - e["sul"]
    assert janela <= alcance * 3, (
        "a janela cobre %.2f graus para uma operacao de %.2f (%.1fx) — o mapa "
        "nao enquadrou, ficou no zoom inicial" % (janela, alcance, janela / alcance))


def test_todas_as_paradas_cabem_na_area_visivel(mapa):
    """Enquadrar e enquadrar TUDO: parada fora da área é parada que ninguém vê,
    e num milk run a que falta é justamente a que interessa."""
    pg = mapa
    pg.evaluate("() => abaTrocar('milkrun','mapa')")
    pg.wait_for_timeout(1200)
    e = pg.evaluate(_ESTADO)
    for p in _PTS:
        _nome, _cid, la, lo = p[0], p[1], p[2], p[3]
        assert e["sul"] <= la <= e["norte"], ("%s ficou fora no eixo N-S" % _nome)
        assert e["oeste"] <= lo <= e["leste"], ("%s ficou fora no eixo L-O" % _nome)


def test_com_a_aba_ESCONDIDA_o_mapa_NAO_se_enquadra(mapa):
    """A outra metade da regra, e a que explica o defeito.

    Enquadrar é MEDIR, e não dá para medir o que não tem tamanho. Com a aba
    escondida o contêiner é 0x0 e qualquer `fitBounds` ali devolve zoom 0 —
    que é o estado que ficava congelado até alguém mexer no mapa. O correto é
    não tentar: o zoom fica o do `setView` inicial, e o enquadramento acontece
    quando a aba abre.
    """
    pg = mapa
    e = pg.evaluate(_ESTADO)
    assert e, "o mapa nem foi criado"
    assert e["w"] == 0 and e["h"] == 0, (
        "a aba do mapa deixou de nascer escondida — este guard mede o caso "
        "oposto e precisa ser revisto junto")
    assert e["zoom"] >= 7, (
        "enquadrou com o container em 0x0 e voltou zoom %s" % e["zoom"])
