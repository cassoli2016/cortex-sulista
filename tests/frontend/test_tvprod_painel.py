# -*- coding: utf-8 -*-
"""O painel de TV da Produtividade da Frota (`tvprod`, 13/09/2026).

A produtividade da frota na parede (a tela `prodveic`, de onde ela saiu, foi
aposentada na 1.75.0), no formato da TV de operação, com um carrossel de
três lâminas: os últimos 30 dias, o mês atual e os veículos. O dublê tem a
ordem de grandeza real: 120 veículos rodando, 40 na lista (de 180), 25
parados, 12 meses de série com um mês SEM dado para provar que o intervalo
é gerado.

O MÊS ATUAL VAI ATÉ ONTEM e compara com os mesmos dias do mês anterior. O
dublê responde pela JANELA pedida (dt_de/dt_ate), então os testes provam
também que a tela pediu a janela certa — e acompanham o relógio: no dia 1
não há dia fechado, e a comparação não existe.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HOJE = date.today()
DIA1 = HOJE.day == 1
INI_MES = HOJE.replace(day=1)
FIM_MES = HOJE if DIA1 else HOJE - timedelta(days=1)
_ULT_ANT = INI_MES - timedelta(days=1)
INI_ANT = _ULT_ANT.replace(day=1)
FIM_ANT = _ULT_ANT.replace(day=min(FIM_MES.day, _ULT_ANT.day))
ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MES_NOME = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
            "setembro", "outubro", "novembro", "dezembro"]


def _mes(i):
    """O mês `i` meses atrás, 'AAAA-MM'."""
    a, m = HOJE.year, HOJE.month - i
    while m <= 0:
        a, m = a - 1, m + 12
    return "%04d-%02d" % (a, m)


MES_SEM_DADO = _mes(5)
MENSAL = [{"mes": _mes(i), "veiculos": 100 + i, "km_carregado": 300000.0 + 5000 * i,
           "km_vazio": 60000.0, "receita": 1.0}
          for i in range(11, -1, -1) if _mes(i) != MES_SEM_DADO]

VEICULOS = [{"placa": "PLA%04d" % i, "frota": "F%03d" % i, "rotulo": "F%03d" % i,
             "modalidade": "AGREGADOS" if i % 3 else "FROTA", "viagens": 20 - i // 3,
             "dias_ativos": 18, "km_carregado": 12000.0 - 200 * i, "km_vazio": 1500.0,
             "receita": 1.0, "retorno_vazio": 0.11, "km_por_dia_ativo": 650.0 - i,
             "rkm": 5.0, "ultima_viagem": "2026-09-12"} for i in range(40)]

PARADOS = [{"placa": "PAR%04d" % i, "frota": "P%03d" % i, "rotulo": "P%03d" % i,
            "modalidade": "FROTA", "tipo": "CAVALO", "ultima_viagem": "2026-01-10",
            "viagens_historicas": 50 - i, "dias_parado": d}
           for i, d in enumerate([200, 120, 45] + [60] * 22)]

PAYLOAD = {
    "kpis": {"veiculos": 120, "viagens": 1700, "km_carregado": 363000.0, "km_vazio": 72000.0,
             "receita": 1.0, "retorno_vazio": 0.166, "rkm": 5.12,
             "km_por_veiculo": 3025.0, "receita_por_veiculo": 15000.0,
             "frota_ociosa_base": 80, "ociosos": 25, "nunca_rodaram": 4, "ociosidade": 0.3125},
    "modalidades": [
        {"modalidade": "AGREGADOS", "veiculos": 90, "viagens": 1200, "km_carregado": 300000.0,
         "km_vazio": 60000.0, "receita": 1500000.0, "retorno_vazio": 0.166},
        {"modalidade": "LOCACAO", "veiculos": 20, "viagens": 300, "km_carregado": 40000.0,
         "km_vazio": 10000.0, "receita": 200000.0, "retorno_vazio": 0.2},
        {"modalidade": "FROTA", "veiculos": 8, "viagens": 150, "km_carregado": 20000.0,
         "km_vazio": 2000.0, "receita": 100000.0, "retorno_vazio": 0.09},
        {"modalidade": "TERCEIROS", "veiculos": 2, "viagens": 50, "km_carregado": 3000.0,
         "km_vazio": 0.0, "receita": 20000.0, "retorno_vazio": None}],
    "veiculos": VEICULOS, "veiculos_total": 180,
    "ociosos": PARADOS, "nunca_rodaram": [{}] * 4,
    "mensal": MENSAL,
}

# o mês atual (dias fechados) e os mesmos dias do anterior. A receita vai de
# propósito: a parede não pode mostrá-la em lâmina nenhuma.
MES = {
    "kpis": {"veiculos": 100, "viagens": 1000, "km_carregado": 200000.0, "km_vazio": 40000.0,
             "receita": 1.0, "rkm": 5.0, "retorno_vazio": 0.1667, "km_por_veiculo": 2000.0,
             "receita_por_veiculo": 1.0, "frota_ociosa_base": 80, "ociosos": 30,
             "nunca_rodaram": 4, "ociosidade": 0.375},
    "modalidades": [
        {"modalidade": "AGREGADOS", "veiculos": 70, "viagens": 700, "km_carregado": 160000.0,
         "km_vazio": 32000.0, "receita": 1.0, "retorno_vazio": 0.1667},
        {"modalidade": "LOCACAO", "veiculos": 10, "viagens": 100, "km_carregado": 20000.0,
         "km_vazio": 4000.0, "receita": 1.0, "retorno_vazio": 0.1667},
        {"modalidade": "FROTA", "veiculos": 20, "viagens": 200, "km_carregado": 20000.0,
         "km_vazio": 4000.0, "receita": 1.0, "retorno_vazio": 0.1667}],
    "veiculos": [], "veiculos_total": 0, "ociosos": [], "nunca_rodaram": [], "mensal": [],
}
ANT = {**MES, "kpis": {**MES["kpis"], "veiculos": 98, "km_carregado": 180000.0,
                       "km_vazio": 45000.0, "retorno_vazio": 0.20, "km_por_veiculo": 1836.7}}


def _corpo(u):
    """A resposta pela JANELA pedida: é assim que o teste prova a janela."""
    q = parse_qs(urlparse(u).query)
    de, ate = q["dt_de"][0], q["dt_ate"][0]
    if de == INI_MES.isoformat() and (ate != HOJE.isoformat() or DIA1):
        return MES
    return PAYLOAD if ate == HOJE.isoformat() else ANT


def _abre(pg, base, largura=1920, altura=1080):
    pedidos = []

    def rota(r):
        u = r.request.url
        if "produtividade-veiculos" in u:
            pedidos.append(u)
            corpo = _corpo(u)
        else:
            corpo = ADMIN if "/api/auth/me" in u else {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    pg.emulate_media(reduced_motion="reduce")
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#tvprod")
    pg.wait_for_function("() => document.querySelectorAll('#tvprod-k1 .tv-card').length === 6"
                         " && document.querySelectorAll('#tvprod-k3 .tv-card').length === 6")
    pg.wait_for_timeout(800)
    return pedidos


def _cartoes(pg, sel):
    c = pg.evaluate("""(s) => [...document.querySelectorAll(s + ' .tv-card')].map(x => ({
        rot: x.querySelector('.tv-label').innerText.trim().toUpperCase(),
        num: x.querySelector('.tv-num').innerText.trim(),
        sub: x.querySelector('.tv-sub').innerText.trim(), cls: x.className}))""", sel)
    return {x["rot"]: x for x in c}


def test_a_tela_esta_registrada_e_abre_como_tv(pagina):
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => ({
        menu: !!document.querySelector('aside nav a[data-view="tvprod"]'),
        gaveta: !!document.querySelector('a[href="#tvprod"][onclick]'),
        tv: TELAS_TV.has('tvprod'), nome: VIEWS.tvprod,
        titulo: document.querySelector('#view-tvprod .tv-head h2').innerText,
        filtros: getComputedStyle(document.getElementById('filterbar')).display,
        parede: document.body.classList.contains('tvwall')})""")
    assert r["menu"] and r["gaveta"] and r["tv"] and r["nome"], r
    assert r["titulo"] == "PRODUTIVIDADE DA FROTA"
    assert r["filtros"] == "none", "recorte fixo: a barra de filtros não pode aparecer"
    assert r["parede"], "o painel tem de usar o layout de parede"


