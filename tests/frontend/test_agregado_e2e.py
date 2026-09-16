# -*- coding: utf-8 -*-
"""A página do app do agregado no navegador, num celular de verdade.

A RÉGUA AQUI É A DO CELULAR (390×780), e não a de 900px do painel: quem lê está
no pátio, com o telefone na mão. Rolagem lateral é o defeito clássico desta
tela — uma tabela larga, um valor que não quebra — e ele não aparece no
desktop, que é onde ele é escrito.

Os dublês copiam a FORMA do servidor (`api/agregado/dados.py`), com os números
na ordem de grandeza do real medido em 16/09/2026: acerto fechado a pagar,
acerto em aberto, viagem com frete pago, abastecimento, lançamento pendente.
"""
from __future__ import annotations

import json

import pytest

EU = {"nome": "Transportes Fulano", "mestre": False, "veiculos": 3,
      "veiculos_ativos": 2,
      "secoes": {"acertos": True, "viagens": True, "abastecimentos": True,
                 "lancamentos": True, "ocorrencias": True}}

ACERTOS = {
    "acertos": [
        {"filial": 1, "numero": 8801, "emissao": "2026-09-10", "bruto": 18400.0,
         "descontos": 900.0, "adiantamentos": 5000.0, "despesas": 1200.0,
         "acrescimos": 0.0, "liquido": 11300.0, "fechado": True,
         "parcelas": 1, "parcelas_pagas": 0, "pago_em": None, "vence_em": "2026-09-20"},
        {"filial": 1, "numero": 8790, "emissao": "2026-08-28", "bruto": 22100.0,
         "descontos": 0.0, "adiantamentos": 6000.0, "despesas": 800.0,
         "acrescimos": 0.0, "liquido": 15300.0, "fechado": True,
         "parcelas": 1, "parcelas_pagas": 1, "pago_em": "2026-09-05", "vence_em": "2026-09-05"},
        {"filial": 2, "numero": 8812, "emissao": "2026-09-15", "bruto": 7400.0,
         "descontos": 0.0, "adiantamentos": 0.0, "despesas": 0.0,
         "acrescimos": 0.0, "liquido": 7400.0, "fechado": False,
         "parcelas": 0, "parcelas_pagas": 0, "pago_em": None, "vence_em": None},
    ],
    "mostrados": 3, "total": 3, "dias": 90,
    "resumo": {"abertos": 1, "valor_abertos": 7400.0, "a_pagar": 1,
               "valor_a_pagar": 11300.0, "pagos": 1, "valor_pago": 15300.0},
}

DETALHE = {
    # A COMPOSIÇÃO INTEIRA, como o servidor passou a devolver: é ela que
    # responde "por que este acerto deu isso?". Os números fecham a conta
    # (18.400 − 900 − 5.000 − 1.200 + 0 = 11.300), e fechar importa: dublê que
    # não fecha deixaria passar um modal que soma errado.
    "acerto": {"emissao": "2026-09-10", "bruto": 18400.0, "descontos": 900.0,
               "adiantamentos": 5000.0, "despesas": 1200.0, "acrescimos": 0.0,
               "liquido": 11300.0, "fechado": True},
    "filial": 1, "numero": 8801,
    "viagens": [{"placa": "ABC1D23", "viagem": 55012, "emissao": "2026-09-02",
                 "documento": "120345", "valor": 9200.0, "descontos": 0.0}],
    "despesas": [{"tipo": "ABASTECIMENTO INTERNO", "placa": "ABC1D23",
                  "emissao": "2026-09-03", "documento": "77", "valor": 1200.0}],
    "adiantamentos": [{"emissao": "2026-09-04", "documento": "9001", "valor": 5000.0}],
    "descontos": [{"emissao": "2026-09-06", "documento": "3321", "valor": 900.0}],
}

VIAGENS = {"viagens": [{"viagem": 55012, "filial": 1, "emissao": "2026-09-02",
                        "placa": "ABC1D23", "origem": "CURITIBA/PR",
                        "destino": "SAO BERNARDO DO CAMPO/SP", "km": 412.0,
                        "valor": 9200.0, "vazio": False}],
           "mostrados": 1, "total": 1, "dias": 90, "km": 412.0, "valor": 9200.0}

