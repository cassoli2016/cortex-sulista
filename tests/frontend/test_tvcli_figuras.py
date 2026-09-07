# -*- coding: utf-8 -*-
"""As figuras e a PAREDE do painel de TV do cliente, EXECUTADAS.

Este arquivo nasceu para o medidor de freetime e a rosca por etapa. Os dois
saíram em 07/09/2026 — o freetime porque é métrica de COBRANÇA e estava num
mural que o cliente lê (ela continua nas telas `sac` e `cliop`, que são de
análise), e a rosca porque repartia as cargas exatamente nos três números que
os chips do herói já mostravam ao lado dela. Os guards deles saíram junto: um
guard que protege função que não existe mais é ruído verde.

O que ficou é a regra que os criou, e ela vale mais que qualquer um deles: as
funções são CHAMADAS no navegador e o que se afirma é o que SAI. Os primeiros
testes desta tela liam o TEXTO-FONTE do `index.html` — "o `path` está lá" — e
continuavam verdes com a função sabotada, porque código morto continua escrito
no arquivo.

E entrou uma classe nova, que o print da parede em produção obrigou: **guard de
GEOMETRIA**. Metade dos defeitos deste painel não eram de dado — eram um terço
da TV vazio, uma lista passando por cima do rodapé e uma linha da tabela
cortada ao meio pelo `overflow` do cartão. Nenhum deles quebra teste de valor
nenhum, e todos são visíveis do outro lado da sala.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _monta(pg, base_url, chamada):
    """Carrega o app e executa uma das funções de desenho da TV."""
    pg.goto(f"{base_url}/static/index.html")
    pg.wait_for_function("() => typeof tvCliBarras === 'function'", timeout=15000)
    return pg.evaluate(f"() => {chamada}")


# --------------------------------------------------------------- as barras

def test_as_barras_saem_na_proporcao_do_maior_mes(pagina):
    """A altura é do valor contra o MAIOR mês, e a leitura é comparativa: numa
    parede ninguém lê o eixo, lê qual coluna é mais alta."""
    pg, base = pagina
    html = _monta(pg, base, """tvCliBarras([
        {mes:'2026-07', cargas:300, parcial:false},
        {mes:'2026-08', cargas:600, parcial:false},
        {mes:'2026-09', cargas:150, parcial:true}])""")
    # A ESCALA PARA EM 86%: o valor de cada mes flutua ACIMA da barra, e uma
    # barra de 100% empurraria o numero para fora da area de desenho.
    alturas = [float(h) for h in re.findall(r'height:([\d.]+)%', html)]
    assert alturas == [43.0, 86.0, 21.5], alturas


def test_o_mes_PARCIAL_sai_hachurado(pagina):
    """Mês corrente hachurado, como em toda série da casa: sem isso a última
    coluna despenca todo dia 1º e alguém lê queda de demanda onde só há mês
    pela metade."""
    pg, base = pagina
    html = _monta(pg, base, """tvCliBarras([
        {mes:'2026-08', cargas:600, parcial:false},
        {mes:'2026-09', cargas:150, parcial:true}])""")
    barras = re.findall(r'class="(bar[^"]*)"', html)
    assert barras[0] == "bar", barras
    assert "par" in barras[1], ("o mês parcial não saiu hachurado: %s" % barras)


def test_mes_SEM_CARGA_continua_no_desenho(pagina):
    """O intervalo é GERADO pelo servidor, não colhido: mês sem carga é uma
    coluna de altura zero, e não um buraco que faria abril emendar em agosto.
    O rótulo do mês tem de continuar lá."""
    pg, base = pagina
    html = _monta(pg, base, """tvCliBarras([
        {mes:'2026-04', cargas:200, parcial:false},
        {mes:'2026-05', cargas:0,   parcial:false},
        {mes:'2026-06', cargas:100, parcial:false}])""")
    assert html.count("tvc-col") == 3, "sumiu o mês vazio"
    assert "mai" in html, "o rótulo do mês vazio sumiu"
    alturas = [float(h) for h in re.findall(r'height:([\d.]+)%', html)]
    assert alturas[1] == 0.0, alturas


def test_mes_com_UMA_carga_nao_se_confunde_com_mes_zerado(pagina):
    """Piso de 2%: uma barra de meio pixel se lê como ausência, e "1 carga" e
    "nenhuma carga" são respostas diferentes para o cliente."""
    pg, base = pagina
    html = _monta(pg, base, """tvCliBarras([
        {mes:'2026-04', cargas:900, parcial:false},
        {mes:'2026-05', cargas:1,   parcial:false},
        {mes:'2026-06', cargas:0,   parcial:false}])""")
    alturas = [float(h) for h in re.findall(r'height:([\d.]+)%', html)]
    assert alturas[1] >= 2.0 > alturas[2], alturas


def test_a_linha_MEDIA_ignora_o_mes_parcial(pagina):
    """A média é de meses FECHADOS. O mês corrente tem meia coleta e entraria
    puxando a régua para baixo — ela ficaria mais fácil de bater justamente no
    dia 1º, e a barra do parcial apareceria acima de uma média que ela mesma
    rebaixou. É a regra da casa para toda média de referência.

    300 e 600 fechados dão 450; incluindo o parcial de 30 dariam 310.
    """
    pg, base = pagina
    html = _monta(pg, base, """tvCliBarras([
        {mes:'2026-07', cargas:300, parcial:false},
        {mes:'2026-08', cargas:600, parcial:false},
        {mes:'2026-09', cargas:30,  parcial:true}])""")
    assert "média 450" in html, html
    # e ela é posicionada na MESMA escala das barras (86% = o maior mês)
    bottom = float(re.search(r'tvc-media" style="bottom:([\d.]+)%', html).group(1))
    assert abs(bottom - 86.0 * 450 / 600) < 0.2, bottom


def test_sem_mes_fechado_nao_ha_linha_media(pagina):
    """Média de um mês pela metade não é média de nada — melhor sem régua do
    que com uma régua que o próprio dado desmente."""
    pg, base = pagina
    html = _monta(pg, base,
                  "tvCliBarras([{mes:'2026-09', cargas:30, parcial:true}])")
    assert "tvc-media" not in html, html


def test_as_rotas_tem_titulo_de_coluna(pagina):
    """Pedido de quem lê a parede: sem cabeçalho o número da direita era um
    número solto — podia ser carga, tonelada ou real."""
    pg, base = pagina
    html = _monta(pg, base, "tvCliRotas([{rota:'A → B', cargas:10}])")
    assert "tvc-rotas-h" in html and ">Rota<" in html and ">Cargas<" in html


def test_sem_historico_a_figura_DIZ_isso(pagina):
    """Cartão vazio numa parede se lê como tela quebrada."""
    pg, base = pagina
    assert "sem histórico" in _monta(pg, base, "tvCliBarras([])")


# ---------------------------------------------------------------- as rotas

def test_a_rota_maior_enche_a_barra_e_as_outras_sao_proporcionais(pagina):
    pg, base = pagina
    html = _monta(pg, base, """tvCliRotas([
        {rota:'A → B', cargas:1000}, {rota:'C → D', cargas:500},
        {rota:'E → F', cargas:250}])""")
    larguras = [float(w) for w in re.findall(r'width:([\d.]+)%', html)]
    assert larguras == [100.0, 50.0, 25.0], larguras


def test_a_lista_de_rotas_para_em_CINCO(pagina):
    """Numa parede a lista é referência. O contador de "5 de N" é do cartão,
    e o guard dele está no teste de parede."""
    pg, base = pagina
    html = _monta(pg, base, "tvCliRotas(" + json.dumps(
        [{"rota": "R%d" % i, "cargas": 100 - i} for i in range(9)]) + ")")
    # `class="tvc-rota"` com as aspas: `tvc-rota` cru casa tambem com o
    # `tvc-rotas-h` do cabecalho, e o guard contaria seis achando que conta
    # cinco -- um verde que passaria com SEIS rotas na parede.
    assert html.count('class="tvc-rota"') == 5, html


# ------------------------------------------------------- há quanto tempo

def test_acima_de_24h_NAO_vira_numero(pagina):
    """O teto físico de 24h é a mesma régua do SAC/Freetime e do portal: acima
    disso é apontamento atravessando dias, não veículo parado. Dizer "há 73h"
    seria número inventado com cara de medição."""
    pg, base = pagina
    velho = (datetime.now() - timedelta(hours=73)).strftime("%Y-%m-%d %H:%M")
    r = _monta(pg, base, "tvCliDesde('%s')" % velho)
    assert r["txt"] == "mais de 24h" and r["acima"] is True, r


def test_abaixo_de_uma_hora_sai_em_MINUTOS(pagina):
    pg, base = pagina
    ha = (datetime.now() - timedelta(minutes=36)).strftime("%Y-%m-%d %H:%M")
    r = _monta(pg, base, "tvCliDesde('%s')" % ha)
    assert r["txt"].endswith("min") and r["acima"] is False, r
    assert 35 <= int(r["txt"].split()[0]) <= 37, r


def test_apontamento_ilegivel_nao_vira_zero(pagina):
    """`null` é "não sei há quanto tempo", e a carga sai da lista — nunca vira
    "há 0 min", que se lê como veículo que acabou de chegar."""
    pg, base = pagina
    assert _monta(pg, base, "tvCliDesde('')") is None
    assert _monta(pg, base, "tvCliDesde('nao-e-data')") is None


# ------------------------------------------------------------- a PAREDE

_AGORA = datetime.now()


def _dt(h):
    return (_AGORA + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M")


_CARGAS = [
    {"coleta": 19900 + i, "emissao": "2026-09-07", "origem": "JOINVILLE",
     "uf_origem": "SC", "destino": "SAO JOSE DOS PINHAIS", "uf_destino": "PR",
     "placa": "APJ6E4%d" % i, "marco": "Em viagem", "marco_cod": 400,
     "marco_em": _dt(-6), "eta": _dt(h), "eta_amostras": 40}
    for i, h in enumerate([-1.4, 0.6, 2.1, 4.8, 7.2, 26.0])
] + [
    # A CAMINHO E SEM ESTIMATIVA: rota sem histórico não tem mediana, e é ela
    # que faz a cobertura do cartão valer alguma coisa ("6 de 7").
    {"coleta": 19950, "emissao": "2026-09-07", "origem": "CASCAVEL",
     "uf_origem": "PR", "destino": "GOIANIA", "uf_destino": "GO",
     "placa": "MIP1G96", "marco": "Saída do carregamento", "marco_cod": 395,
     "marco_em": _dt(-3), "eta": None, "eta_amostras": None},
] + [
    {"coleta": 16020 + i, "emissao": "2026-09-07", "origem": "CURITIBA",
     "uf_origem": "PR", "destino": "BETIM", "uf_destino": "MG",
     "placa": "BQR7C1%d" % i, "marco": rot, "marco_cod": cod,
     "marco_em": _dt(h), "eta": None, "eta_amostras": None}
    for i, (cod, rot, h) in enumerate([
        (394, "Chegada para carregamento", -2.4),
        (398, "Aguardando carregamento", -5.7),
        (396, "Chegada para descarga", -0.6),
        (399, "Aguardando descarga", -30.0)])
]

_MESES = [{"mes": m, "cargas": c, "parcial": m == "2026-09"} for m, c in [
    ("2025-10", 512), ("2025-11", 488), ("2025-12", 402), ("2026-01", 455),
    ("2026-02", 431), ("2026-03", 566), ("2026-04", 590), ("2026-05", 612),
    ("2026-06", 574), ("2026-07", 641), ("2026-08", 668), ("2026-09", 138)]]


def _corpo(url: str) -> dict:
    if "/api/auth/me" in url:
        return ADMIN
    if "/api/portal/cliente" in url:
        selo = {"travado": False, "cliente_raiz": "12345678",
                "cliente_nome": "CLIENTE DE TESTE"}
        if "aba=permanencia" in url:
            return {**selo, "carga": {"mediana_h": 3.1},
                    "descarga": {"mediana_h": 2.5}, "freetime": {},
                    "cargas_no_periodo": 32}
        if "aba=historico" in url:
            return {**selo, "meses": _MESES,
                    "rotas": [{"rota": "A → B", "cargas": 900 - 100 * i}
                              for i in range(7)],
                    "rotas_mostradas": 7, "rotas_total": 25,
                    "cargas_nas_rotas_mostradas": 6134, "cargas_total": 7352}
        return {**selo, "cargas": _CARGAS, "em_curso": len(_CARGAS),
                "sem_apontamento": 0, "concluidas_na_janela": 758,
                "janela_dias": 45,
                "posicao": {"com_posicao": 9, "frescas": 8, "veiculos": 11,
                            "fresca_ate_min": 120, "lista": []}}
    if "/api/tv/estradas" in url:
        return {"configurado": False}
    return {"kpis": {}, "resumo": {}}


def _parede(pg, base, largura=1920, altura=1080):
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_corpo(r.request.url))))
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#tvcli")
    pg.wait_for_selector("#tvcli-barras .bar", timeout=15000)
    pg.wait_for_timeout(600)
    return pg


def test_a_parede_ACOMPANHA_a_altura_da_TV(pagina):
    """UM TERÇO DA TV ESTAVA PRETO (print de 07/09/2026): as duas grades viviam
    em FLUXO e terminavam onde o conteúdo terminava. Numa parede, vazio não é
    respiro — é espaço que podia estar dizendo alguma coisa, e quem paga a TV
    está olhando para ele.

    O GUARD AFIRMA O MECANISMO, e não um percentual de ocupação que eu teria
    escolhido a olho: a grade é medida em DUAS alturas de tela, e o que se
    exige é que ela CRESÇA com a janela. Um painel em fluxo dá a mesma altura
    nas duas — e é exatamente esse o defeito. Percentual de ocupação passaria
    a depender do tamanho do cabeçalho e do ticker, e um dia falharia por um
    motivo que não é este.
    """
    pg, base = pagina
    _parede(pg, base, altura=1080)
    baixa = pg.evaluate("() => document.querySelector('.tvc-wall')"
                        ".getBoundingClientRect().height")
    pg.set_viewport_size({"width": 1920, "height": 1440})
    pg.wait_for_timeout(400)
    alta = pg.evaluate("() => document.querySelector('.tvc-wall')"
                       ".getBoundingClientRect().height")
    # 340 seria apertado demais: sobram ~22 px que NAO sao da grade (o ticker
    # e medido em `vw` e nao acompanha a altura). O que este numero precisa
    # separar e "cresce junto" de "nao cresce" -- em fluxo, o ganho e ZERO.
    assert alta - baixa >= 300, (
        "a grade cresceu só %.0f px para 360 px de tela a mais (%.0f → %.0f): "
        "ela voltou a terminar onde o conteúdo termina, e sobra parede preta"
        % (alta - baixa, baixa, alta))


def test_a_parede_nao_deixa_uma_faixa_morta_embaixo(pagina):
    """O complemento do de cima, e o que o print mostrava: entre o último
    cartão e o rodapé da tela não pode haver um vão do tamanho de um cartão."""
    pg, base = pagina
    _parede(pg, base)
    folga = pg.evaluate("""() => {
      const w = document.querySelector('.tvc-wall');
      const t = document.getElementById('tvcli-tick');
      const base = t && !t.hidden ? t.getBoundingClientRect().top
                                  : window.innerHeight;
      return base - w.getBoundingClientRect().bottom;
    }""")
    assert folga < 60, (
        "sobram %.0f px mortos abaixo da grade" % folga)


def test_a_parede_NAO_rola_nem_para_o_lado_nem_para_baixo(pagina):
    """Ninguém toca numa TV: o que não cabe simplesmente não é visto."""
    pg, base = pagina
    _parede(pg, base)
    m = pg.evaluate("() => [document.documentElement.scrollWidth,"
                    " document.documentElement.scrollHeight,"
                    " window.innerWidth, window.innerHeight]")
    assert m[0] <= m[2], "a parede empurrou a página para o lado (%s)" % m
    assert m[1] <= m[3] + 1, "a parede empurrou a página para baixo (%s)" % m


def test_nenhuma_linha_da_tabela_sai_CORTADA_do_cartao(pagina):
    """A sexta linha era renderizada e o `overflow` do cartão a cortava ao
    MEIO. Numa parede isso não se lê como lista longa — se lê como tela
    quebrada, e é o tipo de defeito que nenhum teste de valor pega."""
    pg, base = pagina
    _parede(pg, base)
    m = pg.evaluate("""() => {
      const tb = document.getElementById('tvcli-cargas');
      const card = tb.closest('.tv-card');
      const base = card.getBoundingClientRect().bottom;
      return [...tb.children].map(tr => tr.getBoundingClientRect().bottom - base);
    }""")
    assert m, "a tabela não renderizou linha nenhuma"
    assert max(m) <= 0, (
        "linha(s) da tabela ultrapassam a base do cartão em %s px" % max(m))


def test_a_lista_da_parede_DIZ_quantas_ficaram_de_fora(pagina):
    """Top-N sem contador é total falso — a mesma regra que o cartão de rotas
    já cumpria do outro lado da tela. Cinco linhas de onze, dito na tela."""
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#tvcli-cargas-sub")
    assert "5 de %d" % len(_CARGAS) in txt, txt


def test_a_lista_do_cartao_CORTA_em_vez_de_empurrar_o_rodape(pagina):
    """As três esperas do cartão "Parados agora" saíam SOBRE a procedência.
    Duas linhas sobrepostas numa parede não se leem como erro — se leem como um
    texto estranho, e ninguém desconfia do número ao lado.

    O GUARD FORÇA A CONDIÇÃO em vez de torcer para a amostra produzi-la. A
    primeira versão media a amostra normal (três esperas e um rodapé curto),
    que CABE — e continuava verde com o `overflow` desligado. Verde que nunca
    ficaria vermelho não conferiu nada; aqui o teste enche a lista até ela ter
    de ceder, que é a única situação em que a regra existe.
    """
    pg, base = pagina
    _parede(pg, base)
    for lista, rodape in (("tvcli-prox", "tvcli-chegam-sub"),
                          ("tvcli-parados-lista", "tvcli-parados-sub")):
        m = pg.evaluate("""(ids) => {
          const l = document.getElementById(ids[0]);
          const r = document.getElementById(ids[1]);
          const card = l.closest('.tv-card');
          const antes = card.getBoundingClientRect().height;
          l.innerHTML = Array.from({length: 14},
            (_, i) => '<div><b>9h9' + i + '</b><span>CIDADE MUITO LONGA/UF'
                      + '</span></div>').join('');
          const cresceu = card.getBoundingClientRect().height - antes;
          const invade = l.getBoundingClientRect().bottom
                       - r.getBoundingClientRect().top;
          const vaza = l.getBoundingClientRect().bottom
                     - card.getBoundingClientRect().bottom;
          return {cresceu, invade, vaza};
        }""", [lista, rodape])
        assert m["cresceu"] < 1, (
            "%s esticou o cartão em %.0f px — a faixa da parede tem altura "
            "fixa, então isso vira cartão passando por cima do vizinho"
            % (lista, m["cresceu"]))
        assert m["invade"] <= 1, (
            "%s passou %.0f px por cima de %s" % (lista, m["invade"], rodape))
        assert m["vaza"] <= 1, (
            "%s vazou %.0f px para fora do cartão" % (lista, m["vaza"]))


def test_o_FREETIME_nao_volta_para_a_parede_do_cliente(pagina):
    """Freetime é quem paga pela hora parada: conversa de cobrança passando na
    parede do cliente. Ele continua vivo nas telas `sac` e `cliop`, que são de
    análise e têm dono nosso — este guard é só sobre o mural.

    Afirma o RENDERIZADO, e não o texto-fonte: a palavra continua no arquivo
    (nos comentários que explicam a decisão, e nas outras telas)."""
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#view-tvcli").lower()
    assert "freetime" not in txt, "o freetime voltou para a parede do cliente"


def test_a_previsao_e_apresentada_como_ESTIMATIVA(pagina):
    """"Chegam hoje" sai de mediana histórica da rota, e metade das viagens
    passa da mediana por definição. Um mural que promete hora de chegada sem
    dizer que estima vira cobrança na reunião seguinte."""
    pg, base = pagina
    _parede(pg, base)
    assert "estimativa" in pg.inner_text("#tvcli-chegam-sub").lower()


def test_a_cobertura_da_previsao_vai_junto(pagina):
    """6 das 7 a caminho têm estimativa (uma rota sem histórico não tem). Sem
    a cobertura, "chegam 5" se lê como "só há 5 no ar"."""
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#tvcli-chegam-sub")
    assert "de 7 a caminho" in txt, txt
