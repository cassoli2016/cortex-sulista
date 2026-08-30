"""Sub-abas: painel de BI cabe em UMA tela.

A REGRA (usuário, 30/08/2026)
=============================
Painel de BI é visual e cabe numa tela só. O que não couber vai para **aba**,
nunca para o fim da rolagem — e o gráfico é sempre ECharts.

Painel que rola é painel que ninguém lê inteiro, e esta casa já produziu página
de 16.000px (CRM) e de 8.602px (Custos). Aba, e não tela nova, porque o RBAC,
os filtros e o estado são os mesmos: duas telas dividiriam um estado que é um
só — foi por isso que a Premiação virou duas abas em vez de duas entradas de
menu.

O QUE ESTES TESTES GUARDAM
==========================
1. **A aba que tem GRÁFICO nasce aberta.** O ECharts mede o contêiner uma vez,
   no `init`, e medida feita sob `hidden` vale zero para sempre — o gráfico
   aparece com os eixos certos e quase todos os rótulos do eixo X suprimidos
   pelo `hideOverlap`. Não dá erro, não fica vazio: fica errado em silêncio.
2. **Nenhum card se perde na divisão.** Cortar tela por marcador já apagou 20
   rotas, o `loadHc` e o `loadMvb` nesta casa; aqui a conferência é a contagem
   de títulos.
3. **O contador na aba diz o que tem lá dentro** sem obrigar o clique — uma
   aba "Ociosidade" vazia e uma com 24 veículos parados pedem coisas
   diferentes de quem olha.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HTML = (Path(__file__).resolve().parents[2] / "api" / "static"
        / "index.html").read_text(encoding="utf-8")

PROD = {
    "kpis": {"veiculos": 3, "viagens": 40, "km_carregado": 120000.0,
             "km_vazio": 30000.0, "receita": 360000.0, "km_total": 150000.0,
             "retorno_vazio": 0.20, "rkm": 3.0, "km_por_veiculo": 40000.0,
             "receita_por_veiculo": 120000.0, "frota_ociosa_base": 10,
             "ociosos": 2, "nunca_rodaram": 1, "ociosidade": 0.2},
    "mensal": [{"mes": "2026-06", "veiculos": 3, "km_carregado": 60000.0,
                "km_vazio": 15000.0, "receita": 180000.0},
               {"mes": "2026-07", "veiculos": 3, "km_carregado": 60000.0,
                "km_vazio": 15000.0, "receita": 180000.0}],
    "modalidades": [{"modalidade": "FROTA", "veiculos": 3, "viagens": 40,
                     "km_carregado": 120000.0, "km_vazio": 30000.0,
                     "retorno_vazio": 0.2, "receita": 360000.0, "rkm": 3.0}],
    "veiculos": [{"placa": "ABC1D23", "modalidade": "FROTA", "viagens": 20,
                  "dias_ativos": 40, "km_carregado": 60000.0,
                  "km_por_dia_ativo": 1500.0, "retorno_vazio": 0.2,
                  "receita": 180000.0, "rkm": 3.0}],
    "veiculos_total": 37,
    "ociosos": [{"placa": "XYZ4E56", "modalidade": "FROTA", "dias_parado": 200,
                 "ultima_viagem": "2026-01-10", "viagens_historicas": 310}],
    "nunca_rodaram": [{"placa": "QRS7F89", "modalidade": "LOCACAO",
                       "tipo": "CAVALO"}],
    "filtros": {"filial": None, "dt_de": "2026-06-01", "dt_ate": "2026-07-31",
                "modalidade": None},
    "fonte": "AVA", "ts": "2026-08-30T11:00:00",
}


def _abrir(pg, base_url):
    def rota(route):
        u = route.request.url
        corpo = (ADMIN if "/api/auth/me" in u
                 else PROD if "produtividade-veiculos" in u else {})
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#prodveic")
    pg.wait_for_selector("#kpis-prodveic .kpi", timeout=20000)
    return erros


# -- a divisão não perde nada -----------------------------------------------


def _cards(bloco):
    return re.findall(r"<h2>([^<]+)", bloco)


def test_os_seis_cards_continuam_na_tela():
    """A divisão em abas é RECORTE, não reescrita. Se um card sumir aqui, o
    dado sumiu do painel sem ninguém perceber — o modo como esta casa já
    perdeu 20 rotas e duas funções de carga num corte por marcador."""
    i = HTML.index('<section class="view" id="view-prodveic">')
    j = HTML.index('<section class="view" id="view-km">', i)
    titulos = [t.split("<")[0].strip() for t in _cards(HTML[i:j])]
    esperados = {"Km carregado e veículos ativos por mês",
                 "Produtividade por modalidade", "Produtividade por veículo",
                 "Parados no período", "Nunca rodaram — cadastro a conferir",
                 "Alertas"}
    assert esperados <= set(titulos), esperados - set(titulos)


def test_a_aba_com_GRAFICO_e_a_que_nasce_aberta():
    """Regra dura: painel novo que puser o gráfico numa aba escondida terá um
    gráfico com os rótulos do eixo X suprimidos, sem erro nenhum aparecer."""
    for grupo, com_grafico in (("prod", "vis"), ("prem", "prem")):
        aberta = re.findall(
            r'<div class="aba" data-abas="' + grupo + r'" data-aba="(\w+)"'
            r'(?![^>]*\bhidden\b)[^>]*>', HTML)
        assert aberta == [com_grafico], (grupo, aberta)


# -- o comportamento --------------------------------------------------------


def test_abre_na_visao_geral_com_o_grafico_visivel(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    assert pg.is_visible("#aba-prod-vis")
    assert not pg.is_visible("#aba-prod-veic")
    assert not pg.is_visible("#aba-prod-ocio")
    pg.wait_for_selector("#chartProd svg", timeout=20000)


def test_o_grafico_e_medido_com_LARGURA_DE_VERDADE(pagina):
    """O sintoma de medir sob `hidden` não é erro nem cartão vazio: é uma série
    de vários pontos mostrando um rótulo só. Medir a largura do SVG é o jeito
    direto de provar que não aconteceu."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.wait_for_selector("#chartProd svg", timeout=20000)
    largura = pg.evaluate(
        "() => document.querySelector('#chartProd svg').getBoundingClientRect().width")
    assert largura > 300, largura


