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

def _prog(cod, sigla, no_prazo):
    """Uma lâmina do carrossel: o mesmo painel, com a programação no prazo
    marcando qual filial está na tela."""
    k = json.loads(json.dumps(PAYLOAD["kpis"]))
    k["programacao"]["no_prazo"] = no_prazo
    return {"codigo": cod, "sigla": sigla, "kpis": k, "alertas_total": 3,
            "cobertura": dict(PAYLOAD["cobertura"], coletas=no_prazo)}


# as filiais de programação na ordem do rádio do Avacorp (api/cco.PROGRAMACAO)
PAYLOAD["programacoes"] = [_prog(1, "CCO", 151), _prog(2, "SBC", 72), _prog(15, "PSA", 31),
                           _prog(19, "JOI", 9), _prog(20, "CRZ", 30)]
PAYLOAD["sem_programacao"] = 14

TELAS = [(1920, 1080), (1600, 900)]

# A FORMA de /api/operacao/cco/detalhe, com os números do PAYLOAD: cada aba
# traz tantas linhas quanto o cartão diz (o servidor garante; aqui é o dublê).
ESTADOS_DUBLE = {
    "programacao": [("atrasadas", "Sem veículo, janela vencida", 2), ("no_prazo", "No prazo", 297)],
    "coletas": [("atrasadas", "Atrasadas", 31), ("a_vencer", "A vencer", 45),
                ("no_prazo", "Chegou na janela", 69), ("sem_apontamento", "Sem apontamento", 13)],
    "emissoes": [("atrasadas", "Atrasadas", 21), ("aguardando", "Aguardando CT-e", 5),
                 ("no_prazo", "No prazo", 61)],
    "entregas": [("atrasadas", "Atrasadas", 52), ("a_vencer", "A vencer", 68),
                 ("no_prazo", "Chegou na janela", 67), ("sem_apontamento", "Sem apontamento", 6)],
    "carregamento": [("freetime", "Freetime excedido", 14), ("motivos", "Motivo de atraso", 1),
                     ("sem_clausula", "Sem cláusula de freetime", 9)],
    "descarga": [("freetime", "Freetime excedido", 27), ("motivos", "Motivo de atraso", 0),
                 ("sem_clausula", "Sem cláusula de freetime", 4)],
    "pendentes": [("pendentes", "Sem fim de descarga", 0)],
}


def _linha(i):
    return {"coleta": 30000 + i, "filial": 1 + i % 3,
            "cliente": f"CLIENTE COM NOME BEM COMPRIDO DA OPERAÇÃO {i}",
            "veiculo": f"ABC{i:04d}", "janela_carga": "2026-09-15 08:00",
            # par: o veículo segue no cliente (sem saída, relógio correndo)
            "chegada_carga": "2026-09-15 09:10",
            "saida_carga": None if i % 2 == 0 else "2026-09-15 11:00",
            "cte": "2026-09-15 11:20", "janela_entrega": "2026-09-16 07:00",
            "chegada_entrega": "2026-09-16 08:30", "fim_descarga": None,
            "horas": round(1 + i / 7, 2), "freetime_h": 3.0, "permanencia_h": 5.5,
            "agora": i % 2 == 0,
            "motivo": "ATRASO NA COLETA - AGUARDANDO LIBERAÇÃO DA DOCA" if i == 0 else None}


def _detalhe(card):
    if card == "cobertura":
        mon = [{"cliente": f"CLIENTE MONITORADO {i}", "coletas": c,
                "cobertura_pct": 96.0 + i / 10, "coletas_30d": 150 + i}
               for i, c in enumerate([60, 40, 30, 24, 20, 15, 12, 8, 5])]
        fora = [{"cliente": n, "coletas": c, "cobertura_pct": p, "coletas_30d": 90}
                for n, c, p in [("MWM", 80, 25.0), ("ADIENT", 50, 22.0), ("TWE", 20, 78.0),
                                ("CLIENTE X", 10, 60.0), ("CLIENTE Y", 6, 40.0),
                                ("CLIENTE Z", 4, None), ("CLIENTE W", 2, 12.5)]]
        estados = [{"estado": "monitorados", "rotulo": "Acompanhados", "n": 214, "linhas": mon},
                   {"estado": "fora", "rotulo": "Fora da conta", "n": 172, "linhas": fora}]
    else:
        estados = [{"estado": e, "rotulo": r, "n": n, "linhas": [_linha(i) for i in range(n)]}
                   for e, r, n in ESTADOS_DUBLE[card]]
    return {"card": card, "regra": f"A regra do cartão {card}, escrita pelo servidor.",
            "periodo": PAYLOAD["periodo"], "agora": PAYLOAD["agora"], "estados": estados,
            "cobertura_min_pct": 90, "cobertura_dias": 30}


