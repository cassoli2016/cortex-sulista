# -*- coding: utf-8 -*-
"""O aplicativo da campanha no navegador.

O que só se prova aqui:

- **a capa não mostra número nenhum.** Ela circula por QR em grupo de WhatsApp,
  e o que circula junto tem de ser só o convite — nem categoria, nem contagem,
  nem nome;
- quem não concorre lê O QUE FALTA antes do resto: é a única parte da tela
  sobre a qual ele ainda pode fazer alguma coisa;
- a tela não rola para o lado num celular de 390px.
"""
from __future__ import annotations

import json

CAMPANHA = {"nome": "Programa de Desempenho", "premio": "Moto elétrica",
            "onde": "Matriz — Piraquara/PR", "sorteio_em": "2026-12-20",
            "ate_ciclo": "2026-12", "cat_elite": 90.0}

MINHA = {
    "tem_dado": True, "fora_do_escopo": False, "campanha": CAMPANHA,
    "ciclo": "2026-11", "rotulo": "16/10 a 15/11 de 2026",
    "encerramento": False, "faltam_ciclos": 1,
    "grupo": "AGREGADO", "grupo_rotulo": "agregados",
    "nota": 93.6, "categoria": "ELITE", "posicao": 3, "de": 42,
    "concorre": True, "motivo": "", "faltas": [],
    "pilares": [
        {"chave": "gobrax", "rotulo": "Condução", "peso": 50.0, "nota": 92.0,
         "entrou": True},
        {"chave": "conduta", "rotulo": "Comportamento", "peso": 30.0,
         "nota": 100.0, "entrou": True},
        {"chave": "gr", "rotulo": "Gerenciamento de risco", "peso": 20.0,
         "nota": 88.0, "entrou": True}],
    "no_grupo": {"participantes": 127, "concorrendo": 42,
                 "por_categoria": {"ELITE": 1, "OURO": 1, "PRATA": 12,
                                   "BRONZE": 29, "PENDENTE": 84}},
    "fonte": "Programa de desempenho · ciclo em curso",
}


def _abrir(pg, base_url, minha=None, status=200, eu=None):
    def rota(route):
        u = route.request.url
        if "/api/motorista/eu" in u:
            if status != 200:
                return route.fulfill(status=401, content_type="application/json",
                                     body=json.dumps({"mensagem": "sem sessão"}))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(eu or {"nome": "JOAO DA SILVA",
                                                        "mestre": False}))
        if "/api/motorista/campanha" in u:
            if status != 200:
                return route.fulfill(status=status,
                                     content_type="application/json",
                                     body=json.dumps({"erro": "recusa",
                                                      "mensagem": "Faça login."}))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(minha or MINHA))
        route.fulfill(status=200, content_type="application/json", body="{}")

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.set_viewport_size({"width": 390, "height": 780})
    # O ENDERECO DE VERDADE E' `/campanha`, servido pelo FastAPI; aqui o
    # servidor da bancada publica a pasta `api/`, entao a pagina abre pelo
    # arquivo. O guard de que `/campanha` responde 200 e' outro, e roda com o
    # app de verdade (`tests/test_aplicativos.py`).
    pg.goto("%s/static/campanha.html" % base_url)
    pg.wait_for_timeout(600)
    return erros


def test_sem_sessao_a_CAPA_nao_mostra_numero_nenhum(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url, status=401)
    assert not erros, erros
    assert pg.is_visible("#tela-capa") and not pg.is_visible("#app")
    texto = pg.inner_text("#entrada")
    for proibido in ("ELITE", "93,6", "127", "42", "Moto"):
        assert proibido not in texto, proibido
    assert "Programa de Desempenho" in texto
    assert pg.is_visible("#b-pedir"), "a capa oferece a entrada"


def _folha(nome):
    """A folha de estilo DE VERDADE de um aplicativo.

    ÂNCORA DERIVADA, e não a primeira ocorrência do texto `<style>`: no
    `motorista.html` ela aparece ANTES, dentro de um comentário que explica o
    `<style>` do painel. Foi exatamente esse recorte a olho que publicou a
    campanha sem CSS nenhum em 18/09/2026 — e o guard não pegou, porque ele
    comparava os dois arquivos com o MESMO recorte errado: idênticos, e os
    dois errados.
    """
    import pathlib
    import re
    static = pathlib.Path(__file__).resolve().parents[2] / "api" / "static"
    html = (static / nome).read_text(encoding="utf-8")
    m = re.search(r"<style>\s*:root\{.*?</style>", html, re.S)
    assert m, f"{nome}: não achei a folha (o <style> que abre com :root)"
    return m.group(0)