def test_os_cartoes_dos_ultimos_30_dias(pagina):
    pg, base = pagina
    _abre(pg, base)
    por = _cartoes(pg, "#tvprod-k1")
    assert por["KM CARREGADO"]["num"] == "363 mil"
    assert por["RETORNO VAZIO"]["num"] == "17%" and "destaque-ok" in por["RETORNO VAZIO"]["cls"]
    assert por["PARADOS"]["num"] == "25" and "destaque-warn" in por["PARADOS"]["cls"]
    # número sem meta leva a borda branca, como na TV de operação
    assert "destaque-neutro" in por["KM POR VEÍCULO"]["cls"]
    # no lugar de receita e R$/km: 1.700 viagens ÷ 120 veículos e 363.000 km ÷ 1.700
    assert por["VIAGENS POR VEÍCULO"]["num"] == "14,2", por.get("VIAGENS POR VEÍCULO")
    assert por["KM POR VIAGEM"]["num"] == "214", por.get("KM POR VIAGEM")


def test_a_pilula_diz_o_periodo_de_cada_lamina(pagina):
    """Quem opera, 13/09/2026: "precisa pôr que são dos últimos 30 dias"."""
    pg, base = pagina
    _abre(pg, base)
    lam = pg.evaluate("() => document.getElementById('tvprod-lamina').innerText")
    d30 = HOJE - timedelta(days=29)
    assert "Últimos 30 dias" in lam and d30.strftime("%d/%m") in lam and HOJE.strftime("%d/%m") in lam, lam
    pg.evaluate("() => tvProdPasso()")
    lam = pg.evaluate("() => document.getElementById('tvprod-lamina').innerText")
    assert MES_NOME[HOJE.month - 1].capitalize() in lam, lam
    assert ("dia 1" in lam) if DIA1 else ("1 a " + FIM_MES.strftime("%d/%m") in lam), lam


