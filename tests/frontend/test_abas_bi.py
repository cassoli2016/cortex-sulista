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


def _grupos() -> list[str]:
    return sorted(set(re.findall(r'<div class="subtabs" role="tablist" '
                                 r'data-abas="(\w+)"', HTML)))


def _painel(grupo: str, aba: str) -> str:
    """O corpo de um painel de aba: do `<div class="aba"…>` até o próximo — ou
    até o FIM DA TELA, o que vier primeiro.

    O `</section>` não estava aqui, e na ÚLTIMA aba de um grupo o helper caía
    no `resto[:20000]`: vinte mil caracteres ADIANTE, atravessando o fim da
    tela e lendo a marcação das telas seguintes. Enquanto havia dois grupos de
    aba isso passava por sorte; com 31, a leitura vazada encontrou o gráfico de
    outra tela e acusou o painel de Antecipação-Portal de pôr gráfico em aba
    escondida — sendo que ele não tem gráfico nenhum.

    Medida que atravessa a fronteira do que se quer medir dá o número de outra
    coisa, e a acusação parece do código."""
    i = HTML.index('data-abas="%s" data-aba="%s"' % (grupo, aba))
    resto = HTML[i:]
    limites = [m.start() + 10 for m in
               [re.search(r'<div class="aba" data-abas=', resto[10:])] if m]
    fim = resto.find("</section>")
    if fim > 0:
        limites.append(fim)
    return resto[:min(limites)] if limites else resto


def test_EXATAMENTE_UMA_aba_por_painel_nasce_aberta():
    """Zero abertas deixa o painel em branco; duas abertas empilham conteúdo
    que deveria estar em lugares diferentes. Vale para todo grupo, inclusive
    os que ainda não existem."""
    grupos = _grupos()
    assert grupos, "nenhum painel com abas — o teste perdeu o alvo"
    for g in grupos:
        aberta = re.findall(
            r'<div class="aba" data-abas="' + g + r'" data-aba="(\w+)"'
            r'(?![^>]*\bhidden\b)[^>]*>', HTML)
        assert len(aberta) == 1, (g, aberta)


def test_a_aba_com_GRAFICO_e_a_que_nasce_aberta():
    """Regra dura: painel que puser o gráfico numa aba escondida terá um
    gráfico com os rótulos do eixo X suprimidos, sem erro nenhum aparecer — o
    `ResizeObserver` conserta na volta, mas nascer visível dispensa a
    correção.

    O teste era uma LISTA ESCRITA À MÃO de dois grupos. Lista assim envelhece
    calada: a Jornada virou quatro abas e não teria sido conferida. Agora ele
    varre todo `data-abas` que existir.
    """
    for g in _grupos():
        aberta = re.findall(
            r'<div class="aba" data-abas="' + g + r'" data-aba="(\w+)"'
            r'(?![^>]*\bhidden\b)[^>]*>', HTML)[0]
        # o painel tem gráfico se algum contêiner dele é alimentado por ECharts
        temGrafico = [a for a in re.findall(
            r'<div class="aba" data-abas="' + g + r'" data-aba="(\w+)"', HTML)
            if re.search(r'style="width:100%;height:\d+px"', _painel(g, a))]
        if not temGrafico:
            continue
        assert aberta in temGrafico, (
            "no painel '%s' a aba aberta é '%s' e o gráfico está em %s"
            % (g, aberta, temGrafico))


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
    pg.click("#tabprod-veic")
    assert pg.is_visible("#aba-prod-veic") and not pg.is_visible("#aba-prod-vis")
    assert pg.get_attribute("#tabprod-veic", "aria-selected") == "true"
    assert pg.get_attribute("#tabprod-vis", "aria-selected") == "false"
    pg.click("#tabprod-ocio")
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


# -- rotacao automatica ------------------------------------------------------