def _abre(pagina, payload=PAYLOAD, status=200, largura=1920, altura=1080, parede=True,
          detalhe=_detalhe, det_status=200, pedidos=None):
    pg, base = pagina

    def rota(r):
        url = r.request.url
        if "/api/auth/me" in url:
            corpo, st = ADMIN, 200
        elif "/api/operacao/cco/detalhe" in url:
            card = url.split("card=", 1)[1].split("&", 1)[0]
            if pedidos is not None:
                prog = url.split("prog=", 1)[1].split("&", 1)[0] if "prog=" in url else None
                pedidos.append(card if prog is None else f"{card}&prog={prog}")
            corpo, st = detalhe(card), det_status
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
    # o giro das filiais de programação é armado na troca de tela; aqui ele é
    # DESLIGADO depois de conferido, para uma troca de lâmina no meio de um
    # teste não mudar o número que ele lê (o teste do giro chama o passo)
    assert pg.evaluate("!!tvTour"), "o giro das filiais de programação não foi armado"
    pg.evaluate("clearInterval(tvTour)")
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
    + ' #view-tvcco .tv-cco-periodo, #view-tvcco .tvp-lamina, #view-tvcco .tvp-lamina span')]
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
    # no celular o carrossel continua, então a pílula que diz a lâmina fica
    assert pg.is_visible("#tvcco-lamina"), "a pílula da lâmina sumiu no celular"
    assert pg.evaluate(_CABECALHO) == _CABECALHO_OK


# ------------------------------------------------------------ o carrossel (1.92.0)

_PILULA = """() => { const el = document.getElementById('tvcco-lamina');
    const pts = [...el.querySelectorAll('i')];
    return {pontos: pts.length, aceso: pts.findIndex(i => i.classList.contains('on')),
            rotulo: el.querySelector('span').textContent}; }"""
_PRIMEIRO = "#tvcco-k1 > .tv-card:nth-child(1) .tv-duo > div:nth-child(1) .tv-num"

# O CABEÇALHO COM A PÍLULA (1.92.0). A régua de texto cortado não pega isto:
# a pílula não corta o PRÓPRIO texto, ela sai inteira pela borda da tela; e o
# contador que quebra em duas linhas também não se corta.
_CABECALHO = """() => { const q = s => document.querySelector('#view-tvcco ' + s);
    const fs = el => parseFloat(getComputedStyle(el).fontSize);
    const umaLinha = el => getComputedStyle(el).display === 'none'
        || el.getBoundingClientRect().height <= 1.6 * fs(el);
    const p = q('.tvp-lamina').getBoundingClientRect();
    return {pilula_dentro: p.width > 0 && p.left >= 0 && p.right <= innerWidth,
            titulo_1_linha: umaLinha(q('.tv-head h2')),
            relogio_1_linha: umaLinha(q('.tv-head .tv-next'))}; }"""
_CABECALHO_OK = {"pilula_dentro": True, "titulo_1_linha": True, "relogio_1_linha": True}