ABASTEC = {"abastecimentos": [{"data": "2026-09-03", "placa": "ABC1D23",
                               "litros": 320.5, "valor": 1980.0,
                               "preco_litro": 6.18, "odometro": 812345.0,
                               "km_litro": 2.31}],
           "mostrados": 1, "total": 1, "dias": 90, "litros": 320.5, "valor": 1980.0}

LANC = {"lancamentos": [
            {"id": 1, "data": "2026-09-08", "placa": "ABC1D23", "valor": 350.0,
             "tipo": "ADICIONAL ENTREGAS", "observacao": "", "situacao": 1, "aprovado": True},
            {"id": 2, "data": "2026-09-12", "placa": "ABC1D23", "valor": 180.0,
             "tipo": "KM FALTOU PAGAR (+)", "observacao": "", "situacao": 0, "aprovado": False}],
        "mostrados": 2, "total": 2, "dias": 90, "pendentes": 1}

OCOR = {"ocorrencias": [{"quando": "2026-09-09 14:20",
                         "ocorrencia": "ATRASO NA ENTREGA - TRANSITO",
                         "coleta": 44120, "placa": "ABC1D23"}],
        "mostrados": 1, "total": 1, "dias": 90}

VEICULOS = {"veiculos": [
    {"placa": "ABC1D23", "frota": "1042", "marca": "SCANIA", "modelo": "R450",
     "ano": 2019, "tipo": "CAVALO MECANICO", "ativo": True},
    {"placa": "XYZ9Z99", "frota": "", "marca": "RANDON", "modelo": "SR CARGA",
     "ano": 2015, "tipo": "SEMIRREBOQUE", "ativo": False}],
    "ativos": 1, "total": 2}

RESUMO = {"dias": 90, "veiculos": VEICULOS, "acertos": ACERTOS, "viagens": VIAGENS,
          "abastecimentos": ABASTEC, "lancamentos": LANC}

CELULAR = {"width": 390, "height": 780}


