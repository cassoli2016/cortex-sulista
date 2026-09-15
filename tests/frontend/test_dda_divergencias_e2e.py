# -*- coding: utf-8 -*-
"""As divergências do DDA no index.html real: o modal conta os casados pela
soma do dia, a lista de divergências sai por dia de credor com os dois lados
(soma no banco, soma no ERP, diferença e o detalhe dos documentos e títulos),
e o relatório baixa como planilha.

Nomes, CNPJs e valores são de mentira — o repositório é público.
"""
from __future__ import annotations

import json
import re

from tests.frontend.conftest import USUARIO
from tests.frontend.test_projecao_tela_e2e import DDA_DETALHE, PAYLOAD

RESUMO = {**DDA_DETALHE["resumo"], "agrupados": 117, "agrupados_valor": 157_185.0,
          "grupos_soma": 75, "divergentes": 2, "divergentes_valor": 1_640.05,
          "divergencias": 1, "divergencias_banco_a_mais": 89.83,
          "divergencias_erp_a_mais": 0.0}
DDA = {**DDA_DETALHE, "resumo": RESUMO, "grupos_soma": 75, "divergencias": [{
    "credor": "FORNECEDOR PARCELADO LTDA", "erp_credor": "FORNECEDOR PARCELADO",
    "beneficiario_doc": "18••••••••55", "vencimento": "2026-09-18",
    "boletos": 2, "titulos": 2, "soma_dda": 1_640.05, "soma_erp": 1_550.22,
    "diferenca": 89.83,
    "itens_dda": [{"documento": "9458/4", "valor": 1_040.05, "a_pagar": 1_040.05, "tipo": "DM"},
                  {"documento": "9460/1", "valor": 600.0, "a_pagar": 600.0, "tipo": "DM"}],
    "itens_erp": [{"titulo": "283700/2", "parcela": 2, "valor": 850.22, "pendente": 850.22,
                   "pago": None},
                  {"titulo": "283701/2", "parcela": 2, "valor": 700.0, "pendente": 0.0,
                   "pago": "2026-09-12"}],
}]}
NOME = "DDA-conferencia-2026-09-09.xlsx"


def _abrir(pagina):
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/financeiro/dda/relatorio" in url:
            r.fulfill(status=200,
                      content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      headers={"Content-Disposition":
                               f"attachment; filename=\"{NOME}\"; filename*=UTF-8''{NOME}"},
                      body=b"PK planilha de duble")
            return
        if "/api/auth/me" in url:
            body = USUARIO
        elif "/api/financeiro/projecao" in url:
            body = PAYLOAD
        elif "/api/financeiro/dda" in url:
            body = DDA
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#fluxcon")
    pg.wait_for_timeout(500)
    pg.evaluate("() => abaTrocar('fluxcon','plano')")
    pg.wait_for_timeout(500)
    pg.eval_on_selector("#kpis-proj .kpi:nth-child(4)", "e => e.click()")
    pg.wait_for_selector("#modalBg.aberto")
    pg.wait_for_function("document.getElementById('modalBox').textContent.includes('sem título')")
    return pg


def _txt(pg):
    return pg.eval_on_selector("#modalBox", "e => e.textContent")


def test_o_modal_do_DDA_conta_os_casados_pela_soma_e_leva_as_divergencias(pagina):
    pg = _abrir(pagina)
    txt = _txt(pg)
    assert "117 casados pela soma do dia" in txt, txt[:400]
    assert "2 em divergência (1 dias de credor)" in txt
    assert "Ver divergências (1)" in txt and "Baixar relatório" in txt


def test_as_divergencias_saem_por_DIA_DE_CREDOR_com_os_dois_lados(pagina):
    pg = _abrir(pagina)
    pg.click("text=Ver divergências (1)")
    pg.wait_for_function(
        "document.getElementById('modalBox').textContent.includes('Divergências do DDA')")
    txt = _txt(pg)
    assert "FORNECEDOR PARCELADO LTDA" in txt and "18••••••••55" in txt
    assert re.search(r"\+R\$\s89,83", txt), txt[:600]
    assert "2 boletos" in txt and "2 títulos" in txt
    assert "9458/4" in txt and "283700/2" in txt and "(pago 12/09" in txt
    assert "117 boletos já casaram pela soma do dia (75 dias de credor)" in txt


def test_baixar_o_relatorio_entrega_a_planilha(pagina):
    pg = _abrir(pagina)
    with pg.expect_download() as dl:
        pg.click("#dda-rel")
    assert dl.value.suggested_filename == NOME
