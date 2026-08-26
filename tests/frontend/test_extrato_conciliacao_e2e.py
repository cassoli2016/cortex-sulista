"""A tela da conciliação linha a linha, no navegador de verdade.

Testa o que só o navegador prova: a ordem em que os dias aparecem, o que a
linha expansível abre, e que a tela não volte a despejar milhares de linhas de
uma vez — que foi o defeito que a versão anterior desta tela tinha.

O `pagina` da conftest serve o `index.html` real por http.server e intercepta
`/api/**`, então nada aqui depende de banco, de túnel ou do AVA.
"""
from __future__ import annotations

import json

import pytest

USUARIO = {"nome": "Teste", "email": "t@sulista.local", "perfil": "admin",
           "admin": True, "telas": []}

# Recorte do retorno REAL de agosto/2026 (Itaú e Caixa), com os números
# medidos: o dia de granularidade da Caixa tem 15 linhas de banco contra 372 do
# razão e resíduo de R$ 0,03; o dia que o ERP não lançou é o do Bradesco.
CONCIL = {
    "ok": True,
    "conta": {"id": 3, "rotulo": "341 / cc 0098539349", "erp_banco": 341},
    "dt_de": "2026-08-01", "dt_ate": "2026-08-26",
    "resumo": {"banco_linhas": 166, "erp_linhas": 1340, "casados": 77,
               "casados_pct": 46.4, "por_janela": 2, "sobra_banco": 89,
               "sobra_erp": 1263, "dias_total": 4,
               "dias_por_estado": {"diverge": 2, "granularidade": 1, "erp_nao_lancou": 1},
               "dias_a_tratar": 3, "valor_sem_explicacao": -292617.56},
    "dias": [
        # de propósito FORA de ordem de gravidade, para provar que a tela ordena
        {"dt": "2026-08-03", "estado": "granularidade", "residuo": 0.0, "fecha": True,
         "residuo_pct": 0.0, "banco_linhas": 15, "banco_valor": 885435.84,
         "erp_linhas": 372, "erp_valor": 885435.84,
         "sobra_banco_linhas": 15, "sobra_banco_valor": 885435.84,
         "sobra_erp_linhas": 372, "sobra_erp_valor": 885435.84},
        {"dt": "2026-08-04", "estado": "diverge", "residuo": 0.03, "fecha": False,
         "residuo_pct": 0.0000034, "banco_linhas": 5, "banco_valor": 885435.84,
         "erp_linhas": 70, "erp_valor": 885435.81,
         "sobra_banco_linhas": 1, "sobra_banco_valor": 0.03,
         "sobra_erp_linhas": 2, "sobra_erp_valor": 0.0},
        {"dt": "2026-08-25", "estado": "diverge", "residuo": -129240.06, "fecha": False,
         "residuo_pct": 99.4, "banco_linhas": 3, "banco_valor": 759.94,
         "erp_linhas": 4, "erp_valor": 130000.0,
         "sobra_banco_linhas": 2, "sobra_banco_valor": 759.94,
         "sobra_erp_linhas": 3, "sobra_erp_valor": 130000.0},
        {"dt": "2026-08-26", "estado": "erp_nao_lancou", "residuo": 1212725.46,
         "fecha": False, "residuo_pct": 100.0, "banco_linhas": 6,
         "banco_valor": 1212725.46, "erp_linhas": 0, "erp_valor": 0.0,
         "sobra_banco_linhas": 6, "sobra_banco_valor": 1212725.46,
         "sobra_erp_linhas": 0, "sobra_erp_valor": 0.0},
    ],
    "sobra_banco": (
        [{"dt": "2026-08-03", "valor": 1000.0 + i, "historico": f"SISPAG {i}",
          "numerodoc": str(i), "ref": f"b{i}"} for i in range(15)]
        + [{"dt": "2026-08-04", "valor": 0.03, "historico": "TARIFA", "numerodoc": "9", "ref": "b90"}]
        + [{"dt": "2026-08-25", "valor": 380.0, "historico": "PIX ENVIADO", "numerodoc": "", "ref": "b91"},
           {"dt": "2026-08-25", "valor": 379.94, "historico": "TED", "numerodoc": "", "ref": "b92"}]
        + [{"dt": "2026-08-26", "valor": 202120.91, "historico": f"TED SOFISA {i}",
            "numerodoc": "", "ref": f"b{200+i}"} for i in range(6)]
    ),
    "sobra_erp": (
        [{"dt": "2026-08-03", "valor": 100.0 + i, "historico": f"PGTO FORNECEDOR {i}",
          "nominal": f"FORNECEDOR {i}", "ref": f"e{i}"} for i in range(372)]
        + [{"dt": "2026-08-04", "valor": 0.0, "historico": "AJUSTE", "nominal": "", "ref": "e900"},
           {"dt": "2026-08-04", "valor": 0.0, "historico": "AJUSTE", "nominal": "", "ref": "e901"}]
        + [{"dt": "2026-08-25", "valor": 43333.34, "historico": "TRANSFERENCIA",
            "nominal": "SULISTA", "ref": f"e{950+i}"} for i in range(3)]
    ),
    "atualizado_em": "26/08/2026 18:00",
}