def test_a_parede_nao_mostra_dinheiro(pagina):
    """Quem opera, 13/09/2026: "não vamos mostrar faturamento nem reais por
    km". O dublê manda receita e rkm de propósito — a tela é que não pode
    publicá-los, em nenhuma das lâminas nem no rodapé."""
    pg, base = pagina
    _abre(pg, base)
    txt = pg.evaluate("() => document.getElementById('view-tvprod').textContent")
    assert "R$" not in txt, txt[txt.find("R$") - 60: txt.find("R$") + 40]
    assert "receita" not in txt.lower() and "faturamento" not in txt.lower()
    frota = pg.evaluate("""() => [...document.querySelectorAll('#tvprod-modal tr')]
        .map(tr => [...tr.cells].map(td => td.innerText.trim())).find(l => l[0] === 'Frota')""")
    assert frota[4] == "16,1", "450 viagens (frota + locação) ÷ 28 veículos: %r" % frota


def test_o_mes_atual_vai_ate_ONTEM_e_o_anterior_nos_mesmos_dias(pagina):
    """O dia em curso é piso, nunca base de comparação: na manhã do dia 2 ele
    faria qualquer mês parecer metade do anterior."""
    pg, base = pagina
    pedidos = _abre(pg, base)
    janelas = {(q["dt_de"][0], q["dt_ate"][0])
               for q in (parse_qs(urlparse(u).query) for u in pedidos)}
    assert (INI_MES.isoformat(), FIM_MES.isoformat()) in janelas, janelas
    if DIA1:
        assert (INI_ANT.isoformat(), FIM_ANT.isoformat()) not in janelas, "no dia 1 não há o que comparar"
    else:
        assert (INI_ANT.isoformat(), FIM_ANT.isoformat()) in janelas, janelas


def test_o_mes_atual_compara_com_os_mesmos_dias_do_anterior(pagina):
    pg, base = pagina
    _abre(pg, base)
    c = _cartoes(pg, "#tvprod-k3")
    assert c["KM CARREGADO"]["num"] == "200 mil"
    assert c["RETORNO VAZIO"]["num"] == "17%" and "destaque-ok" in c["RETORNO VAZIO"]["cls"]
    # sem meta não há semáforo: a comparação é neutra e o cartão, branco
    assert "destaque-neutro" in c["KM CARREGADO"]["cls"]
    if DIA1:
        assert all("amanhã" in x["sub"] for x in c.values()), c
        return
    a = ABREV[INI_ANT.month - 1]
    assert c["KM CARREGADO"]["sub"] == f"{a}: 180 mil · ▲ 11%", c["KM CARREGADO"]
    assert c["VIAGENS"]["sub"] == f"{a}: 1.000 · estável", c["VIAGENS"]
    assert c["KM POR VIAGEM"]["sub"] == f"{a}: 180 · ▲ 11%", c["KM POR VIAGEM"]
    # percentual compara em PONTOS: 16,7% contra 20% é 3 p.p., não "17%"
    assert c["RETORNO VAZIO"]["sub"] == f"{a}: 20% · ▼ 3 p.p.", c["RETORNO VAZIO"]