def test_o_controle_de_giro_aparece_em_TODA_barra_de_abas(pagina):
    """Pedido do usuário: painel com mais de uma aba precisa de controle do
    tempo de transição — num mural não há ninguém para clicar. O controle é
    montado a partir de `[data-abas]`, então painel novo já nasce com ele."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.is_visible("#abaAuto-prod")
    opcoes = pg.eval_on_selector(
        "#abaAuto-prod", "s => Array.from(s.options).map(o => o.value)")
    assert opcoes[0] == "0", "a primeira opção tem de ser 'não girar'"
    assert len(opcoes) >= 4


def test_NAO_GIRAR_esta_DENTRO_do_mesmo_controle(pagina):
    """Um interruptor separado do intervalo cria o estado "ligado com
    intervalo nenhum", que ninguém consegue prever lendo a tela."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    texto = pg.inner_text("#abaAuto-prod").lower()
    assert "não girar" in texto or "nao girar" in texto, texto


def test_o_giro_avanca_a_aba_sozinho(pagina):
    """A ORDEM SAI DO DOM, não de uma lista escrita aqui.

    A versão anterior nomeava `vis → veic → ocio`. Bastou a Produtividade
    ganhar uma quarta aba para ela falhar — e o que falhou foi a lista do
    teste, não a rotação. Teste amarrado à composição de um painel quebra
    quando o painel muda de composição, que é justamente o que se espera que
    ele faça.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    ordem = pg.evaluate(
        "() => Array.from(document.querySelectorAll("
        " '.subtabs[data-abas=\"prod\"] button[data-aba]')).map(b => b.dataset.aba)")
    assert len(ordem) >= 3, "a Produtividade precisa de abas para este teste"
    assert pg.get_attribute("#tabprod-" + ordem[0], "aria-selected") == "true"
    # o menor intervalo real é longo demais para um teste: dispara a rotação
    # pela mesma função que o relógio chama.
    for i in range(1, len(ordem)):
        pg.evaluate("() => window.abaProxima('prod')")
        assert pg.get_attribute("#tabprod-" + ordem[i], "aria-selected") == "true", (
            "a rotação pulou ou repetiu: esperava %s na posição %d"
            % (ordem[i], i))
    pg.evaluate("() => window.abaProxima('prod')")
    assert pg.get_attribute("#tabprod-" + ordem[0], "aria-selected") == "true", (
        "a rotação tem de dar a volta, não parar na última")


def test_a_escolha_do_intervalo_FICA_GUARDADA(pagina):
    """Quem pôs o painel no mural quer que ele continue girando amanhã."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.select_option("#abaAuto-prod", "30")
    assert pg.evaluate("() => window.abaAutoSegundos('prod')") == 30
    pg.reload()
    pg.wait_for_timeout(600)
    assert pg.input_value("#abaAuto-prod") == "30"


def test_o_giro_e_POR_PAINEL(pagina):
    """Ligar o giro na Jornada não pode fazer a Premiação girar junto."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.select_option("#abaAuto-prod", "60")
    assert pg.evaluate("() => window.abaAutoSegundos('prod')") == 60
    assert pg.evaluate("() => window.abaAutoSegundos('prem')") == 0


def test_o_clique_manual_REARMA_o_relogio(pagina):
    """Um clique dado a dois segundos do giro tiraria a pessoa da aba antes de
    ela ler qualquer coisa — e ela concluiria que o clique não funcionou."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.evaluate("""() => {
        window.__rearmou = 0;
        const orig = window.abaAutoRearmar;
        window.abaAutoRearmar = g => { window.__rearmou++; return orig(g); };
    }""")
    pg.click("#tabprod-veic")
    assert pg.evaluate("() => window.__rearmou") >= 1


# -- tela cheia --------------------------------------------------------------


def test_o_botao_de_tela_cheia_existe_em_qualquer_painel(pagina):
    """Pedido do usuário: tela cheia em TODOS os painéis, não só nos dois de
    TV — que já tinham o modo deles."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.is_visible("#btnFull")
    assert pg.get_attribute("#btnFull", "aria-pressed") == "false"


