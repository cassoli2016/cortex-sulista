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
                 "multas": True, "ocorrencias": True, "jornada": False,
                 "conversas": True},
      "avisos": {}}

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
    # SEIS, E NAO SETE: `produtividade` nao tem aba propria — os 30 dias sao o
    # primeiro bloco de `desempenho`, porque respondem a MESMA pergunta e
    # porque sete itens em 390 px dao 55 px cada, onde "Registros" ja nao cabe.
    assert abas == ["viagem", "desempenho", "multas", "registros", "rh"], abas
    assert "jornada" not in abas
    assert len(abas) <= 6, "a barra passou de seis itens — nao cabe no polegar"
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
    for aba, marca in (("desempenho", "Últimos 30 dias"),
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
    for aba in ("viagem", "desempenho", "multas", "registros", "rh"):
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


# ==================================================== o cabecalho da marca ==

def test_o_cabecalho_e_a_faixa_da_marca_com_as_DUAS_logos(pagina):
    """A logo da Sulista é BRANCA (`fill:#fff` no SVG, e é a única que a casa
    versiona): sobre o cinza do app ela simplesmente não existe. A faixa navy é
    o que a torna possível — e é a mesma cor do cartão de entrada, então as
    duas telas passam a ser a mesma marca.

    O anel também depende dela: o brilho dele é ADITIVO, e sobre fundo claro as
    linhas somam até o branco. Antes da faixa ele vinha com um disco escuro por
    baixo, que era remendo — e sobre a faixa esse disco seria uma mancha preta
    em cima de outra.
    """
    pg, base_url = pagina
    _, erros = _abrir(pg, base_url)

    fundo = pg.eval_on_selector(".appbar", "e => getComputedStyle(e).backgroundColor")
    assert fundo not in ("rgba(0, 0, 0, 0)", "transparent"), (
        "a faixa ficou sem fundo — a logo branca some e o anel lava")

    logo = pg.get_attribute(".appbar .sulista", "src")
    assert logo == "/static/sulista-logo-branco.svg"
    largura = pg.eval_on_selector(".appbar .sulista",
                                  "e => e.getBoundingClientRect().width")
    assert largura > 40, (
        "a logo da Sulista não está sendo desenhada (%.0f px)" % largura)
    assert "CÓRTEX" in pg.text_content(".appbar .wordmark")

    disco = pg.eval_on_selector(".anelmini",
                                "e => getComputedStyle(e).backgroundColor")
    assert disco in ("rgba(0, 0, 0, 0)", "transparent"), (
        "o anel manteve o disco de remendo: %r" % disco)
    assert not erros, erros


def test_a_faixa_nao_rola_para_o_lado_com_nome_comprido(pagina):
    """A logo, o wordmark e o botão disputam 390 px. Se algum deles não
    encolher, a faixa empurra a página para o lado — e a régua deste app é a
    largura de um celular, não os 900 px do painel."""
    pg, base_url = pagina
    _abrir(pg, base_url,
           {**EU, "nome": "JOSE CARLOS DE OLIVEIRA SOBRINHO FILHO"})
    sobra = pg.evaluate("document.documentElement.scrollWidth - "
                        "document.documentElement.clientWidth")
    assert sobra <= 0, "a faixa empurrou a página %d px para o lado" % sobra
    # O NOME FICA FORA DA FAIXA justamente por isto: lá ele sairia cortado no
    # primeiro sobrenome. Aqui cabe.
    assert "JOSE" in pg.text_content("#marca-sub").upper()


# ======================================================= o canal com o RH ==

CONVERSAS = {
    "conversas": [
        {"id": 7, "assunto": "ferias", "assunto_rotulo": "Férias",
         "origem": "motorista", "titulo": "", "status": "aguardando_motorista",
         "aberta": True, "criada_em": "2026-09-01T09:00:00",
         "ultima_em": "2026-09-06T15:00:00", "nao_lidas": 1,
         "resumo": "Suas férias vencem em 12/2026.", "pede_ciencia": False,
         "ciencia_em": None},
        {"id": 8, "assunto": "comunicado", "assunto_rotulo": "Comunicado do RH",
         "origem": "rh", "titulo": "Convenção coletiva 2026",
         "status": "aguardando_motorista", "aberta": True,
         "criada_em": "2026-09-05T09:00:00", "ultima_em": "2026-09-05T09:00:00",
         "nao_lidas": 1, "resumo": "O reajuste entra na folha de outubro.",
         "pede_ciencia": True, "ciencia_em": None}],
    "nao_lidas": 2, "pendencias": 1, "abertas": 2,
    "assuntos": [{"chave": "ferias", "rotulo": "Férias",
                  "ajuda": "Para pedir, adiantar ou tirar dúvida.",
                  "pede_ciencia": False},
                 {"chave": "contracheque", "rotulo": "Contracheque e descontos",
                  "ajuda": "Dúvida sobre valor ou desconto.",
                  "pede_ciencia": False}],
    "max_abertas": 5, "fonte": "CÓRTEX · canal do RH"}

CONVERSA = {
    "conversa": {"id": 7, "assunto": "ferias", "assunto_rotulo": "Férias",
                 "origem": "motorista", "titulo": "",
                 "status": "aguardando_motorista", "aberta": True,
                 "pede_ciencia": False, "criada_em": "2026-09-01T09:00:00",
                 "atendente": "Fernanda"},
    "mensagens": [
        {"id": 1, "papel": "sistema", "autor": "",
         "texto": "Pedido aberto sobre Férias.", "evento": "abertura",
         "quando": "2026-09-01T09:00:00"},
        {"id": 2, "papel": "motorista", "autor": "João",
         "texto": "Quando vencem minhas férias?", "evento": "",
         "quando": "2026-09-01T09:00:00"},
        {"id": 3, "papel": "rh", "autor": "Fernanda",
         "texto": "Vencem em 12/2026. Ja pode agendar.", "evento": "",
         "quando": "2026-09-06T15:00:00"}]}


def _com_rh(pg, eu):
    """As rotas do canal POR CIMA das outras.

    No Playwright a rota registrada por ÚLTIMO é avaliada primeiro — por isso
    esta vem depois de `_rotas`, e não antes.
    """
    pedidas = _rotas(pg, eu)

    def rota(route):
        u = route.request.url.split("?")[0]
        pedidas.append(u[u.index("/api"):])
        corpo = CONVERSAS if u.rstrip("/").endswith("/conversas") else CONVERSA
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/motorista/conversas**", rota)
    return pedidas


def _abrir_rh(pg, base_url, avisos=None):
    eu = {**EU, "secoes": {**EU["secoes"], "conversas": True},
          "avisos": avisos if avisos is not None else {"conversas": 2}}
    _com_rh(pg, eu)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 390, "height": 780})
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    return erros