def _abre(pagina, eu=EU, sessao=True, **troca):
    """Abre a página já logada (o boot pergunta `/api/agregado/eu`).

    `sessao=False` simula quem chega sem cookie: a página tem de mostrar a
    entrada, e nunca o app vazio.
    """
    pg, base = pagina
    respostas = {"/api/agregado/eu": (eu if sessao else {"mensagem": "Faça login"},
                                      200 if sessao else 401),
                 "/api/agregado/resumo": (RESUMO, 200),
                 "/api/agregado/acertos": (ACERTOS, 200),
                 "/api/agregado/viagens": (VIAGENS, 200),
                 "/api/agregado/abastecimentos": (ABASTEC, 200),
                 "/api/agregado/lancamentos": (LANC, 200),
                 "/api/agregado/ocorrencias": (OCOR, 200),
                 "/api/agregado/veiculos": (VEICULOS, 200)}
    respostas.update(troca)
    pedidos: list[str] = []

    def rota(r):
        url = r.request.url
        caminho = url.split("?")[0].split("//", 1)[-1]
        caminho = "/" + caminho.split("/", 1)[1] if "/" in caminho else caminho
        pedidos.append(caminho)
        if caminho.startswith("/api/agregado/acertos/"):
            corpo, st = DETALHE, 200
        else:
            corpo, st = respostas.get(caminho, ({}, 200))
        r.fulfill(status=st, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.set_viewport_size(CELULAR)
    pg.goto(base + "/static/agregado.html")
    pg.wait_for_timeout(400)
    pg.pedidos = pedidos
    return pg


def _sem_rolagem_lateral(pg):
    return pg.evaluate("document.documentElement.scrollWidth"
                       " - document.documentElement.clientWidth")


def _ver(pg, aba):
    """Abre a aba e ESPERA O DADO, não o cartão.

    A primeira versão deste helper esperava por `#tela-X .card` — e o estado de
    carregamento TAMBÉM é um `.card` ("carregando…"). O teste lia a tela antes
    da resposta chegar e comparava o texto com "carregando…": falha por espera
    fraca, que se conserta esperando o carregamento SUMIR, nunca afrouxando a
    asserção.
    """
    # A CONTA NÃO ESTÁ NA BARRA — ela abre pelo botão do cabeçalho, e é por
    # isso que este helper precisa saber de onde cada aba é aberta. Com ela na
    # barra eram oito itens em 390px.
    pg.click("#b-conta" if aba == "conta" else f"#navbar button[data-aba='{aba}']")
    pg.wait_for_function(
        "(id) => { const el = document.getElementById(id);"
        # SEÇÃO VAZIA TAMBÉM NÃO É "PRONTA": a aba Conta busca os veículos
        # depois de abrir, e sem esta condição o teste lia "" e reclamava do
        # dado — quando o que faltava era esperar.
        " return el && !el.hidden && el.textContent.trim().length > 0"
        " && !el.textContent.includes('carregando'); }",
        arg=f"tela-{aba}")
    return pg.inner_text(f"#tela-{aba}")


def test_sem_sessao_a_pagina_mostra_a_entrada_e_nao_o_app(pagina):
    pg = _abre(pagina, sessao=False)
    assert pg.is_visible("#tela-entrar")
    assert pg.is_hidden("#app")
    assert _sem_rolagem_lateral(pg) == 0


def test_a_entrada_e_a_mesma_marca_do_app_do_motorista(pagina):
    """A CARA DO LOGIN É REQUISITO, não estética (pedido de quem opera,
    16/09/2026: "deixe a cara do login igual ao do motorista").

    O app fala de dinheiro com gente de fora da casa: uma tela genérica
    pedindo o celular tem a forma exata de um golpe. O que prova a marca é o
    conjunto — fundo navy em gradiente, o cabeçalho escuro, o anel girando com
    CÓRTEX dentro, a logo da Sulista e o acesso da administração como link
    discreto FORA do cartão.
    """
    pg = _abre(pagina, sessao=False)
    m = pg.evaluate("""() => {
        const corpo = getComputedStyle(document.body);
        const cab = document.querySelector('#entrada .lg-head');
        const anel = document.getElementById('lg-anel');
        const r = anel.getBoundingClientRect();
        const cartao = document.querySelector('#entrada .lg-card').getBoundingClientRect();
        const link = document.getElementById('b-abrir-mestre').getBoundingClientRect();
        return {gradiente: corpo.backgroundImage.includes('gradient'),
                entrando: document.body.classList.contains('entrando'),
                cabecalho: getComputedStyle(cab).backgroundColor,
                anel_desenhado: anel.dataset.anel === '1',
                anel_quadrado: Math.abs(r.width - r.height) < 2 && r.width > 100,
                marca: (document.querySelector('.lg-marca span') || {}).textContent,
                logo: (document.querySelector('.lg-head img') || {}).getAttribute('alt'),
                link_fora_do_cartao: link.top > cartao.bottom,
                campo_alto: document.querySelector('#fone').getBoundingClientRect().height}; }""")
    assert m["entrando"] and m["gradiente"], m
    assert m["cabecalho"] == "rgb(11, 25, 38)", m          # o navy da casa
    assert m["anel_desenhado"] and m["anel_quadrado"], m
    assert m["marca"] == "CÓRTEX" and m["logo"] == "Sulista", m
    assert m["link_fora_do_cartao"], m
    # alvo de toque de celular: 48px, e não os ~38 do painel
    assert m["campo_alto"] >= 48, m


def test_o_codigo_chega_e_a_sessao_abre(pagina):
    """O fluxo inteiro: telefone → código → app. A mensagem que a página
    mostra é a do SERVIDOR, e ela é a mesma para número que existe e que não
    existe — a página não acrescenta nada que denuncie o caso."""
    pg = _abre(pagina, sessao=False)
    pg.route("**/api/agregado/entrar", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "mensagem": "Se este número estiver cadastrado, "
                                                 "o código de entrada chegou no seu WhatsApp."})))
    pg.route("**/api/agregado/confirmar", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "nome": "Transportes Fulano"})))
    pg.fill("#fone", "41999990001")
    pg.click("#b-pedir")
    pg.wait_for_selector("#tela-codigo", state="visible")
    assert "cadastrado" in pg.inner_text("#m-codigo")
    # A SESSÃO PASSA A EXISTIR: o `eu` respondia 401 (o teste começa
    # deslogado), e é o cookie do confirmar que o faz responder. A rota
    # registrada por ÚLTIMO é a avaliada primeiro no Playwright.
    pg.route("**/api/agregado/eu", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(EU)))
    pg.fill("#codigo", "123456")
    pg.click("#b-confirmar")
    pg.wait_for_selector("#app", state="visible")
    assert "Transportes Fulano" in pg.inner_text("#ag-nome")
    assert "2 veículos ativos" in pg.inner_text("#ag-sub")


