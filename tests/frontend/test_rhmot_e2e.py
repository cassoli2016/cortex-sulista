# -*- coding: utf-8 -*-
"""A caixa do RH, no navegador — e o que faz dela uma FILA e não uma caixa.

O escopo do app do motorista (`docs/APP_MOTORISTA.md` §10) excluía chat com uma
razão que continua boa: "um canal que ninguém lê e uma expectativa de resposta
que ninguém atende". Esta tela é a metade da casa desse canal, e é aqui que a
razão do escopo se resolve ou se perde:

1. **A ordem é do MAIS PARADO**, e não do mais recente. Numa caixa por data,
   quem escreveu há três semanas nunca mais é visto — e é exatamente essa
   pessoa que liga para a torre, que é o telefonema que o canal existe para
   tirar. O servidor ordena; esta tela NÃO pode reordenar.
2. **"Parada há N dias" é um selo vermelho**, não um campo escondido.
3. **A fila parada é um KPI**, no topo. Sem ele, "temos um canal com o
   motorista" é uma frase; com ele, é uma medição — e é por ele que a decisão
   de manter ou desligar o canal se toma com dado na mesa.

E a regra de sempre: a página não rola para o LADO. A grade é
`minmax(0,1fr)`, porque `1fr` cru não encolhe abaixo do min-content e o painel
da direita nasceria fora da tela, sem erro nenhum.
"""
from __future__ import annotations

import json
import pathlib

from tests.frontend.conftest import USUARIO

USER = {**USUARIO, "admin": False, "perfil": "Recursos Humanos",
        "telas": ["rhmot"], "id": 9}

CAIXA = {
    "conversas": [
        # A MAIS PARADA VEM PRIMEIRO — o servidor manda assim, e o teste
        # confere que a tela respeitou.
        {"id": 3, "motorista_id": 12, "motorista": "ANA MOTORISTA",
         "assunto": "ferias", "assunto_rotulo": "Férias", "origem": "motorista",
         "titulo": "", "status": "aberta", "atendente": "",
         "criada_em": "2026-08-20T08:00:00", "ultima_em": "2026-08-20T08:00:00",
         "parada_dias": 18.0, "nao_lidas": 1,
         "resumo": "Quando vencem minhas ferias?"},
        {"id": 4, "motorista_id": 13, "motorista": "BRUNO MOTORISTA",
         "assunto": "contracheque", "assunto_rotulo": "Contracheque e descontos",
         "origem": "motorista", "titulo": "", "status": "em_atendimento",
         "atendente": "fernanda@sulista.com.br",
         "criada_em": "2026-09-06T08:00:00", "ultima_em": "2026-09-06T18:00:00",
         "parada_dias": 0.4, "nao_lidas": 0,
         "resumo": "Nao entendi o desconto de setembro."}],
    "mostradas": 2, "limite": 200,
    "resumo": {"total": 9, "abertas": 1, "vivas": 2, "paradas_3d": 1},
    "assuntos": [{"chave": "comunicado", "rotulo": "Comunicado do RH",
                  "ajuda": "Aviso da empresa.", "pede_ciencia": True}],
    "estados": ["aberta", "em_atendimento", "aguardando_motorista", "resolvida"],
    "fonte": "CÓRTEX · canal do RH (mot_conversas)"}

CONVERSA = {
    "conversa": {"id": 3, "assunto": "ferias", "assunto_rotulo": "Férias",
                 "origem": "motorista", "titulo": "", "status": "aberta",
                 "aberta": True, "pede_ciencia": False,
                 "criada_em": "2026-08-20T08:00:00", "atendente": "",
                 "motorista": "ANA MOTORISTA", "motorista_id": 12},
    "mensagens": [
        {"id": 1, "papel": "sistema", "autor": "",
         "texto": "Pedido aberto sobre Férias.", "evento": "abertura",
         "quando": "2026-08-20T08:00:00"},
        {"id": 2, "papel": "motorista", "autor": "ANA MOTORISTA",
         "texto": "Quando vencem minhas ferias?", "evento": "",
         "quando": "2026-08-20T08:00:00"}]}


def _rota(route):
    u = route.request.url.split("?")[0]
    if u.endswith("/api/auth/me"):
        corpo = {"usuario": USER, "ok": True, **USER}
    elif "/api/rh/motorista/conversas/" in u:
        corpo = CONVERSA
    elif u.endswith("/api/rh/motorista/conversas"):
        corpo = CAIXA
    elif u.endswith("/api/rh/motorista/motoristas"):
        corpo = {"motoristas": [{"id": 12, "nome": "ANA MOTORISTA"}],
                 "mostrados": 1, "total": 1, "limite": 40}
    else:
        corpo = {}
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))


