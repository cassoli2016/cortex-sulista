# -*- coding: utf-8 -*-
"""O prêmio do ciclo no celular do motorista, NO NAVEGADOR.

Três coisas que só existem depois que a página executa, e que somem calado se
alguém mexer no desenho:

1. **PRÉVIA SE DIZ EM LETRAS.** O ciclo aberto ainda se move, e número de
   premiação errado na mão do premiado é discussão de salário. O selo e a
   frase têm de estar na tela, não numa ajuda escondida.
2. **O CARTÃO NÃO NASCE PARA QUEM ESTÁ FORA DA RÉGUA.** Dois terços de quem
   usa o app são agregados; a premiação por ciclo é dos próprios. Cartão que
   abre e diz "sem dados" para quem nunca vai ter dado ensina a pessoa a não
   confiar no resto da tela.
3. **UMA POSIÇÃO POR TELA.** A da Gobrax ordena a condução, a do ciclo ordena
   o PRÊMIO, e elas não coincidem — duas na mesma tela são duas brigas.

E a página não pode rolar para o lado: a régua deste app é a largura de um
celular.
"""
from __future__ import annotations

import json

from tests.frontend.test_motorista_abas import (DESEMPENHO, EU, OCORRENCIAS,
                                                PRODUTIVIDADE, VIAGEM)

PREMIO = {
    "tem_dado": True, "fora_do_escopo": False,
    "ciclo": "2026-09", "rotulo": "16/08 a 15/09 de 2026",
    "fechado": False, "previa": True,
    "nota": 78.4, "status": "ATENCAO", "categoria": "OURO",
    "reputacao": 96.0, "ciclos_limpos": 5,
    "pilares": [
        {"chave": "gobrax", "rotulo": "Condução", "nota": 80.0, "peso": 40,
         "entrou": True, "explica": "a nota da telemetria no mês"},
        {"chave": "conduta", "rotulo": "Comportamento", "nota": 88.0,
         "peso": 40, "entrou": True, "explica": "as ocorrências no seu nome"},
        {"chave": "gr", "rotulo": "Gerenciamento de risco", "nota": None,
         "peso": 20, "entrou": False, "explica": "os alertas do rastreamento"},
    ],
    "ausentes": ["gr"], "posicao": 12, "de": 81,
    "premio": {"valor": 784.0, "base": 1000.0, "pct": 78.4, "motivo": ""},
    "desvios": [{"nome": "Excesso de velocidade", "grav": "MODERADA",
                 "pts": 7, "data": "2026-09-02"}],
    "meritos": 1,
    "historico": [{"ciclo": "2026-08", "rotulo": "16/07 a 15/08 de 2026",
                   "nota": 91.0, "valor": 910.0}],
    "fonte": "Gestão de Motoristas · cálculo do ciclo em curso",
}


def _tem(texto, *pedacos):
    """`inner_text` devolve o texto RENDERIZADO, e os títulos deste app são
    maiúsculos por CSS. Comparar sem caso evita um guard que quebra no dia em
    que alguém mexe no `text-transform` sem mexer no conteúdo."""
    baixo = texto.lower()
    faltam = [p for p in pedacos if p.lower() not in baixo]
    assert not faltam, "não apareceu na tela: " + str(faltam)


def _abrir(pg, base_url, premio=None, eu=None):
    corpos = {"/api/motorista/eu": eu or EU,
              "/api/motorista/viagem": VIAGEM,
              "/api/motorista/produtividade": PRODUTIVIDADE,
              "/api/motorista/desempenho": DESEMPENHO,
              "/api/motorista/ocorrencias": OCORRENCIAS,
              "/api/motorista/premiacao": PREMIO if premio is None else premio,
              "/api/motorista/multas": {"itens": [], "resumo": {}, "fonte": "x"},
              "/api/motorista/jornada": {"tem_dado": False, "motivo": "x",
                                         "fonte": "RasterJOR"}}

    def rota(route):
        caminho = route.request.url.split("?")[0]
        for chave, corpo in corpos.items():
            if caminho.endswith(chave):
                return route.fulfill(status=200,
                                     content_type="application/json",
                                     body=json.dumps(corpo))
        route.fulfill(status=200, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 390, "height": 780})
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    pg.click("#navbar button[data-aba='desempenho']")
    pg.wait_for_selector("#tela-desempenho:not([hidden])", timeout=15000)
    pg.wait_for_selector("#tela-desempenho .card:not(.carregando)", timeout=15000)
    return erros


