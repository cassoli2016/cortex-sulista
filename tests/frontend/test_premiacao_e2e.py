"""Premiação: as sub-abas e o comparativo que compara.

O QUE ESTA TELA APRENDEU EM 30/08/2026
======================================
O comparativo mensal "estava estranho", e eram três coisas ao mesmo tempo:

1. **Cinco meses em ZERO.** Snapshots gravados por um backfill de 27/07 com
   `drivers: []` e `parcial: false` — vazios e marcados como completos. A
   Gobrax tinha os cinco meses inteiros. (Consertado no serviço, com testes em
   `tests/premiacao/test_coleta_vazia.py`.)
2. **As duas séries na MESMA escala.** "Prêmio total (R$)" e "Motoristas
   premiados" em barras agrupadas: R$ 14.864 e 43 dividindo um eixo fazem a
   segunda barra ter 0,3% da altura — um tracinho colado no zero. Premiados
   virou linha em eixo secundário, com rótulo direto.
3. **O total não é comparável entre meses.** Ele cresce porque a FROTA na
   Gobrax cresceu (8 motoristas em fevereiro contra 67 em julho). Sem o
   denominador, a leitura é "a premiação explodiu". Mesma família do "664 de
   836 rastreadores sem sinal": o número grande precisa vir com a quebra que o
   desarma.

E os parâmetros viraram aba própria — três cards de configuração, mexidos uma
vez por trimestre, ficavam empilhados entre o que se olha todo mês.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

# A frota CRESCE ao longo da série: é isso que faz o total subir, e é isso que
# o card precisa dizer. Números da produção real (fev a ago/2026).
SERIE = {"meses": [
    {"month": "2026-08", "label": "Agosto / 2026", "parcial": True,
     "regra": "nota_km", "premiados": 26, "motoristas": 100,
     "km_total": 155400.0, "premio_total": 5855.17, "pct_premiados": 26.0,
     "premio_por_motorista": 58.55, "km_por_motorista": 1554},
    {"month": "2026-07", "label": "Julho / 2026", "parcial": False,
     "regra": "nota_km", "premiados": 43, "motoristas": 67,
     "km_total": 228713.0, "premio_total": 14864.07, "pct_premiados": 64.2,
     "premio_por_motorista": 221.85, "km_por_motorista": 3414},
    {"month": "2026-02", "label": "Fevereiro / 2026", "parcial": False,
     "regra": "nota_km", "premiados": 2, "motoristas": 8,
     "km_total": 15996.0, "premio_total": 401.82, "pct_premiados": 25.0,
     "premio_por_motorista": 50.23, "km_por_motorista": 2000},
]}


# `configurado: false` esconde `#prem-conteudo` inteiro — e com ele as abas.
# Um dublê vazio faria TODO teste desta tela passar por vacuidade, que é
# exatamente como o teste anterior do ECharts ficou verde depois de a Visão
# Geral mudar de ferramenta.
PAINEL = {
    "configurado": True, "month": "2026-08", "parcial": True,
    "coletado_em": "2026-08-30T11:34:20", "aviso": None, "regra": "nota_km",
    "index": [{"month": m["month"], "label": m["label"],
               "drivers": m["motoristas"], "parcial": m["parcial"]}
              for m in SERIE["meses"]],
    "params": {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0},
    "linhas": [{"driverId": 1, "nome": "GABRIEL", "nota": 91.0, "km": 5200.0,
                "premio": 473.2, "elegivel": True}],
    "kpis": {"premio_total": 5855.17, "premiados": 26, "motoristas": 100,
             "km_total": 155400.0},
    "frota_telemetria": {"veiculos": 98, "cadastrados": 135,
                         "com_motorista": 100},
    "referencias": {},
}


def _abrir(pg, base_url):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/frota/premiacao/serie" in u:
            corpo = SERIE
        elif "/api/frota/premiacao" in u:
            corpo = PAINEL
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#prem")
    pg.wait_for_timeout(700)
    return erros


# -- as sub-abas -------------------------------------------------------------


def test_abre_na_PREMIACAO_e_a_configuracao_comeca_escondida(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    assert pg.is_visible("#aba-prem"), "a aba da premiação tem de nascer aberta"
    assert not pg.is_visible("#aba-cfg")
    assert pg.get_attribute("#tabprem-prem", "aria-selected") == "true"
    assert pg.get_attribute("#tabprem-cfg", "aria-selected") == "false"


def test_a_aba_da_premiacao_nasce_aberta_PORQUE_e_ela_que_tem_grafico(pagina):
    """Não é preferência: o ECharts mede o contêiner UMA VEZ, no `init`, e uma
    medida feita com a aba escondida vale zero para sempre — o gráfico aparece
    com os eixos certos e quase todos os rótulos do eixo X suprimidos. Quem
    tem gráfico abre visível; quem tem só formulário e tabela pode esperar."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.query_selector("#aba-prem #chartPrem") is not None
    assert pg.query_selector("#aba-cfg #chartPrem") is None