def _abrir(pg, base_url):
    pg.route("**/api/**", _rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("%s/static/index.html#rhmot" % base_url)
    pg.wait_for_selector("#view-rhmot.on", timeout=15000)
    pg.wait_for_selector("#kpis-rhmot .kpi", timeout=15000)
    return erros


def test_a_caixa_abre_e_mostra_a_fila(pagina):
    pg, base_url = pagina
    erros = _abrir(pg, base_url)
    texto = pg.text_content("#view-rhmot")
    assert "ANA MOTORISTA" in texto and "BRUNO MOTORISTA" in texto
    assert "Férias" in texto
    assert not erros, erros


def test_a_fila_PARADA_e_um_KPI_no_topo(pagina):
    """O número que diz se o canal está funcionando."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    kpis = pg.text_content("#kpis-rhmot")
    assert "Paradas há 3+ dias" in kpis
    assert "Sem dono" in kpis


def test_conversa_parada_leva_selo_e_a_ordem_e_a_do_SERVIDOR(pagina):
    """A tela NÃO reordena: numa lista por data, quem escreveu há três semanas
    nunca mais é visto."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    ids = pg.eval_on_selector_all(".rhmot-item",
                                  "els => els.map(e => e.dataset.id)")
    assert ids == ["3", "4"], "a tela reordenou a fila: %r" % ids
    primeiro = pg.text_content(".rhmot-item")
    assert "parada há 18d" in primeiro
    assert "1 nova(s)" in primeiro


def test_abrir_a_conversa_mostra_os_dois_lados(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click(".rhmot-item[data-id='3']")
    pg.wait_for_selector(".rhmot-bolha.motorista", timeout=15000)
    texto = pg.text_content("#rhmot-conversa")
    assert "Quando vencem minhas ferias?" in texto
    assert "Pedido aberto sobre Férias." in texto
    assert "ANA MOTORISTA" in pg.text_content("#rhmot-titulo")
    # o estado e o dono ficam à vista: "quem está com isso?" é a pergunta que a
    # fila existe para responder
    assert "sem dono" in pg.text_content("#hintRhmotConv")


def test_a_tela_NAO_rola_para_o_lado(pagina):
    """`1fr` é `minmax(auto,1fr)` e a trilha não encolhe abaixo do min-content:
    foi assim que o cartão da direita de GR e Margem por cliente nasceu fora da
    tela, sem erro nenhum."""
    pg, base_url = pagina
    pg.set_viewport_size({"width": 1280, "height": 900})
    _abrir(pg, base_url)
    pg.click(".rhmot-item[data-id='3']")
    pg.wait_for_selector(".rhmot-bolha.motorista", timeout=15000)
    sobra = pg.evaluate("document.documentElement.scrollWidth - "
                        "document.documentElement.clientWidth")
    assert sobra <= 0, "a tela empurrou a página %d px para o lado" % sobra


def test_em_tela_estreita_a_grade_vira_UMA_coluna(pagina):
    """Duas listas lado a lado não cabem em tela nenhuma estreita — e o RH
    também abre isto num notebook pequeno."""
    pg, base_url = pagina
    pg.set_viewport_size({"width": 900, "height": 800})
    _abrir(pg, base_url)
    colunas = pg.eval_on_selector(
        ".rhmot-grade", "e => getComputedStyle(e).gridTemplateColumns")
    assert len(colunas.split()) == 1, (
        "a grade continuou em duas colunas a 900 px: %r" % colunas)


def test_a_meta_da_conversa_alinha_a_ESQUERDA(pagina):
    """A regra pode existir, estar certa e NÃO VALER — só o navegador diz quem
    venceu a cascata.

    A casa tem `.meta{text-align:right}` (linha 262 do `index.html`), e ela
    ganhava da regra do componente por chegar antes com a MESMA
    especificidade: o nome do motorista ficava à esquerda e o resumo dele à
    direita, dentro do mesmo cartão. Ler o texto do CSS não pega isso; este
    teste lê o `getComputedStyle`.
    """
    pg, base_url = pagina
    _abrir(pg, base_url)
    assert pg.eval_on_selector(".rhmot-item .meta",
                               "e => getComputedStyle(e).textAlign") == "left"
    # E a regra da casa continua valendo onde ela deve — senão este guard
    # estaria provando que alguém apagou a `.meta` da casa, não que a nossa
    # nasceu qualificada.
    fonte = (pathlib.Path(__file__).resolve().parents[2]
             / "api" / "static" / "index.html").read_text(encoding="utf-8")
    assert ".meta{font-size:12px;color:var(--n500);text-align:right" in fonte


# =============================================== o mural, na tela do RH ====

MURAL = {"comunicados": [
    {"id": 5, "titulo": "Convenção coletiva 2026",
     "texto": "A convenção foi assinada. O reajuste entra na folha de outubro.",
     "autor": "fernanda@sulista.com.br", "criado_em": "2026-09-05T09:00:00",
     "encerrado": False, "encerrado_em": None,
     "destinatarios": 80, "confirmaram": 45, "viram_sem_confirmar": 12,
     "faltam": 35, "pct": 56.3},
    {"id": 4, "titulo": "Campanha de exames", "texto": "Procure o RH.",
     "autor": "RH", "criado_em": "2026-08-01T09:00:00",
     "encerrado": True, "encerrado_em": "2026-08-30T09:00:00",
     "destinatarios": 70, "confirmaram": 70, "viram_sem_confirmar": 0,
     "faltam": 0, "pct": 100.0}],
    "mostrados": 2, "limite": 50, "total": 2,
    "fonte": "CÓRTEX · mural do RH (mot_comunicados)"}

FALTAM = {"faltam": [{"motorista_id": 12, "nome": "ANA MOTORISTA", "abriu": True},
                     {"motorista_id": 13, "nome": "BRUNO MOTORISTA", "abriu": False}],
          "n": 2}


def _rota_mural(route):
    u = route.request.url.split("?")[0]
    if u.endswith("/faltam"):
        corpo = FALTAM
    elif u.endswith("/api/rh/motorista/mural"):
        corpo = MURAL
    else:
        corpo = {"ok": True}
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(corpo))


