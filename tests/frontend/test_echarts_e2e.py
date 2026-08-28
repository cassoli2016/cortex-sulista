"""ECharts no CÓRTEX — carga sob demanda e o gráfico da Produtividade.

O que se protege:

1. **990 KB não podem pesar nas 62 telas que não usam gráfico de biblioteca.**
   A promessa do carregamento sob demanda só vale se alguém conferir que a
   Visão Geral não baixa o arquivo.
2. **A biblioteca não pode nos fazer perder o que os gráficos à mão já
   garantiam**: mês parcial hachurado e rótulo direto na linha. Trocar a
   ferramenta e perder a regra seria a pior parte do negócio.
3. **Falha de carga é dita, não escondida.** O arquivo vem do nosso disco: se
   sumir, é deploy quebrado, e um cartão vazio faria parecer "sem viagem no
   período".
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

PAYLOAD = {
    "kpis": {"veiculos": 3, "viagens": 10, "km_carregado": 30000.0,
             "km_vazio": 6000.0, "receita": 90000.0, "km_total": 36000.0,
             "retorno_vazio": 0.1667, "rkm": 3.0, "km_por_veiculo": 10000.0,
             "receita_por_veiculo": 30000.0, "frota_ociosa_base": 10,
             "ociosos": 1, "nunca_rodaram": 0, "ociosidade": 0.1},
    # mai é cortado pelo filtro (dt_de = 15/05) e ago é o corrente: os DOIS
    # têm de sair hachurados
    "mensal": [
        {"mes": "2026-05", "veiculos": 2, "km_carregado": 4000.0,
         "km_vazio": 500.0, "receita": 9000.0},
        {"mes": "2026-06", "veiculos": 3, "km_carregado": 13000.0,
         "km_vazio": 2500.0, "receita": 40000.0},
        {"mes": "2026-08", "veiculos": 3, "km_carregado": 13000.0,
         "km_vazio": 3000.0, "receita": 41000.0},
    ],
    "modalidades": [], "veiculos": [], "veiculos_total": 0,
    "ociosos": [], "nunca_rodaram": [],
    "filtros": {"filial": None, "dt_de": "2026-05-15", "dt_ate": "2026-08-27",
                "modalidade": None},
    "fonte": "AVA", "ts": "2026-08-27T21:00:00",
}


def _abrir(pg, base_url, hash_tela, *, quebrar_vendor=False):
    baixados = []

    def rota_api(route):
        u = route.request.url
        corpo = (ADMIN if "/api/auth/me" in u
                 else PAYLOAD if "produtividade-veiculos" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    def rota_vendor(route):
        baixados.append(route.request.url)
        if quebrar_vendor:
            route.fulfill(status=404, body="")
        else:
            route.continue_()

    pg.route("**/api/**", rota_api)
    pg.route("**/vendor/echarts.min.js", rota_vendor)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#{hash_tela}")
    return baixados, erros


def test_a_visao_geral_NAO_baixa_a_biblioteca(pagina):
    """990 KB numa tela que não desenha gráfico de biblioteca é 990 KB de
    conta de outra pessoa."""
    pg, base = pagina
    baixados, erros = _abrir(pg, base, "home")
    pg.wait_for_timeout(1500)
    assert baixados == [], f"a Visão Geral baixou o echarts: {baixados}"
    assert erros == []


def test_a_produtividade_baixa_a_biblioteca_e_desenha(pagina):
    pg, base = pagina
    baixados, erros = _abrir(pg, base, "prodveic")
    pg.wait_for_selector("#chartProd svg", timeout=20000)
    assert len(baixados) == 1, f"esperava UMA carga, veio {len(baixados)}"
    assert erros == []
    # o gráfico desenhou de verdade: uma barra por mês
    assert pg.locator("#chartProd svg path").count() > 3


def test_mes_parcial_sai_HACHURADO(pagina):
    """Regra mais antiga dos painéis desta casa: mês cortado pelo filtro ou
    corrente com barra cheia mente sobre a queda. O `decal` do ECharts faz o
    papel do `<pattern>` que o SVG à mão desenhava."""
    pg, base = pagina
    _abrir(pg, base, "prodveic")
    pg.wait_for_selector("#chartProd svg", timeout=20000)
    pg.wait_for_timeout(400)
    svg = pg.inner_html("#chartProd")
    assert "pattern" in svg.lower(), "nenhuma hachura no gráfico"
    # o eixo marca os dois meses parciais
    assert svg.count("parcial") >= 2


def test_a_linha_tem_ROTULO_DIRETO(pagina):
    """Ela vive num segundo eixo com escala própria; sem o número em cima do
    ponto o leitor não tem como ler valor nenhum."""
    pg, base = pagina
    _abrir(pg, base, "prodveic")
    pg.wait_for_selector("#chartProd svg", timeout=20000)
    pg.wait_for_timeout(400)
    txt = pg.inner_text("#chartProd")
    for veiculos in ("2", "3"):
        assert veiculos in txt


def test_falha_ao_carregar_a_biblioteca_e_DITA(pagina):
    """Cartão vazio faria parecer 'sem viagem no período'. O arquivo vem do
    nosso disco: se sumiu, é deploy quebrado, e isso se diz."""
    pg, base = pagina
    _abrir(pg, base, "prodveic", quebrar_vendor=True)
    pg.wait_for_timeout(2500)
    txt = pg.inner_text("#chartProd")
    assert "não foi possível carregar" in txt.lower()
    assert "tabelas abaixo continuam corretos" in txt.lower()


def test_o_arquivo_da_biblioteca_esta_no_repositorio():
    """Vendorizado, nunca CDN: o painel roda atrás do túnel e não pode
    depender de host externo em tempo de execução."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[2]
    lib = raiz / "api" / "static" / "vendor" / "echarts.min.js"
    lic = raiz / "api" / "static" / "vendor" / "echarts-LICENSE.txt"
    assert lib.exists() and lib.stat().st_size > 500_000
    assert lic.exists(), "a Apache 2.0 exige distribuir a licença junto"
    html = (raiz / "api" / "static" / "index.html").read_text(encoding="utf-8")
    assert "cdn.jsdelivr" not in html and "cdn.amcharts" not in html
    assert "/static/vendor/echarts.min.js" in html
