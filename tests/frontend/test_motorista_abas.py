# -*- coding: utf-8 -*-
"""As abas do app do motorista, NO NAVEGADOR — e a tarja do acesso mestre.

POR QUE ESTE ARQUIVO É DE NAVEGADOR e não de payload: as três coisas que ele
guarda só existem depois que o navegador executa a página.

1. **A ABA QUE NÃO EXISTE PARA A PESSOA NÃO APARECE.** Dois terços dos
   motoristas são agregados e nunca terão jornada apurada. Ler o texto-fonte
   provaria que o código do filtro existe; só o navegador diz que o botão não
   está lá.
2. **A TARJA DO ACESSO MESTRE É OBRIGATÓRIA.** Quem administra abre a conta de
   outra pessoa e esquece em que conta está — e um print de tela sem a tarja
   vira "o app mostrou isso ao motorista", que é falso. A tarja vem da SESSÃO
   (`mestre` no `/api/motorista/eu`), não de uma variável da página.
3. **CADA ABA CARREGA SOZINHA, na primeira vez.** Seis chamadas no boot, num
   4G de rodovia, é um app que demora dez segundos para abrir. Aqui se conta
   quantas requisições saíram — que é a única forma de provar "sob demanda".

E a página NÃO PODE ROLAR PARA O LADO. A régua da casa (`medir_paineis.py`)
mede desktop e não serve aqui; a régua deste app é a largura de um celular, e
`scrollWidth - clientWidth` tem de ser zero — foi assim que a grade de cards do
painel nasceu com o cartão da direita fora da tela, sem erro nenhum.
"""
from __future__ import annotations

import json

EU = {"nome": "João da Silva", "telefone": "5547999990001", "mestre": False,
      "secoes": {"viagem": True, "produtividade": True, "desempenho": True,
                 "multas": True, "ocorrencias": True, "jornada": False}}

VIAGEM = {"viagem": {
    "numero": "178010", "placa": "NYP3J22", "carretas": ["JOK3011"],
    "cliente": "INDUSTRIA EXEMPLO", "origem": "JOINVILLE/SC",
    "destino": "CURITIBA/PR", "saida": "2026-09-06 06:10",
    "previsao_chegada": "2026-09-06 14:00", "vazio": False}}

#: Payloads copiados do FORMATO real que os módulos devolvem (medidos contra o
#: banco vivo em 07/09/2026). Dublê mais pobre que o original esconde
#: justamente o caminho que interessa.
PRODUTIVIDADE = {
    "atual": {"viagens": 20, "concluidas": 20, "em_curso": 0, "vazias": 10,
              "km": 2097, "com_km": 20, "dias_com_viagem": 11, "ufs": 1,
              "placas": 1, "km_por_dia": 191},
    "anterior": {"viagens": 21, "concluidas": 21, "em_curso": 0, "vazias": 10,
                 "km": 1936, "com_km": 21, "dias_com_viagem": 11, "ufs": 1,
                 "placas": 2, "km_por_dia": 176},
    "variacao": {"viagens": -4.8, "km": 8.3},
    "destinos": [{"destino": "SAO PAULO/SP", "viagens": 8},
                 {"destino": "ITU/SP", "viagens": 3}],
    "destinos_viagens": 11, "destinos_topo": 5, "janela_dias": 30,
    "fonte": "ERP AVA · programacaoembarque (km contratado da viagem)"}

MULTAS = {
    "itens": [{"id": "a37", "especie": "notificacao", "placa": "TBA3C65",
               "data": "2026-08-04", "hora": "10:09",
               "descricao": "Velocidade - ate 20%", "onde": "ARUJA · SP",
               "local": "SP 031", "valor": 195.23, "valor_com_desconto": None,
               "pontos": 4, "vencimento": None, "prazo_indicacao": "2026-09-10",
               "prazo_faltam": 3, "prazo_urgente": True, "em_aberto": True,
               "rota": "SAO PAULO/SP → ITU/SP", "hipotese": True,
               "disputada": False}],
    "resumo": {"multas_abertas": 0, "notificacoes_abertas": 1,
               "valor_aberto": 0.0, "pontos": 0, "total_12m": 1,
               "com_prazo_urgente": 1},
    "pontos_ressalva": "Pontos das multas já em penalidade.",
    "janela_dias": 365,
    "atribuicao": "Estas infrações apareceram nas placas e nos horários das "
                  "SUAS viagens. Isso não é indicação de condutor.",
    "fonte": "Smartec"}

