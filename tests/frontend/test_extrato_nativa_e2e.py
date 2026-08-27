"""O card "Conciliação nativa do ERP" no navegador.

O ponto: o número de pendentes mudou de 27.581 para 24.725 e a tela precisa
DIZER por quê — senão ele aparece diferente do de ontem sem nenhuma pista.
"""
from __future__ import annotations

import json

USUARIO = {"nome": "Teste", "email": "t@sulista.local", "perfil": "admin",
           "admin": True, "telas": []}

NATIVA = {
    "resumo": [
        {"situacao": "Pendente", "qtd": 27581, "creditos": 549313766.04,
         "debitos": 444709679.06, "vinculadas": 2856},
        {"situacao": "Conciliado", "qtd": 1604, "creditos": 19634724.89,
         "debitos": 21389487.78, "vinculadas": 179},
    ],
    "contas": [{"banco": 237, "banco_nome": "BANCO BRADESCO S.A.",
                "rotulo": "BANCO BRADESCO S.A. ag. 36455 cc 1239066",
                "agencia": "36455", "conta": "1239066", "total": 29355,
                "pendentes": 24725, "valor_pendente": 932088882.61,
                "marcadas": 1604, "vinculadas": 2856,
                "pendente_mais_antigo": "2023-05-18",
                "ultimo_movimento": "2026-08-26"}],
    "mensal": [{"mes": "2026-08", "pendentes": 391, "conciliados": 0,
                "vinculados": 17, "valor_pendente": 16168824.29}],
    "kpis": {"total": 29355, "pendentes": 24725, "pct_pendente": 84.2,
             "valor_pendente": 932088882.61, "marcadas": 1604, "vinculadas": 2856,
             "pendentes_pela_situacao": 27581,
             "ultima_marcacao": "2023-08-28", "ultimo_vinculo": "2026-08-27",
             "ultima_carga": "2026-08-27", "contas_com_feed": 1},
    "fonte": "ERP AVA",
}

PAINEL = {"kpis": {}, "contas": [], "dias": [], "importacoes": [],
          "lancamentos_dia": [], "conciliacao_nativa": NATIVA,
          "posicao": {"linhas": [], "total": 0, "contas_no_total": 0,
                      "contas_sem_saldo": 0, "datas_diferentes": False,
                      "dt_mais_antiga": None, "dt_mais_nova": None,
                      "atrasadas": 0, "erp_disponivel": True, "hoje": "2026-08-27"}}


def _abrir(pg, base, painel=None):
    corpo = json.dumps(painel if painel is not None else PAINEL)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato?*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=corpo))
    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_selector("#extb-concil-corpo table tbody tr", timeout=15000)


def test_pendente_mostra_o_numero_corrigido(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#extb-concil-kpis")
    assert "84,2%" in txt
    assert "24.725 de 29.355" in txt


def test_a_tela_explica_por_que_o_numero_mudou(pagina):
    """Sem isto o 84,2% aparece no lugar do 94% de ontem sem nenhuma pista."""
    pg, base = pagina
    _abrir(pg, base)
    aviso = pg.inner_text("#extb-concil-corpo")
    assert "2.856" in aviso
    assert "27.581" in aviso and "24.725" in aviso
    assert "Pendente" in aviso


def test_o_aviso_diz_que_a_marcacao_foi_abandonada(pagina):
    pg, base = pagina
    _abrir(pg, base)
    aviso = pg.inner_text("#extb-concil-corpo")
    assert "28/08/2023" in aviso, "a data da última marcação de situação"
    assert "27/08/2026" in aviso, "a data do último vínculo"


def test_as_duas_marcas_aparecem_separadas(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#extb-concil-kpis")
    assert "1.604 marcadas" in txt
    assert "2.856 só vinculadas" in txt


def test_a_tabela_ganhou_as_colunas_das_duas_marcas(pagina):
    pg, base = pagina
    _abrir(pg, base)
    cabecalhos = pg.eval_on_selector_all(
        "#extb-concil-corpo table thead th",
        "els => els.map(e => e.textContent.trim())")
    assert "Marcadas" in cabecalhos
    assert "Só vinculadas" in cabecalhos
    linha = pg.eval_on_selector_all(
        "#extb-concil-corpo table tbody tr td",
        "els => els.map(e => e.textContent.trim())")
    assert "1.604" in linha and "2.856" in linha and "24.725" in linha


def test_sem_vinculo_nenhum_o_aviso_nao_aparece(pagina):
    """Conta cuja conciliação é feita só pela situação não precisa da explicação."""
    pg, base = pagina
    p = json.loads(json.dumps(PAINEL))
    p["conciliacao_nativa"]["kpis"]["vinculadas"] = 0
    p["conciliacao_nativa"]["kpis"]["pendentes_pela_situacao"] = 24725
    p["conciliacao_nativa"]["contas"][0]["vinculadas"] = 0
    _abrir(pg, base, painel=p)
    corpo = pg.inner_text("#extb-concil-corpo")
    assert "já estão ligados ao razão" not in corpo


def test_sem_feed_o_card_explica_em_vez_de_ficar_vazio(pagina):
    pg, base = pagina
    p = json.loads(json.dumps(PAINEL))
    p["conciliacao_nativa"] = {"resumo": [], "contas": [], "mensal": [],
                               "kpis": {"contas_com_feed": 0}}
    corpo = json.dumps(p)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/extrato?*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=corpo))
    pg.goto(f"{base}/static/index.html#extb")
    pg.wait_for_function(
        "() => document.getElementById('extb-concil-corpo').textContent.includes('não tem feed')",
        timeout=15000)
    assert pg.inner_text("#hintExtbConcil").startswith("nenhuma conta")
