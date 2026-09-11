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


def test_sem_historico_a_figura_DIZ_isso(pagina):
    """Cartão vazio numa parede se lê como tela quebrada."""
    pg, base = pagina
    assert "sem histórico" in _monta(pg, base, "tvCliBarras([])")


# --------------------------------------------- o cartao de rotas SAIU (09/09)

def test_as_ROTAS_nao_voltam_para_a_parede(pagina):
    """"Rotas mais usadas — 12 meses" saiu do mural em 09/09/2026, e o guard
    existe porque a remocao tem duas metades que somem em silencio.

    Ela era CONTEXTO de 12 meses num painel de operacao do dia: respondia
    "como tem sido", que ninguem pergunta de pe na porta da sala, e o cartao de
    volume ao lado ja da esse contexto. O espaco foi para a lista de cargas,
    que mostrava 5 de 31 em meia largura.

    O guard olha o RENDERIZADO e o construtor: um cartao devolvido sem a funcao
    (ou o contrario) e um dos dois lados morto, que e o defeito que a casa ja
    conhece -- existe, esta declarado e nunca aparece.
    """
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#view-tvcli").lower()
    assert "rotas mais usadas" not in txt, "o cartao de rotas voltou"
    assert pg.evaluate("() => typeof tvCliRotas") == "undefined", (
        "o construtor ficou orfao: ninguem o chama e ele continua no arquivo")
    for id_ in ("tvcli-rotas", "tvcli-rotas-sub"):
        assert pg.evaluate("(i) => !!document.getElementById(i)", id_) is False, id_


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