def test_a_aba_do_RH_mostra_os_assuntos_e_a_lista(pagina):
    """NÃO É CHAT, e a tela diz isso sem escrever "isto não é um chat": quem
    abre um pedido escolhe um ASSUNTO e lê a AJUDA dele antes de escrever — é
    ela que resolve metade dos pedidos sem virar fila."""
    pg, base_url = pagina
    erros = _abrir_rh(pg, base_url)
    _ir(pg, "rh")
    texto = pg.text_content("#tela-rh")
    assert "Férias" in texto and "Contracheque" in texto
    assert "Para pedir, adiantar" in texto, "a ajuda do assunto não apareceu"
    assert "Convenção coletiva 2026" in texto
    assert "CONFIRME A LEITURA" in texto, "o comunicado sem ciência não avisa"
    assert not erros, erros


def test_a_bolinha_de_recado_aparece_na_barra(pagina):
    """É ela que faz o motorista ABRIR a aba. Sem isso, a resposta do RH espera
    até ele passar por ali por acaso — que é o "canal que ninguém lê" que o
    escopo do app temia."""
    pg, base_url = pagina
    _abrir_rh(pg, base_url)
    pg.wait_for_selector("#navbar button[data-aba='rh'] .pip", timeout=15000)
    assert pg.eval_on_selector_all(
        "#navbar button[data-aba='multas'] .pip", "e => e.length") == 0


def test_sem_recado_a_bolinha_nao_existe(pagina):
    """A outra ponta: uma bolinha fixa passaria no teste de cima e viraria um
    aviso permanente — que é a mesma coisa que aviso nenhum."""
    pg, base_url = pagina
    _abrir_rh(pg, base_url, avisos={})
    pg.wait_for_selector("#navbar button[data-aba='rh']", timeout=15000)
    assert pg.eval_on_selector_all("#navbar .pip", "e => e.length") == 0


def test_a_conversa_mostra_os_dois_lados_e_quem_atende(pagina):
    """"O RH" não devolve ligação nenhuma; "a Fernanda está com o seu pedido"
    devolve."""
    pg, base_url = pagina
    _abrir_rh(pg, base_url)
    _ir(pg, "rh")
    pg.click("[data-conversa='7']")
    pg.wait_for_selector(".rh-bolha.rh", timeout=15000)
    texto = pg.text_content("#tela-rh")
    assert "Quando vencem minhas férias?" in texto
    assert "Vencem em 12/2026" in texto
    assert "Fernanda" in texto
    # A fala DELE vai à direita — a convenção que diz, sem palavra nenhuma,
    # qual das duas é a dele.
    lado = pg.eval_on_selector(".rh-bolha.motorista",
                               "e => getComputedStyle(e).marginLeft")
    assert lado != "0px", "a bolha do motorista não foi para a direita"