def test_o_telefone_em_dois_cadastros_pergunta_quem_e(pagina):
    pg = _abre(pagina, sessao=False)
    pg.route("**/api/agregado/entrar", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps({"ok": True, "mensagem": "ok"})))
    pg.route("**/api/agregado/confirmar", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"escolher": [{"id": 7, "nome": "Fulano de Tal"},
                                      {"id": 8, "nome": "Transportes Fulano"}]})))
    pg.fill("#fone", "41999990001")
    pg.click("#b-pedir")
    pg.fill("#codigo", "123456")
    pg.click("#b-confirmar")
    pg.wait_for_selector("#tela-escolha", state="visible")
    assert pg.locator("#lista-escolha button").count() == 2
    assert "Transportes Fulano" in pg.inner_text("#lista-escolha")


def test_o_resumo_separa_a_pagar_de_em_aberto_e_de_pago(pagina):
    """Juntar "fechado" com "pago" faria o app dizer que o dinheiro saiu
    quando ele só foi calculado."""
    pg = _abre(pagina)
    t = pg.inner_text("#tela-resumo")
    assert "11.300,00" in t and "acerto fechado a pagar" in t
    assert "7.400,00" in t and "acerto em aberto" in t
    assert "15.300,00" in t and "acerto pago" in t
    assert "1 lançamento aguardando aprovação" in t
    assert _sem_rolagem_lateral(pg) == 0


def test_a_aba_de_acertos_marca_cada_situacao_e_abre_o_detalhe(pagina):
    pg = _abre(pagina)
    t = _ver(pg, "acertos")
    for palavra in ("a pagar", "pago", "em aberto"):
        assert palavra in t, (palavra, t[:300])
    pg.click("#tela-acertos [data-acerto='1/8801']")
    pg.wait_for_function(
        "() => { const b = document.getElementById('modalBox');"
        " return document.getElementById('modalBg').classList.contains('aberto')"
        " && !b.textContent.includes('carregando'); }")
    m = pg.inner_text("#modalBox")
    assert "Acerto 8801" in m
    for bloco in ("Viagens", "Despesas", "Adiantamentos", "Descontos"):
        assert bloco in m, bloco
    assert "ABASTECIMENTO INTERNO" in m
    assert _sem_rolagem_lateral(pg) == 0


def test_as_abas_de_viagem_diesel_extras_e_ocorrencia_desenham(pagina):
    pg = _abre(pagina)
    casos = [("viagens", "CURITIBA/PR"), ("abastecimentos", "320,5 L"),
             ("lancamentos", "KM FALTOU PAGAR (+)"),
             ("ocorrencias", "ATRASO NA ENTREGA - TRANSITO")]
    for aba, trecho in casos:
        assert trecho in _ver(pg, aba), (aba, trecho)
        assert _sem_rolagem_lateral(pg) == 0