def test_o_giro_passa_pelas_filiais_de_programacao_e_volta_ao_geral(pagina):
    pg = _abre(pagina)
    assert pg.evaluate(_PILULA) == {"pontos": 6, "aceso": 0, "rotulo": "Geral · 14 sem programação"}
    assert pg.inner_text(_PRIMEIRO) == "297"
    for i, (sigla, n) in enumerate([("CCO", "151"), ("SBC", "72"), ("PSA", "31"),
                                    ("JOI", "9"), ("CRZ", "30")], 1):
        pg.evaluate("tvCcoPasso()")
        pg.wait_for_timeout(2800)                    # a recontagem dos números
        assert pg.evaluate(_PILULA) == {"pontos": 6, "aceso": i, "rotulo": "Programação " + sigla}
        assert pg.inner_text(_PRIMEIRO) == n, (sigla, pg.inner_text(_PRIMEIRO))
        # a lâmina nova continua clicável: os alvos são refeitos a cada desenho
        assert pg.evaluate("document.querySelectorAll('#view-tvcco [role=\"button\"][data-cco]').length") == 25
    pg.evaluate("tvCcoPasso()")
    assert pg.evaluate(_PILULA)["aceso"] == 0
    # o rodapé é um só, e não é redesenhado pela troca de lâmina
    assert "58 avisos" in pg.inner_text("#tvcco-ticker")


def test_o_modal_e_da_filial_da_tela_e_o_giro_espera_ele_fechar(pagina):
    pedidos = []
    pg = _abre(pagina, pedidos=pedidos)
    pg.evaluate("tvCcoPasso(); tvCcoPasso()")            # SBC
    pg.wait_for_timeout(2800)
    pg.click(_PARTE.format(c=2, p=2))
    m = _modal(pg)
    assert pedidos == ["coletas&prog=2"], pedidos
    assert m["titulo"] == "Coletas · SBC", m
    pg.evaluate("tvCcoPasso()")                          # o giro chega com o modal aberto
    assert pg.evaluate("TVCCO_IDX") == 2
    pg.keyboard.press("Escape")
    pg.evaluate("tvCcoPasso()")
    assert pg.evaluate("TVCCO_IDX") == 3


@pytest.mark.parametrize("largura,altura", TELAS)
def test_nenhum_texto_corta_na_lamina_de_uma_filial(pagina, largura, altura):
    pg = _abre(pagina, largura=largura, altura=altura)
    pg.evaluate("tvCcoPasso()")
    pg.wait_for_timeout(2800)
    assert pg.evaluate(_PILULA)["rotulo"] == "Programação CCO"
    assert pg.evaluate(_CORTADOS) == []
    assert pg.evaluate(_CABECALHO) == _CABECALHO_OK
    larg = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert larg == 0, larg


# ------------------------------------------------------------ os modais (1.91.0)

_PARTE = "#tvcco-k1 > .tv-card:nth-child({c}) .tv-duo > div:nth-child({p})"
_MODAL = """() => {
    const bg = document.getElementById('modalBg'), box = document.getElementById('modalBox');
    const ab = box.querySelector('.ccm-aba[aria-pressed="true"]');
    return {aberto: bg.classList.contains('aberto'),
            titulo: (box.querySelector('h3') || {}).textContent,
            aba: ab ? ab.dataset.estado : null,
            linhas: box.querySelectorAll('#ccm-lista tbody tr').length,
            cont: (document.getElementById('ccm-cont') || {}).textContent,
            cab: [...box.querySelectorAll('#ccm-lista th')].map(t => t.textContent),
            per: (document.getElementById('ccm-per') || {}).textContent}; }"""


def _modal(pg):
    pg.wait_for_selector("#ccm-lista > *")
    return pg.evaluate(_MODAL)


def test_todo_numero_do_painel_abre_um_detalhe(pagina):
    """Cada número, barra e coluna tem alvo com rótulo — e continua tendo
    depois da recarga, que redesenha os cartões."""
    pg = _abre(pagina)
    conta = """() => ({
        alvos: document.querySelectorAll('#view-tvcco [role="button"][data-cco]').length,
        sem_rotulo: [...document.querySelectorAll('#view-tvcco [role="button"][data-cco]')]
                      .filter(e => !e.getAttribute('aria-label')).length,
        orfaos: [...document.querySelectorAll('#view-tvcco .tv-num, #view-tvcco .tvd-col, #view-tvcco .tv-cco-col')]
                  .filter(e => !e.closest('[data-cco]')).map(e => e.textContent.trim().slice(0, 30))})"""
    esperado = {"alvos": 25, "sem_rotulo": 0, "orfaos": []}
    assert pg.evaluate(conta) == esperado
    pg.evaluate("loadTvCco()")
    assert pg.evaluate(conta) == esperado