def _abrir(pg, base, concil=None):
    """Abre a tela de Extrato Bancário já logada, com a API toda mockada."""
    corpo = json.dumps(concil if concil is not None else CONCIL)

    # No Playwright a rota registrada POR ÚLTIMO é avaliada primeiro, então o
    # catch-all vai ANTES do mock específico (armadilha já documentada no
    # CLAUDE.md, custou uma rodada quando os testes da barra de carga nasceram).
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato?*", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"kpis": [], "contas": [], "dias": [], "importacoes": [],
                         "lancamentos_dia": [], "conciliacao_nativa": {}})))
    pg.route("**/api/financeiro/extrato/conciliacao*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=corpo))

    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_selector("#view-extb.on", timeout=15000)
    # a conciliação é sob demanda e exige conta escolhida; o mock do painel não
    # popula o select, então o valor entra direto
    pg.evaluate("""() => {
        const s = document.getElementById('fExtbConta');
        s.innerHTML = '<option value="3">341 / cc 0098539349</option>';
        s.value = '3';
        document.getElementById('fExtbDe').value = '2026-08-01';
        document.getElementById('fExtbAte').value = '2026-08-26';
    }""")
    pg.click("#btnExtbLinha")
    pg.wait_for_selector("#extb-linha-corpo table tbody tr", timeout=15000)


def test_sem_conta_escolhida_nao_chama_a_api(pagina):
    """Sem conta não há razão com que comparar: a tela diz isso em vez de ir à
    API para voltar 422."""
    pg, base = pagina
    chamadas = []
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato/conciliacao*",
             lambda r: (chamadas.append(r.request.url),
                        r.fulfill(status=200, content_type="application/json", body="{}")))
    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_selector("#view-extb.on", timeout=15000)
    pg.evaluate("() => { document.getElementById('fExtbConta').innerHTML=''; }")
    pg.click("#btnExtbLinha")
    pg.wait_for_timeout(400)
    assert chamadas == []
    assert "escolha uma conta" in pg.inner_text("#hintExtbLinha")


def test_ordena_por_gravidade_e_nao_por_data(pagina):
    """Ordenar por data deixaria o dia de R$ 1,2 mi no meio de dias que fecham."""
    pg, base = pagina
    _abrir(pg, base)
    dias = pg.eval_on_selector_all(
        "#extb-linha-corpo table tbody tr.forn-row td:nth-child(2)",
        "els => els.map(e => e.textContent.trim())")
    # 26/08 (ERP não lançou) e 25/08 (diverge R$ 129 mil) antes do dia de
    # granularidade e do diverge de 3 centavos
    assert dias[:2] == ["26/08/2026", "25/08/2026"], dias
    assert dias.index("04/08/2026") > dias.index("25/08/2026")


def test_residuo_de_centavo_fica_atenuado_mas_visivel(pagina):
    """R$ 0,03 sobre R$ 885 mil continua sendo `diverge` — o estado não mente —
    mas não pode competir visualmente com R$ 129 mil."""
    pg, base = pagina
    _abrir(pg, base)
    cor = pg.evaluate("""() => {
        const trs = [...document.querySelectorAll('#extb-linha-corpo table tbody tr.forn-row')];
        const tr = trs.find(t => t.children[1].textContent.trim() === '04/08/2026');
        const span = tr.lastElementChild.querySelector('span');
        return span ? {tem: true, titulo: span.getAttribute('title'),
                       texto: span.textContent.trim()} : {tem: false};
    }""")
    assert cor["tem"], "o resíduo de centavo perdeu a atenuação"
    assert "0,03" in cor["texto"]
    assert "movimentados no dia" in (cor["titulo"] or "")


