"""A página inicial (Radar do Transporte) contra o index.html real.

O DUBLÊ DA ROTA É A SAÍDA REAL DO PAINEL: `radar_payload.json` foi gerado
rodando `api.radar.painel.painel()` sobre as amostras de `tests/radar/dados`
(os corpos que ANP, Yahoo, Banco Central, Google e TomTom devolveram em
11/09/2026), e `tests/radar/test_registro_e_agendador.py` confere que as chaves
dele continuam sendo as da rota. Payload escrito à mão aqui provaria que a
tela lê o que o teste inventou.

E A RÉGUA DE ALTURA RODA COM ESTE PAYLOAD CHEIO, não com o `{}` do
`medir_paineis`: a aba Decidir passava com 854px no esqueleto e ia a 1.303px
com os doze meses reais.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from tests.frontend.conftest import USUARIO

PAYLOAD = json.loads((Path(__file__).parent / "radar_payload.json").read_text(encoding="utf-8"))

#: Quem não tem perfil nenhum — e é para essa pessoa que a página existe.
SEM_PERFIL = {**USUARIO, "admin": False, "perfil": "Operacao", "telas": []}


def _abrir(pg, base_url, quem=USUARIO, payload=None, hash_="#radar"):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = quem
        elif "/api/radar" in u:
            corpo = PAYLOAD if payload is None else payload
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html{hash_}")
    pg.wait_for_selector("#kpis-radar .kpi", timeout=20000)
    return erros


def _com_ocorrencias(pg):
    """Reexibe a aba de ocorrências e repinta, como ela nasce: aberta.

    A ABA ESTÁ OCULTA por pedido de quem opera (11/09/2026) e volta com
    `RD.ocorrencias = true`. Os testes que usam isto seguram o que ela mostra
    para o dia em que voltar — sem eles, o código dela apodreceria calado.
    """
    pg.evaluate("() => { RD.ocorrencias = true; RD.rodAuto = false;"
                " abaTrocar('radarrod', 'oc'); rdRender(RD.d); }")


def test_os_quatro_cartoes_trazem_o_numero_e_a_comparacao(pagina):
    pg, base = pagina
    erros = _abrir(pg, base)
    txt = pg.inner_text("#kpis-radar")
    assert "R$ 6,88/l" in txt and "R$ 6,47/l" in txt
    assert "US$ 103,68" in txt and "R$ 5,0949" in txt
    assert "PTAX" in txt, "a PTAX oficial viaja ao lado do dólar de agora"
    assert pg.locator("#kpis-radar .kpi").count() == 4
    assert pg.locator("#kpis-radar .trend").count() >= 3, "número-chave sem comparação"
    assert not erros, erros


def test_os_dois_graficos_desenham_com_largura_de_verdade(pagina):
    pg, base = pagina
    _abrir(pg, base)
    for alvo in ("#chartRadarDiesel svg", "#chartRadarBrent svg"):
        pg.wait_for_selector(alvo, timeout=20000)
        assert pg.locator(alvo).bounding_box()["width"] > 200, alvo


def test_a_noticia_abre_NO_VEICULO_em_outra_aba(pagina):
    pg, base = pagina
    _abrir(pg, base)
    esperado = len(PAYLOAD["noticias"]["trc"]["itens"])
    links = pg.locator("#rd-feed-trc a.rd-item")
    assert links.count() == esperado > 0
    for i in range(links.count()):
        a = links.nth(i)
        assert a.get_attribute("target") == "_blank"
        assert "noopener" in (a.get_attribute("rel") or "")
        assert (a.get_attribute("href") or "").startswith("https://")


def test_a_aba_diz_quantas_manchetes_tem_sem_precisar_entrar(pagina):
    pg, base = pagina
    _abrir(pg, base)
    for tema in ("trc", "diesel", "reforma", "antt"):
        total = PAYLOAD["noticias"][tema]["total"]
        assert pg.inner_text(f"#rd-n-{tema}") == (str(total) if total else "")


# ------------------------------------------------ o cartão das rodovias

def test_o_cartao_de_rodovias_mostra_so_as_interdicoes_e_nao_fala_da_outra_aba(pagina):
    """Pedido de quem opera (11/09/2026): a aba de ocorrências fica oculta, e
    o cartão NÃO diz que ocultou — nem no cabeçalho, nem num aviso, nem no ⓘ.
    Vale com a TomTom e a frota trazendo dado (o payload padrão traz os dois)."""
    pg, base = pagina
    erros = _abrir(pg, base)
    assert pg.locator("#tabradarrod-oc").is_hidden()
    assert pg.get_attribute("#tabradarrod-int", "aria-selected") == "true"
    assert pg.locator("#rd-feed-rodovias a.rd-item").first.is_visible()
    assert pg.locator("#rd-rod-lista").is_hidden()
    assert pg.inner_text("#rd-rod-hint") == ""
    cartao = pg.locator(".card", has=pg.locator("#rd-rod-hint"))
    falado = (cartao.locator(".head").inner_text() + " "
              + cartao.locator(".subtabs").inner_text() + " "
              + (cartao.locator(".ihelp").first.get_attribute("title") or "")).lower()
    for palavra in ("tomtom", "frota", "ocorrência", "ocult", "desligad"):
        assert palavra not in falado, f"o cartão fala de '{palavra}': {falado!r}"
    assert not erros, erros


def test_a_rodovia_fechada_aparece_com_o_corredor(pagina):
    pg, base = pagina
    _abrir(pg, base)
    _com_ocorrencias(pg)
    lista = pg.inner_text("#rd-rod-lista")
    assert "BR-101" in lista and "Via fechada" in lista
    assert "Curitiba" in lista
    # o contador soma as ocorrências da TomTom e os caminhões LENTOS da frota
    assert pg.inner_text("#rd-n-rodoc") == str(len(PAYLOAD["rodovias"]["itens"])
                                                + PAYLOAD["frota"]["lentos"])


# ---------------------------------------------------- a página de TODO mundo

def test_quem_nao_tem_perfil_nenhum_ENTRA_pela_pagina_inicial(pagina):
    """Sem hash, sem perfil: antes, quem não tinha a Visão Geral caía na
    primeira tela da lista em que tivesse acesso."""
    pg, base = pagina
    erros = _abrir(pg, base, quem=SEM_PERFIL, hash_="")
    assert "on" in (pg.get_attribute("#view-radar", "class") or "")
    assert pg.is_visible('nav a[data-view="radar"]')
    assert pg.is_visible('nav a[data-view="apps"]'), (
        "a tela Aplicativos é de todo usuário logado e sumia do menu de quem "
        "não é administrador")
    assert not pg.is_visible('nav a[data-view="home"]')
    assert not erros, erros


# ------------------------------------------------------------ a honestidade

def test_fonte_atrasada_ACENDE_a_tarja_dizendo_qual(pagina):
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["coleta"]["brent"].update(estado="erro", ok=False, erro="HTTPError 429")
    _abrir(pg, base, payload=p)
    pg.wait_for_selector("#rd-tarja:not([hidden])", timeout=5000)
    t = pg.inner_text("#rd-tarja")
    assert "Brent (Yahoo)" in t and "HTTPError 429" in t
    assert "t-dang" in (pg.get_attribute("#rd-tarja", "class") or "")


def test_TomTom_SEM_CREDITO_diz_o_motivo_e_abre_as_interdicoes(pagina):
    """Visto no ar em 11/09/2026: o cartão dizia 'a primeira leitura ainda
    não chegou' (uma espera que não ia terminar), a aba aberta era a vazia, e
    uma tarja vermelha acusava dado velho que não estava na tela."""
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["rodovias"].update(itens=[], bloqueios=0)
    p["coleta"]["rodovias"].update(estado="erro", ok=False, sucesso_em=None,
                                      erro="TomTom sem créditos no produto de trânsito")
    _abrir(pg, base, payload=p)
    _com_ocorrencias(pg)
    txt = pg.inner_text("#rd-rod-lista")
    assert "sem créditos" in txt and "ainda não chegou" not in txt
    assert pg.locator("#rd-tarja").is_hidden(), "não há dado velho na tela para a tarja acusar"
    # COM A FROTA MEDINDO, O CARTÃO FICA NAS OCORRÊNCIAS e mostra a lentidão
    # dos nossos caminhões (11/09/2026: "quero que apareça e esteja certo").
    bruto = pg.text_content("#rd-rod-lista")    # inner_text segue o text-transform do CSS
    assert "Nossa frota nos corredores" in bruto and "1 lento" in bruto
    assert pg.get_attribute("#tabradarrod-oc", "aria-selected") == "true"


def test_sem_TomTom_e_sem_frota_abre_as_interdicoes(pagina):
    """Nada ao vivo de fonte nenhuma: aí a aba que tem dado abre sozinha."""
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["rodovias"].update(itens=[], bloqueios=0)
    p["coleta"]["rodovias"].update(estado="erro", ok=False, sucesso_em=None,
                                      erro="TomTom sem créditos no produto de trânsito")
    p["frota"] = {"corredores": [], "coletado_em": None, "caminhoes": 0, "lentos": 0}
    _abrir(pg, base, payload=p)
    _com_ocorrencias(pg)
    assert pg.get_attribute("#tabradarrod-int", "aria-selected") == "true"
    assert "sem créditos" in pg.inner_text("#rd-rod-lista")


def test_tudo_em_dia_NAO_mostra_tarja(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.locator("#rd-tarja").is_hidden()


def test_sem_TomTom_a_aba_de_ocorrencias_explica_e_nao_finge_estrada_livre(pagina):
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["rodovias"].update(configurado=False, itens=[], bloqueios=0)
    _abrir(pg, base, payload=p)
    _com_ocorrencias(pg)
    assert "TomTom não está configurada" in pg.inner_text("#rd-rod-lista")


def test_transito_DESLIGADO_por_decisao_diz_a_decisao_e_abre_as_interdicoes(pagina):
    """11/09/2026: sem crédito no trânsito, e quem opera decidiu não
    recarregar. A tela diz a DECISÃO — não "não configurada", que mandaria
    alguém procurar uma chave que existe — e abre a aba que tem dado."""
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["rodovias"].update(configurado=False, itens=[], bloqueios=0, desligado={
        "desde": "2026-09-11", "desde_br": "11/09/2026",
        "motivo": "sem crédito no produto de trânsito, e a decisão foi não recarregar"})
    p["coleta"].pop("rodovias")
    # sem a frota medindo: é o caso em que a aba de ocorrências não tem o que mostrar
    p["frota"] = {"corredores": [], "coletado_em": None, "caminhoes": 0, "lentos": 0}
    erros = _abrir(pg, base, payload=p)
    _com_ocorrencias(pg)
    txt = pg.inner_text("#rd-rod-lista")
    assert "desligadas por decisão desde 11/09/2026" in txt
    assert "não está configurada" not in txt and "sem créditos" not in txt
    assert pg.get_attribute("#tabradarrod-int", "aria-selected") == "true"
    assert pg.locator("#rd-tarja").is_hidden()
    assert not erros, erros

    # A ABA VAZIA SAI, e o cartão fica com o que tem dado. Visto no celular
    # em 11/09/2026: com a troca automática já gasta (ela só vale na primeira
    # pintura), o cartão parava em "Ocorrências" e se lia "sem informação".
    assert pg.locator("#tabradarrod-oc").is_hidden(), "aba que não pode ter conteúdo"
    assert "por decisão" in pg.inner_text("#rd-rod-hint"), "a decisão vai para o cabeçalho"
    assert pg.locator("#rd-feed-rodovias a.rd-item").first.is_visible()
    pg.evaluate("() => { RD.rodAuto = true; abaTrocar('radarrod', 'oc');"
                " rdRodovias(RD.d.rodovias, RD.d.noticias.rodovias, RD.d.frota); }")
    assert pg.get_attribute("#tabradarrod-int", "aria-selected") == "true", (
        "com a troca automática já usada, a recarga deixava o cartão na aba vazia")
    assert pg.locator("#rd-feed-rodovias a.rd-item").first.is_visible()


def test_transito_DESLIGADO_com_a_FROTA_medindo_a_aba_fica_e_mostra_a_frota(pagina):
    """Com a nossa frota medindo, a aba de ocorrências tem o que mostrar mesmo
    com a TomTom desligada — e a decisão fica dita numa linha."""
    pg, base = pagina
    p = copy.deepcopy(PAYLOAD)
    p["rodovias"].update(configurado=False, itens=[], bloqueios=0, desligado={
        "desde": "2026-09-11", "desde_br": "11/09/2026", "motivo": "teste"})
    p["coleta"].pop("rodovias")
    _abrir(pg, base, payload=p)
    _com_ocorrencias(pg)
    assert pg.locator("#tabradarrod-oc").is_visible()
    assert pg.get_attribute("#tabradarrod-oc", "aria-selected") == "true"
    txt = pg.inner_text("#rd-rod-lista")
    bruto = pg.text_content("#rd-rod-lista")    # inner_text segue o text-transform do CSS
    assert "Nossa frota nos corredores" in bruto and "1 lento" in bruto
    assert "desligadas por decisão" in txt
    assert "nenhum caminhão nosso no corredor agora" in txt, "corredor vazio diz isso, não 'livre'"


def test_com_o_transito_LIGADO_as_duas_abas_continuam(pagina):
    """O contrapeso: reexibida, a aba de ocorrências só sai com a decisão em vigor."""
    pg, base = pagina
    _abrir(pg, base)
    _com_ocorrencias(pg)
    assert pg.locator("#tabradarrod-oc").is_visible()
    assert pg.get_attribute("#tabradarrod-oc", "aria-selected") == "true"


# -------------------------------------------------------------- a régua

_ALTURA = ("() => { const c = document.getElementById('content'); if(!c) return 0;"
           " const b = c.querySelector('#banner');"
           " const fora = (b && b.offsetParent !== null) ? Math.round(b.getBoundingClientRect().height) + 14 : 0;"
           " return Math.round(c.scrollHeight) - fora; }")
_LADO = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"


def test_cabe_em_UMA_tela_com_o_payload_cheio(pagina):
    pg, base = pagina
    pg.set_viewport_size({"width": 1500, "height": 1000})
    _abrir(pg, base)
    pg.wait_for_selector("#chartRadarBrent svg", timeout=20000)
    altura = pg.evaluate(_ALTURA)
    assert altura <= 900, f"a página inicial tem {altura}px com dado real — a régua é 900"
    assert pg.evaluate(_LADO) == 0, "a página rola para o lado"


def test_no_celular_nao_rola_para_o_lado(pagina):
    pg, base = pagina
    pg.set_viewport_size({"width": 400, "height": 860})
    _abrir(pg, base)
    assert pg.evaluate(_LADO) == 0


# ------------------------------------------------- a régua NO LIMITE

#: Dezenas de ocorrências: a lista das rodovias NÃO tem teto no servidor, e
#: uma caixa real da TomTom já trouxe 194 incidentes (`tests/test_tomtom.py`),
#: dos quais o filtro de rodovia numerada deixa algumas dezenas.
OCORRENCIAS_NO_LIMITE = 40


def _no_limite() -> dict:
    """O payload no TETO DO CADASTRO, e não o do dia das amostras.

    PAYLOAD CHEIO NÃO É PAYLOAD NO LIMITE: com as 3 manchetes por tema das
    amostras, remover a rolagem interna não mudaria um pixel, e o guard de
    altura aprovaria a remoção. Aqui cada aba recebe o teto que o SERVIDOR
    manda (`painel.LIMITE_NOTICIAS`, 15) com o título mais longo das amostras
    reais, e o total da aba passa do que a lista mostra — como no dia real,
    46 manchetes de diesel em 14 dias.
    """
    from api.radar import painel
    p = copy.deepcopy(PAYLOAD)
    titulo = max((i["titulo"] for n in PAYLOAD["noticias"].values() for i in n["itens"]),
                 key=len)
    for tema, n in p["noticias"].items():
        base = n["itens"][0]
        n["itens"] = [dict(base, titulo=f"{titulo} ({k})", link=f"{base['link']}&n={k}")
                      for k in range(painel.LIMITE_NOTICIAS)]
        n["total"] = 46
    modelo = p["rodovias"]["itens"][0]
    p["rodovias"]["itens"] = [dict(modelo, rodovias=f"BR-{101 + k}")
                              for k in range(OCORRENCIAS_NO_LIMITE)]
    p["rodovias"]["bloqueios"] = OCORRENCIAS_NO_LIMITE
    return p


#: As caixas que rolam por dentro: (lista, aba que precisa estar aberta).
_CAIXAS = (("rd-feed-trc", None),
           ("rd-feed-reforma", ("radar", "reforma")),
           ("rd-rod-lista", ("radarrod", "oc")),
           ("rd-feed-rodovias", ("radarrod", "int")))


def test_cabe_em_UMA_tela_NO_LIMITE_e_a_rolagem_e_de_quem_segura(pagina):
    """Três afirmações, e cada uma segura a outra:

    1. o dublê CHEGOU na tela (15 manchetes, 40 ocorrências desenhadas) — sem
       isto, aba vazia cabe em qualquer régua e o teste passa por vacuidade;
    2. o conteúdo EXERCITA a caixa (ao menos 3× a altura dela, a mira da casa)
       — abaixo disso, tirar o `max-height` não mudaria a altura da página;
    3. e mesmo assim a página cabe em 900px e não rola para o lado.

    MEDIDO EM 11/09/2026, 1500×1000, depois de o piso da ANTT sair da página
    (as listas das rodovias passaram a ter a altura das notícias): 728px, e as
    razões 3,07× (notícias, o teto de 15 do servidor alcança a mira por pouco),
    4,56× (reforma), 6,8× (ocorrências) e 3,07× (interdições). SABOTANDO O
    VALOR, e não a existência da regra: o `max-height` das listas de 446 para
    4.460px leva a página a 3.291px, e o guard fica vermelho.

    Mede COM a aba de ocorrências reexibida: é o caso mais alto do cartão.
    """
    pg, base = pagina
    pg.set_viewport_size({"width": 1500, "height": 1000})
    _abrir(pg, base, payload=_no_limite())
    _com_ocorrencias(pg)
    pg.wait_for_selector("#chartRadarBrent svg", timeout=20000)
    assert pg.locator("#rd-feed-trc a.rd-item").count() == 15
    # as linhas da TomTom (a frota vem antes, com as dela)
    assert pg.locator("#rd-rod-lista .rd-rod.rd-oc").count() == OCORRENCIAS_NO_LIMITE
    razoes = {}
    for caixa, aba in _CAIXAS:
        if aba:
            pg.evaluate("([g, a]) => abaTrocar(g, a)", list(aba))
        rol, vis = pg.evaluate(
            "id => { const e = document.getElementById(id); return [e.scrollHeight, e.clientHeight]; }",
            caixa)
        razoes[caixa] = round(rol / vis, 2) if vis else 0
    assert all(r >= 3 for r in razoes.values()), (
        f"o conteúdo não exercita a caixa (razão rolável/visível): {razoes}")
    altura = pg.evaluate(_ALTURA)
    assert altura <= 900, f"a página inicial tem {altura}px NO LIMITE — a régua é 900 ({razoes})"
    assert pg.evaluate(_LADO) == 0
