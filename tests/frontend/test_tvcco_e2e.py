# -*- coding: utf-8 -*-
"""O painel de TV do CCO (`tvcco`) no navegador, com o dublê na ORDEM DE
GRANDEZA do dia real (15/09/2026: 297 programações, 100 coletas e 119
entregas com base, 58 avisos) — régua com dublê vazio mede o esqueleto.

Dois modos, porque a TV roda nos dois: PAREDE (tela cheia — o Chromium
headless diz que a tela é do tamanho da janela, então é o padrão aqui) e
QUIOSQUE (janela maximizada numa tela maior, sem `tvfull`).
"""
from __future__ import annotations

import json

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

ALERTAS = [{"tipo": "entrega", "horas": 20.0 - i / 2,
            "texto": f"Entrega atrasada · coleta {20000 + i} · CLIENTE {i} · +{20 - i // 2}h00"}
           for i in range(20)]

# os subtítulos mais longos do dia real (15/09, 15:36), que é onde cortava
PAYLOAD = {
    "periodo": {"de": "2026-09-14", "ate": "2026-09-16"},
    "agora": "2026-09-15 15:35",
    "kpis": {
        "programacao": {"total": 299, "no_prazo": 297, "atrasadas": 2},
        "coletas": {"no_prazo": 69, "atrasadas": 31, "a_vencer": 45,
                    "sem_apontamento": 13, "pontualidade": 69.0},
        "emissoes": {"no_prazo": 61, "atrasadas": 21, "aguardando": 5},
        "entregas": {"no_prazo": 67, "atrasadas": 52, "a_vencer": 68,
                     "sem_apontamento": 6, "pontualidade": 56.3},
        "carregamento": {"motivos": 1, "freetime": 14, "freetime_agora": 4, "sem_clausula": 9},
        "descarga": {"motivos": 0, "freetime": 27, "freetime_agora": 5, "sem_clausula": 4},
        "pendentes_finalizacao": 0,
    },
    "cobertura": {"clientes": 9, "coletas": 214, "fora_coletas": 172,
                  "fora_clientes": ["MWM", "ADIENT", "TWE"], "fora_clientes_n": 7,
                  "clientes_avaliados": 16},
    "alertas": ALERTAS,
    "alertas_total": 58,
    "regras": {"tolerancia_cte_min": 60, "cobertura_min": 0.9,
               "cobertura_dias": 30, "pendente_fim_h": 24},
}

TELAS = [(1920, 1080), (1600, 900)]


