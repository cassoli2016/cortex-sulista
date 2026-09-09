"""O Plano 12 meses contra o `index.html` real.

O QUE ESTE ARQUIVO PROTEGE, e por que cada coisa está aqui:

1. **O payload chega inteiro à tela.** A primeira versão lia `respostaJSON(r)`
   como se ela devolvesse o corpo — ela devolve `{ok, dados}`. Não levantava
   erro nenhum: tudo virava `undefined`, os quatro KPIs saíam "R$ 0" e a tabela
   saía vazia, com a cara exata de "não há dado". Só apareceu ao renderizar com
   o payload REAL de 12 meses e contar as linhas. Por isso o teste conta linhas
   e lê os KPIs, em vez de conferir que a função foi chamada.

2. **O estimado é visivelmente estimado.** A barra hachurada e o badge de
   confiança são a única coisa que separa "novembro custa R$ 1,9 mi" (o que o
   ERP tem lançado) de "novembro vai custar R$ 12 mi" (o que ele vai custar).

3. **As duas bandas de KPI nunca aparecem juntas.** `kpis-fluxcon` publica
   "Necessidade operacional" sobre o LANÇADO e o Plano publica "Buraco
   acumulado" sobre lançado + estimado: números diferentes com nomes parecidos,
   um em cima do outro, se leem como contradição. E quem esconde tem de repor —
   senão a tela fica sem banda para sempre depois de uma visita ao Plano,
   defeito que só aparece na volta.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO


def _linha(mes, rotulo, entradas, saidas, lancadas, a_lancar, saldo,
           confianca, dda=0.0, dda_manda=False):
    return {
        "mes": mes, "rotulo": rotulo,
        "saldo_inicial": 0.0, "entradas": entradas, "saidas": saidas,
        "entradas_lancadas": entradas * 0.4, "saidas_lancadas": lancadas,
        "a_lancar": a_lancar, "a_faturar": entradas * 0.6,
        "dda": dda, "dda_manda": dda_manda,
        "resultado": entradas - saidas, "saldo_final": saldo,
        "necessidade": max(0.0, -saldo), "confianca": confianca,
        "titulos_lancados": 120,
        "naturezas": [
            {"natureza": "Operacional", "lancado": lancadas * 0.7,
             "previsto": saidas * 0.7, "a_lancar": a_lancar * 0.7,
             "completude": 0.09, "dispersao": 0.05, "indice": 0.98,
             "resto_do_mes": 1.0, "metodo": "nivel", "divergencia": None},
            {"natureza": "Pessoal", "lancado": 0.0, "previsto": saidas * 0.1,
             "a_lancar": saidas * 0.1, "completude": 0.0, "dispersao": 0.0,
             "indice": 1.41 if mes.endswith("-12") else 1.0,
             "resto_do_mes": 1.0, "metodo": "nivel", "divergencia": None},
        ],
    }


# Doze meses, com dezembro carregando o 13º — é o mês que a tela existe para
# achar, e o único cujo índice de Pessoal passa de 1,1.
LINHAS = [
    _linha("2026-09", "set/26", 7_762_000, 10_427_000, 8_035_000, 2_391_000,
           -2_508_000, 0.34, dda=1_470_509),
    _linha("2026-10", "out/26", 11_943_000, 12_545_000, 3_181_000, 9_365_000,
           -3_110_000, 0.25, dda=888_208),
    _linha("2026-11", "nov/26", 12_239_000, 12_219_000, 1_897_000, 10_322_000,
           -3_090_000, 0.16, dda=70_362),
    _linha("2026-12", "dez/26", 11_849_000, 12_101_000, 1_851_000, 10_250_000,
           -3_342_000, 0.15, dda=3_881),
] + [_linha(f"2027-{m:02d}", f"{m}/27", 11_000_000, 11_500_000, 1_500_000,
            10_000_000, -3_500_000 - m * 200_000, 0.02)
     for m in range(1, 9)]

PAYLOAD = {
    "hoje": "2026-09-09", "meses": 12,
    "kpis": {
        "saldo_inicial": 156_555.24, "saldo_final": -5_000_000.0,
        "pior_saldo": -5_000_000.0, "pior_mes": "ago/27",
        "necessidade": 5_000_000.0, "necessidade_mensal": 2_664_968.0,
        "pior_mes_resultado": "set/26", "meses_negativos": 11,
        "queima_media": -1_031_311.0, "primeiro_negativo": "set/26",
        "primeiro_negativo_mes": "2026-09",
        "entradas": 0.0, "saidas": 0.0, "a_lancar": 22_077_867.0,
        "a_faturar": 0.0, "dda_no_horizonte": 2_432_961.0,
        "dso": 53.6, "deslocamento_meses": 2, "nivel_faturamento": 11_331_480.0,
    },
    "linhas": LINHAS,
    "entradas": [],
    "lastro": {
        "antecipacao": {"total": 5_322_433.21, "custo": 181_020.94,
                        "custo_pct": 3.4, "operacoes": 42},
        "credito": {"limite": 485_000.0, "taxa_efetiva": 15.67,
                    "custo_mes": 75_999.0, "bancos": 3},
        "recebiveis": {"aberto": 16_465_569.6, "titulos": 9_066,
                       "vencido": 1_138_952.0, "prox30": 5_817_295.33},
        "cobertura_mensal": 2.18, "cobertura_acumulada": 1.16,
        "estrutural": False,
    },
    "sazonalidade": {"faturamento": {
        "indice": {str(m): v for m, v in enumerate(
            [0.91, 0.90, 1.04, 1.01, 1.02, 1.01, 1.08, 1.05, 1.08, 1.05,
             0.98, 0.87], start=1)},
        "n": {}, "dispersao": {}, "metodo": "razao_media_movel", "meses": 43}},
    "quebra_de_nivel": None,
    "dda": {"estado": {"configurado": True, "boletos": 1061,
                       "valor": 6_401_242.91, "extraido_em": "2026-09-03T00:00:00",
                       "importado_em": "2026-09-09T11:13:37", "idade_dias": 6,
                       "velho": False, "arquivo": "DDA.xlsx", "cargas": 1},
            "resumo": {"boletos": 1061, "valor": 6_401_242.91,
                       "casados": 480, "casados_valor": 3_703_434.94,
                       "divergentes": 167, "divergentes_valor": 211_198.0,
                       "prorrogados": 9, "prorrogados_valor": 53_647.99,
                       "faltantes": 405, "faltantes_valor": 2_432_961.98},
            "por_mes": {"2026-09": 1_470_509.4, "2026-10": 888_208.69},
            "disponivel": True},
    "atualizado_em": "2026-09-09T11:00:00", "fonte": "ERP AVA · …",
}

DDA_DETALHE = {
    "disponivel": True, "erp_indisponivel": False,
    "estado": PAYLOAD["dda"]["estado"], "resumo": PAYLOAD["dda"]["resumo"],
    "mes": None,
    "faltantes": [
        {"barras": "2" * 44, "beneficiario": "OFICINA EXEMPLO LTDA",
         "beneficiario_doc": "43••••••••09", "vencimento": "2026-10-05",
         "valor": 12_400.0, "a_pagar": 12_400.0, "documento": "1555",
         "tipo": "DM Duplicata Mercantil", "banco": "237",
         "observacao": None, "visto_em": "2026-09-09T11:13:37"},
    ],
    "divergentes": [], "prorrogados": [], "fonte": "DDA × contaapagar",
}


def _abrir(pagina, payload=None, dda=None, usuario=None):
    pg, base = pagina
    corpo = PAYLOAD if payload is None else payload

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            body = usuario or USUARIO
        elif "/api/financeiro/projecao" in url:
            body = corpo
        elif "/api/financeiro/dda" in url:
            body = dda if dda is not None else DDA_DETALHE
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#fluxcon")
    pg.wait_for_timeout(500)
    pg.evaluate("() => abaTrocar('fluxcon','plano')")
    pg.wait_for_timeout(500)
    return pg


def test_o_payload_chega_inteiro_na_tela(pagina):
    """O defeito que este teste nasceu para pegar não levanta erro: ele
    silencia a tela inteira em R$ 0."""
    pg = _abrir(pagina)
    vals = pg.eval_on_selector_all("#kpis-proj .kpi .val", "es => es.map(e => e.textContent)")
    assert len(vals) == 4, vals
    assert all(v.strip() not in ("", "R$ 0", "R$\xa00") for v in vals), vals
    pg.evaluate("() => abaTrocar('fluxcon','planotab')")
    pg.wait_for_timeout(300)
    assert pg.eval_on_selector_all("#proj-linhas tr.forn-row", "es => es.length") == 12


def test_o_grafico_desenha_e_separa_lancado_de_estimado(pagina):
    """Barra cheia num mês que o ERP não conhece afirma um superávit que é
    falta de lançamento. A hachura é a marca que a casa usa para isso."""
    pg = _abrir(pagina)
    assert pg.eval_on_selector_all("#chartProj svg", "es => es.length") == 1
    series = pg.evaluate(
        "() => { const i = echarts.getInstanceByDom(document.getElementById('chartProj'));"
        " return i.getOption().series.map(s => s.name); }")
    assert "Entradas lançadas" in series and "Entradas estimadas" in series
    assert "Saídas lançadas" in series and "Saídas estimadas" in series
    # a série ESTIMADA carrega decal; a lançada, não
    decais = pg.evaluate(
        "() => { const i = echarts.getInstanceByDom(document.getElementById('chartProj'));"
        " const s = i.getOption().series;"
        " const de = n => s.find(x => x.name === n).data[0].itemStyle.decal ? 1 : 0;"
        " return [de('Saídas lançadas'), de('Saídas estimadas')]; }")
    assert decais == [0, 1], decais


def test_a_confianca_de_cada_mes_aparece_na_tabela(pagina):
    """Um mês 90% estimado e um mês 90% lançado não são a mesma informação."""
    pg = _abrir(pagina)
    pg.evaluate("() => abaTrocar('fluxcon','planotab')")
    pg.wait_for_timeout(300)
    badges = pg.eval_on_selector_all(
        "#proj-linhas tr.forn-row td:last-child .badge",
        "es => es.map(e => e.textContent.trim())")
    assert badges[0] == "34% lançado", badges[:3]
    assert badges[2] == "16% lançado", badges[:3]
    # e o mês em que o DDA mandou leva marca própria
    marcado = pg.eval_on_selector_all("#proj-linhas .badge", "es => es.length")
    assert marcado >= 12


def test_a_banda_da_tela_some_no_plano_e_VOLTA_depois(pagina):
    """Esconder sem repor deixaria a tela sem banda para sempre depois de uma
    visita ao Plano — e o defeito só aparece na volta."""
    pg = _abrir(pagina)
    assert pg.evaluate(
        "() => getComputedStyle(document.getElementById('kpis-fluxcon')).display") == "none"
    for aba in ("proj", "posicao", "venc"):
        pg.evaluate("(q) => abaTrocar('fluxcon',q)", aba)
        pg.wait_for_timeout(150)
        assert pg.evaluate(
            "() => getComputedStyle(document.getElementById('kpis-fluxcon')).display"
        ) != "none", aba


def test_dezembro_avisa_sobre_o_13o_com_a_receita_baixa(pagina):
    """As duas metades separadas não parecem problema; juntas, são o mês em que
    o caixa aperta."""
    pg = _abrir(pagina)
    txt = pg.eval_on_selector("#proj-avisos", "e => e.textContent")
    assert "13º" in txt and "Dezembro" in txt, txt


def test_sem_DDA_a_tela_DIZ_que_esta_so_no_modelo(pagina):
    """Ausência de piso medido não pode passar calada: sem os boletos do banco,
    o 'falta lançar' é inteiramente estimativa."""
    sem = json.loads(json.dumps(PAYLOAD))
    sem["dda"] = {"estado": {"configurado": False, "boletos": 0, "valor": 0.0,
                             "extraido_em": None, "importado_em": None,
                             "idade_dias": None, "velho": False,
                             "arquivo": None, "cargas": 0},
                  "resumo": None, "por_mes": {}, "disponivel": False}
    pg = _abrir(pagina, payload=sem)
    txt = pg.eval_on_selector("#proj-avisos", "e => e.textContent")
    assert "só no modelo" in txt, txt
    vals = pg.eval_on_selector_all("#kpis-proj .kpi .val", "es => es.map(e => e.textContent)")
    assert vals[3].strip() == "não importado", vals


def test_DDA_velho_avisa_a_idade(pagina):
    """Boleto pago some da extração seguinte: acima de uma semana o retrato
    deixa de descrever a carteira."""
    velho = json.loads(json.dumps(PAYLOAD))
    velho["dda"]["estado"].update({"idade_dias": 23, "velho": True})
    pg = _abrir(pagina, payload=velho)
    txt = pg.eval_on_selector("#proj-avisos", "e => e.textContent")
    assert "23 dias" in txt, txt


def test_o_card_do_DDA_abre_a_lista_com_nome_e_CNPJ(pagina):
    """É o único número medido da tela, e o que o torna acionável é o clique
    levar à fila de lançamento com nome e documento."""
    pg = _abrir(pagina)
    pg.eval_on_selector("#kpis-proj .kpi:nth-child(4)", "e => e.click()")
    pg.wait_for_timeout(400)
    corpo = pg.eval_on_selector("#modalBox", "e => e.textContent")
    assert "OFICINA EXEMPLO LTDA" in corpo, corpo[:300]
    assert "43••••••••09" in corpo, "o documento tem de sair MASCARADO"


def test_o_buraco_estrutural_diz_que_antecipar_nao_resolve(pagina):
    """Antecipar traz o dinheiro de depois para hoje e deixa o depois vazio.
    Quando o acumulado passa do lastro, o remédio é outro — e a tela diz."""
    est = json.loads(json.dumps(PAYLOAD))
    est["lastro"]["estrutural"] = True
    est["lastro"]["cobertura_acumulada"] = 0.47
    pg = _abrir(pagina, payload=est)
    txt = pg.eval_on_selector("#proj-avisos", "e => e.textContent")
    assert "não se resolve antecipando" in txt, txt
    assert "resultado, prazo com fornecedor ou capital" in txt, txt