# A AMOSTRA CARREGA OS CAMPOS QUE O PAYLOAD CARREGA, inclusive os que este
# arquivo nao consulta. Dubles enxutos escondem a coluna nova: quando a janela
# de entrega e a chegada entraram, os cartoes que passaram a le-las acharam
# `undefined` aqui e o guard ficou verde descrevendo uma parede que nao existe
# mais. `janela_entrega` e RELATIVA ao relogio pela mesma razao de sempre --
# literal de setembro vira "chegou ha meses" no dia seguinte ao commit.
_CARGAS = [
    {"coleta": 19900 + i, "emissao": "2026-09-07", "origem": "JOINVILLE",
     "uf_origem": "SC", "destino": "SAO JOSE DOS PINHAIS", "uf_destino": "PR",
     "destinatario": "MONTADORA - SAO JOSE DOS PINHAIS/PR",
     "placa": "APJ6E4%d" % i, "marco": "Em viagem", "marco_cod": 400,
     "marco_em": _dt(-6), "marco_fonte": "apontamento",
     "janela_carga": _dt(-8), "janela_entrega": _dt(h),
     "chegada": None, "chegada_fonte": None, "desvio_h": None,
     # TRES SITUACOES DE POSICAO, e a do meio e a que pega o defeito real.
     #   i<3  -> tres no MESMO patio (o caso obvio de empilhamento)
     #   i==3 -> um patio VIZINHO, a ~40 km: longe demais para a grade de graus
     #           juntar (ela separa acima de ~1 km) e perto demais para caber
     #           sem encostar na tela. Era exatamente esse o embolamento que a
     #           parede mostrava, e um duble so com "mesmo ponto" e "800 km"
     #           passa verde sem tocar nele.
     #   i>=4 -> outro estado, a ~800 km: tem de continuar SEPARADO.
     "pos": {"lat": (-25.53 if i < 3 else -25.19 if i == 3 else -19.97),
             "lon": (-49.20 if i < 3 else -49.05 if i == 3 else -44.20),
             "velocidade": 0 if i < 4 else 62, "fonte": "erp",
             "idade_min": 5.0, "velha": False},
     "eta": _dt(h), "eta_amostras": 40}
    for i, h in enumerate([-1.4, 0.6, 2.1, 4.8, 7.2, 26.0])
] + [
    # A CAMINHO E SEM ESTIMATIVA: rota sem histórico não tem mediana. Ela
    # continua na amostra porque a JANELA existe mesmo onde a estimativa não
    # existe — que é exatamente a diferença de cobertura que motivou a troca.
    {"coleta": 19950, "emissao": "2026-09-07", "origem": "CASCAVEL",
     "uf_origem": "PR", "destino": "GOIANIA", "uf_destino": "GO",
     "destinatario": "CLIENTE DUBLÊ - GOIANIA/GO",
     "placa": "MIP1G96", "marco": "Saída do carregamento", "marco_cod": 395,
     "marco_em": _dt(-3), "marco_fonte": "apontamento",
     "janela_carga": _dt(-5), "janela_entrega": _dt(3.5),
     "chegada": None, "chegada_fonte": None, "desvio_h": None,
     "eta": None, "eta_amostras": None},
] + [
    {"coleta": 16020 + i, "emissao": "2026-09-07", "origem": "CURITIBA",
     "uf_origem": "PR", "destino": "BETIM", "uf_destino": "MG",
     "destinatario": "PLANTA DUBLÊ - BETIM/MG",
     "placa": "BQR7C1%d" % i, "marco": rot, "marco_cod": cod,
     "marco_em": _dt(h), "marco_fonte": "apontamento",
     "janela_carga": _dt(h - 2), "janela_entrega": _dt(h + 1),
     # as duas que JA CHEGARAM levam a hora real e o desvio, que e o par que a
     # coluna "Chegada" e os chips "ja chegaram / faltam" consomem
     "chegada": _dt(h) if cod in (396, 399) else None,
     "chegada_fonte": "apontamento" if cod in (396, 399) else None,
     "desvio_h": 1.2 if cod in (396, 399) else None,
     "eta": None, "eta_amostras": None}
    for i, (cod, rot, h) in enumerate([
        (394, "Chegada para carregamento", -2.4),
        (398, "Aguardando carregamento", -5.7),
        (396, "Chegada para descarga", -0.6),
        # PARADO NO CLIENTE HA HORAS, e dentro da regua fisica de 24h: e o
        # estado que o ticker existe para cobrar, e a amostra nao o tinha --
        # entre uma chegada de 36 min e uma de 30h (que e artefato de
        # apontamento) faltava justamente a faixa do meio, que e a real.
        (396, "Chegada para descarga", -8.3),
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
        # O DUBLÊ ECOA O FILTRO, como o servidor de verdade: ele devolve as
        # CHAVES normalizadas ("RODA") e o catálogo que as traduz de volta ao
        # rótulo ("RODAS"). Dublê que não ecoasse testaria a parede contra ele
        # mesmo — ela mostraria o título sem recorte e o teste passaria.
        import urllib.parse as _u
        from api import freetime as _ft
        escolhidas = _u.parse_qs(_u.urlparse(url).query).get("merc", [])
        catalogo = [{"chave": _ft.normalizar(m), "rotulo": m, "cargas": 100}
                    for m in escolhidas]
        return {**selo, "cargas": _CARGAS, "em_curso": len(_CARGAS),
                "sem_apontamento": 0, "concluidas_na_janela": 758,
                "janela_dias": 45,
                "mercadorias_filtro": [_ft.normalizar(m) for m in escolhidas],
                "mercadorias": catalogo,
                "posicao": {"com_posicao": 9, "frescas": 8, "veiculos": 11,
                            "fresca_ate_min": 120, "lista": []}}
    if "/api/tv/estradas" in url:
        return {"configurado": False}
    return {"kpis": {}, "resumo": {}}


def _estavel(pg, seletor, timeout=8000):
    """O texto de um numero DEPOIS que a contagem crescente termina.

    Os numeros da parede animam desde 10/09/2026 (`tvAnimarNums`): quem le no
    meio ve um valor intermediario, verdadeiro no instante e falso como
    afirmacao -- o teste que quebrou por isso lia "9" a caminho de "10".

    ESPERAR ESTABILIDADE POR AMOSTRAGEM NAO SERVE, e a tentativa fica
    registrada porque ela ensina: a curva de easing tem um patamar de ~400 ms
    perto do fim (a 60% do caminho o valor ja arredonda para o penultimo
    inteiro), e duas leituras espacadas de 250 ms caem as duas dentro dele. O
    teste "esperou a estabilidade" e leu 9 com toda a confianca.

    Quem sabe que acabou e a animacao: ela marca o elemento com `.contando` e
    tira a marca no ultimo quadro. Esperar por isso nao amarra o teste a
    nenhuma duracao.
    """
    pg.wait_for_selector(seletor + ":not(.contando)", timeout=timeout)
    return pg.inner_text(seletor).strip()


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
    """Top-N sem contador é total falso. O NUMERO DE LINHAS vem do
    renderizador (`TVCLI_LINHAS`), e o guard le ele em vez de repetir a
    constante: escrito a mao, ele viraria uma segunda fonte da verdade que
    passa a discordar da primeira no dia em que alguem mexer numa so."""
    pg, base = pagina
    _parede(pg, base)
    n = pg.evaluate("() => TVCLI_LINHAS")
    assert n < len(_CARGAS), "a amostra precisa ter mais cargas que as linhas"
    txt = pg.inner_text("#tvcli-cargas-sub")
    assert "%d de %d" % (n, len(_CARGAS)) in txt, txt
    assert len(pg.query_selector_all("#tvcli-cargas tr")) == n


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


def test_chegam_hoje_conta_pela_JANELA_e_nao_pela_estimativa(pagina):
    """A troca de 09/09/2026, e ela e de COBERTURA — o numero antigo estava
    errado na parede.

    Medido na operacao do dia, 31 cargas em curso: 3 tinham estimativa de
    chegada (10%) e 31 tinham janela de entrega (100%). "Chegam hoje" dizia
    3 onde a resposta era 24. A estimativa so existe para quem JA SAIU e cuja
    rota tem historico bastante, e desde que a carga passou a ficar na tela
    depois de chegar, a maioria das cargas em curso esta justamente no estado
    que nao tem estimativa: a correcao anterior encolheu a cobertura desta, e
    o cartao nao acompanhou.

    A janela tambem responde melhor a pergunta do mural — quem espera na doca
    quer o que foi COMBINADO, nao a nossa mediana.
    """
    pg, base = pagina
    _parede(pg, base)
    hoje = pg.evaluate("() => _iso(new Date())")
    esperado = len([c for c in _CARGAS
                    if (c.get("janela_entrega") or "").startswith(hoje)])
    assert esperado, "a amostra precisa ter carga com janela para hoje"
    assert _estavel(pg, "#tvcli-chegam") == str(esperado)
    # e a procedencia continua dita: regua nossa publicada sem nome vira promessa
    assert "janela combinada" in pg.inner_text("#tvcli-chegam-sub").lower()


def test_chegam_hoje_reparte_entre_JA_CHEGARAM_e_FALTAM(pagina):
    """Os chips viraram o progresso do dia. "ate as 12h / a tarde" repartia por
    um relogio que ninguem consulta de pe; estes dois somam o numero grande,
    que e o que torna um chip legivel numa parede."""
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#tvcli-chegam-fx").lower()
    assert "já chegaram" in txt and "faltam" in txt, txt


# ======================================= a lista da parede, depois de 09/09/2026


def test_a_lista_da_parede_diz_QUEM_RECEBE_e_nao_so_a_cidade(pagina):
    """Duas docas na mesma cidade nao se distinguem por "CIDADE/UF".

    A tabela mostrava a rota; numa parede do cliente isso reune a montadora e
    a planta dele mesmo numa linha so. O destinatario DETERMINA a cidade, e
    nao o contrario.
    """
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#tvcli-cargas")
    assert "MONTADORA - SAO JOSE DOS PINHAIS/PR" in txt, txt
    assert "→" not in txt, "a rota voltou para a lista"


def test_a_coluna_de_chegada_NUNCA_fica_vazia(pagina):
    """A diferenca entre uma tabela de referencia e uma que se le de longe.

    Tres respostas, e cada uma pede coisa diferente de quem olha: chegou (a
    hora), passou da janela (ha quanto tempo, em ambar) e ainda no prazo
    (quanto falta). Celula vazia numa parede se le como dado faltando.
    """
    pg, base = pagina
    _parede(pg, base)
    linhas = pg.query_selector_all("#tvcli-cargas tr")
    assert linhas, "a tabela nao renderizou"
    for tr in linhas:
        celulas = tr.query_selector_all("td")
        ultima = celulas[-1].inner_text().strip()
        assert ultima and ultima != "—", (
            "coluna de chegada vazia em: " + tr.inner_text())


def test_a_situacao_ganha_a_COR_da_etapa_e_o_rotulo_junto(pagina):
    """Cor sozinha nao diz nada numa TV sem tooltip -- por isso ela nao
    substitui o texto, acompanha. E a paleta e a MESMA dos chips do heroi:
    repetir o par cor/etapa nos dois lugares e o que dispensa legenda."""
    pg, base = pagina
    _parede(pg, base)
    cores = pg.evaluate("""() => [...document.querySelectorAll('#tvcli-cargas tr')]
        .map(tr => { const td = tr.children[3];
                     return {txt: td.textContent.trim(),
                             cor: getComputedStyle(td).color}; })""")
    assert cores, "sem linhas"
    for c in cores:
        assert c["txt"], "situacao sem rotulo: a cor teria de responder sozinha"
    assert len({c["cor"] for c in cores}) > 1, (
        "todas as situacoes na mesma cor: a coluna nao separa nada " + str(cores))


def test_o_ticker_cobra_a_JANELA_e_nao_a_estimativa(pagina):
    """Ele ficou para tras quando o cartao trocou de regua e passou a dizer
    "passaram da estimativa de chegada" para um painel que nao mostra
    estimativa nenhuma. Alarme que nomeia uma regua que saiu da tela e pior
    que alarme nenhum: quem le vai procurar o numero e nao acha."""
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#tvcli-tick").lower()
    assert "estimativa" not in txt, txt
    assert "janela combinada" in txt, txt


def test_o_ticker_NOMEIA_onde_o_veiculo_esta_parado(pagina):
    """"7 veiculos parados" manda quem le procurar onde. Numa parede a linha
    seguinte so volta depois de a faixa dar a volta inteira, entao o ONDE tem
    de vir na mesma linha do QUANTOS."""
    pg, base = pagina
    _parede(pg, base)
    txt = pg.inner_text("#tvcli-tick")
    assert "no cliente há mais de" in txt, txt
    assert "PLANTA DUBLÊ - BETIM/MG" in txt, txt


# ================================================================ o mapa


def test_o_mapa_SEPARA_veiculos_de_patios_diferentes(pagina):
    """O COMPORTAMENTO, medido na tela — e não a ordem das linhas no arquivo.

    Este guard nasceu porque a versão de texto-fonte dele ficou CEGA: ela
    afirmava que `fitBounds` aparecia antes de `project()`, e há dois
    `fitBounds` antes do agrupamento — apagar o primeiro (que é justamente o
    que define o zoom lido) deixava o segundo satisfazendo a comparação, e a
    sabotagem passou verde. Ordem de texto não é ordem de execução.

    O que importa é observável: marcas de pátios distantes não podem encostar
    umas nas outras. Se o agrupamento medir a distância no chão (a grade de
    graus antiga) ou projetar num zoom que não é o da tela, elas encostam.

    O QUE ESTE GUARD NÃO ALCANÇA, e fica dito em vez de fingido: apagar o
    `fitBounds` SÍNCRONO não o faz falhar. Na primeira pintura o
    reenquadramento (um quadro depois) corrige o zoom sozinho, e a diferença
    de um nível não muda o agrupamento desta amostra. O síncrono existe para
    as RECARGAS — o reenquadramento roda uma vez só, e sem ele o mapa deixaria
    de acompanhar a operação que se move ao longo do dia. Cobrir isso exigiria
    o painel recarregar dentro do teste (60 s), e um caso calibrado só para
    acender seria calibrar o teste para o teste.
    """
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)      # o reenquadramento roda um quadro depois
    marcas = pg.evaluate("""() => [...document.querySelectorAll('#tvCliMapa .tv-vmk')]
        .map(d => { const r = d.getBoundingClientRect();
                    return {txt: d.textContent, x: r.x, y: r.y,
                            w: r.width, h: r.height}; })""")
    assert len(marcas) >= 2, (
        "os dois pátios viraram uma marca só: o agrupamento juntou o que está "
        "a centenas de km " + str(marcas))
    for i, a in enumerate(marcas):
        for b in marcas[i + 1:]:
            encosta = (abs(a["x"] - b["x"]) < max(a["w"], b["w"])
                       and abs(a["y"] - b["y"]) < max(a["h"], b["h"]))
            assert not encosta, ("marcas sobrepostas: %r e %r" % (a["txt"], b["txt"]))


def test_o_mapa_NAO_JUNTA_os_veiculos_do_mesmo_patio(pagina):
    """A REGRA MUDOU EM 10/09/2026, a pedido de quem opera: não junte.

    Antes, veículos a menos de 52 px viravam UMA marca escrita "3 veíc." — e
    isso apagava exatamente o que se vai olhar numa parede de operação: qual
    caminhão está onde. O agrupamento resolvia colisão de etiqueta, e o preço
    era alto demais para o problema.

    Agora cada veículo tem a SUA marca, com a SUA placa, e quem resolve a
    colisão é o degrau: a etiqueta sobe até achar lugar livre, ancorada na
    coordenada real. Ninguém é movido de lugar — deslocar o ponto para
    desempilhar mentiria sobre onde o caminhão está, e no zoom desta parede
    30 px são dezenas de quilômetros.
    """
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    txts = pg.evaluate("""() => [...document.querySelectorAll('#tvCliMapa .tv-vmk')]
        .map(d => d.textContent)""")
    assert not any("veíc." in t for t in txts), (
        "o agrupamento voltou: alguma marca virou contagem " + str(txts))
    # uma marca por veículo, cada uma com a placa
    assert len(txts) == 6, ("sumiu ou sobrou marca: " + str(txts))
    assert len(set(txts)) == 6, ("placa repetida na parede: " + str(txts))
    for t in txts:
        assert re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}", t), (
            "etiqueta que não é placa: %r" % t)