def _abrir_mural(pg, base_url):
    pg.route("**/api/**", _rota)
    pg.route("**/api/rh/motorista/mural**", _rota_mural)   # a última vence
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto("%s/static/index.html#rhmot" % base_url)
    pg.wait_for_selector("#view-rhmot.on", timeout=15000)
    pg.click("#tabrhmot-mural")
    pg.wait_for_selector("#rhmot-mural .rhmot-item", timeout=15000)
    return erros


def test_o_mural_e_UM_cartao_com_a_fracao(pagina):
    """O que faz ele caber ao lado da caixa sem afogá-la: 300 destinatários
    viram UMA linha com "45 / 80", e não 300 linhas na fila."""
    pg, base_url = pagina
    erros = _abrir_mural(pg, base_url)
    itens = pg.eval_on_selector_all("#rhmot-mural .rhmot-item", "e => e.length")
    assert itens == 2, "um cartão por comunicado, e não por destinatário"
    texto = pg.text_content("#rhmot-mural")
    assert "45 / 80" in texto and "56,3%" in texto
    assert "35 sem confirmar" in texto
    assert "12 abriram e não confirmaram" in texto
    assert not erros, erros


def test_o_encerrado_nao_pede_mais_nada(pagina):
    pg, base_url = pagina
    _abrir_mural(pg, base_url)
    texto = pg.text_content("#rhmot-mural")
    assert "encerrado" in texto and "todos confirmaram" in texto


def test_ver_quem_falta_marca_quem_ABRIU(pagina):
    """"45 de 80" sem os nomes não vira ação. E quem abriu e não confirmou é a
    conversa mais útil das duas."""
    pg, base_url = pagina
    _abrir_mural(pg, base_url)
    pg.click("#rhmot-mural .integ-lnk")
    # `.badge` e a classe DA CASA (`.b-warn`/`.b-info`). A primeira versao
    # usava `.pill`, que nao existe — e classe inexistente nao da erro: o nome
    # sairia como texto cru no meio da frase. Mesma familia do token fantasma.
    pg.wait_for_selector("#rhmot-faltam-5 .badge", timeout=15000)
    texto = pg.text_content("#rhmot-faltam-5")
    assert "ANA MOTORISTA · abriu" in texto
    assert "BRUNO MOTORISTA" in texto and "BRUNO MOTORISTA · abriu" not in texto


def test_a_aba_do_mural_carrega_SO_quando_e_aberta(pagina):
    """`data-ao-abrir`: a caixa é o que o RH usa todo dia, o mural é ocasional.
    Buscar os dois na abertura da tela paga por um que ninguém pediu."""
    pg, base_url = pagina
    pedidas = []
    pg.route("**/api/**", lambda r: (pedidas.append(r.request.url), _rota(r))[-1])
    pg.route("**/api/rh/motorista/mural**",
             lambda r: (pedidas.append(r.request.url), _rota_mural(r))[-1])
    pg.goto("%s/static/index.html#rhmot" % base_url)
    pg.wait_for_selector("#kpis-rhmot .kpi", timeout=15000)
    assert not any("/mural" in u for u in pedidas), (
        "o mural foi buscado sem ninguém abrir a aba")
    pg.click("#tabrhmot-mural")
    pg.wait_for_selector("#rhmot-mural .rhmot-item", timeout=15000)
    assert any("/mural" in u for u in pedidas)


def test_os_selos_usam_o_BADGE_da_casa_e_nao_um_nome_inventado(pagina):
    """`.pill` não existe no `index.html` — e classe inexistente NÃO dá erro:
    o texto sai cru, sem cor e sem contorno, no meio da frase. Foi o que
    aconteceu na primeira versão desta tela.

    É a mesma família do token de cor fantasma (`test_tema.py`): um nome que
    parece componente e não é. A diferença é que este só aparece OLHANDO — por
    isso o guard mede o `borderRadius` computado, e não o texto do CSS.
    """
    pg, base_url = pagina
    _abrir_mural(pg, base_url)
    selo = pg.query_selector("#rhmot-mural .badge")
    assert selo, "nenhum selo desenhado — a classe do badge está errada"
    raio = pg.eval_on_selector("#rhmot-mural .badge",
                               "e => getComputedStyle(e).borderRadius")
    assert raio not in ("0px", ""), (
        "o selo não recebeu estilo: a classe existe no HTML mas não no CSS")
    assert "class=\"pill" not in pg.content()