def _folha(pg):
    """Espera a folha de detalhe abrir E o conteúdo chegar.

    Esperar só o `.aberto` mediria o "carregando…" — a mesma espera fraca que
    já enganou o helper das abas aqui. Conserta-se esperando o carregamento
    SUMIR, nunca afrouxando a asserção.
    """
    pg.wait_for_function(
        "() => { const b = document.getElementById('modalBox');"
        " return document.getElementById('modalBg').classList.contains('aberto')"
        " && b.textContent.trim().length > 0"
        " && !b.textContent.includes('carregando'); }")
    return pg.inner_text("#modalBox")


def test_a_barra_tem_sete_itens_e_a_conta_SAIU_dela(pagina):
    """O aperto é aritmética, não gosto: com `conta` na barra eram OITO itens
    num celular de 390px — 48px por alvo, e o rótulo já vinha abreviado
    ("Ocorrén."). O app do motorista parou em seis pela mesma conta.

    A largura mínima é medida no NAVEGADOR, e não calculada aqui: é o único
    lugar que sabe o que o flex fez de verdade.
    """
    pg = _abre(pagina)
    rotulos = pg.eval_on_selector_all(
        "#navbar button", "es => es.map(e => e.dataset.aba)")
    assert rotulos == ["resumo", "acertos", "viagens", "abastecimentos",
                       "lancamentos", "ocorrencias", "canal"], rotulos
    assert "conta" not in rotulos
    larguras = pg.eval_on_selector_all(
        "#navbar button", "es => es.map(e => e.getBoundingClientRect().width)")
    assert min(larguras) >= 50, larguras
    # e cada item tem DESENHO além do rótulo — é o que dispensa abreviar
    assert pg.eval_on_selector_all("#navbar button svg", "es => es.length") == 7


def test_os_botoes_DENTRO_do_app_tem_o_estilo_da_casa(pagina):
    """A armadilha de especificidade desta casa, medida no navegador.

    O estilo do botão grande mora em `.lg-body button.lg-btn` — qualificado
    pelo cartão de ENTRADA. Dentro do app a regra existe, está certa e NÃO
    VALE: "Sair deste aparelho" e o botão de enviar do canal saíam com a cara
    nativa do navegador, pequenos e encostados à esquerda, desde que foram
    escritos. Teste de estilo lê `getComputedStyle`/caixa real, nunca o texto
    do CSS — só o navegador sabe quem venceu.
    """
    pg = _abre(pagina)
    _ver(pg, "conta")
    caixa = pg.evaluate(
        "() => { const b = document.getElementById('b-sair');"
        " const r = b.getBoundingClientRect();"
        " return {w: r.width, h: r.height,"
        "         fundo: getComputedStyle(b).backgroundColor}; }")
    assert caixa["w"] >= 300, ("o botão não ocupa a largura do cartão", caixa)
    assert caixa["h"] >= 44, ("alvo de dedo pequeno demais", caixa)
    assert caixa["fundo"] not in ("rgba(0, 0, 0, 0)", "rgb(239, 239, 239)"), caixa


def test_a_conta_abre_pelo_cabecalho_e_ACENDE_ali(pagina):
    """Sair da barra não pode virar "sumiu": se nenhum item acende quando a
    conta está aberta, a tela parece ter perdido o rumo."""
    pg = _abre(pagina)
    assert "ABC1D23" in _ver(pg, "conta")
    assert pg.get_attribute("#b-conta", "aria-current") == "page"
    acesos = pg.eval_on_selector_all(
        "#navbar button[aria-current='page']", "es => es.length")
    assert acesos == 0, "a barra continuou com um item aceso fora da aba aberta"
    # e voltar para uma aba da barra apaga o botão do cabeçalho
    _ver(pg, "acertos")
    assert pg.get_attribute("#b-conta", "aria-current") is None