# ═══════════════════ o passeio por regiao e a contagem crescente ═══════════
#
# As duas coisas que quem opera pediu em 10/09/2026, e que substituem o
# agrupamento de marcas: como nao se junta mais, quem resolve a legibilidade e
# a ESCALA -- o mapa passeia e cada regiao aparece grande.

def test_o_mapa_PASSEIA_pelas_regioes(pagina):
    """A regiao e distancia NO CHAO, e nao em pixel, e a diferenca importa:
    pixel depende do zoom, e o zoom e justamente o que o passeio muda. Uma
    regiao tem de ser a mesma no panorama e no close, senao o roteiro mudaria
    a cada passo.

    A amostra tem dois estados (~800 km), entao sao duas regioes. O passo e
    disparado a mao: esperar os 11 s do panorama faria o teste medir o
    relogio, nao a regra.
    """
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    assert pg.evaluate("() => (tvCliRegs || []).length") == 2, (
        "as duas pracas da amostra tinham de virar duas regioes")
    z0 = pg.evaluate("() => tvCliMap.getZoom()")
    pg.evaluate("() => tvCliTourPasso()")
    pg.wait_for_timeout(2400)                      # o flyToBounds dura 1,6 s
    z1 = pg.evaluate("() => tvCliMap.getZoom()")
    assert z1 > z0, (
        "o passeio nao aproximou: panorama em %s, regiao em %s" % (z0, z1))
    # O QUE O PASSEIO TEM DE FAZER E APROXIMAR, e so isso. Ele nao escreve
    # mais em lugar nenhum: a tarja que dizia "regiao 3 de 3" saiu junto com a
    # cobertura em 11/09/2026, a pedido de quem e dono da parede.


