# -*- coding: utf-8 -*-
"""A tela `whrval` no navegador.

O dublê é a RESPOSTA do servidor montada pela própria `conferir_coleta` sobre
os fixtures de `tests/validacao_whirlpool/test_validacao.py` — a forma é a
do código, não uma cópia escrita à mão que envelhece. O volume (150 coletas)
fica acima das ~140 que a Whirlpool emite em 30 dias: a tabela tem de rolar
DENTRO do cartão.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta

from api.validacao_whirlpool import validacao as V
from tests.frontend.conftest import USUARIO
from tests.validacao_whirlpool import test_validacao as F

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}


def _payload() -> dict:
    coletas = []
    for i in range(150):
        col = {**F.COLETA, "numero": 20000 + i, "dtemissao": datetime(2026, 9, 16) - timedelta(hours=i * 4)}
        ctes = F._ctes_iguais()
        anexos, doc = [F.ANEXO], F.DOC
        tipo = i % 6
        if tipo == 1:
            ctes[0]["frete"] += 37.87
            ctes[0]["total"] += 37.87
        elif tipo == 2:
            ctes[0]["frete"] += 0.28
            ctes[0]["total"] += 0.28
        elif tipo == 3:
            anexos = []
        elif tipo == 4:
            doc = {"formato": "desconhecido", "motivo": "requisição de transporte expresso"}
        linha = V.conferir_coleta(col, anexos, {900: copy.deepcopy(doc)}, ctes)
        coletas.append(linha)
    contagem = {e: 0 for e in V.ESTADOS}
    grupos: dict = {}
    for c in coletas:
        contagem[c["estado"]] += 1
        for g in c["falhas"]:
            grupos[g] = grupos.get(g, 0) + 1
    corpo = {"periodo": {"de": "2026-08-17", "ate": "2026-09-16"}, "coletas": coletas,
             "contagem": contagem, "divergencias_por_grupo": grupos, "estados": V.ESTADOS,
             "anexos_ainda_nao_lidos": 0,
             "regras": {"tol_valor": V.TOL_VALOR, "tol_arredondamento": V.TOL_ARREDONDAMENTO,
                        "tol_peso_rel": V.TOL_PESO_REL, "tol_icms_pct": V.TOL_ICMS_PCT,
                        "ocorrencia": 262}}
    return json.loads(json.dumps(corpo, default=str))


def _abre(pagina, largura=1440, altura=900):
    pg, base = pagina
    corpo = _payload()
    pedidos = []

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            dado = ADMIN
        elif "/api/operacao/whirlpool/validacao" in url:
            pedidos.append(url)
            dado = corpo
        else:
            dado = {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(dado))
    pg.route("**/api/**", rota)
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#whrval")
    pg.wait_for_selector("#whrval-lista table")
    return pg, corpo, pedidos


def test_abre_com_kpis_e_a_lista_do_que_precisa_de_atencao(pagina):
    pg, corpo, pedidos = _abre(pagina)
    assert pedidos and "de=" in pedidos[0] and "ate=" in pedidos[0]
    kpis = pg.inner_text("#kpis-whrval")
    assert "Coletas no período" in kpis and "150" in kpis
    assert "Divergentes" in kpis and "25" in kpis
    # o padrão é "precisa de atenção": conferido e aguardando CT-e ficam fora
    n = pg.evaluate("document.querySelectorAll('#whrval-lista tbody tr').length")
    esperado = sum(1 for c in corpo["coletas"] if c["estado"] not in ("ok", "sem_cte"))
    assert n == esperado and n < 150
    assert "Conferido" not in pg.inner_text("#whrval-lista")


def test_filtro_e_busca(pagina):
    pg, corpo, _ = _abre(pagina)
    pg.select_option("#fWhrvalEstado", "ok")
    assert pg.evaluate("document.querySelectorAll('#whrval-lista tbody tr').length") == \
        sum(1 for c in corpo["coletas"] if c["estado"] == "ok")
    pg.select_option("#fWhrvalEstado", "")
    pg.fill("#fWhrvalBusca", "20007")
    assert pg.evaluate("document.querySelectorAll('#whrval-lista tbody tr').length") == 1


def test_detalhe_mostra_cada_fornecedor_com_o_seu_cte(pagina):
    pg, corpo, _ = _abre(pagina)
    pg.fill("#fWhrvalBusca", "20001")            # tipo 1: frete divergente
    pg.click("#whrval-lista tbody tr")
    pg.wait_for_selector("#modalBg.aberto")
    txt = pg.inner_text("#modalBox")
    assert "Coleta 1/20001" in txt
    assert "ALFA" in txt and "BETA" in txt and "55606" in txt
    assert "diverge" in txt and "Frete" in txt
    assert "/api/operacao/whirlpool/anexo/900" in pg.inner_html("#modalBox")


def test_sem_barra_global_e_sem_rolagem_lateral(pagina):
    pg, _, _ = _abre(pagina)
    assert pg.evaluate("getComputedStyle(document.querySelector('.filterbar')).display") == "none"
    assert pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    # a tabela rola DENTRO do cartão, não a página
    rola = pg.evaluate("""() => { const e = document.getElementById('whrval-lista');
        return e.scrollHeight > e.clientHeight; }""")
    assert rola, "150 coletas deviam rolar dentro do cartão"


def test_esta_no_menu_e_na_gaveta(pagina):
    pg, _, _ = _abre(pagina)
    assert pg.evaluate("!!document.querySelector('#sidebar a[href=\"#whrval\"] .ic svg')")
    assert pg.evaluate("!!document.querySelector('.drawer a[href=\"#whrval\"]')")