def test_clicar_no_numero_abre_o_detalhe_na_situacao_dele(pagina):
    pedidos = []
    pg = _abre(pagina, pedidos=pedidos)
    pg.click(_PARTE.format(c=2, p=2))          # Coletas · o vermelho das atrasadas
    m = _modal(pg)
    assert pedidos == ["coletas"], pedidos
    assert (m["aberto"], m["titulo"], m["aba"], m["linhas"]) == (True, "Coletas", "atrasadas", 31), m
    assert m["cont"] == "31 coletas", m
    assert m["cab"][:4] == ["Coleta", "Filial", "Cliente", "Veículo"] and m["cab"][-1] == "Atraso", m
    assert "leitura 15:35" in m["per"] and "mais nova" not in m["per"], m
    assert "A regra do cartão coletas" in pg.inner_text("#modalBox")


def test_o_resto_do_cartao_abre_na_primeira_situacao_com_coleta(pagina):
    def det(card):
        d = _detalhe(card)
        d["estados"][0].update(n=0, linhas=[])          # nenhuma atrasada
        return d
    pg = _abre(pagina, detalhe=det)
    pg.click("#tvcco-k1 > .tv-card:nth-child(2) .tv-label")
    m = _modal(pg)
    assert (m["aba"], m["linhas"], m["cab"][-1]) == ("a_vencer", 45, "Janela em"), m


def test_abas_e_filtro(pagina):
    pg = _abre(pagina)
    pg.click(_PARTE.format(c=2, p=2))
    _modal(pg)
    pg.click('#modalBox .ccm-aba[data-estado="no_prazo"]')
    m = pg.evaluate(_MODAL)
    assert (m["aba"], m["linhas"], m["cab"][-1]) == ("no_prazo", 69, "Antes da janela"), m
    pg.fill("#modalBox .ccm-busca", "30003")
    m = pg.evaluate(_MODAL)
    assert (m["linhas"], m["cont"]) == (1, "1 de 69 coletas"), m
    pg.fill("#modalBox .ccm-busca", "abc0010")                 # placa, sem caixa
    assert pg.evaluate(_MODAL)["linhas"] == 1
    pg.fill("#modalBox .ccm-busca", "nada disso")
    assert "Nada com esse filtro" in pg.inner_text("#ccm-lista")


def test_teclado_abre_e_esc_fecha_e_devolve_o_foco(pagina):
    pg = _abre(pagina)
    pg.focus(_PARTE.format(c=3, p=2))                           # Emissão · atrasadas
    pg.keyboard.press("Enter")
    m = _modal(pg)
    assert (m["titulo"], m["aba"], m["linhas"]) == ("Emissão do CT-e", "atrasadas", 21), m
    pg.keyboard.press("Escape")
    fim = pg.evaluate("""() => ({aberto: document.getElementById('modalBg').classList.contains('aberto'),
        foco: document.activeElement.dataset.cco + '/' + document.activeElement.dataset.estado})""")
    assert fim == {"aberto": False, "foco": "emissoes/atrasadas"}, fim


def test_as_barras_as_colunas_e_a_pontualidade_abrem_o_cartao_delas(pagina):
    pg = _abre(pagina)
    casos = [("#tvcco-k3 .tvd-col:nth-child(4)", "Descarga", "freetime"),
             ("#tvcco-k3 .tv-cco-col:nth-child(2)", "Emissão do CT-e", "atrasadas"),
             ("#tvcco-k3 .tv-cco-pont > div:nth-child(2)", "Entregas", "atrasadas")]
    for sel, titulo, aba in casos:
        pg.click(sel)
        m = _modal(pg)
        assert (m["titulo"], m["aba"]) == (titulo, aba), (sel, m)
        pg.keyboard.press("Escape")
        pg.wait_for_selector("#modalBg.aberto", state="hidden")
    # o freetime diz a cláusula, a permanência, o excesso e o motivo
    pg.click("#tvcco-k3 .tvd-col:nth-child(3)")
    m = _modal(pg)
    assert (m["titulo"], m["linhas"]) == ("Carregamento", 14), m
    assert m["cab"][-4:] == ["Freetime", "Permanência", "Excesso", "Motivo apontado"], m
    assert "segue lá" in pg.inner_text("#ccm-lista")