def test_o_mapa_NAO_TEM_TARJA_por_cima(pagina):
    """A tarja saiu por decisao de quem e dono da parede (11/09/2026).

    Ela dizia duas coisas: a COBERTURA ("15 de 15 veiculos · 15 com posicao de
    ate 120 min") e o passo do roteiro ("regiao 3 de 3 · 1 veiculo"). A
    cobertura e regra da casa -- contador impede ler a amostra como o todo --,
    e por isso a remocao tem guard PROPRIO em vez de simplesmente acontecer:
    quem vier depois vai ler a regra, achar que falta a tarja e recolocar.

    O que sustenta a remocao: o mapa desta parede mostra as cargas EM CURSO, os
    cartoes ao lado contam essas mesmas cargas, e a leitura acontece de longe e
    de passagem. Se um dia a frota passar a ter veiculo sem posicao com
    frequencia, o lugar de dizer isso e um CARTAO -- que a sala le -- e nao uma
    faixa por cima do mapa.
    """
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    assert pg.eval_on_selector_all("#tvcli-mapa-sub", "e => e.length") == 0, (
        "a tarja voltou por cima do mapa da parede do cliente")
    # e o mapa continua la: remover a tarja nao pode ter levado o mapa junto
    assert pg.is_visible("#tvCliMapa"), "o mapa sumiu com a tarja"
    assert pg.evaluate("() => (tvCliRegs || []).length") == 2, (
        "as regioes sumiram: o passeio depende delas")