DESEMPENHO = {
    "tem_dado": True,
    "nota": {"competencia": "2026-08", "parcial": False, "nota": 98.0,
             "km": 1859, "posicao": 4, "ranqueados": 87, "abaixo_do_piso": 14,
             "km_piso": 500.0, "nota_mediana_frota": 75.0,
             "sem_ranking_motivo": None},
    # A evolução com DOIS meses (o mínimo para a lista aparecer) e com o
    # PARCIAL marcado — é a forma real do payload, não uma lista vazia que
    # deixaria esse caminho do desenho sem nenhum teste passando por ele.
    "evolucao": [{"competencia": "2026-07", "parcial": False, "nota": 91.0,
                  "km": 1700},
                 {"competencia": "2026-08", "parcial": False, "nota": 98.0,
                  "km": 1859}],
    "competencia": "2026-08", "parcial": False,
    "placas": ["TBA3C65"], "veiculo_compartilhado": True,
    "indicadores": [{"chave": "idle", "rotulo": "Motor ligado parado",
                     "pct": 35.0, "menor_melhor": True, "mediana_frota": 12.0,
                     "p25_frota": 6.0, "p75_frota": 21.0,
                     "veiculos_na_frota": 46, "distancia_pp": 23.0,
                     "pior_que_a_frota": True, "no_quarto_pior": True,
                     "motoristas_no_mes": 3}],
    "melhorar": [{"chave": "idle", "rotulo": "Motor ligado parado", "pct": 35.0,
                  "menor_melhor": True, "mediana_frota": 12.0,
                  "p25_frota": 6.0, "p75_frota": 21.0,
                  "veiculos_na_frota": 46, "distancia_pp": 23.0,
                  "pior_que_a_frota": True, "no_quarto_pior": True,
                  "motoristas_no_mes": 3,
                  "o_que": "Tempo com o motor ligado e o caminhão parado.",
                  "como": "Desligue o motor na fila, na doca e na espera."}],
    "melhorar_criterio": "Aparece aqui o que está no quarto pior da frota.",
    "melhorar_vazio": "Nada a apontar.",
    "ressalva": "Os indicadores abaixo são do VEÍCULO no mês.",
    "fonte": "Gobrax"}

OCORRENCIAS = {
    "itens": [{"data": "2026-08-20", "tipo": "MULTA DE TRANSITO (LEVE)",
               "codigo": 2, "veiculo": "TBA3C65", "tratada_em": None,
               "situacao_codigo": 1, "merito": False}],
    "resumo": {"total_12m": 1, "recentes_30d": 1, "sem_solucao": 1,
               "meritos": 0},
    "janela_dias": 365, "recente_dias": 30, "fonte": "ERP AVA"}


def _rotas(pg, eu=None):
    corpos = {"/api/motorista/eu": eu or EU,
              "/api/motorista/viagem": VIAGEM,
              "/api/motorista/produtividade": PRODUTIVIDADE,
              "/api/motorista/multas": MULTAS,
              "/api/motorista/desempenho": DESEMPENHO,
              "/api/motorista/ocorrencias": OCORRENCIAS,
              "/api/motorista/jornada": {"tem_dado": False, "motivo": "x",
                                         "fonte": "RasterJOR"}}
    pedidas = []

    def rota(route):
        caminho = route.request.url.split("?")[0]
        for chave, corpo in corpos.items():
            if caminho.endswith(chave):
                pedidas.append(chave)
                return route.fulfill(status=200,
                                     content_type="application/json",
                                     body=json.dumps(corpo))
        route.fulfill(status=200, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    return pedidas


def _ir(pg, aba):
    """Clica na aba e ESPERA O CONTEUDO, nao a secao.

    `abrirAba` e assincrona: a secao aparece na hora e o cartao fica em
    "Carregando..." ate a resposta chegar. Esperar so pelo `:not([hidden])` da
    secao le o placeholder e o teste falha por corrida, nao por defeito — que e
    o jeito mais barato de ninguem mais confiar na suite.
    """
    pg.click("#navbar button[data-aba='%s']" % aba)
    pg.wait_for_selector("#tela-%s:not([hidden])" % aba, timeout=15000)
    pg.wait_for_selector("#tela-%s .card:not(.carregando)" % aba, timeout=15000)


def _abrir(pg, base_url, eu=None):
    pedidas = _rotas(pg, eu)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 390, "height": 780})   # um celular de verdade
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    return pedidas, erros