def test_a_aba_do_RH_some_se_o_servidor_disser_que_nao_ha(pagina):
    """`secoes` manda, aqui como na jornada: a barra desenha o que o servidor
    disser, e não uma lista fixa da página."""
    pg, base_url = pagina
    eu = {**EU, "secoes": {**EU["secoes"], "conversas": False}}
    _com_rh(pg, eu)
    pg.set_viewport_size({"width": 390, "height": 780})
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    abas = pg.eval_on_selector_all("#navbar button",
                                   "els => els.map(e => e.dataset.aba)")
    assert "rh" not in abas


# =========================================================== o mural =======

MURAL = {"comunicados": [
    {"id": 5, "titulo": "Convenção coletiva 2026",
     "texto": "A convenção foi assinada.\nO reajuste entra na folha de outubro.",
     "autor": "fernanda@sulista.com.br", "quando": "2026-09-05T09:00:00",
     "confirmado": False, "confirmado_em": None},
    {"id": 4, "titulo": "Campanha de exames",
     "texto": "Procure o RH até 30/09.", "autor": "RH",
     "quando": "2026-09-01T09:00:00", "confirmado": True,
     "confirmado_em": "2026-09-02T10:00:00"}],
    "pendentes": 1}


def _com_mural(pg, eu):
    """As rotas do canal E do mural. A registrada por ÚLTIMO vence."""
    pedidas = _com_rh(pg, eu)

    def rota(route):
        u = route.request.url.split("?")[0]
        pedidas.append(u[u.index("/api"):])
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(MURAL if u.endswith("/mural")
                                      else {"ok": True}))

    pg.route("**/api/motorista/mural**", rota)
    return pedidas


def _abrir_mural(pg, base_url):
    eu = {**EU, "secoes": {**EU["secoes"], "conversas": True},
          "avisos": {"conversas": 3}}
    pedidas = _com_mural(pg, eu)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 390, "height": 780})
    pg.goto("%s/static/motorista.html" % base_url)
    pg.wait_for_selector("#tela-viagem:not([hidden])", timeout=15000)
    return pedidas, erros


def test_o_comunicado_vem_ANTES_do_pedido_dele(pagina):
    """O comunicado é o único item desta aba que a empresa PRECISA que ele
    leia. Um pedido de férias dele pode esperar a rolagem; a convenção
    coletiva, não."""
    pg, base_url = pagina
    _, erros = _abrir_mural(pg, base_url)
    _ir(pg, "rh")
    texto = pg.text_content("#tela-rh")
    assert "Convenção coletiva 2026" in texto
    assert "comunicado espera a sua confirmação" in texto
    # a ordem na tela: comunicados antes de "Seus pedidos"
    assert texto.index("Comunicados da empresa") < texto.index("Seus pedidos")
    assert not erros, erros


def test_o_texto_do_comunicado_PRESERVA_a_quebra_de_linha(pagina):
    """O RH separa parágrafo, e colapsar isso vira um bloco que ninguém lê."""
    pg, base_url = pagina
    _abrir_mural(pg, base_url)
    _ir(pg, "rh")
    assert pg.eval_on_selector(".rh-comunicado",
                               "e => getComputedStyle(e).whiteSpace") == "pre-wrap"


def test_ABRIR_A_ABA_ja_conta_como_visto(pagina):
    """"Viu e não confirmou" e "nunca abriu" são duas conversas diferentes com
    a pessoa, e o RH precisa das duas. O carimbo sai sozinho ao abrir."""
    pg, base_url = pagina
    pedidas, _ = _abrir_mural(pg, base_url)
    _ir(pg, "rh")
    pg.wait_for_timeout(400)
    assert "/api/motorista/mural/5/visto" in pedidas
    # e SÓ para o que falta confirmar — o já confirmado não se remarca
    assert "/api/motorista/mural/4/visto" not in pedidas


def test_o_ja_confirmado_mostra_a_data_e_nao_o_botao(pagina):
    """Pedir de novo o que ele já fez é o jeito de ele parar de acreditar no
    pedido — inclusive no comunicado seguinte."""
    pg, base_url = pagina
    _abrir_mural(pg, base_url)
    _ir(pg, "rh")
    texto = pg.text_content("#tela-rh")
    assert "VOCÊ CONFIRMOU EM" in texto
    botoes = pg.eval_on_selector_all("[data-mural]", "e => e.map(x => x.dataset.mural)")
    assert botoes == ["5"], "o comunicado já confirmado ganhou botão: %r" % botoes
