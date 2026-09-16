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
    "acerto": {"emissao": "2026-09-10", "bruto": 18400.0, "liquido": 11300.0, "fechado": True},
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
    pg.click(f"#navbar button[data-aba='{aba}']")
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