def test_a_CARA_e_a_mesma_do_app_do_motorista():
    """Duas caras diferentes para a mesma empresa fazem a pessoa desconfiar da
    segunda — e a campanha é justamente a que chega por link encaminhado. A
    casa não tem folha compartilhada entre aplicativos (cada um é página
    própria), então o bloco de estilo é COPIADO: este guard é o que impede os
    dois de derivarem no primeiro ajuste."""
    folha = _folha("campanha.html")
    assert folha == _folha("motorista.html"), (
        "a campanha saiu da cara do app do motorista — se a mudança é "
        "intencional, ela vale para os dois")
    # E A FOLHA TEM DE SER FOLHA: sem isto, dois recortes vazios (ou dois
    # pedaços de comentário) passariam por iguais.
    for regra in ("--navy-900:", ".lg-btn", ".mestre{", ".card{"):
        assert regra in folha, regra


def test_a_pagina_esta_PINTADA(pagina):
    """O guard que faltava em 18/09/2026: a campanha foi ao ar com a folha
    recortada do lugar errado e apareceu no celular sem estilo nenhum — fonte
    serifada, sem marca, sem botão. Nenhum teste pegou, porque todos liam
    TEXTO. Só o navegador diz se a página está pintada, e é ele que responde
    aqui (`getComputedStyle`, nunca o texto do CSS)."""
    pg, base_url = pagina
    _abrir(pg, base_url, status=401)
    visual = pg.evaluate("""() => {
      const lg = document.body;   // quem pinta a entrada é `body.entrando`
      const btn = document.getElementById('b-pedir');
      const cs = getComputedStyle(document.body);
      const cb = getComputedStyle(btn);
      return {fonte: cs.fontFamily,
              fundo: getComputedStyle(lg).backgroundImage,
              botao: cb.backgroundColor, altura: btn.getBoundingClientRect().height};
    }""")
    assert "saira" in visual["fonte"].lower() or "sans" in visual["fonte"].lower(), (
        f"a página caiu na fonte padrão do navegador: {visual['fonte']}")
    assert "gradient" in visual["fundo"], (
        "a entrada perdeu o fundo da marca — a folha não está valendo")
    assert visual["botao"] not in ("rgba(0, 0, 0, 0)", "transparent"), (
        "o botão de entrar está sem cor: a folha não está valendo")
    assert visual["altura"] >= 44, (
        f"o alvo de toque ficou em {visual['altura']}px — o mínimo da casa é 48")