@pytest.mark.parametrize("aba,seletor,esperados", [
    # O QUE CADA FOLHA PRECISA DIZER, e em toda ela há pelo menos um dado que a
    # LINHA não mostrava — senão a folha é um clique que não responde nada.
    ("viagens", "#tela-viagens [data-idx='0']",
     ["Viagem 55012", "CURITIBA/PR", "SAO BERNARDO DO CAMPO/SP", "412 km", "9.200,00"]),
    # preço por litro e odômetro vinham do servidor desde o primeiro dia e a
    # lista não tinha onde dizê-los
    ("abastecimentos", "#tela-abastecimentos [data-idx='0']",
     ["320,5 L", "6,18", "812.345", "2,31 km/L", "1.980,00"]),
    ("lancamentos", "#tela-lancamentos [data-idx='0']",
     ["ADICIONAL ENTREGAS", "aprovado", "350,00"]),
    ("ocorrencias", "#tela-ocorrencias [data-idx='0']",
     ["ATRASO NA ENTREGA - TRANSITO", "44120", "ABC1D23"]),
    ("conta", "#tela-conta [data-idx='0']",
     ["ABC1D23", "SCANIA", "R450", "1042", "CAVALO MECANICO", "ativo"]),
])
def test_cada_lista_ABRE_A_FOLHA_com_o_que_a_linha_nao_cabia(pagina, aba, seletor, esperados):
    """Antes desta versão só o acerto tinha detalhe: viagem, diesel, extras,
    ocorrência e veículo eram linhas mortas — e o acerto, que abria, tinha a
    mesma cara de uma linha que não abre."""
    pg = _abre(pagina)
    _ver(pg, aba)
    pg.click(seletor)
    texto = _folha(pg)
    for trecho in esperados:
        assert trecho in texto, (aba, trecho, texto[:400])
    assert _sem_rolagem_lateral(pg) == 0


def test_a_folha_fecha_PELO_TOPO_sem_rolar_ate_o_fim(pagina):
    """O fechar morava só no fim, depois da lista: num acerto com dez viagens
    era preciso rolar a folha inteira para sair. Sair de uma tela não pode
    depender do tamanho do conteúdo dela."""
    pg = _abre(pagina)
    _ver(pg, "viagens")
    pg.click("#tela-viagens [data-idx='0']")
    _folha(pg)
    x = pg.query_selector("#modalBox .mhead .mx")
    assert x is not None, "a folha não tem fechar no topo"
    caixa = pg.evaluate(
        "() => { const r = document.querySelector('#modalBox .mhead .mx')"
        ".getBoundingClientRect(); return {w: r.width, h: r.height}; }")
    assert caixa["w"] >= 44 and caixa["h"] >= 44, caixa   # alvo de dedo
    # O FECHAR DO RODAPÉ TAMBÉM É BOTÃO DE VERDADE. O estilo do botão grande da
    # casa mora em `.lg-body button.lg-btn` — qualificado pelo cartão de
    # ENTRADA —, e a folha não é `.lg-body`: a regra existia, estava certa e
    # não valia aqui, e o botão saía com a cara nativa do navegador. Só o
    # navegador sabe quem venceu a especificidade, então o guard MEDE em vez de
    # procurar a regra no CSS.
    rodape = pg.evaluate(
        "() => { const b = document.querySelector('#modalBox button.lg-btn');"
        " if (!b) return null; const r = b.getBoundingClientRect();"
        " return {w: r.width, h: r.height}; }")
    assert rodape, "a folha ficou sem o fechar do rodapé"
    assert rodape["w"] >= 300 and rodape["h"] >= 44, rodape
    x.click()
    assert not pg.eval_on_selector("#modalBg", "e => e.classList.contains('aberto')")


def test_o_detalhe_do_acerto_mostra_A_CONTA_INTEIRA(pagina):
    """"Quanto deu" a lista já respondeu. Quem abre o acerto quer saber POR QUE
    deu isso — e a conta vem somada do ERP, pelo servidor: a página não soma
    nada, senão o total daqui poderia discordar do total de lá."""
    pg = _abre(pagina)
    _ver(pg, "acertos")
    pg.click("#tela-acertos [data-acerto='1/8801']")
    m = _folha(pg)
    assert "Acerto 8801" in m
    for parcela in ("18.400,00", "900,00", "5.000,00", "1.200,00", "11.300,00"):
        assert parcela in m, (parcela, m[:400])
    assert "Líquido a receber" in m
    assert _sem_rolagem_lateral(pg) == 0


