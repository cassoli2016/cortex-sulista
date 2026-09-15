# -*- coding: utf-8 -*-
"""O painel de TV do CCO (`tvcco`) no navegador, com o dublê na ORDEM DE
GRANDEZA do dia real (15/09/2026: 281 programações, 88 coletas e 117 entregas
com base, 50 avisos) — régua com dublê vazio mede o esqueleto, não a tela.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

ALERTAS = [{"tipo": "entrega", "horas": 20.0 - i / 2,
            "texto": f"Entrega atrasada · coleta {20000 + i} · CLIENTE {i} · +{20 - i // 2}h00"}
           for i in range(20)]

PAYLOAD = {
    "periodo": {"de": "2026-09-14", "ate": "2026-09-16"},
    "agora": "2026-09-15 13:38",
    "kpis": {
        "programacao": {"total": 281, "no_prazo": 279, "atrasadas": 2},
        "coletas": {"no_prazo": 65, "atrasadas": 23, "a_vencer": 49,
                    "sem_apontamento": 13, "pontualidade": 73.9},
        "emissoes": {"no_prazo": 59, "atrasadas": 21, "aguardando": 3},
        "entregas": {"no_prazo": 66, "atrasadas": 51, "a_vencer": 71,
                     "sem_apontamento": 1, "pontualidade": 56.4},
        "carregamento": {"motivos": 1, "freetime": 13, "freetime_agora": 3, "sem_clausula": 8},
        "descarga": {"motivos": 0, "freetime": 26, "freetime_agora": 5, "sem_clausula": 4},
        "pendentes_finalizacao": 0,
    },
    "cobertura": {"clientes": 9, "coletas": 205, "fora_coletas": 163,
                  "fora_clientes": ["MWM", "ADIENT", "LEAR"], "fora_clientes_n": 7,
                  "clientes_avaliados": 16},
    "alertas": ALERTAS,
    "alertas_total": 50,
    "regras": {"tolerancia_cte_min": 60, "cobertura_min": 0.9,
               "cobertura_dias": 30, "pendente_fim_h": 24},
}


def _abre(pagina, payload=PAYLOAD, status=200, largura=1920, altura=1080):
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
    pg.set_viewport_size({"width": largura, "height": altura})
    pg.goto(base + "/static/index.html#tvcco")
    pg.wait_for_selector("#tvcco-k1 .tv-card")
    pg.wait_for_timeout(3000)          # a contagem animada dos números (2,6 s)
    return pg


def test_os_numeros_e_as_regras_chegam_nos_cartoes(pagina):
    pg = _abre(pagina)
    k1 = pg.inner_text("#tvcco-k1")
    for trecho in ("PROGRAMAÇÃO", "279", "SEM VEÍCULO, JANELA VENCIDA".lower(),
                   "EMISSÃO DO CT-E", "até 1 h da saída", "49 a vencer"):
        assert trecho.lower() in k1.lower(), (trecho, k1)
    k2 = pg.inner_text("#tvcco-k2")
    # o DENOMINADOR na parede: quantos o SAC acompanha e quem ficou de fora
    assert "205" in k2 and "MWM" in k2 and "163" in k2, k2
    assert "13 freetime excedido" not in k2  # o número vem no cartão, a regra no rótulo
    assert "freetime excedido · 3 agora" in k2, k2
    assert "ontem, hoje e amanhã · 14/09 a 16/09 · leitura 13:38" in pg.inner_text("#tvcco-periodo")


def test_a_cor_e_a_da_regra(pagina):
    pg = _abre(pagina)
    cores = pg.evaluate("""() => {
        const cor = el => getComputedStyle(el).color;
        const nums = [...document.querySelectorAll('#tvcco-k3 .tv-num')];
        const atr = document.querySelectorAll('#tvcco-k1 .tv-card')[1].querySelectorAll('.tv-num')[1];
        return {coleta: cor(nums[0]), entrega: cor(nums[1]), atrasadas: cor(atr)}; }""")
    assert cores["coleta"] == "rgb(251, 191, 36)", cores       # 73,9%: 70 a 94 amarelo
    assert cores["entrega"] == "rgb(248, 113, 113)", cores     # 56,4%: abaixo de 70
    assert cores["atrasadas"] == "rgb(248, 113, 113)", cores


def test_por_etapa_e_100_por_cento_empilhado(pagina):
    pg = _abre(pagina)
    med = pg.evaluate("""() => [...document.querySelectorAll('#tvcco-k3 .tv-cco-col')].map(c => {
        const p = c.querySelector('.tv-cco-pilha').getBoundingClientRect().height;
        const ok = c.querySelector('.ok').getBoundingClientRect().height;
        return {rotulo: c.querySelector('b').textContent, fr: ok / p,
                v: c.querySelector('.v').textContent}; })""")
    assert [m["rotulo"] for m in med] == ["Programação", "Emissão", "Coleta", "Entrega"]
    esperado = {"Programação": 279 / 281, "Emissão": 59 / 80, "Coleta": 65 / 88, "Entrega": 66 / 117}
    for m in med:
        assert abs(m["fr"] - esperado[m["rotulo"]]) < 0.02, m
    assert med[3]["v"] == "56%", med


def test_gargalos_na_proporcao(pagina):
    pg = _abre(pagina)
    alt = pg.evaluate("""() => [...document.querySelectorAll('#tvcco-k3 .tvd-col')].map(c =>
        [c.querySelector('b').textContent, c.querySelector('i').getBoundingClientRect().height])""")
    alt = dict(alt)
    assert alt["Freetime na descarga"] > alt["Freetime na carga"] > alt["Atraso na carga"], alt
    assert abs(alt["Freetime na carga"] / alt["Freetime na descarga"] - 13 / 26) < 0.03, alt


def test_cabe_na_tv_sem_rolar_nem_para_o_lado(pagina):
    pg = _abre(pagina)
    m = pg.evaluate("""() => { const v = document.getElementById('view-tvcco');
        const r = v.getBoundingClientRect();
        // o cartao que vaza E o elemento que vaza: "1 cartao cortado" sozinho
        // nao diz onde mexer
        const corte = [...v.querySelectorAll('.tv-card')].filter(c => c.scrollWidth > c.clientWidth + 2)
          .map(c => { const cr = c.getBoundingClientRect();
            const fora = [...c.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > cr.right + 2)
              .map(e => (e.className || e.tagName) + ':' + (e.textContent || '').trim().slice(0, 30));
            return (c.querySelector('.tv-label') || {}).textContent + ' -> ' + fora.slice(0, 3).join(' | '); });
        return {fundo: r.bottom, larg: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                corte}; }""")
    assert m["fundo"] <= 1050, m
    assert m["larg"] == 0, m
    assert m["corte"] == [], m


def test_o_rodape_diz_o_corte_e_traz_os_avisos(pagina):
    pg = _abre(pagina)
    rod = pg.inner_text("#tvcco-ticker")
    assert "50 avisos" in rod, rod[:200]
    assert "Entrega atrasada · coleta 20000" in rod, rod[:300]


def test_falha_diz_sem_conexao(pagina):
    pg = _abre(pagina, payload={"erro": "erro_consulta"}, status=500)
    # innerText respeita o text-transform do rótulo (maiúsculas)
    assert "sem conexão" in pg.inner_text("#tvcco-k1").lower()


def test_no_celular_nada_sai_para_o_lado(pagina):
    pg = _abre(pagina, largura=400, altura=860)
    larg = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert larg == 0, larg
