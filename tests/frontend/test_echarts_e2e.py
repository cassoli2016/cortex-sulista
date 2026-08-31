"""ECharts no CÓRTEX — carga sob demanda e as regras que ela não dispensa.

O QUE ESTE ARQUIVO PROTEGIA MUDOU. A Visão Geral passou a desenhar com a
biblioteca, então o teste que exigia que ela NÃO a baixasse virou mentira — e
pior, passava por vacuidade: com o payload vazio do dublê os gráficos saíam
antes de chegar ao carregador, e o teste dava verde sem medir nada.

O que se protege agora:

1. **A carga continua SOB DEMANDA.** A Visão Geral baixa os 990 KB porque
   desenha com eles; uma tela que não desenha continua sem pagar por isso. É a
   diferença entre "todo mundo paga" e "quem usa paga".
2. **UMA carga serve todos os gráficos da tela.** São três na Visão Geral e
   quatro na Jornada; baixar por gráfico seria o mesmo custo várias vezes.
3. **A biblioteca não nos faz perder o que os gráficos à mão garantiam**: mês
   parcial hachurado, rótulo direto onde o número decide, unidade FINAL no
   eixo e semáforo discreto. Trocar a ferramenta e perder a regra seria a pior
   parte do negócio.
4. **Falha de carga é dita, não escondida.** O arquivo vem do nosso disco: se
   sumir, é deploy quebrado, e um cartão vazio faria parecer ausência de dado.
"""
from __future__ import annotations

import datetime as _dt
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


# Payload mínimo da Visão Geral: só o que os três gráficos consomem. Um
# dublê VAZIO faria os gráficos saírem antes do carregador e o teste passaria
# sem medir nada — foi exatamente assim que a versão anterior deste arquivo
# continuou verde depois de a tela mudar de ferramenta.
#
# O DIA VAI ALÉM DE HOJE, e isso não é detalhe: a faixa "a realizar" só existe
# quando há dia FUTURO no mês, porque o gráfico lê o relógio do navegador
# (`new Date().getDate()`). Com o `range(1, 32)` fixo que estava aqui, o
# `assert "a realizar" in dia` passava 30 dias por mês e falhava **no dia 31** —
# e falhava sem haver defeito, apontando para quem tivesse mexido na tela por
# último (custou uma bissecção alheia em 31/08/2026, que concluiu, errado, ser
# regressão da entrega de pedágio). Teste que depende do calendário é teste que
# acusa a pessoa errada uma vez por mês.
_DIA_HOJE = _dt.date.today().day
HOME = {
    "diario": [{"dia": d, "realizado": (0 if d > 20 else 40000 + d*900),
                "meta": (0 if d % 7 == 0 else 45000)}
               for d in range(1, max(32, _DIA_HOJE + 6))],
    "receita_12m": [{"mes": f"2026-{m:02d}", "receita": 9_000_000 + m*90_000}
                    for m in range(1, 9)],
    "fluxo_serie": [{"periodo": "atrasado", "saldo_projetado": 2_500_000},
                    {"periodo": "2026-09", "saldo_projetado": 1_200_000},
                    {"periodo": "2026-10", "saldo_projetado": -800_000},
                    {"periodo": "2026-11", "saldo_projetado": -2_100_000}],
}


ABA_HOME = {"#chartHdia": "dia", "#chartHrec": "fin", "#chartHsal": "fin",
            "#alerts-home": "ope"}


def _abaHome(pg, alvo):
    chave = ABA_HOME.get(alvo)
    if chave:
        pg.click("#tabhome-" + chave)
        pg.wait_for_timeout(350)   # o ResizeObserver remede no quadro seguinte


def _home(pg, base_url):
    """Abre a Visão Geral e desenha os três gráficos com o payload acima.

    As funções são chamadas DIRETO em vez de esperar o render completo da
    tela: o `renderHome` lê dezenas de escalares que não têm nada a ver com o
    que se mede aqui, e completá-los todos faria o teste falhar por causa da
    fixture, não do código.
    """
    baixados = []

    def rota_api(route):
        corpo = ADMIN if "/api/auth/me" in route.request.url else {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    def rota_vendor(route):
        baixados.append(route.request.url)
        route.continue_()

    pg.route("**/api/**", rota_api)
    pg.route("**/vendor/echarts.min.js", rota_vendor)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#home")
    pg.wait_for_timeout(600)
    for fn, campo in (("chartHomeDiario", "diario"),
                      ("chartHomeReceita", "receita_12m"),
                      ("chartHomeSaldo", "fluxo_serie")):
        r = pg.evaluate("(a) => { try { window[a[0]](a[1]); return 'ok'; }"
                        " catch(e){ return 'ERRO: ' + e.message; } }",
                        [fn, HOME[campo]])
        assert r == "ok", f"{fn}: {r}"
    # A VISAO GERAL VIROU ABAS (v0.158.0): as bandas de KPI ficaram fora (sao a
    # linha de status da empresa) e os graficos giram entre "Meta do mes",
    # "Financeiro" e "Operacao e alertas". `wait_for_selector` espera
    # VISIBILIDADE, entao nao basta o grafico existir no DOM.
    for cid in ("#chartHdia", "#chartHrec", "#chartHsal"):
        _abaHome(pg, cid)
        pg.wait_for_selector(f"{cid} svg", timeout=20000)
    pg.wait_for_timeout(300)
    return baixados, erros


def test_uma_carga_da_biblioteca_serve_os_TRES_graficos_da_visao_geral(pagina):
    """Baixar por gráfico seria pagar o mesmo custo três vezes. O
    `carregarECharts()` memoiza a promessa justamente para isso."""
    pg, base = pagina
    baixados, erros = _home(pg, base)
    assert len(baixados) == 1, f"esperava UMA carga, veio {len(baixados)}"
    assert erros == [], erros


def test_tela_SEM_grafico_de_biblioteca_continua_sem_baixar(pagina):
    """A promessa da carga sob demanda: quem não desenha não paga. Se um dia
    alguém puser uma tag <script> fixa, é aqui que aparece."""
    pg, base = pagina
    baixados, erros = _abrir(pg, base, "veic")
    pg.wait_for_timeout(1500)
    assert baixados == [], f"a tela de Veículos baixou o echarts: {baixados}"
    assert erros == []


def test_a_visao_geral_mantem_as_REGRAS_da_casa(pagina):
    """Mês parcial hachurado, rótulo direto onde o número decide, dia futuro
    sem barra de realizado e unidade FINAL no eixo. A biblioteca entrou para
    desenhar melhor, não para dispensar isto."""
    pg, base = pagina
    _home(pg, base)
    _abaHome(pg, "#chartHdia"); dia = pg.inner_text("#chartHdia")
    _abaHome(pg, "#chartHrec"); rec = pg.inner_text("#chartHrec")
    sal = pg.inner_text("#chartHsal")
    # dia futuro é marcado, e não desenhado como realizado zero
    assert "a realizar" in dia
    # rótulo direto no melhor dia e no melhor mês
    assert "R$" in dia and "R$" in rec
    # a média é dos meses FECHADOS e tem rótulo direto na linha
    assert "média" in rec
    # mês corrente hachurado (o `decal` do ECharts vira <pattern> no SVG)
    assert "pattern" in pg.inner_html("#chartHrec").lower()
    # o gap e o pior saldo são anotados no gráfico, não só no tooltip
    assert "gap" in sal and "pior" in sal
    # eixo com a unidade FINAL, nunca composta com ×1000
    assert "R$ MI" in rec.upper()


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