def test_o_passeio_PARA_ao_sair_da_parede(pagina):
    """Ele reagenda a si mesmo. Sem desligar, continuaria dando `flyToBounds`
    num mapa que ninguem esta vendo -- e a parede voltaria com o roteiro no
    meio, o que numa TV se le como travada."""
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    assert pg.evaluate("() => tvCliTour !== null"), "o passeio nem comecou"
    pg.evaluate("() => { location.hash = '#home'; }")
    pg.wait_for_timeout(900)
    assert pg.evaluate("() => tvCliTour === null"), (
        "o passeio continuou rodando fora da parede")


def test_os_numeros_da_parede_CONTAM_e_param_no_valor_certo(pagina):
    """O efeito pedido -- e a parte que importa e a segunda metade.

    Contar e enfeite; parar no numero certo e o dado. A animacao REESCREVE o
    texto do elemento quadro a quadro, entao um erro no ultimo quadro deixaria
    a parede exibindo um valor intermediario para sempre, sem erro nenhum no
    console.

    A marca `.contando` e o que torna o fim observavel: sem ela, so restaria
    esperar um tempo fixo, e a curva tem um patamar de ~400 ms perto do fim
    que faz duas leituras espacadas parecerem estaveis no valor ERRADO.
    """
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    pg.evaluate("""() => { document.getElementById('tvcli-hero').textContent = '42';
                           tvAnimarNums('view-tvcli'); }""")
    assert pg.eval_on_selector("#tvcli-hero", "e => e.classList.contains('contando')"), (
        "o numero nao esta animando")
    pg.wait_for_selector("#tvcli-hero:not(.contando)", timeout=8000)
    assert pg.inner_text("#tvcli-hero").strip() == "42", (
        "a contagem parou num valor intermediario")


