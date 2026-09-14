# -*- coding: utf-8 -*-
"""A Régua de Cobrança por grupo de cliente e as faixas do BI, no index.html real.

O payload é o que `queries.get_cobranca` devolve desde a 1.81.0 (grupo,
empresas, faixas ate_15/de_16_30/de_31_90/mais_90, empresa por título).
Nomes e valores são de mentira — o repositório é público.
"""
from __future__ import annotations

import json
import re

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _tit(empresa, numero, dias, saldo):
    return {"empresa": empresa, "numero": numero, "filial": 1, "emissao": "2026-07-01",
            "vencimento": "2026-08-01", "dias_vencido": dias, "saldo": saldo}


COB = {
    "clientes": [
        {"cliente": "GRUPO FICTICIO", "grupo": True, "empresas": 2, "doc": None,
         "titulos": 3, "vencido": 500.0, "ate_15": 200.0, "de_16_30": 300.0,
         "de_31_90": 0.0, "mais_90": 0.0, "vencimento_mais_antigo": "2026-08-25",
         "dso": 42.0, "ocultos": 0,
         "titulos_lista": [_tit("FILIAL NORTE FICTICIA", 101, 10, 100.0),
                           _tit("FILIAL NORTE FICTICIA", 102, 10, 100.0),
                           _tit("FILIAL SUL FICTICIA", 103, 20, 300.0)]},
        {"cliente": "INDUSTRIA DE MENTIRA SA", "grupo": False, "empresas": 1,
         "doc": "44" + "•" * 10 + "72", "titulos": 2, "vencido": 460.0,
         "ate_15": 50.0, "de_16_30": 130.0, "de_31_90": 170.0, "mais_90": 110.0,
         "vencimento_mais_antigo": "2026-06-15", "dso": 70.0, "ocultos": 0,
         "titulos_lista": [_tit("INDUSTRIA DE MENTIRA SA", 201, 91, 110.0)]},
    ],
    "total_vencido_top": 960.0, "pendente_faturamento": 0.0,
    "pendente_faturamento_docs": 0, "atualizado_em": "2026-09-14T09:00:00",
    "fonte": "dublê",
}

OVERVIEW = {
    "kpis": {"receber_aberto": 1500.0, "receber_qtd": 11, "receber_vencido": 1000.0,
             "receber_pendente_fatur": 0.0, "pagar_aberto": 20.0,
             "pagar_aberto_todos": 40.0, "pagar_qtd": 2, "pagar_vencido": 2.0,
             "faturamento_mes": 5.0, "receber_prox30": 1.0, "pagar_prox30": 1.0},
    "aging_receber": [
        {"faixa": "1_a_vencer", "qtd": 1, "valor": 500.0},
        {"faixa": "2_vencido_ate_15", "qtd": 4, "valor": 290.0},
        {"faixa": "3_vencido_16_30", "qtd": 3, "valor": 430.0},
        {"faixa": "4_vencido_31_90", "qtd": 2, "valor": 170.0},
        {"faixa": "5_vencido_mais_90", "qtd": 1, "valor": 110.0}],
    "aging_pagar": [
        {"faixa": "1_a_vencer", "qtd": 1, "valor": 18.0},
        {"faixa": "4_vencido_91_365", "qtd": 1, "valor": 2.0}],
    "fluxo_caixa": [], "ciclo_caixa": [], "custo_financeiro": [], "top_receber": [],
    "top_pagar": [], "venc_receber": [], "venc_pagar": [], "pagar_por_tipo": [],
    "pagar_por_natureza": [], "receber_por_tipo": [],
    "filial": None, "venc_de": None, "venc_ate": None,
    "clientes_sel": 0, "fornecedores_sel": 0,
    "data_ref": "2026-09-14", "atualizado_em": "2026-09-14T09:00:00", "fonte": "dublê",
}


def _montar(pg):
    def rota(route):
        u = route.request.url
        if "/api/financeiro/cobranca" in u:
            corpo = COB
        elif "/api/financeiro/overview" in u:
            corpo = OVERVIEW
        elif "/api/auth/me" in u:
            corpo = ADMIN
        elif "/api/financeiro/filtros" in u:
            corpo = {"empresa": "SULISTA", "filiais": []}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
    pg.route("**/api/**", rota)


def _ir(pg, base, tela):
    pg.goto(base + "/static/index.html#" + tela)
    pg.wait_for_selector("#view-" + tela + ".on", timeout=20000)
    pg.wait_for_timeout(700)


def _txt(pg, sel):
    # text_content, e não inner_text: o inner_text aplica o text-transform do
    # CSS e devolve cabeçalho e badge em CAIXA ALTA.
    return pg.eval_on_selector(sel, "e=>e.textContent")


def test_a_regua_mostra_o_GRUPO_as_faixas_do_BI_e_a_empresa_de_cada_titulo(pagina):
    pg, base = pagina
    _montar(pg)
    _ir(pg, base, "cob")
    cab = _txt(pg, "#view-cob thead")
    for faixa in ("Até 15d", "16–30d", "31–90d", "+90d"):
        assert faixa in cab, faixa
    assert "91–365d" not in cab and "+365d" not in cab

    linhas = pg.query_selector_all("#cob-cli tr.forn-row")
    assert len(linhas) == 2
    grupo, avulso = (l.text_content() for l in linhas)
    assert "GRUPO FICTICIO" in grupo and "grupo · 2 empresas" in grupo
    assert "44" + "•" * 10 + "72" in avulso and "grupo ·" not in avulso

    kpis = _txt(pg, "#kpis-cob")
    # o valor vem colado no texto do chip seguinte ("R$ 110acompanhar"): o
    # fim do número é "não vem outro dígito", e não fronteira de palavra
    assert re.search(r"Acima de 90 dias.{0,60}?R\$\s110(?!\d)", kpis, re.S), kpis
    assert re.search(r"Últimos 30 dias.{0,60}?R\$\s680(?!\d)", kpis, re.S), kpis
    assert "2 clientes (3 empresas)" in kpis
    estagio = _txt(pg, "#cob-estagio")
    for rot in ("Até 15 dias", "16 a 30 dias", "31 a 90 dias", "Acima de 90 dias"):
        assert rot in estagio, rot

    # o detalhe do GRUPO diz de qual empresa é cada título; o do avulso, não
    det_grupo = _txt(pg, "#cob-det-0")
    assert "Empresa" in det_grupo and "FILIAL SUL FICTICIA" in det_grupo
    assert "Empresa" not in _txt(pg, "#cob-det-1")


def test_o_aging_do_A_RECEBER_usa_as_faixas_do_BI_e_o_do_a_pagar_as_de_sempre(pagina):
    pg, base = pagina
    _montar(pg)
    _ir(pg, base, "receber")
    ar = _txt(pg, "#aging-ar-barras")
    for rot in ("Vencido ≤ 15d", "Vencido 16–30d", "Vencido 31–90d", "Vencido > 90d"):
        assert rot in ar, rot
    assert "365" not in ar
    alertas = _txt(pg, "#alerts-receber")
    assert "Vencido há mais de 90 dias" in alertas and "crônica" not in alertas
    _ir(pg, base, "pagar")
    assert "Vencido 91–365d" in _txt(pg, "#aging-ap-barras")
