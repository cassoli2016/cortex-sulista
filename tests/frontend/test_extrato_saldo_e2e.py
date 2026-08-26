"""O card "Saldo nos bancos", que é o que a rotina diária abre para olhar.

Os números vêm do retorno real de 26/08/2026: o Bradesco sem saldo utilizável
(o arquivo grava a data zerada), o Sicredi com cinco dias úteis parado, e o
ERP atrás do extrato em quase todas as contas.
"""
from __future__ import annotations

import json

USUARIO = {"nome": "Teste", "email": "t@sulista.local", "perfil": "admin",
           "admin": True, "telas": []}

POSICAO = {
    "total": 50132.89, "contas_no_total": 6, "contas_sem_saldo": 1,
    "datas_diferentes": False, "dt_mais_antiga": "2026-08-26",
    "dt_mais_nova": "2026-08-26", "atrasadas": 2, "erp_disponivel": True,
    "hoje": "2026-08-26",
    "linhas": [
        {"conta_id": 6, "rotulo": "748 / cc 7300000000075455", "ident": "748/?/73",
         "mapeada": True, "saldo": 7.41, "dt": "2026-08-26", "sem_saldo_por": None,
         "erp_saldo": 7.41, "erp_dt": "2026-08-17", "diferenca": 0.0,
         "atraso_uteis": 5, "ultimo_extrato": "2026-08-18"},
        {"conta_id": 2, "rotulo": "336 / cc 000034988068-9", "ident": "336/0001/00",
         "mapeada": True, "saldo": 202.02, "dt": "2026-08-26", "sem_saldo_por": None,
         "erp_saldo": 408000.0, "erp_dt": "2026-08-19", "diferenca": -407797.98,
         "atraso_uteis": 4, "ultimo_extrato": "2026-08-19"},
        {"conta_id": 1, "rotulo": "237 / cc 123906", "ident": "0237/?/123906",
         "mapeada": True, "saldo": None, "dt": None,
         "sem_saldo_por": "o arquivo deste banco nao traz saldo utilizavel "
                          "(sem LEDGERBAL, ou com a data zerada)",
         "erp_saldo": -1129794.18, "erp_dt": "2026-08-25", "diferenca": None,
         "atraso_uteis": 0, "ultimo_extrato": "2026-08-26"},
        {"conta_id": 3, "rotulo": "341 / cc 0098539349", "ident": "0341/?/00",
         "mapeada": True, "saldo": 1325.59, "dt": "2026-08-26", "sem_saldo_por": None,
         "erp_saldo": 293943.14, "erp_dt": "2026-08-25", "diferenca": -292617.55,
         "atraso_uteis": 0, "ultimo_extrato": "2026-08-25"},
        {"conta_id": 4, "rotulo": "422 / cc 00380012235", "ident": "422/?/00",
         "mapeada": True, "saldo": 0.96, "dt": "2026-08-26", "sem_saldo_por": None,
         "erp_saldo": None, "erp_dt": None, "diferenca": None,
         "atraso_uteis": 0, "ultimo_extrato": "2026-08-26"},
        {"conta_id": 5, "rotulo": "33 / cc 4849130000265", "ident": "033/?/48",
         "mapeada": True, "saldo": 19.77, "dt": "2026-08-26", "sem_saldo_por": None,
         "erp_saldo": 19.77, "erp_dt": "2026-08-26", "diferenca": 0.0,
         "atraso_uteis": 0, "ultimo_extrato": "2026-08-25"},
    ],
}

PAINEL = {"kpis": {}, "contas": [], "dias": [], "importacoes": [],
          "lancamentos_dia": [], "conciliacao_nativa": {}, "posicao": POSICAO}


def _abrir(pg, base, painel=None):
    corpo = json.dumps(painel if painel is not None else PAINEL)
    # a rota registrada POR ÚLTIMO é avaliada primeiro: catch-all antes
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato?*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=corpo))
    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_selector("#extb-pos-corpo table tbody tr", timeout=15000)


def test_total_declara_quem_ficou_de_fora(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#extb-pos-kpis")
    assert "50.132,89" in txt
    assert "1 sem saldo, fora do total" in txt


def test_saldo_ausente_nao_vira_zero(pagina):
    """Zero é um saldo; ausência não é. E jamais em verde."""
    pg, base = pagina
    _abrir(pg, base)
    linha = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#extb-pos-corpo tbody tr')]
          .find(t => t.children[0].textContent.includes('237'));
        const td = tr.children[3];
        const sp = td.querySelector('span');
        return {texto: td.textContent.trim(), titulo: sp && sp.getAttribute('title')};
    }""")
    assert "não informado" in linha["texto"]
    assert "0,00" not in linha["texto"]
    assert "data zerada" in (linha["titulo"] or "")


def test_conta_atrasada_mostra_dias_uteis(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#extb-pos-corpo tbody tr')]
          .find(t => t.children[0].textContent.includes('748'));
        return tr.children[1].textContent.trim();
    }""")
    assert "5 dias úteis" in txt