def test_a_cobertura_mostra_os_clientes(pagina):
    pg = _abre(pagina)
    pg.click("#tvcco-k2 > .tv-card:nth-child(4)")
    m = _modal(pg)
    assert (m["titulo"], m["aba"], m["linhas"]) == ("Acompanhados pelo SAC", "monitorados", 9), m
    assert m["cont"] == "9 clientes · 214 coletas", m
    pg.click('#modalBox .ccm-aba[data-estado="fora"]')
    m = pg.evaluate(_MODAL)
    assert (m["linhas"], m["cont"]) == (7, "7 clientes · 172 coletas"), m
    primeira = pg.evaluate("""() => { const tr = document.querySelector('#ccm-lista tbody tr');
        const at = tr.querySelector('.ccm-at');
        return [tr.cells[0].textContent, at ? at.textContent : null]; }""")
    assert primeira == ["MWM", "25%"], primeira


@pytest.mark.parametrize("largura,altura", [(1920, 1080), (400, 860)])
def test_o_modal_cabe_na_tela_e_a_lista_rola_dentro(pagina, largura, altura):
    pg = _abre(pagina, largura=largura, altura=altura)
    pg.click("#tvcco-k1 > .tv-card:nth-child(1) .tv-duo > div:nth-child(1)")   # 297 no prazo
    assert _modal(pg)["linhas"] == 297
    med = pg.evaluate("""() => { const b = document.getElementById('modalBox').getBoundingClientRect();
        const l = document.getElementById('ccm-lista');
        return {top: b.top, bottom: b.bottom, left: b.left, right: b.right, w: innerWidth, h: innerHeight,
                rola: l.scrollHeight > l.clientHeight + 50,
                lado: document.documentElement.scrollWidth - document.documentElement.clientWidth}; }""")
    assert med["top"] >= 0 and med["bottom"] <= med["h"], med
    assert med["left"] >= 0 and med["right"] <= med["w"], med
    assert med["rola"] and med["lado"] == 0, med


def test_a_largura_do_detalhe_nao_vaza_para_o_proximo_modal(pagina):
    """O detalhe é mais largo que a ficha da casa, e a largura vem do
    conteúdo: o formulário que abrir depois volta aos 560px."""
    pg = _abre(pagina)
    pg.click(_PARTE.format(c=2, p=2))
    _modal(pg)
    larga = pg.evaluate("document.getElementById('modalBox').getBoundingClientRect().width")
    pg.keyboard.press("Escape")
    pg.evaluate("abrirModal('<h3>Outro modal</h3><p>formulário da casa</p>')")
    padrao = pg.evaluate("document.getElementById('modalBox').getBoundingClientRect().width")
    assert larga > 1100 and padrao <= 560, (larga, padrao)


def test_a_falha_do_detalhe_e_dita_no_modal(pagina):
    pg = _abre(pagina, det_status=503, detalhe=lambda c: {
        "erro": "banco_inacessivel", "mensagem": "Sem conexão com o banco do ERP."})
    pg.click(_PARTE.format(c=2, p=2))
    pg.wait_for_function("(document.getElementById('ccm-corpo') || {}).textContent"
                         " && document.getElementById('ccm-corpo').textContent.includes('Não foi possível')")
    assert "Sem conexão com o banco do ERP." in pg.inner_text("#ccm-corpo")


def test_leitura_mais_nova_que_a_do_painel_e_dita(pagina):
    def det(card):
        d = _detalhe(card)
        d["agora"] = "2026-09-15 15:37"
        return d
    pg = _abre(pagina, detalhe=det)
    pg.click(_PARTE.format(c=2, p=2))
    assert "leitura 15:37 · mais nova que a do painel (15:35)" in _modal(pg)["per"]