def test_trocar_de_aba_mostra_uma_e_esconde_as_outras(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabProd-veic")
    assert pg.is_visible("#aba-prod-veic") and not pg.is_visible("#aba-prod-vis")
    assert pg.get_attribute("#tabProd-veic", "aria-selected") == "true"
    assert pg.get_attribute("#tabProd-vis", "aria-selected") == "false"
    pg.click("#tabProd-ocio")
    assert pg.is_visible("#aba-prod-ocio") and not pg.is_visible("#aba-prod-veic")


def test_o_contador_da_aba_diz_o_tamanho_do_assunto(pagina):
    """Veículos: o TOTAL, não o tamanho do recorte da tabela — quem olha a aba
    quer o tamanho do assunto. Ociosidade: parados + nunca rodaram, que é a
    fila de trabalho de quem abre."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.inner_text("#abanProdVeic").strip() == str(PROD["veiculos_total"])
    esperado = len(PROD["ociosos"]) + len(PROD["nunca_rodaram"])
    assert pg.inner_text("#abanProdOcio").strip() == str(esperado)


def test_contador_ZERO_fica_em_branco(pagina):
    """Aba vazia não precisa chamar atenção — um "0" de destaque na aba é
    ruído com cara de número."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.evaluate("() => window.abaContador('abanProdOcio', 0)")
    assert not pg.is_visible("#abanProdOcio")


def test_a_premiacao_usa_a_MESMA_funcao(pagina):
    """Dois mecanismos de aba divergem no dia em que um deles ganhar um
    ajuste. `premAba` saiu; quem troca aba em qualquer painel é `abaTrocar`."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.evaluate("() => typeof window.abaTrocar") == "function"
    assert pg.evaluate("() => typeof window.premAba") == "undefined"
