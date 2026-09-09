# -*- coding: utf-8 -*-
"""O filtro de cliente/credor na barra, contra o index.html real.

AS TRÊS TELAS DIVIDEM UMA RESPOSTA E NÃO PODEM DIVIDIR O FILTRO. Fluxo de
Caixa, Contas a Receber e Contas a Pagar chamam o MESMO
`/api/financeiro/overview` e são a mesma chave (`fin`) no cache do front. Quem
escolhe três clientes em Contas a Receber não está pedindo que o fluxo de caixa
da empresa inteira encolha junto — e, como a chave é comum, um descuido faria
exatamente isso, calado: a tela de Fluxo mostraria o caixa de três clientes com
todo o resto igual.

Por isso o teste central aqui não é "o campo aparece": é a QUERY STRING que sai
em cada tela. Ele também confere o que não pode sair — o CNPJ — porque essa
falha não tem sintoma nenhum na tela.
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

CNPJ_CLI = "61156113000175"
CNPJ_FOR = "60746948000112"
# O id opaco é o mesmo que `queries.parte_id` produz — aqui ele é LITERAL, e
# não derivado da função: dublê que se monta a partir do código testado não
# testa o código. Se o digest mudar de forma, este teste acusa.
ID_CLI = "53e1292f9f11"
ID_FOR = "ff8921fadcaf"

PARTES = {
    "clientes": [
        {"id": ID_CLI, "nome": "IOCHPE MAXION - CRUZEIRO/SP",
         "doc": "61" + "•" * 10 + "75", "titulos": 12, "valor": 1890323.41},
        {"id": "aaaaaaaaaaaa", "nome": "TUPY - JOINVILE/SC",
         "doc": "60" + "•" * 10 + "10", "titulos": 5, "valor": 1600000.0},
    ],
    "fornecedores": [
        {"id": ID_FOR, "nome": "BRADESCO - OSASCO/SP",
         "doc": "60" + "•" * 10 + "12", "titulos": 9, "valor": 15451319.89},
        {"id": "bbbbbbbbbbbb", "nome": "RECEITA FEDERAL",
         "doc": "00" + "•" * 10 + "87", "titulos": 4, "valor": 9848101.4},
    ],
}

OVERVIEW = {
    "kpis": {"receber_aberto": 10.0, "receber_qtd": 1, "receber_vencido": 1.0,
             "receber_pendente_fatur": 0.0, "pagar_aberto": 20.0,
             "pagar_aberto_todos": 40.0, "pagar_qtd": 2, "pagar_vencido": 2.0,
             "faturamento_mes": 5.0, "receber_prox30": 1.0, "pagar_prox30": 1.0},
    "aging_receber": [], "aging_pagar": [], "fluxo_caixa": [],
    "ciclo_caixa": [], "custo_financeiro": [], "top_receber": [], "top_pagar": [],
    "venc_receber": [], "venc_pagar": [], "pagar_por_tipo": [],
    "pagar_por_natureza": [], "receber_por_tipo": [],
    "filial": None, "venc_de": None, "venc_ate": None,
    "clientes_sel": 0, "fornecedores_sel": 0,
    "data_ref": "2026-09-09", "atualizado_em": "2026-09-09T09:00:00",
    "fonte": "dublê",
}


def _montar(pg, capturadas):
    def rota(route):
        u = route.request.url
        if "/api/financeiro/overview" in u:
            capturadas.append(u)
            corpo = dict(OVERVIEW)
            if "clientes=" in u:
                corpo["clientes_sel"] = u.split("clientes=")[1].split("&")[0].count(",") + 1
            if "fornecedores=" in u:
                corpo["fornecedores_sel"] = 1
        elif "/api/financeiro/partes" in u:
            corpo = PARTES
        elif "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/financeiro/filtros" in u:
            corpo = {"empresa": "SULISTA", "filiais": []}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))
    pg.route("**/api/**", rota)


def _ir(pg, base, tela):
    pg.goto(base + "/static/index.html#" + tela)
    pg.wait_for_selector("#view-" + tela + ".on", timeout=20000)
    pg.wait_for_timeout(700)


@pytest.mark.parametrize("tela,visivel,oculto", [
    ("receber", "fldRecCli", "fldPagForn"),
    ("pagar", "fldPagForn", "fldRecCli"),
])
def test_cada_tela_mostra_so_o_proprio_campo(pagina, tela, visivel, oculto):
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, tela)
    assert pg.eval_on_selector("#" + visivel, "e=>getComputedStyle(e).display") != "none"
    assert pg.eval_on_selector("#" + oculto, "e=>getComputedStyle(e).display") == "none"


def test_o_fluxo_de_caixa_nao_ganha_campo_de_parte(pagina):
    """A rota aceita o parâmetro, mas o Fluxo não o oferece: ali a pergunta é o
    caixa da EMPRESA, e um recorte por cliente responderia outra coisa com a
    mesma cara."""
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, "fluxo")
    for campo in ("fldRecCli", "fldPagForn"):
        assert pg.eval_on_selector("#" + campo, "e=>getComputedStyle(e).display") == "none"


def test_a_escolha_vira_query_string_e_o_documento_NAO_vai_junto(pagina):
    pg, base = pagina
    urls = []
    _montar(pg, urls)
    _ir(pg, base, "receber")
    pg.click("#fRecCliChips button:last-child")          # "+ Escolher…"
    pg.wait_for_selector("#pk-lista label", timeout=10000)
    pg.check("#pk-lista label:nth-child(1) input")
    pg.click("#modalBox button:has-text('Aplicar')")
    pg.wait_for_timeout(1200)
    assert urls, "nenhuma chamada ao overview"
    ultima = urls[-1]
    assert "clientes=" + ID_CLI in ultima, ultima
    assert CNPJ_CLI not in ultima, "o CNPJ foi parar na query string"
    assert "fornecedores=" not in ultima


def test_o_filtro_do_a_receber_NAO_vaza_para_o_fluxo_nem_para_o_a_pagar(pagina):
    """As três telas dividem a chave `fin`; o parâmetro sai da TELA ATUAL."""
    pg, base = pagina
    urls = []
    _montar(pg, urls)
    _ir(pg, base, "receber")
    pg.click("#fRecCliChips button:last-child")
    pg.wait_for_selector("#pk-lista label", timeout=10000)
    pg.check("#pk-lista label:nth-child(1) input")
    pg.click("#modalBox button:has-text('Aplicar')")
    pg.wait_for_timeout(1200)
    assert "clientes=" in urls[-1]

    _ir(pg, base, "fluxo")
    pg.wait_for_timeout(1200)
    assert "clientes=" not in urls[-1], (
        "o filtro de cliente vazou para o Fluxo de Caixa: " + urls[-1])

    _ir(pg, base, "pagar")
    pg.wait_for_timeout(1200)
    assert "clientes=" not in urls[-1], urls[-1]

    # e a seleção CONTINUA no lugar ao voltar — perdê-la ao passear pelo menu
    # faria a pessoa refazer a escolha a cada ida e volta
    _ir(pg, base, "receber")
    pg.wait_for_timeout(1200)
    assert "clientes=" + ID_CLI in urls[-1], urls[-1]


def test_a_posicao_liquida_sai_da_banda_quando_ha_filtro_de_credor(pagina):
    """Ela é "a receber − a pagar", e o filtro de credor encolhe SÓ o lado de
    baixo: o número viraria o a receber da empresa inteira menos o pagável de
    dois fornecedores. Badge não resolve — quem lê a banda lê o número
    primeiro."""
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, "pagar")
    assert "Posição líquida" in pg.text_content("#kpis-pagar")
    pg.click("#fPagFornChips button:last-child")
    pg.wait_for_selector("#pk-lista label", timeout=10000)
    pg.check("#pk-lista label:nth-child(1) input")
    pg.click("#modalBox button:has-text('Aplicar')")
    pg.wait_for_timeout(1200)
    texto = pg.text_content("#kpis-pagar")
    assert "Posição líquida" not in texto, texto
    assert "Fatia do passivo" in texto, texto


def test_o_recorte_esta_ESCRITO_no_rodape_de_todos_os_indicadores(pagina):
    """Quem chega numa tela já filtrada vê um número e o rodapé DELE. Se o
    recorte estivesse escrito só no primeiro cartão, os outros três pareceriam
    ser da empresa inteira."""
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, "receber")
    pg.click("#fRecCliChips button:last-child")
    pg.wait_for_selector("#pk-lista label", timeout=10000)
    pg.check("#pk-lista label:nth-child(1) input")
    pg.click("#modalBox button:has-text('Aplicar')")
    pg.wait_for_timeout(1200)
    subs = pg.eval_on_selector_all("#kpis-receber .sub", "es=>es.map(e=>e.textContent)")
    assert len(subs) == 4, subs
    assert all("no filtro" in t for t in subs), subs


def test_a_busca_do_modal_filtra_por_nome(pagina):
    pg, base = pagina
    _montar(pg, [])
    _ir(pg, base, "pagar")
    pg.click("#fPagFornChips button:last-child")
    pg.wait_for_selector("#pk-lista label", timeout=10000)
    assert pg.eval_on_selector_all("#pk-lista label", "e=>e.length") == 2
    pg.fill("#pk-busca", "receita")
    pg.wait_for_timeout(200)
    assert pg.eval_on_selector_all("#pk-lista label", "e=>e.length") == 1
    pg.fill("#pk-busca", "nao existe nada assim")
    pg.wait_for_timeout(200)
    assert "Nenhum credor" in pg.text_content("#pk-lista")


def test_cancelar_o_modal_nao_muda_nada(pagina):
    """A escolha vive numa cópia até o Aplicar: sem isso, "Cancelar" deixaria os
    chips descrevendo um recorte que o número da tela não tem."""
    pg, base = pagina
    urls = []
    _montar(pg, urls)
    _ir(pg, base, "receber")
    antes = len(urls)
    pg.click("#fRecCliChips button:last-child")
    pg.wait_for_selector("#pk-lista label", timeout=10000)
    pg.check("#pk-lista label:nth-child(1) input")
    pg.click("#modalBox button:has-text('Cancelar')")
    pg.wait_for_timeout(800)
    assert len(urls) == antes, "cancelar recarregou a tela"
    assert "IOCHPE" not in pg.text_content("#fRecCliChips")