# ═════════ a parede herda o filtro de mercadoria da Minha Operação ═════════
#
# Pedido de 11/09/2026: "o filtro de mercadoria deve também refletir no painel
# de tv do cliente". Numa TV ninguém clica, então a parede não ganha seletor
# próprio — ela HERDA a escolha pela mesma memória do navegador que já carrega
# o cliente, exatamente como faz com ele.

def test_a_parede_MANDA_o_filtro_guardado_na_Minha_Operacao(pagina):
    """Sem isso o mural mostraria a operação inteira enquanto quem o preparou
    escolheu duas mercadorias — e as duas telas, lado a lado na mesma sala,
    diriam números diferentes para a mesma pergunta."""
    pg, base = pagina
    pedidos = []

    def rota(route):
        u = route.request.url
        if "/api/portal/cliente" in u:
            pedidos.append(u)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_corpo(u)))

    pg.add_init_script(
        "try{ localStorage.setItem('cliop.raiz','11222333');"
        " localStorage.setItem('cliop.merc', JSON.stringify(['RODAS','CHASSI']));"
        " }catch(e){}")
    pg.route("**/api/**", rota)
    pg.goto(base + "/static/index.html#tvcli")
    pg.wait_for_timeout(1600)

    assert pedidos, "a parede não consultou a operação"
    from urllib.parse import urlparse, parse_qs
    # AS TRES consultas levam o filtro, e não só a primeira: a parede lê
    # `agora`, `permanencia` e `historico`, e um mural com o topo filtrado e o
    # rodapé inteiro é pior que um mural sem filtro nenhum.
    abas = {}
    for u in pedidos:
        q = parse_qs(urlparse(u).query)
        abas[(q.get("aba") or ["agora"])[0]] = sorted(q.get("merc", []))
    for aba in ("agora", "permanencia", "historico"):
        assert abas.get(aba) == ["CHASSI", "RODAS"], (
            "a aba %s da parede não levou o filtro: %s" % (aba, abas.get(aba)))


def test_a_parede_DIZ_que_esta_filtrada(pagina):
    """O aviso é o que separa "recorte" de "mentira".

    Um mural filtrado sem dizer mostra parte da operação com cara de todo, e
    quem lê de longe não tem como desconfiar. O nome do cliente continua
    primeiro — é ele que impede alguém na sala de ler a conta de outro.

    E o recorte sai no ROTULO de verdade ("RODAS"), não na chave normalizada
    que o servidor usa por dentro ("RODA"): normalizada é um texto que ninguém
    escreveu.
    """
    pg, base = pagina
    pg.add_init_script(
        "try{ localStorage.setItem('cliop.raiz','11222333');"
        " localStorage.setItem('cliop.merc', JSON.stringify(['RODAS']));"
        " }catch(e){}")
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    tit = pg.inner_text("#tvcli-titulo")
    assert "RODAS" in tit, "a parede não disse que está filtrada: %s" % tit
    assert "RODA," not in tit and not tit.endswith("RODA"), (
        "a parede mostrou a chave normalizada em vez do rótulo: %s" % tit)


def test_sem_filtro_a_parede_NAO_inventa_recorte(pagina):
    """O título fica limpo quando não há filtro — um "· todas as mercadorias"
    pendurado ali seria ruído permanente numa tela que se lê em três
    segundos."""
    pg, base = pagina
    _parede(pg, base)
    pg.wait_for_timeout(1400)
    assert "·" not in pg.inner_text("#tvcli-titulo").split("—")[-1]