def test_dia_que_fecha_nao_mostra_residuo(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.evaluate("""() => {
        const trs = [...document.querySelectorAll('#extb-linha-corpo table tbody tr.forn-row')];
        const tr = trs.find(t => t.children[1].textContent.trim() === '03/08/2026');
        return tr.lastElementChild.textContent.trim();
    }""")
    assert txt == "—"


def test_a_tela_nao_despeja_as_sobras_de_uma_vez(pagina):
    """O defeito que esta versão corrigiu: a tela listava as sobras de TODOS os
    dias a tratar de uma vez — 1.352 linhas no Itaú. Fechada, a tela mostra uma
    linha por dia e nada mais."""
    pg, base = pagina
    _abrir(pg, base)
    visiveis = pg.eval_on_selector_all(
        "#extb-linha-corpo table tbody tr",
        "els => els.filter(e => e.offsetParent !== null).length")
    assert visiveis <= 8, f"{visiveis} linhas visíveis com a tela fechada"


def test_abrir_um_dia_traz_so_as_linhas_daquele_dia(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.evaluate("""() => {
        const trs = [...document.querySelectorAll('#extb-linha-corpo table tbody tr.forn-row')];
        const tr = trs.find(t => t.children[1].textContent.trim() === '25/08/2026');
        tr.click();
    }""")
    pg.wait_for_selector("#extb-linha-corpo tr.forn-det.open table", timeout=5000)
    linhas = pg.eval_on_selector_all(
        "#extb-linha-corpo tr.forn-det.open table tbody tr",
        "els => els.map(e => e.children[0].textContent.trim())")
    # 2 do extrato + 3 do razão daquele dia, e nada dos 372 de 03/08
    assert len(linhas) == 5, linhas
    assert linhas.count("Extrato") == 2
    assert linhas.count("Razão ERP") == 3


def test_dia_de_granularidade_avisa_que_o_valor_fecha(pagina):
    """Abrir um dia com 387 linhas sem par e nenhuma explicação faria parecer
    caos; o aviso diz que falta o par, não o dinheiro."""
    pg, base = pagina
    _abrir(pg, base)
    pg.evaluate("""() => {
        const trs = [...document.querySelectorAll('#extb-linha-corpo table tbody tr.forn-row')];
        const tr = trs.find(t => t.children[1].textContent.trim() === '03/08/2026');
        tr.click();
    }""")
    pg.wait_for_selector("#extb-linha-corpo tr.forn-det.open p", timeout=5000)
    p = pg.inner_text("#extb-linha-corpo tr.forn-det.open p")
    assert "FECHA" in p
    assert "372 do razão" in p


def test_conta_sem_vinculo_com_o_erp_explica_em_vez_de_quebrar(pagina):
    # `_abrir` não serve aqui: ele espera a tabela nascer, e o caso sem vínculo
    # justamente não desenha tabela nenhuma.
    pg, base = pagina
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato/conciliacao*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps({
            "ok": False, "precisa": "mapa_erp",
            "conta": {"id": 9, "rotulo": "422 / cc 00380012235"},
            "mensagem": "Esta conta ainda nao esta vinculada a uma conta do ERP."})))
    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_selector("#view-extb.on", timeout=15000)
    pg.evaluate("""() => {
        const s = document.getElementById('fExtbConta');
        s.innerHTML = '<option value="9">422</option>'; s.value = '9';
        document.getElementById('fExtbDe').value = '2026-08-01';
        document.getElementById('fExtbAte').value = '2026-08-26';
    }""")
    pg.click("#btnExtbLinha")
    pg.wait_for_function(
        "() => document.getElementById('hintExtbLinha').textContent.includes('vinculada')",
        timeout=10000)
    assert pg.inner_html("#extb-linha-corpo").strip() == ""