def test_conta_em_dia_nao_alarma(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#extb-pos-corpo tbody tr')]
          .find(t => t.children[0].textContent.includes('341'));
        return tr.children[1].textContent.trim();
    }""")
    assert "em dia" in txt


def test_diferenca_de_datas_diferentes_nao_sai_em_vermelho(pagina):
    """Em dias distintos a diferença mistura divergência com defasagem de
    lançamento; pintar de vermelho acusaria o ERP de um erro que pode ser só
    atraso."""
    pg, base = pagina
    _abrir(pg, base)
    r = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#extb-pos-corpo tbody tr')]
          .find(t => t.children[0].textContent.includes('336'));
        const sp = tr.children[5].querySelector('span');
        return {texto: tr.children[5].textContent, cor: getComputedStyle(sp).color,
                titulo: sp.getAttribute('title')};
    }""")
    assert "datas" in r["texto"]
    assert "defasagem de lançamento" in (r["titulo"] or "")
    # --red é #C03221; o cinza --n500 é bem mais claro
    assert r["cor"] != "rgb(192, 50, 33)"


def test_diferenca_do_mesmo_dia_sai_marcada(pagina):
    pg, base = pagina
    p = json.loads(json.dumps(PAINEL))
    for x in p["posicao"]["linhas"]:
        if x["conta_id"] == 3:
            x["erp_dt"] = "2026-08-26"          # mesmo dia do extrato
    _abrir(pg, base, painel=p)
    r = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#extb-pos-corpo tbody tr')]
          .find(t => t.children[0].textContent.includes('341'));
        const sp = tr.children[5].querySelector('span');
        return {texto: tr.children[5].textContent.trim(), cor: getComputedStyle(sp).color};
    }""")
    assert "292.617,55" in r["texto"]
    assert "datas" not in r["texto"]
    assert r["cor"] == "rgb(192, 50, 33)"


def test_saldo_que_bate_diz_bate(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#extb-pos-corpo tbody tr')]
          .find(t => t.children[0].textContent.includes('33 / cc'));
        return tr.children[5].textContent.trim();
    }""")
    assert txt == "bate"


def test_datas_diferentes_no_total_sao_declaradas(pagina):
    pg, base = pagina
    p = json.loads(json.dumps(PAINEL))
    p["posicao"]["datas_diferentes"] = True
    p["posicao"]["dt_mais_antiga"] = "2026-08-18"
    _abrir(pg, base, painel=p)
    assert "datas DIFERENTES" in pg.inner_text("#hintExtbPos")
    assert "18/08/2026" in pg.inner_text("#hintExtbPos")
    assert "datas diferentes" in pg.inner_text("#extb-pos-kpis")


def test_erp_fora_nao_esconde_o_saldo_do_banco(pagina):
    pg, base = pagina
    p = json.loads(json.dumps(PAINEL))
    p["posicao"]["erp_disponivel"] = False
    for x in p["posicao"]["linhas"]:
        x["erp_saldo"] = None
        x["erp_dt"] = None
        x["diferenca"] = None
    _abrir(pg, base, painel=p)
    assert "50.132,89" in pg.inner_text("#extb-pos-kpis")
    assert "ERP indisponível agora" in pg.inner_text("#extb-pos-kpis")


def test_sem_conta_nenhuma_o_card_explica(pagina):
    pg, base = pagina
    p = {"kpis": {}, "contas": [], "dias": [], "importacoes": [],
         "lancamentos_dia": [], "conciliacao_nativa": {},
         "posicao": {"linhas": [], "total": 0, "contas_no_total": 0,
                     "contas_sem_saldo": 0, "datas_diferentes": False,
                     "dt_mais_antiga": None, "dt_mais_nova": None,
                     "atrasadas": 0, "erp_disponivel": True, "hoje": "2026-08-26"}}
    corpo = json.dumps(p)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato?*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=corpo))
    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_function(
        "() => document.getElementById('hintExtbPos').textContent.includes('nenhuma conta')",
        timeout=15000)
    assert pg.inner_html("#extb-pos-corpo").strip() == ""