def test_a_SAIDA_e_visivel_quando_o_topo_some(pagina):
    """O botão que entrou na tela cheia está na barra de topo, que some junto.
    Sem o flutuante, a única saída seria o Esc — e quem não sabe disso fica
    preso num painel sem navegação."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert not pg.is_visible("#btnFullSair")
    pg.evaluate("""() => {
        document.body.classList.add('painelfull');
        document.getElementById('btnFullSair').hidden = false;
    }""")
    assert pg.is_visible("#btnFullSair")


def test_as_telas_de_TV_ficam_FORA_deste_modo(pagina):
    """Elas já têm `tvfull`, que esconde o cursor e reflui em `vw`. Duas
    classes sobre o mesmo elemento fariam um painel comum herdar o cursor
    escondido — e ali ainda há alguém clicando."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    for tela in ("tvfat", "tvope"):
        pg.evaluate("(t) => { location.hash = '#' + t; }", tela)
        pg.wait_for_timeout(250)
        pg.evaluate("() => window.telaCheiaSincronizar()")
        assert not pg.evaluate(
            "() => document.body.classList.contains('painelfull')"), tela


def test_o_estado_vem_do_NAVEGADOR_e_nao_de_variavel_nossa():
    """Guardar o estado à parte cria a divergência clássica: a pessoa sai com
    Esc, que o navegador atende sozinho, e a tela continua achando que está
    cheia — sem barra lateral e sem jeito de voltar."""
    assert "fullscreenchange" in HTML
    assert "document.fullscreenElement" in HTML


# -- o estilo chega mesmo? ---------------------------------------------------
#
# A LIÇÃO MAIS CARA DA RODADA. As regras da estrela, do tema, da tela cheia, da
# barra de abas, do contador e do giro foram parar DENTRO de
# `@media(max-width:880px)` — porque a inserção foi ancorada num seletor
# vizinho sem conferir a profundidade de chaves. No desktop, que é onde o
# painel é usado, esses controles ficaram sem estilo nenhum da 0.152.0 à
# 0.156.0.
#
# Nada pegou: `node --check` valida JS e não CSS; `verificar_estrutura.py` olha
# atributos e aspas; o auditor de tema roda a 1500px mas mede COR — e elemento
# sem estilo tem cor padrão com contraste ótimo.
#
# O guarda certo não é ler o texto do CSS: é PERGUNTAR AO NAVEGADOR, na largura
# de desktop, se a regra chegou.


def test_os_controles_do_painel_TEM_ESTILO_no_desktop(pagina):
    pg, base_url = pagina
    pg.set_viewport_size({"width": 1500, "height": 1000})
    _abrir(pg, base_url)
    estilos = pg.evaluate("""() => {
        const cs = s => { const e = document.querySelector(s);
            return e ? getComputedStyle(e) : null; };
        const bt = cs('#btnFull'), tema = cs('#btnTema'), tabs = cs('.subtabs');
        return {
            full: bt && bt.cursor, tema: tema && tema.cursor,
            tabsDisplay: tabs && tabs.display,
            tabsBorda: tabs && tabs.borderBottomStyle,
        };
    }""")
    assert estilos["full"] == "pointer", estilos
    assert estilos["tema"] == "pointer", estilos
    assert estilos["tabsDisplay"] == "flex", (
        "a barra de sub-abas está sem estilo no desktop — a regra caiu dentro "
        "de um @media de celular: " + str(estilos))
    assert estilos["tabsBorda"] == "solid", estilos


def test_a_tela_cheia_TEM_EFEITO_no_desktop(pagina):
    """A regra de esconder a moldura também estava presa ao @media de celular:
    entrar em tela cheia no desktop não escondia nada."""
    pg, base_url = pagina
    pg.set_viewport_size({"width": 1500, "height": 1000})
    _abrir(pg, base_url)
    pg.evaluate("() => document.body.classList.add('painelfull')")
    d = pg.evaluate("""() => {
        const q = s => { const e = document.querySelector(s);
            return e ? getComputedStyle(e).display : 'ausente'; };
        return {aside: q('aside'), topbar: q('.topbar'), content: q('#content')};
    }""")
    assert d["aside"] == "none" and d["topbar"] == "none", d
    assert d["content"] != "none", d


