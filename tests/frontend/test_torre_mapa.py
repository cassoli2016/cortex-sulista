"""O mapa da Torre carrega — e por que ele passou meses quebrado sem ninguém ver.

O DEFEITO
=========
`let leafletPromise = null, torreMap = null, torreLayer = null;` era UMA linha,
e ela sumiu na v0.144.0, num corte da conversão dos gráficos para ECharts. O
mapa da Torre de Controle ficou quebrado desde então.

O SINTOMA É MUDO, e é isso que o fez durar:

1. `ensureLeaflet` **LÊ** `leafletPromise` na primeira linha. Ler nome não
   declarado é `ReferenceError`.
2. Ele estoura DENTRO do `try` de `torreMapa`, cujo `catch` escreve a mensagem
   no próprio quadro do mapa. O resultado é um retângulo cinza com
   "leafletPromise is not defined" em letra miúda — que passa por "o mapa não
   carregou hoje".
3. `node --check` passa: o código continua sintaticamente válido.
4. E a suíte não pegava porque o Leaflet vinha de **CDN** (unpkg): nenhum teste
   offline conseguia provar que o mapa carrega, então não havia teste.

`torreMap` e `torreLayer` sumiram na mesma linha e NÃO davam erro, porque só
são ATRIBUÍDOS — atribuir a nome não declarado cria global implícita. Só a
LEITURA estoura. Por isso a perda de três nomes produziu um defeito só, e o
mais difícil de rastrear.

O QUE MUDOU PARA ISTO SER TESTÁVEL
==================================
O Leaflet foi VENDORIZADO (`/static/vendor/leaflet/`), como o ECharts e pela
mesma regra: o painel roda atrás do túnel e não deve depender de host externo
em tempo de execução. O ganho de segurança veio junto com o de testabilidade —
é este arquivo.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HTML = (Path(__file__).resolve().parents[2] / "api" / "static"
        / "index.html").read_text(encoding="utf-8")

# Payload no formato REAL da Torre (274 posições e 70 viagens em produção);
# aqui bastam três, mas com TODOS os campos que o render lê — dublê pobre faz
# o render abortar antes do mapa e o teste passa sem medir nada.
TORRE = {
    "kpis": {"veiculos": 3, "em_viagem": 2, "atrasadas": 1, "sem_posicao": 0,
             "posicao_recente": 3, "viagens": 2, "km": 1200.0, "parados": 1},
    "posicoes": [
        {"placa": "ABC1D23", "utilizacao": "FROTA", "frota": "101",
         "lat": -26.30, "lng": -48.84, "posicao_em": "2026-08-30 16:00",
         "velocidade": 62, "recente": True},
        {"placa": "DEF4G56", "utilizacao": "AGREGADO", "frota": "DEF4G56",
         "lat": -25.43, "lng": -49.27, "posicao_em": "2026-08-30 15:40",
         "velocidade": 0, "recente": True},
        {"placa": "GHI7J89", "utilizacao": "LOCACAO", "frota": "205",
         "lat": -27.10, "lng": -48.60, "posicao_em": "2026-08-28 09:00",
         "velocidade": 0, "recente": False},
    ],
    "transito": [
        {"numero": 1, "filial": 1, "placa": "ABC1D23", "utilizacao": "FROTA",
         "motorista": "JOAO", "cliente": "TUPY", "origem": "JOINVILLE/SC",
         "destino": "CURITIBA/PR", "saida": "2026-08-30 08:00",
         "previsao_chegada": "2026-08-30 18:00", "atrasada": False,
         "vazio": False, "km": 130.0, "valorfrete": 1200.0},
        {"numero": 2, "filial": 1, "placa": "DEF4G56", "utilizacao": "AGREGADO",
         "motorista": "MARIA", "cliente": "VOLVO", "origem": "CURITIBA/PR",
         "destino": "SAO PAULO/SP", "saida": "2026-08-29 06:00",
         "previsao_chegada": "2026-08-29 20:00", "atrasada": True,
         "vazio": False, "km": 400.0, "valorfrete": 3000.0},
    ],
    "atualizado_em": "2026-08-30T16:05:00",
}


def _abrir(pg, base_url):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/operacao/torre/estradas" in u:
            corpo = {"configurado": True, "trechos": [], "resumo": {}}
        elif "/api/operacao/torre" in u:
            corpo = TORRE
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#torre")
    # state="attached": wait_for_selector espera VISIBILIDADE por padrão, e o
    # painel de tiles do Leaflet é um div posicionado de tamanho ZERO — a mesma
    # armadilha que o "#loadbar[hidden]" já custou nesta casa.
    pg.wait_for_selector("#mapaTorre .leaflet-tile-pane", state="attached",
                         timeout=25000)
    pg.wait_for_timeout(600)
    return erros


# -- o que quebrou -----------------------------------------------------------


def test_as_variaveis_do_mapa_ESTAO_DECLARADAS():
    """A conferência barata, que teria evitado tudo. Ler `leafletPromise` sem
    declaração é ReferenceError — e ele é engolido pelo `catch` que escreve no
    próprio quadro do mapa."""
    assert re.search(r"^\s*let\s+leafletPromise\s*=", HTML, re.M), (
        "a declaração de leafletPromise sumiu de novo")
    for nome in ("torreMap", "torreLayer"):
        assert re.search(r"(?:let|var|const)\s+[^;\n]*\b" + nome + r"\b", HTML), nome


def test_o_leaflet_e_VENDORIZADO_e_nao_CDN():
    """A mesma regra do ECharts. O painel roda atrás do túnel; depender do
    unpkg é comprar um ponto de falha — e foi o que impediu, por meses, que
    existisse um teste provando que o mapa carrega."""
    assert "unpkg.com" not in HTML
    assert "/static/vendor/leaflet/leaflet.js" in HTML
    vendor = (Path(__file__).resolve().parents[2] / "api" / "static"
              / "vendor" / "leaflet")
    for arq in ("leaflet.js", "leaflet.css", "LICENSE.txt"):
        assert (vendor / arq).exists(), arq


# -- o comportamento ---------------------------------------------------------


def test_o_mapa_CARREGA_e_desenha_a_frota(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    assert pg.evaluate("() => typeof window.L") == "object", (
        "o Leaflet não carregou")
    assert pg.evaluate(
        "() => document.querySelectorAll('#mapaTorre .leaflet-tile').length") > 0
    marcadores = pg.evaluate(
        "() => document.querySelectorAll('#mapaTorre .leaflet-marker-icon,"
        " #mapaTorre .leaflet-interactive').length")
    assert marcadores >= len(TORRE["posicoes"]), marcadores


def test_o_quadro_do_mapa_NAO_MOSTRA_mensagem_de_erro(pagina):
    """O sintoma que durou meses: um retângulo cinza com o texto de uma
    exceção dentro, indistinguível de "hoje não carregou"."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    txt = pg.inner_text("#mapaTorre")
    for suspeita in ("is not defined", "não foi possível carregar"):
        assert suspeita not in txt, txt[:200]


def test_o_mapa_e_o_MESMO_objeto_entre_recargas(pagina):
    """`ensureLeaflet` memoiza numa Promise e `torreMap` guarda a instância: a
    recarga de 2 min não pode empilhar mapas. Sem a declaração, cada ciclo
    tentava criar tudo de novo."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    antes = pg.evaluate("() => document.querySelectorAll('#mapaTorre .leaflet-map-pane').length")
    pg.evaluate("() => window.torreMapa()")
    pg.wait_for_timeout(500)
    assert antes == 1
    assert pg.evaluate(
        "() => document.querySelectorAll('#mapaTorre .leaflet-map-pane').length") == 1