def test_o_ritmo_poe_o_mes_atual_na_regua_dos_fechados(pagina):
    """Total de mês parcial contra mês inteiro só mostra queda; POR DIA os dois
    cabem na mesma régua. O atual divide pelos dias FECHADOS."""
    pg, base = pagina
    _abre(pg, base)
    cols = pg.evaluate("""() => [...document.querySelectorAll('#tvprod-ritmo .tvd-col')]
        .map(c => ({cls: c.className, v: c.querySelector('.v').innerText.trim()}))""")
    assert len(cols) == 6, cols
    assert "atual" in cols[-1]["cls"]
    assert sum("sem" in c["cls"].split() for c in cols[:-1]) == 1, "o mês sem viagem sumiu ou emendou"
    if DIA1:
        assert cols[-1]["v"] == "—"
    else:
        esperado = ("%.1f" % (200000.0 / FIM_MES.day / 1000)).replace(".", ",")
        assert cols[-1]["v"] == esperado, cols[-1]


def test_a_modalidade_do_mes_soma_locacao_em_frota(pagina):
    pg, base = pagina
    _abre(pg, base)
    linhas = pg.evaluate("""() => [...document.querySelectorAll('#tvprod-modal-mes tr')]
        .map(tr => [...tr.cells].map(td => td.innerText.trim()))""")
    frota = next(l for l in linhas if l[0] == "Frota")
    assert frota[1] == "30" and frota[4] == "10,0", "20 de frota + 10 de locação, 300 viagens: %r" % frota


def test_a_serie_tem_12_meses_gerados_e_o_corrente_parcial(pagina):
    pg, base = pagina
    _abre(pg, base)
    cols = pg.evaluate("""() => [...document.querySelectorAll('#tvprod-mensal .tvd-col')]
        .map(c => ({cls: c.className, txt: c.innerText}))""")
    assert len(cols) == 12, cols
    assert "parcial" in cols[-1]["cls"] and "parcial" in cols[-1]["txt"]
    assert sum("sem" in c["cls"].split() for c in cols) == 1, "o mês sem viagem sumiu ou emendou"


def test_modalidade_soma_locacao_em_frota(pagina):
    pg, base = pagina
    _abre(pg, base)
    linhas = pg.evaluate("""() => [...document.querySelectorAll('#tvprod-modal tr')]
        .map(tr => [...tr.cells].map(td => td.innerText.trim()))""")
    assert [l[0] for l in linhas] == ["Agregado", "Frota", "Terceiro"], linhas
    frota = next(l for l in linhas if l[0] == "Frota")
    assert frota[1] == "28", "8 de frota + 20 de locação"
    terceiro = next(l for l in linhas if l[0] == "Terceiro")
    assert terceiro[3] == "n/d", "vazio de terceiro não é lançado: n/d, não 0%"


def test_as_listas_usam_a_frota_e_cortam_com_contador(pagina):
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => ({
        top: [...document.querySelectorAll('#tvprod-top tr')].map(tr => tr.cells[0].innerText),
        par: [...document.querySelectorAll('#tvprod-par tr')].map(tr => [tr.cells[0].innerText,
               tr.cells[2].innerText, tr.cells[2].style.color]),
        ntop: document.getElementById('tvprod-top-n').innerText,
        npar: document.getElementById('tvprod-par-n').innerText})""")
    assert r["top"][0] == "F000" and not any(x.startswith("PLA") for x in r["top"]), r["top"][:3]
    assert r["ntop"] == "%d de 180" % len(r["top"]), r["ntop"]
    assert r["npar"] == "%d de 25" % len(r["par"]), r["npar"]
    # parado há 200 dias vermelho, 120 amarelo, 45 sem cor
    cores = [p[2] for p in r["par"][:3]]
    assert cores[0] == "rgb(248, 113, 113)" and cores[1] == "rgb(251, 191, 36)" and cores[2] == "", cores


def test_o_carrossel_desliza_entre_as_tres_laminas(pagina):
    pg, base = pagina
    _abre(pg, base)
    passo = r"""() => { const t = document.getElementById('tvprod-trilho');
        const m = /translateX\((-?[\d.]+)%\)/.exec(t.style.transform);
        return {x: m ? parseFloat(m[1]) : null,
                lam: document.getElementById('tvprod-lamina').innerText.trim()}; }"""
    a = pg.evaluate(passo)
    assert a["x"] == 0 and "Últimos 30 dias" in a["lam"], a
    pg.evaluate("() => tvProdPasso()")
    b = pg.evaluate(passo)
    assert abs(b["x"] + 100 / 3) < 0.01 and MES_NOME[HOJE.month - 1] in b["lam"].lower(), b
    pg.evaluate("() => tvProdPasso()")
    c = pg.evaluate(passo)
    assert abs(c["x"] + 200 / 3) < 0.01 and "Veículos" in c["lam"], c
    pg.evaluate("() => tvProdPasso()")
    assert pg.evaluate(passo)["x"] == 0, "o giro tem de dar a volta"


def test_as_tres_laminas_estao_renderizadas_e_cabem(pagina):
    """As lâminas ficam lado a lado e só deslizam: as de fora da tela também
    têm tamanho real (nada medido com zero). E nenhum cartão estoura."""
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => ({
        larg2: document.querySelector('.tvp-mes .tv-card').getBoundingClientRect().width,
        larg3: document.querySelector('.tvp-veic .tv-card').getBoundingClientRect().width,
        rola: document.documentElement.scrollWidth,
        estouros: [...document.querySelectorAll('#tvprod-k1 .tv-card, #tvprod-k2 .tv-card, #tvprod-k3 .tv-card')]
          .filter(c => c.scrollHeight > c.clientHeight + 1).map(c => c.innerText.slice(0, 30))})""")
    assert r["larg2"] > 200 and r["larg3"] > 200, r
    assert r["rola"] <= 1920, "o trilho empurrou a página para o lado: %r" % r
    assert not r["estouros"], r["estouros"]