def test_todo_BOTAO_de_aba_tem_PAINEL_e_vice_versa():
    """O botão diz `abaTrocar(grupo, qual)` e o painel responde por `data-aba`.
    Quando os dois discordam, a aba simplesmente NÃO ABRE.

    ISTO ACONTECEU E FICOU DOIS MESES NO AR. Na Visão Geral, o botão
    "Operação e alertas" chamava `abaTrocar('home','ope')` e o painel era
    `data-aba="oper"` — os dois com o mesmo `id` e o mesmo `aria-controls`,
    o que faz a marcação PARECER certa em qualquer leitura por cima. Entrou na
    v0.158.0, quando a tela virou abas, e só apareceu quando alguém foi clicar.

    O modo de falha é o pior que existe nesta casa: **não dá erro, dá
    ausência.** Nada no console, nenhum banner, a aba fica lá e o conteúdo não
    aparece — igual ao ícone que some do menu e ao mês que o `GROUP BY` não
    devolve. Nenhum guard existente pegava: o JS compila, a estrutura é válida,
    o painel EXISTE (só com outro nome) e o medidor de altura o encontra pelo
    seletor de `.aba`, não pelo que o botão chama.
    """
    botoes: dict[str, set] = {}
    for m in re.finditer(r"abaTrocar\('([\w-]+)','([\w-]+)'\)", HTML):
        botoes.setdefault(m.group(1), set()).add(m.group(2))
    paineis: dict[str, set] = {}
    for m in re.finditer(
            r'<div class="aba"[^>]*data-abas="([\w-]+)"[^>]*data-aba="([\w-]+)"',
            HTML):
        paineis.setdefault(m.group(1), set()).add(m.group(2))

    assert botoes, "nenhum botão de aba — o teste perdeu o alvo"
    problemas = []
    for g in sorted(set(botoes) | set(paineis)):
        b, p = botoes.get(g, set()), paineis.get(g, set())
        if b - p:
            problemas.append(
                f"{g}: botão chama {sorted(b - p)} e não há painel com esse "
                f"data-aba (a aba não abre)")
        if p - b:
            problemas.append(
                f"{g}: painel {sorted(p - b)} existe e nenhum botão o chama "
                f"(conteúdo inalcançável)")
    assert not problemas, "aba que não abre -> " + " | ".join(problemas)


def test_toda_TELA_e_filha_do_CONTAINER_de_conteudo(pagina):
    """Um `</div>` a mais numa tela FECHA o container e joga as SEGUINTES
    para fora do layout.

    ISTO ACONTECEU (v0.185.0). Ao fundir as duas telas de multa eu deixei dois
    `</div>` sobrando; o `#content` fechou cedo e as 14 telas seguintes —
    Torre, Análise de KM, Make vs Buy, Jornada, Documentação e Saúde do
    Servidor — viraram filhas do `<body>`. Elas continuavam existindo, com o
    conteúdo todo renderizado e o texto certo: só que posicionadas fora da
    área visível (a Saúde ficou em `top: 889px`). Quem abria via TELA BRANCA.

    NENHUM GUARD PEGAVA, e vale saber por quê: o JS compila, o
    `verificar_estrutura` não olha aninhamento, o medidor de altura acha a
    view pelo id e a mede feliz, e o navegador NÃO reclama de `</div>` extra —
    ele fecha o que dá e segue. O sintoma é ausência, não erro.

    A pergunta só tem resposta no DOM montado, então quem responde é o
    navegador: contar tag no texto não diz de quem é filho.
    """
    import json
    pg, base_url = pagina        # a fixture desta suite devolve (page, url)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"nome": "T", "email": "t@s.local", "perfil": "admin",
                         "admin": True, "telas": []}
                        if "/api/auth/me" in r.request.url else {})))
    pg.goto(f"{base_url}/static/index.html#home")
    pg.wait_for_selector("#view-home.on", timeout=15000)

    fora = pg.evaluate("""() => [...document.querySelectorAll('section.view')]
        .filter(v => !v.parentElement || v.parentElement.id !== 'content')
        .map(v => v.id + ' (pai: ' + (v.parentElement
             ? v.parentElement.tagName.toLowerCase() + (v.parentElement.id ? '#'+v.parentElement.id : '')
             : 'nenhum') + ')')""")
    assert not fora, (
        "tela fora do #content -> " + ", ".join(fora)
        + " — quase sempre um </div> a mais numa tela ANTERIOR a estas")
