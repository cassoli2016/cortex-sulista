"""A aba Decidir contra o `index.html` real.

O QUE ESTE ARQUIVO PROTEGE, e por que cada coisa está aqui:

1. **O número grande é o do MÊS, não o do ano.** `antecipar_agora` e
   `antecipar_12m` diferem por um fator de dezessete no payload real
   (R$ 4,3 mi contra R$ 73,1 mi). Trocá-los não levanta erro nenhum e manda a
   tesouraria ao banco com o número errado — é o defeito mais caro que esta
   tela pode ter, e o único jeito de pegá-lo é ler o KPI desenhado.

2. **As três linhas do gráfico.** Só "com o plano" seria um painel
   permanentemente verde, porque ela fica colada no piso por construção; só
   "sem o plano" seria a projeção de sempre. É a distância entre as duas que
   se lê, e ela só existe se as duas estiverem desenhadas.

3. **As duas bandas de KPI nunca aparecem juntas.** `kpis-fluxcon` publica
   "Necessidade operacional" sobre o LANÇADO; a Decidir publica "Antecipe
   agora" sobre lançado + estimado. Números diferentes com nomes parecidos, um
   em cima do outro, leem-se como contradição — que é a queixa que originou a
   reforma. E quem esconde tem de repor.

4. **O payload chega inteiro.** `respostaJSON` devolve `{ok, dados}`, não o
   corpo. Ler `d.kpis` direto não levanta erro: tudo vira `undefined`, os KPIs
   saem "R$ 0" e a tabela sai vazia, com a cara exata de "não há dado".
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO


def _op(mes, rotulo, origem, origem_rotulo, bruto, prazo=36, taxa=1.1722):
    desagio = taxa / 100.0 * (prazo / 30.0)
    liquido = round(bruto * (1 - desagio), 2)
    return {"mes": mes, "rotulo": rotulo, "origem": origem,
            "origem_rotulo": origem_rotulo, "prazo_dias": prazo,
            "taxa_am": taxa, "desagio_pct": round(desagio * 100, 3),
            "bruto": bruto, "liquido": liquido,
            "custo": round(bruto - liquido, 2),
            "de_lancado": round(bruto * 0.32, 2),
            "de_futuro": round(bruto * 0.68, 2)}


def _linha(mes, rotulo, entradas, saidas, piso, antecipar, custo, saldo,
           pilha, saturacao, descoberto=0.0, sacado_de_mim=0.0, ops=()):
    return {"mes": mes, "rotulo": rotulo, "saldo_inicial": 0.0,
            "entradas": entradas, "entradas_projetadas": entradas + sacado_de_mim,
            "sacado_de_mim": sacado_de_mim, "saidas": saidas, "piso": piso,
            "antecipar": antecipar, "custo": custo,
            "liquido": round(antecipar - custo, 2), "saldo_final": saldo,
            "descoberto": descoberto, "pilha": pilha,
            "pilha_lancado": pilha * 0.31, "pilha_futuro": pilha * 0.69,
            "pilha_consumida": round(pilha * (saturacao or 0), 2),
            "saturacao": saturacao, "confianca": 0.3, "operacoes": list(ops)}


# Os doze meses MEDIDOS em 09/09/2026. A saturação bate 100% em jan/27 — é o
# mês que a tela existe para achar, e o alarme que acende antes do descoberto.
LINHAS = [
    _linha("2026-09", "set/26", 7_761_632, 10_426_599, 1_737_766, 4_309_169,
           60_612, 1_737_766, 2_990_000, 0.0,
           ops=[_op("2026-09", "set/26", "2026-10", "out/26", 4_309_169)]),
    _linha("2026-10", "out/26", 7_634_000, 12_545_132, 2_090_855, 5_329_000,
           64_500, 2_090_855, 4_459_226, 0.97, sacado_de_mim=4_309_169,
           ops=[_op("2026-10", "out/26", "2026-11", "nov/26", 5_329_000, 31)]),
    _linha("2026-11", "nov/26", 6_911_000, 12_218_882, 2_036_480, 5_316_000,
           62_300, 2_036_480, 6_001_000, 0.89, sacado_de_mim=5_329_000,
           ops=[_op("2026-11", "nov/26", "2026-12", "dez/26", 5_316_000, 30)]),
    _linha("2026-12", "dez/26", 6_533_000, 12_101_181, 2_016_863, 5_618_000,
           69_700, 2_016_863, 6_219_000, 0.85, sacado_de_mim=5_316_000,
           ops=[_op("2026-12", "dez/26", "2027-01", "jan/27", 5_618_000, 31)]),
] + [
    _linha(f"2027-{m:02d}", f"{m}/27", 5_500_000, 11_800_000, 1_970_000,
           6_500_000, 120_000 + m * 8_000, 1_970_000, 5_200_000, 1.0,
           sacado_de_mim=5_500_000,
           ops=[_op(f"2027-{m:02d}", f"{m}/27", f"2027-{m+1:02d}",
                    f"{m+1}/27", 6_500_000, 31)])
    for m in range(1, 9)
]

PAYLOAD = {
    "hoje": "2026-09-09", "meses": 12,
    "kpis": {
        # O par que NUNCA pode ser trocado — 17× de diferença.
        "antecipar_agora": 4_309_169.10, "custo_agora": 60_612.29,
        "mes_agora": "set/26", "piso_agora": 1_737_766.55,
        "de_lancado_agora": 1_387_681.09,
        "antecipar_12m": 73_063_528.67, "custo_12m": 1_395_595.86,
        "custo_pct": 1.91, "meses_com_operacao": 12,
        "capital_medio": 9_787_835.83, "custo_efetivo_aa": 14.26,
        "prazo_medio": 48.9, "giros_ano": 7.5,
        "descoberto_total": 0.0, "primeiro_descoberto": None,
        "meses_descobertos": 0,
        "primeiro_saturado": "jan/27", "meses_saturados": 8,
        "saturacao_media": 1.0,
        "estrutural_mes": -855_833.77, "pior_saldo_sem": -11_080_405.42,
        "pilha_total": 63_271_631.28, "pilha_usada": 73_063_528.67,
    },
    "linhas": LINHAS,
    "operacoes": [o for l in LINHAS for o in l["operacoes"]],
    "piso": {"dias": 5, "por_mes": {l["mes"]: l["piso"] for l in LINHAS},
             "metodo": "5 dias da saída projetada de cada mês"},
    "pilha": {
        "por_mes": {l["mes"]: {"lancado": l["pilha_lancado"],
                               "futuro": l["pilha_futuro"],
                               "total": l["pilha"]} for l in LINHAS},
        "fatia_elegivel": {"share": 0.4979, "n": 6, "min": 0.4251,
                           "max": 0.5471, "meses": []},
        "convenios": [{"cnpj": "84683374000300", "nome": "TUPY S/A", "portal": "tupy"},
                      {"cnpj": "61156113000175", "nome": "Iochpe Maxion S A",
                       "portal": "maxion"}],
        "raizes": ["61156113", "84683374"], "lancado_total": 5_686_819.31,
    },
    "curva": {"origem": "medida", "referencia": 1.1722, "base": 1345,
              "faixas": [{"ate": 20, "taxa": 1.1722, "base": 13}]},
    "rotativo": {"limite": 485_000.0, "taxa_efetiva": 15.67, "bancos": 3},
    "sem_plano": [{"mes": l["mes"], "rotulo": l["rotulo"],
                   "saldo_final": -2_508_412 - i * 780_000}
                  for i, l in enumerate(LINHAS)],
    "quebra_de_nivel": None,
    "atualizado_em": "2026-09-09T18:00:00",
    "fonte": "Projeção de 12 meses + pilha antecipável · leitura",
}


def _abrir(pagina, payload=None, usuario=None):
    pg, base = pagina
    corpo = PAYLOAD if payload is None else payload

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            body = usuario or USUARIO
        elif "/api/financeiro/plano" in url:
            body = corpo
        else:
            body = {}
        r.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))

    pg.route("**/api/**", rota)
    pg.goto(f"{base}/static/index.html#fluxcon")
    pg.wait_for_selector("#aba-fluxcon-decidir", state="visible")
    pg.wait_for_timeout(800)
    return pg


def _kpi(pg, rotulo):
    return pg.evaluate(
        "(rot) => { const c = [...document.querySelectorAll('#kpis-plano .kpi')]"
        ".find(e => e.querySelector('.label').textContent.includes(rot));"
        " return c ? c.querySelector('.val').textContent.trim() : null; }", rotulo)


def test_o_payload_chega_inteiro_na_tela(pagina):
    """O defeito que este teste nasceu para pegar não levanta erro: ele
    silencia a tela inteira em R$ 0."""
    pg = _abrir(pagina)
    vals = pg.eval_on_selector_all("#kpis-plano .kpi .val",
                                   "es => es.map(e => e.textContent.trim())")
    assert len(vals) == 4, vals
    assert all(v not in ("", "R$ 0", "R$\xa00") for v in vals), vals


def test_o_numero_grande_e_o_do_MES_e_nunca_o_do_ano(pagina):
    """R$ 4,3 mi (o mês) contra R$ 73,1 mi (o ano). Trocá-los manda a
    tesouraria ao banco com dezessete vezes o necessário, sem erro nenhum."""
    pg = _abrir(pagina)
    v = _kpi(pg, "Antecipe agora")
    assert "4.309.169" in v, v
    assert "73.063" not in v, ("o KPI de ação está publicando o total de 12 "
                               f"meses: {v!r}")


def test_o_custo_aparece_como_capital_medio_e_taxa_ao_ano(pagina):
    """Somar o nominal antecipado e chamar de dívida erra por um fator de
    cinco — o mesmo dinheiro gira 7,5 vezes no ano."""
    pg = _abrir(pagina)
    sub = pg.evaluate(
        "() => [...document.querySelectorAll('#kpis-plano .kpi')]"
        ".find(e => e.querySelector('.label').textContent.includes('Custo do plano'))"
        ".querySelector('.sub').textContent")
    assert "14,3% a.a." in sub or "14,26" in sub, sub
    assert "9.787" in sub, ("o capital médio sumiu do KPI de custo: "
                            f"{sub!r}")


def test_o_grafico_tem_as_TRES_linhas(pagina):
    """Sem "sem antecipar" o painel fica verde para sempre; sem o piso não se
    vê o que a linha está encostando."""
    pg = _abrir(pagina)
    assert pg.eval_on_selector_all("#chartPlano svg", "es => es.length") == 1
    series = pg.evaluate(
        "() => { const i = echarts.getInstanceByDom(document.getElementById('chartPlano'));"
        " return i.getOption().series.map(s => s.name); }")
    assert "Sem antecipar" in series, series
    assert "Com o plano" in series, series
    assert "Piso" in series, series


def test_a_saturacao_acende_antes_do_descoberto(pagina):
    """O payload tem descoberto ZERO e saturação de 100% em oito meses. Uma
    tela que só alarmasse no descoberto ficaria verde o ano inteiro."""
    pg = _abrir(pagina)
    v = _kpi(pg, "Folga da antecipação")
    assert "jan/27" in v, v
    # e o cartão do limite repete o mês com a consequência escrita
    pg.evaluate("() => abaTrocar('fluxcon','planotab')")
    pg.wait_for_timeout(300)
    lim = pg.inner_text("#plano-limite")
    assert "jan/27" in lim, lim
    assert "100%" in lim, lim


def test_o_buraco_estrutural_e_dito_mesmo_com_o_plano_fechando(pagina):
    """O plano fecha todos os meses e mesmo assim o fluxo é deficitário. Sem
    este KPI a tela venderia a antecipação como solução, e ela é um
    empréstimo."""
    pg = _abrir(pagina)
    v = _kpi(pg, "Buraco estrutural")
    assert "855.834" in v, v      # BRL arredonda os 855.833,77 do payload
    assert "/mês" in v, v


def test_a_tabela_tem_um_mes_por_linha_e_abre_as_operacoes(pagina):
    pg = _abrir(pagina)
    pg.evaluate("() => abaTrocar('fluxcon','planotab')")
    pg.wait_for_timeout(400)
    assert pg.eval_on_selector_all("#plano-linhas tr.forn-row", "es => es.length") == 12
    pg.evaluate("() => planoToggle(0)")
    pg.wait_for_timeout(200)
    det = pg.inner_text("#plano-det-0")
    assert "out/26" in det, det          # de qual vencimento o saque sai
    assert "36 d" in det, det            # e a que prazo


def test_o_saque_do_mes_de_origem_e_DITO_na_linha(pagina):
    """Antecipar é saque, e o saque esvazia o mês de origem: a entrada de
    out/26 é menor que a projetada. Sem essa frase o usuário lê a diferença
    como erro de conta."""
    pg = _abrir(pagina)
    pg.evaluate("() => abaTrocar('fluxcon','planotab')")
    pg.wait_for_timeout(400)
    pg.evaluate("() => planoToggle(1)")
    pg.wait_for_timeout(200)
    det = pg.inner_text("#plano-det-1")
    assert "anteciparam" in det, det


def test_as_duas_bandas_de_kpi_nunca_aparecem_juntas(pagina):
    """`kpis-fluxcon` fala do LANÇADO e a Decidir fala de lançado+estimado:
    números diferentes com nomes parecidos, um em cima do outro."""
    pg = _abrir(pagina)
    assert pg.eval_on_selector(
        "#kpis-fluxcon", "e => getComputedStyle(e).display") == "none"


def test_a_barra_de_filtros_SAI_nas_abas_do_plano(pagina):
    """Os dois filtros desta tela — granularidade e janela em dias — são da
    consulta de CURTO prazo. O plano de 12 meses não os recebe nem poderia:
    ele é mensal por construção. Deixá-los à mostra numa aba que os ignora é
    o defeito que a casa já pagou em `integ` e `apps` — dá para escolher
    "semana", clicar em Aplicar filtros e nada mudar, e campo que aceita valor
    sem mudar nada é pior que campo nenhum.
    """
    pg = _abrir(pagina)
    assert pg.eval_on_selector(
        "#filterbar", "e => getComputedStyle(e).display") == "none"
    # e VOLTA na aba de curto prazo, que é de quem eles são
    pg.evaluate("() => abaTrocar('fluxcon','proj')")
    pg.wait_for_timeout(300)
    assert pg.eval_on_selector(
        "#filterbar", "e => getComputedStyle(e).display") != "none"


def test_quem_esconde_a_banda_REPOE_ao_sair(pagina):
    """Defeito que só aparece na volta: a tela ficaria sem banda para sempre
    depois de uma visita à Decidir."""
    pg = _abrir(pagina)
    pg.evaluate("() => abaTrocar('fluxcon','posicao')")
    pg.wait_for_timeout(300)
    assert pg.eval_on_selector(
        "#kpis-fluxcon", "e => getComputedStyle(e).display") != "none"


def test_as_premissas_dizem_de_onde_saiu_a_taxa(pagina):
    """Custo estimado por constante envelhece calado. A tela diz se a taxa foi
    MEDIDA no portal e com quantos títulos."""
    pg = _abrir(pagina)
    pg.evaluate("() => abaTrocar('fluxcon','posicao')")
    pg.wait_for_timeout(300)
    pr = pg.inner_text("#plano-premissas")
    # DUAS casas: 1,17% e 1,2% não são a mesma informação quando o número é
    # juro, e é a segunda casa que separa comparar de "dá no mesmo".
    assert "1,17% a.m." in pr, pr
    assert "1345" in pr, ("a base da medição sumiu — sem ela a taxa é uma "
                          f"afirmação: {pr!r}")


def test_as_abas_cabem_na_tela_COM_DADO_REAL(pagina):
    """A régua oficial (`scripts/medir_paineis.py`) mede com a API dublada em
    `{}`: tabela vazia, avisos mudos, KPIs zerados. É a medida do esqueleto.

    Com os doze meses a tabela vai ao teto do `.tabroll` (430px) e os avisos
    aparecem — e é exatamente aí que a aba estoura. Medir cheio é o único jeito
    de pegar isso antes de quem opera pegar rolando a página.
    """
    pg = _abrir(pagina)
    alt = ("() => { const c = document.getElementById('content');"
           " const b = c.querySelector('#banner');"
           " const fora = (b && b.offsetParent !== null)"
           "   ? Math.round(b.getBoundingClientRect().height) + 14 : 0;"
           " return Math.round(c.scrollHeight) - fora; }")
    larg = ("() => Math.max(0, document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth)")
    pg.set_viewport_size({"width": 1500, "height": 1000})
    for aba in ("decidir", "planotab", "posicao"):
        pg.evaluate("(q) => abaTrocar('fluxcon', q)", aba)
        pg.wait_for_timeout(350)
        h, w = pg.evaluate(alt), pg.evaluate(larg)
        assert h <= 900, f"aba {aba} com {h}px — a régua da casa é 900"
        assert w == 0, f"aba {aba} rola para o LADO ({w}px de excesso)"


def test_sem_medicao_no_portal_a_tela_AVISA_que_o_custo_e_teto(pagina):
    """Um plano barato demais por falta de dado se executa; a tela tem de
    dizer que aquilo é teto, não preço."""
    corpo = json.loads(json.dumps(PAYLOAD))
    corpo["curva"] = {"origem": "fallback", "referencia": 2.0, "base": 0,
                      "faixas": []}
    pg = _abrir(pagina, payload=corpo)
    avisos = pg.inner_text("#plano-avisos")
    assert "sem medição do portal" in avisos.lower(), avisos
