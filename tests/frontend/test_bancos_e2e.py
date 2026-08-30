"""A tela Bancos no navegador.

Os números são os reais de agosto/2026. O que estes testes protegem é a
distinção que governa a tela: o que foi MEDIDO e o que foi DERIVADO, e o fato
de o saldo aqui ser o de CONTA CORRENTE, não o caixa da empresa.
"""
from __future__ import annotations

import json

USUARIO = {"nome": "Teste", "email": "t@sulista.local", "perfil": "admin",
           "admin": True, "telas": []}

DADOS = {
    "dt_de": "2026-08-01", "dt_ate": "2026-08-26",
    "atualizado_em": "27/08/2026 16:40",
    "kpis": {"saldo_total": 52924.69, "contas": 6, "contas_sem_saldo": 1,
             "recebido": 27739641.02, "pago": -26427185.02,
             "custo": 46343.96, "custo_ano": 650597.90,
             "custo_juros": 40075.81, "custo_juros_pct": 86.5,
             "contas_com_juros": 3, "concentracao_2": 72.7, "dias": 26},
    "custo_por_natureza": [
        {"chave": "juros", "rotulo": "Juros de limite / cheque especial",
         "qtd": 6, "valor": 40075.81},
        {"chave": "iof", "rotulo": "IOF", "qtd": 5, "valor": 5098.99},
    ],
    "bancos": [
        {"conta_id": 6, "ident": "748/?/7300000000075455", "rotulo": "748 / cc x",
         "banco": 748, "banco_nome": "Banco Cooperativo Sicredi S.A. - Bansicredi",
         "recebido": 4700.0, "pago": -5131.8, "pct_recebido": 0.0,
         "saldo": 7.41, "saldo_dt": "2026-08-26", "sem_saldo_por": None,
         "atraso_uteis": 6, "custo": 1659.31, "custo_por_mil": 353.04,
         "custo_natureza": [{"chave": "juros", "qtd": 1, "valor": 1431.61}],
         "ancoras": 1, "saldo_medido": False, "lancamentos": 8},
        {"conta_id": 3, "ident": "0341/?/0098539349", "rotulo": "341 / cc y",
         "banco": 341, "banco_nome": "Banco Itaú S.A.",
         "recebido": 11072207.28, "pago": -9177178.55, "pct_recebido": 39.9,
         "saldo": 4117.36, "saldo_dt": "2026-08-27", "sem_saldo_por": None,
         "atraso_uteis": 0, "custo": 36935.35, "custo_por_mil": 3.34,
         "custo_natureza": [{"chave": "juros", "qtd": 2, "valor": 32913.53},
                            {"chave": "iof", "qtd": 1, "valor": 3764.10}],
         "ancoras": 21, "saldo_medido": True, "lancamentos": 180},
        {"conta_id": 1, "ident": "0237/?/123906", "rotulo": "237 / cc z",
         "banco": 237, "banco_nome": "Banco Bradesco S.A.",
         "recebido": 9096288.0, "pago": -7851313.22, "pct_recebido": 32.8,
         "saldo": None, "saldo_dt": None,
         "sem_saldo_por": "o arquivo deste banco nao traz saldo utilizavel "
                          "(sem LEDGERBAL, ou com a data zerada)",
         "atraso_uteis": 0, "custo": 294.64, "custo_por_mil": 0.03,
         "custo_natureza": [{"chave": "transacao", "qtd": 35, "valor": 183.44}],
         "ancoras": 0, "saldo_medido": False, "lancamentos": 364},
    ],
    "serie": [
        {"dt": "2026-08-03", "saldo": 842262.16, "contas": 6},
        {"dt": "2026-08-04", "saldo": 429516.92, "contas": 5},
        {"dt": "2026-08-05", "saldo": -224.19, "contas": 4},
        {"dt": "2026-08-26", "saldo": 52924.69, "contas": 6},
    ],
    "alertas": [
        {"nivel": "critico", "banco": "Sicredi",
         "texto": "Sicredi custou R$ 1.659,31 para movimentar R$ 4.700,00 — "
                  "35.3% de tudo que passou por ela."},
        {"nivel": "atencao", "banco": None,
         "texto": "72.7% do que entra passa por dois bancos."},
    ],
}


