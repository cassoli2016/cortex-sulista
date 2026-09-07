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