def test_trocar_de_aba_mostra_a_configuracao_e_esconde_o_resto(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#tabprem-cfg")
    assert pg.is_visible("#aba-cfg")
    assert not pg.is_visible("#aba-prem")
    assert pg.is_visible("#prem-cfg-params"), "os parâmetros por eixo têm de estar na aba"
    assert pg.get_attribute("#tabprem-cfg", "aria-selected") == "true"
    pg.click("#tabprem-prem")
    assert pg.is_visible("#aba-prem")


def test_NAO_existe_mais_o_formulario_de_parametro_solto(pagina):
    """Havia DOIS editores para as mesmas três chaves — um gravando um arquivo
    que o cálculo deixou de ler. Formulário que diz "salvo" e não muda o
    prêmio é pior que formulário que falta."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    for velho in ("#fPremValorKm", "#fPremNotaMin", "#fPremKmMin",
                  "#btnPremSalvar"):
        assert pg.query_selector(velho) is None, velho + " devia ter saído com o card"


# -- o comparativo -----------------------------------------------------------


def _desenhar(pg):
    return pg.evaluate(
        "(d) => { try { window.DATAPREM = {configurado:true};"
        " window.premRenderSerie(d); return 'ok'; }"
        " catch(e){ return 'ERRO: ' + e.message; } }", SERIE)


def test_o_comparativo_desenha_com_DUAS_ESCALAS(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert _desenhar(pg) == "ok"
    pg.wait_for_selector("#chartPrem svg", timeout=20000)
    op = pg.evaluate(
        "() => { const el=document.getElementById('chartPrem');"
        " const i=window.echarts.getInstanceByDom(el).getOption();"
        " return {tipos:i.series.map(s=>s.type),"
        "         eixos:i.series.map(s=>s.yAxisIndex||0),"
        "         nEixos:i.yAxis.length}; }")
    assert op["tipos"] == ["bar", "line"], (
        "premiados em BARRA na mesma escala do prêmio dá 0,3% de altura: "
        + str(op["tipos"]))
    assert op["eixos"] == [0, 1], "a linha tem de viver no eixo secundário"
    assert op["nEixos"] == 2


def test_a_linha_do_eixo_escondido_tem_ROTULO_DIRETO(pagina):
    """Eixo secundário oculto sem rótulo no ponto deixa o leitor sem forma
    nenhuma de ler o valor — é a regra mais repetida dos painéis da casa."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert _desenhar(pg) == "ok"
    pg.wait_for_selector("#chartPrem svg", timeout=20000)
    mostra = pg.evaluate(
        "() => { const el=document.getElementById('chartPrem');"
        " const s=window.echarts.getInstanceByDom(el).getOption().series[1];"
        " return !!(s.label && s.label.show); }")
    assert mostra, "a linha de % premiados precisa do rótulo direto"


def test_o_mes_PARCIAL_sai_hachurado(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert _desenhar(pg) == "ok"
    pg.wait_for_selector("#chartPrem svg", timeout=20000)
    n = pg.evaluate(
        "() => { const el=document.getElementById('chartPrem');"
        " const d=window.echarts.getInstanceByDom(el).getOption().series[0].data;"
        " return d.filter(x => x.itemStyle && x.itemStyle.decal).length; }")
    esperado = sum(1 for m in SERIE["meses"] if m["parcial"])
    assert n == esperado, (
        str(esperado) + " mês parcial na série, " + str(n) + " hachurado(s) — "
        "barra cheia num mês em coleta lê-se como queda")


def test_o_rodape_DIZ_que_parte_da_alta_e_cobertura(pagina):
    """O número que desarma o número: entre fevereiro e julho a base foi de 8
    para 67 motoristas. Sem isso, a série lê-se como premiação explodindo."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert _desenhar(pg) == "ok"
    txt = pg.inner_text("#prem-comp-premios")
    assert "8" in txt and "67" in txt, txt
    assert "COBERTURA" in txt.upper(), txt
    plano = txt.replace(" ", " ").replace(" ", " ")
    assert "50" in plano and "222" in plano and "→" in plano, (
        "o por-motorista é o que compara entre meses: " + plano)


def test_serie_VAZIA_diz_isso_em_vez_de_ficar_em_branco(pagina):
    """O contêiner virou <div> na conversão para ECharts, e o estado vazio
    ainda mexia em `viewBox` e injetava `<text>` solto — não desenhava NADA."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    r = pg.evaluate(
        "() => { try { window.DATAPREM={configurado:true};"
        " window.premRenderSerie({meses:[]}); return 'ok'; }"
        " catch(e){ return 'ERRO: '+e.message; } }")
    assert r == "ok"
    assert "nenhum mês coletado" in pg.inner_text("#chartPrem")