def test_o_rodape_traz_os_alertas_da_produtividade(pagina):
    pg, base = pagina
    _abre(pg, base)
    rod = pg.evaluate("() => document.getElementById('tvprod-ticker').textContent")
    assert "25 parado(s)" in rod and "P000 há 200 dias" in rod, rod[:200]
    assert "4 veículo(s) sem nenhuma viagem" in rod
    if not DIA1:
        assert "▲ 11% sobre os mesmos dias de " + MES_NOME[INI_ANT.month - 1] in rod, rod


def test_no_celular_as_laminas_empilham(pagina):
    pg, base = pagina
    pg.add_init_script("Object.defineProperty(screen,'height',{get:()=>1000});")
    _abre(pg, base, 390, 844)
    r = pg.evaluate("""() => {
        const a = document.querySelector('.tvp-vis').getBoundingClientRect();
        const b = document.querySelector('.tvp-veic').getBoundingClientRect();
        const s = document.getElementById('tvprod-mensal');
        const card = s.closest('.tv-card');
        const rt = document.getElementById('tvprod-ritmo');
        return {rola: document.documentElement.scrollWidth, a_fim: a.bottom, b_ini: b.top,
                b_esq: b.left, lamina: getComputedStyle(document.getElementById('tvprod-lamina')).display,
                serie: s.scrollWidth, cabe: card.clientWidth,
                ritmo: rt.scrollWidth, cabeR: rt.closest('.tv-card').clientWidth,
                colunas: [...s.children].filter(c => getComputedStyle(c).display !== 'none').length,
                colunasR: [...rt.children].filter(c => getComputedStyle(c).display !== 'none').length,
                tabs: ['tvprod-modal', 'tvprod-modal-mes'].map(i => {
                  const tb = document.getElementById(i).closest('table');
                  return [tb.getBoundingClientRect().right, tb.closest('.tv-card').getBoundingClientRect().right]; }),
                cabs: [...document.querySelectorAll('.tvp-cab')].map(c =>
                  getComputedStyle(c).display + '|' + c.innerText),
                rotulo: card.querySelector('.tv-label').innerText}; }""")
    assert r["rola"] <= 390, r
    # o gráfico não passa do cartão: no celular são os 6 últimos meses, e o
    # rótulo diz isso; o ritmo já nasce com 6
    assert r["serie"] <= r["cabe"] and r["ritmo"] <= r["cabeR"], r
    assert r["colunas"] == 6 and "6 MESES" in r["rotulo"].upper(), r
    assert r["colunasR"] == 6, r
    assert r["b_ini"] >= r["a_fim"] - 1 and r["b_esq"] < 40, "a última lâmina não empilhou: %r" % r
    assert r["lamina"] == "none"
    # as tabelas por modalidade cabem no cartão: a última coluna saía cortada
    assert all(tab <= card + 0.5 for tab, card in r["tabs"]), r["tabs"]
    # sem a pílula do título, cada bloco diz o próprio período
    assert len(r["cabs"]) == 3 and all(c.startswith("block|") for c in r["cabs"]), r["cabs"]
    assert "Últimos 30 dias" in r["cabs"][0] and MES_NOME[HOJE.month - 1] in r["cabs"][1].lower(), r["cabs"]