def test_a_barra_desenha_so_as_abas_que_a_pessoa_TEM(pagina):
    """`secoes.jornada` é falso (é um agregado): o botão não pode existir.

    Uma aba que abre e diz "sem dados" para quem nunca vai ter dado ensina a
    pessoa a não confiar no resto da tela — é regra escrita do escopo.
    """
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url)
    abas = pg.eval_on_selector_all(
        "#navbar button", "els => els.map(e => e.dataset.aba)")
    assert abas == ["viagem", "produtividade", "desempenho", "multas",
                    "registros"], abas
    assert "jornada" not in abas
    assert not erros, erros


def test_a_aba_da_jornada_APARECE_quando_ha_apuracao(pagina):
    """A outra ponta do guard acima: sem ela, uma barra que nunca desenhasse a
    jornada passaria no teste de cima e o empregado nunca veria a dele."""
    pg, base_url = pagina
    eu = {**EU, "secoes": {**EU["secoes"], "jornada": True}}
    _, erros = _abrir(pg, base_url, eu)
    abas = pg.eval_on_selector_all(
        "#navbar button", "els => els.map(e => e.dataset.aba)")
    assert "jornada" in abas
    assert not erros, erros


def test_cada_aba_carrega_SO_quando_e_aberta(pagina):
    """Seis chamadas no boot, num 4G de rodovia, é um app que demora dez
    segundos para abrir. Contar as requisições é a única forma de provar
    "sob demanda" — o texto-fonte só provaria que a intenção existe."""
    pg, base_url = pagina
    pedidas, erros = _abrir(pg, base_url)
    assert sorted(set(pedidas)) == ["/api/motorista/eu", "/api/motorista/viagem"], \
        "o boot saiu buscando aba que ninguém abriu: %r" % sorted(set(pedidas))

    _ir(pg, "multas")
    assert "/api/motorista/multas" in pedidas

    # E a SEGUNDA visita não repete a chamada: o resultado fica guardado
    # enquanto a sessão viver.
    antes = pedidas.count("/api/motorista/multas")
    pg.click("#navbar button[data-aba='viagem']")
    pg.click("#navbar button[data-aba='multas']")
    pg.wait_for_timeout(300)
    assert pedidas.count("/api/motorista/multas") == antes
    assert not erros, erros


def test_as_cinco_abas_desenham_sem_erro_de_script(pagina):
    """Renderizar com o FORMATO REAL acha o que a leitura do código não acha —
    nulo no meio, campo que o payload não tem, chave escrita com outro nome."""
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url)
    for aba, marca in (("produtividade", "Últimos 30 dias"),
                       ("desempenho", "O que melhorar"),
                       ("multas", "Multas e notificações"),
                       ("registros", "Registros da operação")):
        _ir(pg, aba)
        texto = pg.text_content("#tela-%s" % aba)
        assert marca in texto, "%s não desenhou: %r" % (aba, texto[:200])
    assert not erros, erros


def test_a_multa_se_declara_HIPOTESE_na_tela(pagina):
    """O leitor é a pessoa acusada. "A viagem estava com o Fulano" não é "o
    Fulano cometeu a infração" — e a frase que diz isso vem do payload, não
    escrita na página: texto na página diverge do servidor."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    _ir(pg, "multas")
    texto = pg.text_content("#tela-multas")
    assert "não é indicação de condutor" in texto
    assert "INDICAR ATÉ" in texto, "o prazo de indicação não virou destaque"


def test_o_indicador_diz_que_e_do_VEICULO(pagina):
    """Não existe indicador por motorista na API da Gobrax — foi medido. "Seu
    motor ficou 35% ligado parado" seria uma frase falsa."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    _ir(pg, "desempenho")
    texto = pg.text_content("#tela-desempenho")
    assert "do VEÍCULO" in texto
    assert "mais de um motorista" in texto, (
        "o veículo teve três condutores no mês e a tela não disse")