def test_a_tela_de_DENTRO_tambem_esta_pintada(pagina):
    """A capa e o app são dois desenhos, e o guard do primeiro não fala pelo
    segundo: a faixa da marca, os cartões e a banda de KPI usam outras classes.
    Se alguma delas não existir na folha (foi o caso de `.topo`, `.marca-txt` e
    `.barra`, inventadas), a tela de dentro sai como texto cru."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    visual = pg.evaluate("""() => {
      const faixa = document.querySelector('.appbar');
      const card = document.querySelector('#conteudo .card');
      const kpi = document.querySelector('#conteudo .kpi');
      const cor = (el) => el ? getComputedStyle(el).backgroundColor : null;
      return {faixa: cor(faixa), card: cor(card), kpi: cor(kpi),
              temFaixa: !!faixa, temCard: !!card, temKpi: !!kpi,
              anel: !!document.querySelector('#anelmini'),
              // A CLASSE DA ENTRADA TEM DE SAIR: ela pinta a página INTEIRA de
              // navy e centra o cartão do login. O `body` nasce com ela no
              // HTML (a capa é a primeira tela), então quem a remove é o
              // `mostrar("")` — e um toggle quebrado não aparece na capa,
              // só aqui: o app com o fundo do login por baixo.
              naEntrada: document.body.classList.contains('entrando'),
              fundo: getComputedStyle(document.body).backgroundImage};
    }""")
    assert visual["temFaixa"] and visual["temCard"] and visual["temKpi"]
    assert not visual["naEntrada"], "o app ficou com a classe da entrada"
    assert "gradient" not in visual["fundo"], (
        "o app ficou com o fundo do login por baixo")
    assert visual["anel"], "a marca da casa não está na faixa"
    for onde in ("faixa", "card", "kpi"):
        assert visual[onde] not in ("rgba(0, 0, 0, 0)", "transparent"), (
            f"{onde} sem fundo: a classe não existe na folha")


def test_a_TARJA_do_acesso_mestre_e_obrigatoria(pagina):
    """Quem administra esquece em que conta está, e um print sem a tarja vira
    "o app mostrou isso ao motorista", que é falso."""
    pg, base_url = pagina
    _abrir(pg, base_url, eu={"nome": "FULANO DE TAL", "mestre": True})
    assert pg.is_visible("#tarja-mestre")
    tarja = pg.inner_text("#tarja-mestre")
    assert "ADMINISTRAÇÃO" in tarja.upper() and "FULANO DE TAL" in tarja


def test_sem_acesso_mestre_NAO_ha_tarja(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert not pg.is_visible("#tarja-mestre")
    assert "Olá" in pg.inner_text("#marca-sub")


def test_o_acesso_da_administracao_abre_pela_entrada(pagina):
    """Ele entra pela porta da frente, com a empresa na tela — não por uma
    página escondida."""
    pg, base_url = pagina
    _abrir(pg, base_url, status=401)
    assert pg.is_visible("#b-abrir-mestre")
    pg.click("#b-abrir-mestre")
    assert pg.is_visible("#tela-mestre") and not pg.is_visible("#tela-capa")
    assert pg.is_visible("#mestre-codigo") and pg.is_visible("#mestre-busca")
    # o rodape da entrada do motorista some: ele nao e' desta tela
    assert not pg.is_visible("#b-abrir-mestre")
    pg.click("#b-mestre-voltar")
    assert pg.is_visible("#tela-capa")


def test_com_sessao_a_CATEGORIA_vem_primeiro_e_a_posicao_junto(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    assert not erros, erros
    # A CATEGORIA E A POSIÇÃO ficam na banda, e não num card: são as duas
    # coisas que ele abre o app para ver.
    banda = pg.inner_text("#conteudo .kpis")
    for pedaco in ("ELITE", "93,6", "3º", "entre os 42",
                   "você está concorrendo"):
        assert pedaco.lower() in banda.lower(), pedaco


def test_quem_NAO_concorre_le_o_que_falta_ANTES_do_resto(pagina):
    pg, base_url = pagina
    fora = {**MINHA, "concorre": False, "posicao": None, "categoria": "PENDENTE",
            "nota": 96.4,
            "pilares": [{**MINHA["pilares"][0], "nota": None, "entrou": False},
                        *MINHA["pilares"][1:]],
            "faltas": ["sem leitura da telemetria no ciclo — a nota de condução "
                       "vale metade do regulamento, e sem ela não dá para "
                       "concorrer"]}
    _abrir(pg, base_url, minha=fora)
    # `inner_text` devolve o texto RENDERIZADO, e os títulos desta página são
    # maiúsculos por CSS — comparar sem caso evita um guard que quebra no dia
    # em que alguém mexe no `text-transform` sem mexer no conteúdo.
    banda = pg.inner_text("#conteudo .kpis").lower()
    assert "fora do sorteio" in banda and "sem categoria" in banda
    # `inner_text` devolve o texto RENDERIZADO, e os títulos são maiúsculos por
    # CSS — comparar sem caso evita um guard que quebra no dia em que alguém
    # mexe no `text-transform` sem mexer no conteúdo.
    cards = [x.lower() for x in pg.eval_on_selector_all(
        "#conteudo .card", "els => els.map(e => e.innerText)")]
    falta = next((i for i, c in enumerate(cards) if "para concorrer, falta" in c),
                 None)
    nota = next((i for i, c in enumerate(cards) if "de onde vem a sua nota" in c),
                None)
    assert falta is not None and nota is not None
    assert falta < nota, "o que falta vem antes da nota"
    assert "telemetria" in cards[falta] and "faltam 1 ciclo" in cards[falta]


def test_o_pilar_que_nao_entrou_e_DITO_e_nao_vira_zero(pagina):
    pg, base_url = pagina
    fora = {**MINHA, "pilares": [{**MINHA["pilares"][0], "nota": None,
                                  "entrou": False}, *MINHA["pilares"][1:]]}
    _abrir(pg, base_url, minha=fora)
    texto = pg.inner_text("#conteudo")
    assert "sem leitura" in texto
    assert "Condução" in texto and "peso 50%" in texto


def test_o_painel_do_grupo_nao_tem_NOME_de_ninguem(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    texto = pg.inner_text("#conteudo")
    assert "42 de 127 estão concorrendo" in texto
    assert "competem separados" in texto
    assert "Elite" in texto and "Bronze" in texto


def test_o_premio_e_o_prazo_aparecem(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    texto = pg.inner_text("#conteudo")
    assert "Moto elétrica" in texto and "20/12/2026" in texto
    assert "2026-12" in texto


def test_sem_campanha_a_tela_DIZ_e_nao_fica_vazia(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url, minha={"tem_dado": False, "fora_do_escopo": True,
                                "motivo": "Não há campanha em andamento agora.",
                                "fonte": "Programa de desempenho"})
    assert "Não há campanha em andamento" in pg.inner_text("#conteudo")


def test_a_tela_nao_rola_para_o_lado(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    sobra = pg.evaluate("() => document.documentElement.scrollWidth"
                        " - document.documentElement.clientWidth")
    assert sobra == 0, f"a campanha empurra {sobra}px para o lado"