def test_a_multa_e_dita_em_vez_de_virar_aba_com_zero(pagina):
    """A Smartec cobre a frota própria: zero infrações em placa de agregado em
    12 meses. Uma aba "Multas" vazia seria lida como "não tenho multa"."""
    pg = _abre(pagina)
    # o título do cartão é maiúsculo por CSS, e `innerText` respeita o
    # `text-transform` — a comparação é em minúsculas, nunca afrouxada
    t = _ver(pg, "lancamentos").lower()
    assert "multas" in t and "desconto no acerto" in t
    assert "multas" not in pg.inner_text("#navbar").lower()


def test_a_aba_some_quando_o_servidor_diz_que_a_pessoa_nao_tem_aquilo(pagina):
    """Item que não existe não abre vazio: 174 das 298 placas de agregado
    passam pela CtaPlus, e para as outras a aba de abastecimento abriria sempre
    vazia — o que ensina a duvidar do resto da tela."""
    eu = json.loads(json.dumps(EU))
    eu["secoes"]["abastecimentos"] = False
    pg = _abre(pagina, eu=eu)
    barra = pg.inner_text("#navbar")
    assert "Diesel" not in barra and "Acertos" in barra


def test_a_tarja_do_acesso_mestre_aparece_e_diz_de_quem_e_a_conta(pagina):
    eu = {**EU, "mestre": True}
    pg = _abre(pagina, eu=eu)
    tarja = pg.inner_text("#tarja-mestre")
    assert "ADMINISTRAÇÃO" in tarja and "Transportes Fulano" in tarja
    cor = pg.evaluate("getComputedStyle(document.getElementById('tarja-mestre')).backgroundColor")
    assert cor == "rgb(148, 40, 33)", cor      # o vermelho da marca


CANAL = {
    "conversas": [
        {"id": 31, "assunto": "acerto", "assunto_rotulo": "Acerto e pagamento",
         "origem": "agregado", "titulo": "", "status": "aguardando_agregado",
         "aberta": True, "criada_em": "2026-09-14T10:00:00-03:00",
         "ultima_em": "2026-09-15T16:20:00-03:00", "nao_lidas": 1,
         "resumo": "Já está na conta a pagar, vence sexta.", "atendente": "Fernanda"},
        {"id": 28, "assunto": "viagem", "assunto_rotulo": "Viagem e frete",
         "origem": "agregado", "titulo": "", "status": "resolvida",
         "aberta": False, "criada_em": "2026-09-02T08:00:00-03:00",
         "ultima_em": "2026-09-03T09:00:00-03:00", "nao_lidas": 0,
         "resumo": "Resolvido no acerto 8790.", "atendente": "Fernanda"},
    ],
    "nao_lidas": 1, "abertas": 1, "max_abertas": 5,
    "assuntos": [
        {"chave": "acerto", "rotulo": "Acerto e pagamento",
         "ajuda": "Diga o NÚMERO do acerto — ele aparece na aba Acertos."},
        {"chave": "viagem", "rotulo": "Viagem e frete", "ajuda": "Diga a PLACA e a data."},
    ],
    "fonte": "CÓRTEX · canal do setor de agregados",
}

CONVERSA = {
    "conversa": {"id": 31, "assunto": "acerto", "assunto_rotulo": "Acerto e pagamento",
                 "origem": "agregado", "titulo": "", "status": "aguardando_agregado",
                 "aberta": True, "criada_em": "2026-09-14T10:00:00-03:00",
                 "atendente": "Fernanda"},
    "mensagens": [
        {"id": 1, "papel": "sistema", "autor": "", "texto": "Pedido aberto sobre Acerto e pagamento.",
         "evento": "abertura", "quando": "2026-09-14T10:00:00-03:00"},
        {"id": 2, "papel": "agregado", "autor": "Transportes Fulano",
         "texto": "O acerto 8801 não caiu na conta.", "evento": "",
         "quando": "2026-09-14T10:00:05-03:00"},
        {"id": 3, "papel": "setor", "autor": "Fernanda",
         "texto": "Já está na conta a pagar, vence sexta.", "evento": "",
         "quando": "2026-09-15T16:20:00-03:00"},
    ],
}