def test_o_premio_abre_PRIMEIRO_e_diz_que_e_previa(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    primeiro = pg.inner_text("#card-desempenho .card:first-child")
    _tem(primeiro, "Seu prêmio", "16/08 a 15/09", "PRÉVIA", "pode mudar",
         "R$ 784,00", "78,4", "12º", "81")


def test_ciclo_FECHADO_troca_o_selo_e_a_frase(pagina):
    pg, base_url = pagina
    pago = {**PREMIO, "fechado": True, "previa": False,
            "fonte": "Gestão de Motoristas · fotografia do fechamento"}
    _abrir(pg, base_url, premio=pago)
    primeiro = pg.inner_text("#card-desempenho .card:first-child")
    _tem(primeiro, "PAGO", "foi para o pagamento", "Prêmio pago")
    assert "PRÉVIA" not in primeiro.upper()


def test_os_tres_pilares_aparecem_com_peso_e_o_ausente_e_DITO(pagina):
    """Nota renormalizada entre dois pilares não é comparável com a de três —
    quem lê precisa saber disso antes de comparar a sua com a do colega."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    _tem(pg.inner_text("#card-desempenho .card:first-child"),
         "Condução", "Comportamento", "Gerenciamento de risco",
         "peso 40%", "peso 20%", "não entrou")


def test_os_desvios_aparecem_e_a_MEDIDA_nao(pagina):
    """Ele vê os fatos; o nível sugerido é conversa do RH, e o app não dá a
    notícia antes dela. O servidor nem manda — este guard é a segunda porta."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    tela = pg.inner_text("#card-desempenho")
    _tem(tela, "Excesso de velocidade", "−7", "02/09/26")
    for proibido in ("N1", "N2", "N3", "N4", "Suspensão", "Advertência"):
        assert proibido.lower() not in tela.lower(), proibido


def test_o_que_JA_FOI_PAGO_aparece_por_ciclo(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    _tem(pg.inner_text("#card-desempenho"), "O que já foi pago",
         "16/07 a 15/08 de 2026", "R$ 910,00")


def test_sem_ocorrencia_o_cartao_DIZ_que_nao_houve(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url, premio={**PREMIO, "desvios": [], "meritos": 2})
    _tem(pg.inner_text("#card-desempenho"),
         "Nenhuma ocorrência registrada neste ciclo",
         "2 registro(s) a seu favor")


def test_AGREGADO_nao_ve_cartao_nenhum_de_premio(pagina):
    """`fora_do_escopo` é diferente de falha: um é "esta régua não é sua", o
    outro é "não consegui ler agora"."""
    pg, base_url = pagina
    fora = {"tem_dado": False, "fora_do_escopo": True,
            "motivo": "A premiação por ciclo é dos motoristas próprios.",
            "fonte": "Gestão de Motoristas"}
    _abrir(pg, base_url, premio=fora)
    tela = pg.inner_text("#card-desempenho").lower()
    assert "seu prêmio" not in tela and "motoristas próprios" not in tela
    assert tela.lstrip().startswith("últimos 30 dias"),         "os 30 dias continuam no topo para quem está fora da régua"


def test_fonte_fora_do_ar_DIZ_o_motivo_no_lugar_do_numero(pagina):
    pg, base_url = pagina
    caiu = {"tem_dado": False, "fora_do_escopo": False,
            "motivo": "Não consegui ler a premiação agora. Tente de novo "
                      "daqui a pouco.", "fonte": "Gestão de Motoristas"}
    _abrir(pg, base_url, premio=caiu)
    tela = pg.inner_text("#card-desempenho")
    _tem(tela, "Tente de novo")
    assert "R$" not in tela.upper().split("ÚLTIMOS")[0]


def test_UMA_posicao_por_tela(pagina):
    """Com o prêmio na tela, a nota da Gobrax vira PILAR: ela mostra o peso, e
    a palavra "posição" fica com quem decide o dinheiro."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    tela = pg.inner_text("#card-desempenho").lower()
    assert tela.count("posição") == 1
    _tem(tela, "Peso no prêmio", "um dos três pilares")


def test_sem_premio_a_nota_da_Gobrax_volta_a_ter_POSICAO(pagina):
    """Para o agregado nada muda: a tela dele continua a de antes."""
    pg, base_url = pagina
    _abrir(pg, base_url, premio={"tem_dado": False, "fora_do_escopo": True,
                                 "motivo": "x", "fonte": "y"})
    tela = pg.inner_text("#card-desempenho")
    _tem(tela, "Posição", "4º")
    assert "peso no prêmio" not in tela.lower()


def test_a_pagina_nao_rola_para_o_lado(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    sobra = pg.evaluate("() => document.documentElement.scrollWidth"
                        " - document.documentElement.clientWidth")
    assert sobra == 0, f"a tela do prêmio empurra {sobra}px para o lado"
