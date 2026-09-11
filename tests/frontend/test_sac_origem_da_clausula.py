"""A tela SAC / Freetime diz CONTRA QUAL cláusula cada coleta foi medida.

Até 10/09/2026 ela não dizia porque não sabia: o contrato tem uma linha por
tipo de mercadoria e a consulta escolhia UMA AO ACASO entre as que tinham a
mesma data de início. Agora a cláusula é casada pela mercadoria da própria
coleta, e a estimativa de estadia mudou de R$ 877.771,15 para R$ 949.714,50 em
60 dias.

Número que muda de valor tem de mudar de explicação junto. Sem a coluna, quem
abre a tela vê um total diferente do de ontem e não tem como conferir de onde
veio — e a primeira reação a um número que subiu R$ 72 mil não é acreditar
nele, é desconfiar da tela. A coluna é o que transforma a desconfiança em
conferência.

E ela separa as três origens porque elas pedem coisas diferentes:

    clausula propria   o contrato tem uma linha para esta mercadoria
    clausula generica  caiu na linha sem mercadoria do contrato
    sem clausula       nem uma nem outra — vale o MAIOR freetime, e esta é a
                       única que vira conversa com o comercial
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CASA = {**USUARIO, "admin": True, "perfil": "Administrador"}

# Forma REAL do payload de `get_sac_freetime` (10/09/2026), com as três
# origens que a consulta publica. As três aparecem juntas em produção: em 60
# dias foram 1.685 genéricas, 256 por mercadoria e 1 sem cláusula.
SAC = {
    "kpis": {"valor_estimado": 949714.50, "coletas_excedidas": 1942,
             "horas_excedentes": 9626.4, "clientes_freetime": 16},
    "por_cliente": [
        {"cliente": "IOCHPE MAXION", "coletas": 900, "exc_carga": 300.0,
         "exc_descarga": 4100.0, "valor_est": 520000.0},
    ],
    "coletas": [
        {"data": "2026-09-01", "coleta": 31001, "cliente": "IOCHPE MAXION",
         "mercadoria": "RODAS", "origem_ft": "mercadoria",
         "h_carga": 2.0, "h_descarga": 9.0, "exc_carga": 0.0,
         "exc_descarga": 2.5, "valor_est": 250.0},
        {"data": "2026-09-02", "coleta": 31002, "cliente": "IOCHPE MAXION",
         "mercadoria": "CONJUNTO PHEVUS", "origem_ft": "generico",
         "h_carga": 1.0, "h_descarga": 6.0, "exc_carga": 0.0,
         "exc_descarga": 3.0, "valor_est": 300.0},
        {"data": "2026-09-03", "coleta": 31003, "cliente": "LEAR",
         "mercadoria": "DIVERSOS", "origem_ft": "sem_clausula",
         "h_carga": 1.0, "h_descarga": 8.0, "exc_carga": 0.0,
         "exc_descarga": 3.0, "valor_est": 180.0},
    ],
    "freetime_cliente": [
        {"cliente": "IOCHPE MAXION", "filial": 1, "ft_carga_h": 3.0,
         "ft_descarga_h": 6.5, "valor_coleta": 100.0, "valor_entrega": 100.0,
         "obs": "RODAS"},
    ],
    "atualizado_em": "2026-09-11T00:00:00",
    "fonte": "ERP AVA · leitura",
}


def _abrir(pg, base_url):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/api/sac" in u or "freetime" in u:
            corpo = SAC
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#sac")
    pg.wait_for_selector("#sac-coletas tr", state="attached", timeout=20000)
    return erros


def test_a_tela_abre_sem_erro(pagina):
    pg, base = pagina
    assert _abrir(pg, base) == []


def test_cada_coleta_mostra_a_MERCADORIA(pagina):
    """Sem ela não há como conferir a cláusula aplicada — e é a conferência
    que o pedido de validação pediu."""
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#sac-coletas")
    for merc in ("RODAS", "CONJUNTO PHEVUS", "DIVERSOS"):
        assert merc in txt, "a mercadoria %s não apareceu: %s" % (merc, txt)


def test_as_TRES_origens_aparecem_e_se_distinguem(pagina):
    """O mesmo número de horas com três procedências diferentes.

    Se as três saíssem iguais na tela, a coluna seria decoração: o leitor
    continuaria sem saber quais linhas dependem de uma decisão comercial que
    ninguém tomou.
    """
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#sac-coletas").lower()
    assert "clausula propria" in txt
    assert "clausula generica" in txt
    assert "sem clausula" in txt, (
        "a origem que vira conversa com o comercial não foi marcada: %s" % txt)


def test_o_cabecalho_acompanha_a_coluna_nova(pagina):
    """Coluna sem cabeçalho desalinha a tabela inteira em silêncio — os dados
    escorregam uma casa e cada valor passa a ser lido sob o rótulo errado."""
    pg, base = pagina
    _abrir(pg, base)
    cabecalhos = pg.eval_on_selector_all(
        "#sac-coletas thead th", "els => els.map(e => e.textContent.trim())")
    assert "Mercadoria" in cabecalhos, cabecalhos
    celulas = pg.eval_on_selector_all(
        "#sac-coletas tbody tr:first-child td", "els => els.length")
    assert celulas == len(cabecalhos), (
        "a linha tem %d células para %d colunas — a tabela escorregou"
        % (celulas, len(cabecalhos)))