def test_a_aba_falar_lista_os_pedidos_e_diz_quem_atende(pagina):
    """O canal é FILA: cada pedido mostra assunto, estado e quem está com ele."""
    pg = _abre(pagina, **{"/api/agregado/conversas": (CANAL, 200)})
    t = _ver(pg, "canal")
    assert "Acerto e pagamento" in t and "Fernanda" in t
    assert "1 nova" in t                      # a resposta que ele ainda não leu
    assert "encerrado" in t                   # o pedido resolvido, marcado
    assert _sem_rolagem_lateral(pg) == 0


def test_abrir_um_pedido_mostra_a_ajuda_do_assunto_antes_de_escrever(pagina):
    """O texto de ajuda resolve metade dos pedidos ANTES de virar fila."""
    pg = _abre(pagina, **{"/api/agregado/conversas": (CANAL, 200)})
    _ver(pg, "canal")
    pg.select_option("#canal-assunto", "acerto")
    assert "NÚMERO do acerto" in pg.inner_text("#canal-ajuda")


def test_a_conversa_abre_com_a_linha_do_tempo_e_deixa_responder(pagina):
    pg = _abre(pagina, **{"/api/agregado/conversas": (CANAL, 200)})
    _ver(pg, "canal")
    pg.route("**/api/agregado/conversas/31", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(CONVERSA)))
    pg.click("#tela-canal [data-conversa='31']")
    pg.wait_for_function(
        "() => { const b = document.getElementById('modalBox');"
        " return document.getElementById('modalBg').classList.contains('aberto')"
        " && !b.textContent.includes('carregando'); }")
    m = pg.inner_text("#modalBox")
    assert "Acerto e pagamento" in m and "aguardando você" in m
    assert "Fernanda" in m and "vence sexta" in m
    assert "Pedido aberto sobre" in m          # o evento na mesma linha do tempo
    assert pg.is_visible("#b-canal-responder")


def test_com_o_teto_de_pedidos_abertos_o_formulario_da_lugar_ao_aviso(pagina):
    """Item que a pessoa não pode usar não fica lá desabilitado sem explicação:
    o formulário some e a tela diz por quê."""
    cheio = json.loads(json.dumps(CANAL))
    cheio["abertas"] = cheio["max_abertas"]
    pg = _abre(pagina, **{"/api/agregado/conversas": (cheio, 200)})
    t = _ver(pg, "canal")
    assert "5 pedidos em aberto" in t
    assert not pg.is_visible("#canal-assunto")


def test_a_conta_lista_os_veiculos_e_permite_sair(pagina):
    pg = _abre(pagina)
    t = _ver(pg, "conta")
    assert "ABC1D23" in t and "SCANIA" in t and "inativo" in t
    pg.route("**/api/agregado/sair", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps({"ok": True})))
    pg.click("#b-sair")
    pg.wait_for_selector("#tela-entrar", state="visible")


def test_sessao_vencida_no_meio_do_uso_volta_para_a_entrada(pagina):
    pg = _abre(pagina, **{"/api/agregado/viagens": ({"mensagem": "Sua sessão terminou."}, 401)})
    pg.click("#navbar button[data-aba='viagens']")
    pg.wait_for_selector("#tela-entrar", state="visible")


def test_a_pagina_nunca_manda_de_quem_e_o_que_ela_pede(pagina):
    """O escopo vem do cookie. Uma página que mandasse "de quem" teria, na
    barra de endereço, o seletor de vítima."""
    pg = _abre(pagina)
    for aba in ("acertos", "viagens", "abastecimentos", "lancamentos", "ocorrencias"):
        _ver(pg, aba)
    proibidos = ("proprietario", "cod=", "cpf", "cnpj", "dono")
    for p in pg.pedidos:
        assert not any(x in p.lower() for x in proibidos), p