def _abrir(pg, base, dados=None):
    corpo = json.dumps(dados if dados is not None else DADOS)
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{}"))
    pg.route("**/api/auth/me*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(USUARIO)))
    pg.route("**/api/financeiro/bancos*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=corpo))
    pg.goto(f"{base}/static/index.html#banc")
    pg.wait_for_selector("#banc-tab table tbody tr", timeout=15000)


def test_a_tela_abre(pagina):
    """Fora de VIEWS o clique cai calado na Visão Geral."""
    pg, base = pagina
    _abrir(pg, base)
    assert pg.is_visible("#view-banc")


def test_o_saldo_diz_que_e_de_conta_corrente(pagina):
    """"Total nos bancos" seria mentira por omissão: o dinheiro varrido para
    aplicação não está aqui, e nenhum arquivo o reporta."""
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#kpis-banc")
    assert "Saldo em conta corrente" in txt
    assert "52.924,69" in txt
    assert "1 sem saldo, fora do total" in txt


def test_o_custo_traz_o_anualizado_e_a_fatia_de_juros(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#kpis-banc")
    assert "46.343,96" in txt
    assert "650.597,90/ano" in txt
    assert "86,5% é juro de limite" in txt, "percentual em pt-BR, com vírgula"


def test_a_tabela_ordena_por_custo_relativo_e_nao_absoluto(pagina):
    """Em valor absoluto o Sicredi (R$ 1.659) parece barato ao lado do Itaú
    (R$ 36.935); por R$ mil movimentado ele é 100 vezes pior."""
    pg, base = pagina
    _abrir(pg, base)
    nomes = pg.eval_on_selector_all(
        "#banc-tab table tbody tr.forn-row td:nth-child(2)",
        "els => els.map(e => e.textContent.trim())")
    assert nomes[0].startswith("Banco Cooperativo Sicredi"), nomes
    assert any(n.startswith("Banco Itaú") for n in nomes)


def test_conta_sem_ancora_avisa_que_a_serie_e_derivada(pagina):
    """Âncora única: o saldo dos outros dias é soma, não medição."""
    pg, base = pagina
    _abrir(pg, base)
    r = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#banc-tab table tbody tr.forn-row')]
          .find(t => t.textContent.includes('Bradesco'));
        const td = tr.children[7];
        return {texto: td.textContent.trim(),
                titulo: (td.querySelector('span')||{}).getAttribute
                        ? td.querySelector('span').getAttribute('title') : null};
    }""")
    assert r["texto"] == "0"
    assert "derivado" in (r["titulo"] or "")


def test_saldo_ausente_nao_vira_zero(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.evaluate("""() => {
        const tr = [...document.querySelectorAll('#banc-tab table tbody tr.forn-row')]
          .find(t => t.textContent.includes('Bradesco'));
        return tr.children[6].textContent.trim();
    }""")
    assert "não informado" in txt
    assert "0,00" not in txt


def test_dia_de_cobertura_parcial_sai_marcado(pagina):
    """Cobertura parcial NÃO é dia com menos dinheiro — é dia com menos conta
    medida. Sem a marca, a série mentiria sobre uma queda de caixa.

    A asserção mede a REGRA, não a marcação: antes ela procurava o
    `stroke-dasharray` que a versão desenhada à mão punha na barra, e quebrou
    na conversão para ECharts sem que a hachura tivesse sumido — só mudou de
    forma (agora é um `<pattern>` referenciado por `fill`). O que vale é que
    UMA barra saia hachurada e as outras não.
    """
    pg, base = pagina
    _abrir(pg, base)
    r = pg.evaluate("""() => {
        const barras = [...document.querySelectorAll('#banc-serie path, #banc-serie rect')]
          .map(x => x.getAttribute('fill') || '')
          .filter(f => f && f !== 'none' && f !== 'transparent');
        return {total: barras.length,
                hachuradas: barras.filter(f => f.startsWith('url(')).length,
                padroes: document.querySelectorAll('#banc-serie pattern').length};
    }""")
    # o esperado sai do PROPRIO payload: dia parcial e o que mediu menos
    # contas que o melhor dia da serie
    serie = DADOS["serie"]
    maxc = max(d["contas"] for d in serie)
    esperado = sum(1 for d in serie if d["contas"] < maxc)
    assert esperado, "o payload de teste nao tem dia parcial — nada a medir"

    assert r["padroes"] >= 1, "nenhuma hachura definida no gráfico"
    assert r["hachuradas"] == esperado, (
        f"esperava {esperado} dia(s) hachurado(s), achei {r['hachuradas']} "
        f"de {r['total']} elementos pintados")
    assert r["hachuradas"] < len(serie), (
        "todos os dias saíram hachurados — a marca deixa de distinguir")
    assert pg.inner_text("#hintBancSerie").count("cobertura parcial") == 1


def test_abrir_um_banco_mostra_a_quebra_do_custo(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.evaluate("""() => {
        [...document.querySelectorAll('#banc-tab table tbody tr.forn-row')]
          .find(t => t.textContent.includes('Itaú')).click();
    }""")
    pg.wait_for_selector("#banc-tab tr.forn-det.open table", timeout=5000)
    txt = pg.inner_text("#banc-tab tr.forn-det.open")
    assert "Juros de limite" in txt
    assert "32.913,53" in txt


def test_alertas_carregam_o_numero_que_os_sustenta(pagina):
    pg, base = pagina
    _abrir(pg, base)
    txt = pg.inner_text("#banc-alertas")
    assert "1.659,31" in txt
    assert "72.7%" in txt or "72,7%" in txt


def test_o_extrato_bancario_nao_tem_mais_o_cartao_de_saldo(pagina):
    """Ele mudou de tela: era o único bloco de tesouraria numa tela de
    conciliação."""
    pg, base = pagina
    _abrir(pg, base)
    assert pg.eval_on_selector_all("#view-extb #extb-pos-corpo", "els => els.length") == 0


def test_atraso_no_envio_aparece_na_tela_do_saldo(pagina):
    """Extrato atrasado deixa o saldo desta tela velho — o sinal de frescor
    pertence aqui, não só à tela de conciliação."""
    pg, base = pagina
    _abrir(pg, base)
    r = pg.evaluate("""() => {
        const trs = [...document.querySelectorAll('#banc-tab table tbody tr.forn-row')];
        const sic = trs.find(t => t.textContent.includes('Sicredi'));
        const ita = trs.find(t => t.textContent.includes('Itaú'));
        return {sicredi: sic.children[2].textContent.trim(),
                itau: ita.children[2].textContent.trim()};
    }""")
    assert "6 dias úteis" in r["sicredi"]
    assert "em dia" in r["itau"]