# ------------------------------------------------------------ acesso mestre

def test_a_tarja_do_acesso_mestre_APARECE(pagina):
    """Obrigatória. Sem ela, quem administra esquece em que conta está — e um
    print de tela vira "o app mostrou isso ao motorista", que é falso."""
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url, {**EU, "mestre": True})
    pg.wait_for_selector("#tarja-mestre:not([hidden])", timeout=15000)
    texto = pg.text_content("#tarja-mestre")
    assert "ADMINISTRAÇÃO" in texto.upper()
    assert "João da Silva" in texto, "a tarja não diz de QUEM é a conta aberta"
    assert not erros, erros


def test_sem_acesso_mestre_a_tarja_NAO_aparece(pagina):
    """A outra ponta: uma tarja fixa passaria no teste de cima e assustaria
    todo motorista com um aviso de administração que não é dele."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.is_hidden("#tarja-mestre")


def test_a_entrada_mestre_nao_lista_ninguem_sem_codigo(pagina):
    """A página não decide se o código vale — quem decide é o servidor, nas
    DUAS rotas. Aqui se prova que ela não tenta sequer listar sem código."""
    pg, base_url = pagina
    pedidas, _ = _abrir(pg, base_url, {**EU, "mestre": False})
    pg.evaluate("void pedir('/api/motorista/sair', {method:'POST'})")
    pg.evaluate("void mostrar('tela-entrar')")
    pg.click("#b-abrir-mestre")
    pg.wait_for_selector("#tela-mestre:not([hidden])", timeout=15000)
    pg.click("#b-mestre")
    pg.wait_for_timeout(300)
    assert "/api/motorista/mestre/motoristas" not in pedidas
    assert "código mestre" in pg.text_content("#m-mestre").lower()


# ------------------------------------------------------------- a régua daqui

def test_a_pagina_nao_rola_para_o_LADO(pagina):
    """A régua deste app é a largura de um celular. A grade de cards do painel
    já nasceu com o cartão da direita fora da tela, sem erro nenhum, porque
    `1fr` é `minmax(auto,1fr)` e a trilha não encolhe abaixo do min-content."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    for aba in ("viagem", "produtividade", "desempenho", "multas", "registros"):
        _ir(pg, aba)
        sobra = pg.evaluate(
            "document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        assert sobra <= 0, "%s empurrou a página %d px para o lado" % (aba, sobra)


def test_a_barra_de_baixo_nao_cobre_o_fim_do_conteudo(pagina):
    """Sem a folga no fim da página, o último cartão fica debaixo da barra e
    ninguém descobre que há mais conteúdo ali."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    folga = pg.evaluate(
        "parseFloat(getComputedStyle(document.getElementById('app'))"
        ".paddingBottom)")
    altura = pg.evaluate(
        "document.getElementById('navbar').getBoundingClientRect().height")
    assert folga >= altura, (
        "a folga do fim (%.0f px) é menor que a barra (%.0f px)" % (folga, altura))


def test_a_nota_mes_a_mes_aparece_SEM_grafico(pagina):
    """A regra da casa é que todo gráfico é ECharts — e o ECharts são 990 KB
    que esta página não carrega, porque o leitor está no 4G de uma rodovia.
    A evolução sai em LISTA, com o número e a variação, que diz a mesma coisa e
    custa zero. Este guard também prova que a página não passou a carregar
    biblioteca nenhuma por baixo."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    _ir(pg, "desempenho")
    texto = pg.text_content("#tela-desempenho")
    assert "Sua nota mês a mês" in texto
    assert "07/2026" in texto and "08/2026" in texto
    assert "+7,7%" in texto, "a variação entre os meses não saiu: %r" % texto[:300]

    externos = pg.eval_on_selector_all(
        "script[src]", "els => els.map(e => e.getAttribute('src'))")
    assert externos == ["/static/anel.js"], (
        "a página do motorista passou a carregar script além da marca: %r"
        % externos)
