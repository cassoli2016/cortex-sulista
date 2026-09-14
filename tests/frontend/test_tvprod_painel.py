# -*- coding: utf-8 -*-
"""O painel de TV da Produtividade da Frota (`tvprod`, 13/09/2026).

A tela `prodveic` na parede, no formato da TV de operação, com um carrossel
de duas lâminas (visão geral e veículos). O dublê tem a ordem de grandeza
real: 120 veículos rodando, 40 na lista (de 180), 25 parados, 12 meses de
série com um mês SEM dado para provar que o intervalo é gerado.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HOJE = date.today()


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


def _abre(pg, base, largura=1920, altura=1080):
    def rota(r):
        u = r.request.url
        corpo = ADMIN if "/api/auth/me" in u else (PAYLOAD if "produtividade-veiculos" in u else {})
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    pg.emulate_media(reduced_motion="reduce")
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#tvprod")
    pg.wait_for_function("() => document.querySelectorAll('#tvprod-k1 .tv-card').length === 6")
    pg.wait_for_timeout(800)


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


def test_os_cartoes_da_visao_geral(pagina):
    pg, base = pagina
    _abre(pg, base)
    c = pg.evaluate("""() => [...document.querySelectorAll('#tvprod-k1 .tv-card')].map(x => ({
        rot: x.querySelector('.tv-label').innerText.trim().toUpperCase(),
        num: x.querySelector('.tv-num').innerText.trim(), cls: x.className}))""")
    por = {x["rot"]: x for x in c}
    assert por["KM CARREGADO"]["num"] == "363 mil"
    assert por["RETORNO VAZIO"]["num"] == "17%" and "destaque-ok" in por["RETORNO VAZIO"]["cls"]
    assert por["PARADOS"]["num"] == "25" and "destaque-warn" in por["PARADOS"]["cls"]
    # número sem meta leva a borda branca, como na TV de operação
    assert "destaque-neutro" in por["KM POR VEÍCULO"]["cls"]


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


def test_o_carrossel_desliza_entre_as_duas_laminas(pagina):
    pg, base = pagina
    _abre(pg, base)
    passo = """() => { const t = document.getElementById('tvprod-trilho');
        return {tr: t.style.transform, lam: document.getElementById('tvprod-lamina').innerText.trim()}; }"""
    a = pg.evaluate(passo)
    assert a["tr"] in ("translateX(0%)", "translateX(-0%)") and "Visão geral" in a["lam"], a
    pg.evaluate("() => tvProdPasso()")
    b = pg.evaluate(passo)
    assert b["tr"] == "translateX(-50%)" and "Veículos" in b["lam"], b
    pg.evaluate("() => tvProdPasso()")
    assert pg.evaluate(passo)["tr"] in ("translateX(0%)", "translateX(-0%)")


def test_as_duas_laminas_estao_renderizadas_e_cabem(pagina):
    """As lâminas ficam lado a lado e só deslizam: a de fora da tela também
    tem tamanho real (nada medido com zero). E nenhum cartão estoura."""
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => ({
        larg2: document.querySelector('.tvp-veic .tv-card').getBoundingClientRect().width,
        rola: document.documentElement.scrollWidth,
        estouros: [...document.querySelectorAll('#tvprod-k1 .tv-card, #tvprod-k2 .tv-card')]
          .filter(c => c.scrollHeight > c.clientHeight + 1).map(c => c.innerText.slice(0, 30))})""")
    assert r["larg2"] > 200, r
    assert r["rola"] <= 1920, "o trilho empurrou a página para o lado: %r" % r
    assert not r["estouros"], r["estouros"]


def test_o_rodape_traz_os_alertas_da_produtividade(pagina):
    pg, base = pagina
    _abre(pg, base)
    rod = pg.evaluate("() => document.getElementById('tvprod-ticker').textContent")
    assert "25 parado(s)" in rod and "P000 há 200 dias" in rod, rod[:200]
    assert "4 veículo(s) sem nenhuma viagem" in rod


def test_no_celular_as_laminas_empilham(pagina):
    pg, base = pagina
    pg.add_init_script("Object.defineProperty(screen,'height',{get:()=>1000});")
    _abre(pg, base, 390, 844)
    r = pg.evaluate("""() => {
        const a = document.querySelector('.tvp-vis').getBoundingClientRect();
        const b = document.querySelector('.tvp-veic').getBoundingClientRect();
        const s = document.getElementById('tvprod-mensal');
        const card = s.closest('.tv-card');
        return {rola: document.documentElement.scrollWidth, a_fim: a.bottom, b_ini: b.top,
                b_esq: b.left, lamina: getComputedStyle(document.getElementById('tvprod-lamina')).display,
                serie: s.scrollWidth, cabe: card.clientWidth,
                colunas: [...s.children].filter(c => getComputedStyle(c).display !== 'none').length,
                rotulo: card.querySelector('.tv-label').innerText}; }""")
    assert r["rola"] <= 390, r
    # o gráfico não passa do cartão: no celular são os 6 últimos meses, e o
    # rótulo diz isso
    assert r["serie"] <= r["cabe"], r
    assert r["colunas"] == 6 and "6 MESES" in r["rotulo"].upper(), r
    assert r["b_ini"] >= r["a_fim"] - 1 and r["b_esq"] < 40, "a segunda lâmina não empilhou: %r" % r
    assert r["lamina"] == "none"