def _abre(pagina, payload=PAYLOAD, status=200, largura=1920, altura=1080, parede=True):
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo, st = ADMIN, 200
        elif "/api/operacao/cco" in url:
            corpo, st = payload, status
        else:
            corpo, st = {}, 200
        r.fulfill(status=st, content_type="application/json", body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    if not parede:
        # a tela maior que a janela é a TV em quiosque/maximizada, sem tvfull
        pg.add_init_script("Object.defineProperty(screen,'width',{get:()=>3840});"
                           "Object.defineProperty(screen,'height',{get:()=>2160});")
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#tvcco")
    pg.wait_for_selector("#tvcco-k1 .tv-card")
    pg.wait_for_timeout(3000)          # a contagem animada dos números (2,6 s)
    modo = pg.evaluate("() => ({cheia: document.body.classList.contains('tvfull'),"
                       " parede: document.body.classList.contains('tvwall')})")
    assert modo == {"cheia": parede, "parede": True}, modo
    return pg


def test_os_numeros_e_as_regras_chegam_nos_cartoes(pagina):
    pg = _abre(pagina)
    k1 = pg.inner_text("#tvcco-k1").lower()
    for trecho in ("programação", "297", "sem veículo, janela vencida",
                   "emissão do ct-e", "até 1 h da saída", "45 a vencer"):
        assert trecho in k1, (trecho, k1)
    k2 = pg.inner_text("#tvcco-k2")
    assert "214" in k2 and "MWM" in k2 and "172" in k2, k2
    assert "freetime excedido · 4 agora" in k2, k2
    assert "ontem, hoje e amanhã · 14/09 a 16/09 · leitura 15:35" in pg.inner_text("#tvcco-periodo")


_CORTADOS = """() => [...document.querySelectorAll(
    '#view-tvcco .tv-sub, #view-tvcco .tv-label, #view-tvcco .tv-num, #view-tvcco .tvd-col b,'
    + ' #view-tvcco .tv-cco-col b, #view-tvcco .tv-cco-col em, #view-tvcco .tv-cco-pl b,'
    + ' #view-tvcco .tv-cco-periodo')]
    .filter(e => e.scrollWidth > e.clientWidth + 1)
    .map(e => (e.className || e.tagName) + ': ' + e.textContent.trim().slice(0, 40))"""


@pytest.mark.parametrize("largura,altura", TELAS)
@pytest.mark.parametrize("parede", [True, False])
def test_nenhum_texto_corta(pagina, largura, altura, parede):
    """O pedido de 15/09: a reticência corta DENTRO do elemento, e o guard da
    1.90.0 medía o cartão, que não vaza — por isso passou verde com texto
    cortado na parede. Aqui cada texto é medido, nos dois modos e em duas TVs."""
    pg = _abre(pagina, largura=largura, altura=altura, parede=parede)
    assert pg.evaluate(_CORTADOS) == []


def test_a_cor_e_a_da_regra(pagina):
    pg = _abre(pagina)
    cores = pg.evaluate("""() => {
        const cor = el => getComputedStyle(el).color;
        const nums = [...document.querySelectorAll('#tvcco-k3 .tv-num')];
        const atr = document.querySelectorAll('#tvcco-k1 .tv-card')[1].querySelectorAll('.tv-num')[1];
        return {coleta: cor(nums[0]), entrega: cor(nums[1]), atrasadas: cor(atr)}; }""")
    assert cores["coleta"] == "rgb(248, 113, 113)", cores     # 69%: abaixo de 70
    assert cores["entrega"] == "rgb(248, 113, 113)", cores
    assert cores["atrasadas"] == "rgb(248, 113, 113)", cores


def test_amarelo_entre_70_e_94(pagina):
    p = json.loads(json.dumps(PAYLOAD))
    p["kpis"]["coletas"]["pontualidade"] = 73.9
    pg = _abre(pagina, payload=p)
    cor = pg.evaluate("getComputedStyle(document.querySelector('#tvcco-k3 .tv-num')).color")
    assert cor == "rgb(251, 191, 36)", cor


def test_pontualidade_empilhada_ocupa_o_cartao(pagina):
    """Coleta em cima, entrega embaixo — e o conteúdo desce até o pé do
    cartão, em vez de ficar no alto com meio cartão vazio."""
    pg = _abre(pagina)
    m = pg.evaluate("""() => {
        const card = document.querySelector('#tvcco-k3 .tv-card');
        const blocos = [...card.querySelectorAll('.tv-cco-pont > div')];
        const c = card.getBoundingClientRect();
        return {rot: blocos.map(b => b.querySelector('b').textContent),
                topos: blocos.map(b => b.getBoundingClientRect().top),
                sobra: c.bottom - blocos[blocos.length - 1].getBoundingClientRect().bottom,
                alt: c.height}; }""")
    assert m["rot"] == ["Coleta", "Entrega"], m
    assert m["topos"][1] > m["topos"][0], m
    assert m["sobra"] < 0.25 * m["alt"], m


def test_por_etapa_e_100_por_cento_empilhado(pagina):
    pg = _abre(pagina)
    med = pg.evaluate("""() => [...document.querySelectorAll('#tvcco-k3 .tv-cco-col')].map(c => {
        const p = c.querySelector('.tv-cco-pilha').getBoundingClientRect().height;
        const ok = c.querySelector('.ok').getBoundingClientRect().height;
        return {rotulo: c.querySelector('b').textContent, fr: ok / p,
                v: c.querySelector('.v').textContent}; })""")
    assert [m["rotulo"] for m in med] == ["Programação", "Emissão", "Coleta", "Entrega"]
    esperado = {"Programação": 297 / 299, "Emissão": 61 / 82, "Coleta": 69 / 100, "Entrega": 67 / 119}
    for m in med:
        assert abs(m["fr"] - esperado[m["rotulo"]]) < 0.02, m
    assert med[3]["v"] == "56%", med


def test_gargalos_na_proporcao_e_na_mesma_base(pagina):
    pg = _abre(pagina)
    bar = pg.evaluate("""() => [...document.querySelectorAll('#tvcco-k3 .tvd-col')].map(c => {
        const r = c.querySelector('i').getBoundingClientRect();
        return [c.querySelector('b').innerText.replace(/\\s+/g, ' ').trim(), r.height, r.bottom]; })""")
    alt = {b[0]: b[1] for b in bar}
    assert set(alt) == {"Atraso carga", "Atraso descarga", "Freetime carga", "Freetime descarga"}, alt
    assert alt["Freetime descarga"] > alt["Freetime carga"] > alt["Atraso carga"], alt
    assert abs(alt["Freetime carga"] / alt["Freetime descarga"] - 14 / 27) < 0.03, alt
    bases = [b[2] for b in bar]
    assert max(bases) - min(bases) <= 1, bar       # o eixo não fica torto


def test_na_parede_o_painel_ocupa_a_tv_sem_rolar(pagina):
    pg = _abre(pagina)
    m = pg.evaluate("""() => ({alt: innerHeight,
        rolagem: document.documentElement.scrollHeight - innerHeight,
        larg: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        rodape: document.querySelector('#view-tvcco .tv-ticker').getBoundingClientRect().bottom})""")
    assert m["rolagem"] <= 0 and m["larg"] == 0, m
    assert m["rodape"] >= m["alt"] - 40, m      # vai até o pé da TV, sem faixa vazia


def test_no_quiosque_cabe_na_regua_da_tv(pagina):
    pg = _abre(pagina, parede=False)
    m = pg.evaluate("""() => ({fundo: document.getElementById('view-tvcco').getBoundingClientRect().bottom,
        larg: document.documentElement.scrollWidth - document.documentElement.clientWidth})""")
    assert m["fundo"] <= 1050 and m["larg"] == 0, m


def test_o_rodape_diz_o_corte_e_traz_os_avisos(pagina):
    pg = _abre(pagina)
    rod = pg.inner_text("#tvcco-ticker")
    assert "58 avisos" in rod, rod[:200]
    assert "Entrega atrasada · coleta 20000" in rod, rod[:300]


def test_falha_diz_sem_conexao(pagina):
    pg = _abre(pagina, payload={"erro": "erro_consulta"}, status=500)
    # innerText respeita o text-transform do rótulo (maiúsculas)
    assert "sem conexão" in pg.inner_text("#tvcco-k1").lower()


def test_no_celular_nada_sai_para_o_lado(pagina):
    pg, base = pagina
    pg.set_viewport_size({"width": 400, "height": 860})
    pg = _abre(pagina, largura=400, altura=860)
    larg = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert larg == 0, larg
    assert pg.evaluate(_CORTADOS) == []
