# -*- coding: utf-8 -*-
"""A TV de operação depois da revisão com quem opera (13/09/2026).

Cada teste é um pedido dito na parede, e o dublê tem a ORDEM DE GRANDEZA do
dia real (67 em trânsito, 63 agregados em viagem, 4 modalidades de km) —
régua com dublê vazio mede o esqueleto, não a tela.

1. frota no lugar da placa;
2. carga crítica (ocorrência 261) no TOPO das chegadas, com a linha
   destacada e o selo escrito — inclusive a que não tem previsão;
3. sem o selo piscante no título e sem "frota reportando" no cabeçalho;
4. sem valor de combustível, locação somada em frota, terceiro visível;
5. meta do dia E do mês, cada uma com a sua data — e o dia sem meta DIZ
   isso em vez de mostrar o dia anterior;
6. tração e motoristas com frota e agregado separados;
7. telemetria com os três indicadores de condução no lugar dos cartões que
   ninguém sabia ler;
8. mapa com legenda, tração no marcador e grupos de no máximo 5.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}

AGORA = datetime.now()


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")


def _viagem(i, frota, placa, *, critica=False, atrasada=False, prev=True, horas=5):
    return {"numero": 1000 + i, "placa": placa, "frota": frota,
            "rotulo": f"{frota} · {placa}", "utilizacao": "AGREGADOS",
            "destino": f"DESTINO {i}/SP", "saida": _fmt(AGORA - timedelta(hours=10)),
            "previsao_chegada": (_fmt(AGORA + timedelta(hours=horas)) if prev else None),
            "atrasada": atrasada, "critica": critica,
            "posicao_em": _fmt(AGORA - timedelta(minutes=5)), "velocidade": 60}


# 12 viagens: 2 atrasadas, 2 CRÍTICAS (uma sem previsão e a outra com a
# previsão MAIS distante de todas -- sem a regra, as duas ficariam no fim)
TRANSITO = (
    [_viagem(i, f"A{i:03d}", f"AAA{i}A{i:02d}", horas=2 + i) for i in range(8)]
    + [_viagem(20, "B020", "BBB2B20", atrasada=True, horas=-3),
       _viagem(21, "B021", "BBB2B21", atrasada=True, horas=-1),
       _viagem(30, "C030", "CCC3C30", critica=True, horas=90),
       _viagem(31, "C031", "CCC3C31", critica=True, prev=False)]
)


def _pos(i, util, tracao, lat, lng, vel=0, frota=None):
    return {"placa": f"POS{i:04d}", "frota": frota or f"{i}", "rotulo": f"{i}",
            "utilizacao": util, "lat": lat, "lng": lng, "velocidade": vel,
            "com_motor": True, "recente": True, "tracao": tracao,
            "posicao_em": _fmt(AGORA - timedelta(minutes=3))}


# 6 veículos NO MESMO PONTO: tem de dar um grupo de 5 e um avulso, nunca 6.
MESMO_PONTO = [_pos(100 + i, "AGREGADOS", "6x2", -23.55, -46.63) for i in range(6)]
POSICOES = MESMO_PONTO + [
    _pos(1, "FROTA", "4x2", -25.43, -49.27),
    _pos(2, "LOCACAO", "6x2", -26.30, -48.85),
    _pos(3, "TERCEIROS", "truck", -22.90, -47.06),
    _pos(4, "AGREGADOS", "3/4", -29.70, -51.10, vel=95),   # alerta: >90 km/h
    # a atrasada B020 no mapa, longe de qualquer polo, com o destino
    # geocodificado de antemão: é o caso em que o tracejado (removido) nasceria
    {**_pos(5, "AGREGADOS", "4x2", -21.00, -44.00), "placa": "BBB2B20"},
]

TELEMETRIA = {"disponivel": True, "escopo": "frota", "veiculos": 47,
              "km_l_frota": 3.18, "alvo_km_l": 2.5, "com_consumo_valido": 41,
              "leitura_suspeita": 6, "dias_atras": 0, "vel_media": 43.4,
              "freadas_alta": 120, "freadas_alta_por_mil_km": 2.27,
              "motor_parado_pct": 14.3, "faixa_extra_eco_pct": 93.9,
              "pedal_critico_pct": 14.5, "conducao_veiculos": 46,
              "conducao_dias_atras": 0}

PROG_KPIS = {"tracao_total": 80, "tracao_viagem": 4, "tracao_os": 4, "tracao_disp": 72,
             "agr_total": 120, "agr_viagem": 64, "agr_ativos_30d": 116, "agr_disp": 52,
             "mot_total": 224, "mot_viagem": 67, "mot_parados": 157,
             "mot_viagem_proprio": 4, "mot_viagem_agregado": 63, "mot_viagem_terceiro": 0,
             "mot_proprios": 68, "mot_proprios_disp": 64, "pct_proprios_disp": 94.1,
             "chegando_72h": 30, "sem_retorno": 5, "cargas_sem_chegada": 3,
             "cnh_vencida": 2, "cnh_vencida_rodando": 0}

KM = {"kpis": {"km_total": 454000.0, "km_carregado": 363000.0, "km_vazio": 91000.0},
      "modalidades": [
          {"utilizacao": "AGREGADOS", "viagens": 1162, "km_total": 365000.0},
          {"utilizacao": "LOCACAO", "viagens": 355, "km_total": 49000.0},
          {"utilizacao": "FROTA", "viagens": 181, "km_total": 27000.0},
          {"utilizacao": "TERCEIROS", "viagens": 25, "km_total": 12000.0}]}


def _visao(com_hoje: bool) -> dict:
    """DOMINGO: o dia sem meta NÃO entra no `diario` -- é exatamente o que fazia
    a TV mostrar o sábado. O dia anterior tem realizado para a regra velha ter
    onde cair."""
    ontem = (AGORA - timedelta(days=1)).day
    diario = [{"dia": ontem, "realizado": 50.0, "meta": 100.0}] if ontem < AGORA.day else []
    if com_hoje:
        diario.append({"dia": AGORA.day, "realizado": 30.0, "meta": 100.0})
    return {"diario": diario, "atingimento_mes": 0.876,
            "atualizado_em": AGORA.isoformat(), "kpis": {}}


def _abre(pg, base, *, com_hoje=False, prog=None):
    pedidos = []

    def rota(r):
        url = r.request.url
        pedidos.append(url)
        if "/api/auth/me" in url:
            corpo = ADMIN
        elif "/api/operacao/torre/estradas" in url:
            corpo = {}
        elif "/api/operacao/torre" in url:
            corpo = {"kpis": {"em_transito": len(TRANSITO), "atrasadas": 2, "criticas": 2,
                              "saidas_hoje": 3, "chegadas_previstas_hoje": 1},
                     "posicoes": POSICOES, "transito": TRANSITO,
                     "telemetria": TELEMETRIA}
        elif "/api/operacao/programacao" in url:
            corpo = {"kpis": prog or PROG_KPIS}
        elif "/api/operacao/seguranca" in url:
            # cercas > 0 de propósito: o rodapé não pode mais publicá-las
            corpo = {"kpis": {"cercas_24h": 7}}
        elif "/api/operacao/analise-km" in url:
            corpo = KM
        elif "/api/visao-geral" in url:
            corpo = _visao(com_hoje)
        else:
            corpo = {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    pg.route("**/tile.openstreetmap.org/**", lambda r: r.abort())
    pg.route("**/geocoding-api.open-meteo.com/**", lambda r: r.abort())
    pg.route("**/api.open-meteo.com/**", lambda r: r.abort())
    # o geocoder externo está bloqueado no teste: o destino da atrasada vem
    # do cache que o próprio tvGeo lê
    pg.add_init_script("try{localStorage.setItem('geo.DESTINO 20/SP',"
                       "JSON.stringify([-23.55,-46.63]))}catch(e){}")
    # reduced-motion: tvAnimarNums deixa o número FINAL na tela, sem contagem
    pg.emulate_media(reduced_motion="reduce")
    pg.set_viewport_size({"width": 1920, "height": 1080})
    pg.goto(base + "/static/index.html#tvope")
    pg.wait_for_function(
        "() => document.querySelectorAll('#tvope-cheg tr').length > 1"
        " && document.querySelector('#tvope-km .tvw-gauge')")
    pg.wait_for_timeout(1500)       # o relógio do cabeçalho bate de 1 em 1 s
    return pedidos


def _linhas(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#tvope-cheg tr')].map(tr => ({
        classe: tr.className, texto: tr.innerText,
        fundo: getComputedStyle(tr.cells[0]).backgroundColor}))""")


# ------------------------------------------------------------ as chegadas

def test_a_carga_critica_vem_primeiro_mesmo_sem_previsao(pagina):
    pg, base = pagina
    _abre(pg, base)
    ls = _linhas(pg)
    assert "C030" in ls[0]["texto"] or "C031" in ls[0]["texto"], ls[0]
    topo = {ls[0]["texto"].split()[0], ls[1]["texto"].split()[0]}
    assert topo == {"C030", "C031"}, (
        "as duas críticas têm de ocupar o topo, antes das atrasadas: %r"
        % [l["texto"][:20] for l in ls[:4]])
    # e as atrasadas vêm logo depois, antes das que ainda estão no prazo
    assert {ls[2]["texto"].split()[0], ls[3]["texto"].split()[0]} == {"B020", "B021"}


def test_a_linha_critica_e_destacada_e_diz_por_que(pagina):
    """Cor sem rótulo não se explica numa TV — o selo escrito vai junto."""
    pg, base = pagina
    _abre(pg, base)
    ls = _linhas(pg)
    assert "crit" in ls[0]["classe"] and "CRÍTICA" in ls[0]["texto"]
    normal = next(l for l in ls if "crit" not in l["classe"])
    assert ls[0]["fundo"] != normal["fundo"], (
        "a linha crítica tem o mesmo fundo das outras: %s" % ls[0]["fundo"])
    assert "CRÍTICA" not in normal["texto"]


def test_a_tabela_mostra_a_frota_e_nao_a_placa(pagina):
    pg, base = pagina
    _abre(pg, base)
    cab = pg.evaluate("() => document.querySelector('#view-tvope .tv-tab th').innerText")
    assert cab.strip().upper() == "FROTA"
    texto = " ".join(l["texto"] for l in _linhas(pg))
    assert "A000" in texto or "B020" in texto
    assert "AAA0A00" not in texto and "BBB2B20" not in texto, "placa na tabela"


# ------------------------------------------------------------ o cabeçalho

def test_o_cabecalho_nao_tem_selo_piscando_nem_frota_reportando(pagina):
    pg, base = pagina
    _abre(pg, base)
    assert pg.evaluate("() => document.getElementById('tvope-farol')") is None
    beat = pg.evaluate("() => document.getElementById('tvope-beat').innerText.trim()")
    assert "reportando" not in beat.lower()
    assert beat == "agora" or beat.startswith("há "), repr(beat)
    assert pg.evaluate("() => !!document.querySelector('#tvope-beat i')"), "sem a bolinha"


# ------------------------------------------------------------ km e meta

def test_o_cartao_de_km_nao_tem_combustivel_e_mostra_o_terceiro(pagina):
    pg, base = pagina
    pedidos = _abre(pg, base)
    km = pg.evaluate("() => document.getElementById('tvope-km').innerText")
    assert "Combustível" not in km and "R$" not in km
    mods = pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .mod b')]
                                 .map(b => b.innerText.trim())""")
    assert mods == ["Agregado", "Frota", "Terceiro"], mods
    # locação SOMADA em frota: 49 + 27 = 76 mil km
    frota = pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .mod')]
                                  .find(m => m.innerText.includes('Frota')).innerText""")
    assert "76 mil km" in frota, frota
    assert not any("/api/frota/combustivel" in u for u in pedidos), (
        "a TV ainda pede o combustível que não mostra")


def _metas(pg):
    # textContent e nao innerText: o percentual mora num <text> de SVG
    return pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .tvw-meta')]
                                 .map(m => m.textContent.replace(/\\s+/g, ' ').trim())""")


def test_dia_sem_meta_diz_isso_e_nao_mostra_o_dia_anterior(pagina):
    pg, base = pagina
    _abre(pg, base, com_hoje=False)
    dia, mes = _metas(pg)
    hoje = AGORA.strftime("%d/%m")
    assert hoje in dia and "sem meta" in dia.lower(), dia
    assert "50%" not in dia, "voltou a mostrar o dia anterior: %r" % dia
    assert "88%" in mes and "META DO MÊS" in mes.upper(), mes


def test_dia_com_meta_mostra_o_percentual_de_hoje(pagina):
    pg, base = pagina
    _abre(pg, base, com_hoje=True)
    dia, _ = _metas(pg)
    assert AGORA.strftime("%d/%m") in dia and "30%" in dia, dia


# ------------------------------------------------------------ os cartões

def _cartao(pg, raiz, rotulo):
    return pg.evaluate("""([raiz, rotulo]) => {
        const c = [...document.querySelectorAll('#' + raiz + ' .tv-card')]
          .find(x => x.querySelector('.tv-label').innerText.trim().toUpperCase()
                     === rotulo.toUpperCase());
        return c ? {nums: [...c.querySelectorAll('.tv-num')].map(n => n.innerText.trim()),
                    texto: c.innerText} : null; }""", [raiz, rotulo])


def _barras(pg, raiz, rotulo):
    """As larguras (%) das barras do cartão — a proporção que se lê de longe."""
    return pg.evaluate("""([raiz, rotulo]) => {
        const c = [...document.querySelectorAll('#' + raiz + ' .tv-card')]
          .find(x => x.querySelector('.tv-label').innerText.trim().toUpperCase()
                     === rotulo.toUpperCase());
        return c ? [...c.querySelectorAll('.tv-barra i')]
                     .map(i => Math.round(parseFloat(i.style.width))) : null; }""",
        [raiz, rotulo])


def test_tracao_separa_frota_de_agregado(pagina):
    pg, base = pagina
    _abre(pg, base)
    c = _cartao(pg, "tvope-k1", "Tração disponível")
    assert c and c["nums"] == ["72", "52"], c
    assert "de 80" in c["texto"] and "de 116" in c["texto"]
    # 72 de 80 = 90%; 52 de 116 = 45%
    assert _barras(pg, "tvope-k1", "Tração disponível") == [90, 45]


def test_motoristas_traz_o_percentual_de_proprios_livres(pagina):
    pg, base = pagina
    _abre(pg, base)
    c = _cartao(pg, "tvope-k1", "Motoristas")
    assert c and c["nums"] == ["67", "94%"], c
    assert _barras(pg, "tvope-k1", "Motoristas") == [94]


@pytest.mark.parametrize("pct, destaque", [
    (94.1, "destaque-ruim"),     # o dia do pedido: acima do p90 de dia útil
    (91.0, "destaque-warn"),     # entre 90 e 93
    (85.0, None),                # dentro do normal de dia útil (mediana 88)
])
def test_muitos_ociosos_acendem_o_cartao(pagina, pct, destaque):
    """Os cortes (90 amarelo, 93 vermelho) saíram da distribuição de 28 dias:
    o cartão inteiro ganha a borda, e o número a cor — e no normal, nada."""
    pg, base = pagina
    _abre(pg, base, prog={**PROG_KPIS, "pct_proprios_disp": pct})
    classe = pg.evaluate("""() => [...document.querySelectorAll('#tvope-k1 .tv-card')]
        .find(c => c.querySelector('.tv-label').innerText.trim().toUpperCase()
                   === 'MOTORISTAS').className""")
    if destaque:
        assert destaque in classe, classe
    else:
        assert "destaque" not in classe, classe


def test_as_reguas_de_conducao_pintam_numero_e_barra(pagina):
    pg, base = pagina
    _abre(pg, base)
    cls = pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#tvope-k2 .tv-card')]
        .map(c => [c.querySelector('.tv-label').innerText.trim().toUpperCase(),
                   c.querySelector('.tv-num').className]))""")
    assert "ruim" in cls["MOTOR LIGADO PARADO"]      # 14,3% > 10
    assert "ruim" in cls["PEDAL CRÍTICO"]            # 14,5% > 10
    assert "warn" in cls["FAIXA EXTRA ECONÔMICA"]    # 93,9% entre 90 e 95
    # as fronteiras, pela própria função da tela
    casos = pg.evaluate("""() => [
        [4.9, 5, 5.1, 10, 10.1].map(v => tvRegua(v, TV_REGUAS.pedal_critico).cls),
        [89.9, 90, 95, 95.1].map(v => tvRegua(v, TV_REGUAS.faixa_extra_eco).cls),
        tvRegua(null, TV_REGUAS.motor_parado).cls]""")
    assert casos[0] == ["ok", "ok", "warn", "warn", "ruim"], casos[0]
    assert casos[1] == ["ruim", "warn", "warn", "ok"], casos[1]
    assert casos[2] == "", "sem leitura não pode ganhar cor"
    # a barra desenha as faixas no trilho
    trilho = pg.evaluate("""() => [...document.querySelectorAll('#tvope-k2 .tv-card')]
        .find(c => c.innerText.toUpperCase().includes('PEDAL CRÍTICO'))
        .querySelector('.tv-barra').getAttribute('style') || ''""")
    assert "linear-gradient" in trilho, trilho


def test_carregado_e_vazio_numa_barra_so(pagina):
    pg, base = pagina
    _abre(pg, base)
    larg = pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .kmstack i')]
                               .map(i => Math.round(parseFloat(i.style.width)))""")
    # 91 mil de 454 mil = 20% de vazio
    assert larg == [80, 20], larg


def test_chegadas_uma_linha_por_carga_e_com_contador(pagina):
    pg, base = pagina
    _abre(pg, base)
    alturas = pg.evaluate("""() => [...document.querySelectorAll('#tvope-cheg tr')]
                                  .map(tr => tr.getBoundingClientRect().height)""")
    assert max(alturas) < 1.3 * min(alturas), "alguma linha quebrou: %r" % alturas
    cont = pg.evaluate("() => document.getElementById('tvope-cheg-n').innerText")
    assert cont.endswith("de %d" % len(TRANSITO)), cont
    assert int(cont.split()[0]) == len(alturas)


def test_o_mapa_nao_desenha_tracejado_da_atrasada(pagina):
    """Quem opera pediu para tirar: a reta até o destino cruzava o mapa sem
    dizer nada que a tabela não diga. O dublê tem uma atrasada NO MAPA e com
    o destino já geocodificado — sem a remoção, a linha seria desenhada."""
    pg, base = pagina
    _abre(pg, base)
    pg.wait_for_timeout(800)          # o geocoder é assíncrono
    assert pg.evaluate("() => tvLinhas.getLayers().length") == 0
    assert pg.evaluate("() => !!document.querySelector('#tvMapa .tv-vmk.alerta')"), (
        "a atrasada tem de continuar marcada no próprio veículo")
    leg = pg.evaluate("() => document.getElementById('tvope-legenda').innerText")
    assert "destino" not in leg.lower(), leg
    # e o mapa de fundo voltou às cores originais (sem o filtro de 1.73.0)
    filtros = pg.evaluate("""() => [...document.querySelectorAll('#tvMapa .leaflet-tile-pane > *')]
                                   .map(e => getComputedStyle(e).filter)""")
    assert filtros and all(f in ("none", "") for f in filtros), filtros


def test_o_contorno_vale_para_todo_cartao_em_alerta(pagina):
    """O contorno do cartão de motoristas estendido aos demais: número
    amarelo ou vermelho acende a borda na mesma cor; verde e neutro, não."""
    pg, base = pagina
    _abre(pg, base)
    cls = pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll(
        '#tvope-k1 .tv-card, #tvope-k2 .tv-card')].map(c => [
          c.querySelector('.tv-label').innerText.trim().toUpperCase(), c.className]))""")
    for rot in ("MOTOR LIGADO PARADO", "PEDAL CRÍTICO", "MOTORISTAS"):
        assert "destaque-ruim" in cls[rot], (rot, cls[rot])
    for rot in ("FAIXA EXTRA ECONÔMICA", "CHEGANDO 72H"):
        assert "destaque-warn" in cls[rot], (rot, cls[rot])
    for rot in ("EM TRÂNSITO", "CONSUMO DA FROTA", "VELOCIDADE MÉDIA", "SEM SINAL HÁ +6H"):
        assert "destaque" not in cls[rot], (rot, cls[rot])


def test_o_cartao_de_km_divide_a_altura_entre_os_blocos(pagina):
    """Três blocos (números, modalidades, medidores) e o respiro dividido
    entre eles — antes todo o vão ia para cima dos medidores."""
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => {
        const b = [...document.querySelectorAll('#tvope-km > *')].map(e => e.getBoundingClientRect());
        return {n: b.length, vaos: b.slice(1).map((x, i) => Math.round(x.top - b[i].bottom))}; }""")
    assert r["n"] == 3, r
    # os dois vãos entre blocos existem e são parecidos (space-between)
    assert min(r["vaos"]) > 8 and max(r["vaos"]) - min(r["vaos"]) <= 2, r


def test_sem_sinal_traz_o_denominador(pagina):
    pg, base = pagina
    _abre(pg, base)
    c = _cartao(pg, "tvope-k1", "Sem sinal há +6h")
    assert c and "de %d em viagem" % len(TRANSITO) in c["texto"], c
    assert "ocupação" not in c["texto"].lower()


def test_telemetria_troca_os_cartoes_confusos_pelos_de_conducao(pagina):
    pg, base = pagina
    _abre(pg, base)
    rotulos = pg.evaluate("""() => [...document.querySelectorAll('#tvope-k2 .tv-label')]
                                   .map(l => l.innerText.trim().toUpperCase())""")
    for novo in ("MOTOR LIGADO PARADO", "FAIXA EXTRA ECONÔMICA", "PEDAL CRÍTICO"):
        assert novo in rotulos, rotulos
    for velho in ("ABAIXO DO ALVO", "LEITURA DESCARTADA", "CARGA SEM VEÍCULO"):
        assert velho not in rotulos, rotulos
    assert _cartao(pg, "tvope-k2", "Motor ligado parado")["nums"] == ["14,3%"]
    # a barra vai na escala de 0 a 20% (a régua é 5/10): 14,3% = 72% do trilho
    assert _barras(pg, "tvope-k2", "Motor ligado parado") == [72]
    consumo = _cartao(pg, "tvope-k2", "Consumo da frota")["texto"]
    assert "41 veíc." in consumo
    # coleta de hoje não se anuncia; só a velha é dita
    assert "coleta" not in consumo.lower()


def test_subtitulos_curtos(pagina):
    """"Menos informação escrita, fácil de interpretar": nenhum subtítulo
    passa de uma linha curta. O teto sai do cartão mais estreito da parede."""
    pg, base = pagina
    _abre(pg, base)
    longos = pg.evaluate("""() => [...document.querySelectorAll(
        '#tvope-k1 .tv-sub, #tvope-k2 .tv-sub')].map(s => s.innerText.trim())
        .filter(t => t.length > 28)""")
    assert not longos, longos


def test_nenhum_cartao_estoura_a_propria_celula(pagina):
    """Os cartões de dois números e os subtítulos novos são mais altos: se não
    couberem, o `overflow` corta o fim sem erro nenhum."""
    pg, base = pagina
    _abre(pg, base)
    estouros = pg.evaluate("""() => [...document.querySelectorAll(
        '#tvope-k1 .tv-card, #tvope-k2 .tv-card')]
        .filter(c => c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1)
        .map(c => c.querySelector('.tv-label').innerText + ' ' + c.scrollHeight + '/' + c.clientHeight)""")
    assert not estouros, estouros


# ------------------------------------------------------------ o rodapé

def test_o_rodape_so_tem_o_que_e_de_hoje_e_pede_acao(pagina):
    """O dublê TEM cerca (7), "sem retorno" (5) e meta do mês (88%): com a
    regra antiga os três estariam no rodapé. E as chegadas vão de hoje até
    depois da meia-noite, então a de amanhã existe para ser recusada."""
    pg, base = pagina
    _abre(pg, base)
    rod = pg.evaluate("() => document.getElementById('tvope-ticker').textContent")
    for fora in ("cerca", "72h", "Meta do mês", "Mês:", "Estradas livres"):
        assert fora not in rod, (fora, rod[:200])
    # a crítica abre o rodapé, antes das atrasadas, e não se repete nelas
    assert "C030 carga crítica" in rod and rod.index("C030") < rod.index("B020"), rod[:200]
    # chegada: só as de HOJE (no máximo 6, das mais cedo), nunca a de amanhã
    hoje = AGORA.strftime("%Y-%m-%d")
    de_hoje = sorted((v for v in TRANSITO if not v["atrasada"] and not v["critica"]
                      and (v["previsao_chegada"] or "").startswith(hoje)),
                     key=lambda v: v["previsao_chegada"])
    outros = [v for v in TRANSITO if not v["atrasada"] and not v["critica"]
              and not (v["previsao_chegada"] or "").startswith(hoje)]
    for v in de_hoje[:6]:
        assert v["frota"] + " chega hoje" in rod, (v["frota"], rod[:300])
    for v in outros:
        assert v["frota"] + " chega" not in rod, (v["frota"], rod[:300])


# ------------------------------------------------------------ a marca


@pytest.mark.parametrize("tela", ["tvope", "tvfat", "tvdir", "tvcom", "tvcli", "tvjor"])
def test_a_logo_aparece_em_todo_painel_de_tv_sem_tela_cheia(pagina, tela):
    """A logo só acendia com `body.tvfull`; TV de parede em modo quiosque não
    passa por lá. O guard abre cada painel SEM tela cheia e mede a imagem
    renderizada — largura zero é logo escondida, mesmo com o <img> no HTML."""
    pg, base = pagina

    def rota(r):
        corpo = ADMIN if "/api/auth/me" in r.request.url else {}
        r.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
    pg.route("**/api/**", rota)
    pg.route("**/tile.openstreetmap.org/**", lambda r: r.abort())
    # tvChecaFull chama de "tela cheia" a janela do tamanho da TELA, e o
    # Chromium headless diz que a tela e do tamanho da janela -- o teste cairia
    # sempre no modo cheio e nao mediria nada. A tela declarada maior que a
    # janela e a TV em modo quiosque ou maximizada, que e o caso do defeito.
    pg.add_init_script("Object.defineProperty(screen,'width',{get:()=>3840});"
                       "Object.defineProperty(screen,'height',{get:()=>2160});")
    pg.set_viewport_size({"width": 1600, "height": 900})
    pg.goto(base + "/static/index.html#" + tela)
    pg.wait_for_timeout(1200)
    medida = pg.evaluate("""(tela) => {
        const img = document.querySelector('#view-' + tela + ' .tv-head .tv-logo');
        return img ? {largura: img.getBoundingClientRect().width,
                      cheia: document.body.classList.contains('tvfull')} : null; }""", tela)
    assert medida is not None, "o painel %s não tem a logo no cabeçalho" % tela
    assert not medida["cheia"], "o teste caiu em tela cheia e não mede o caso real"
    assert medida["largura"] > 0, "a logo está escondida no painel %s" % tela


# ------------------------------------------------------------ o mapa

def test_o_mapa_agrupa_no_maximo_cinco_e_nunca_o_alerta(pagina):
    pg, base = pagina
    _abre(pg, base)
    grupos = pg.evaluate("""() => tvLayer.getLayers().map(l => l.options.veiculos || 1)""")
    assert sum(grupos) == len(POSICOES), "o mapa perdeu veículo: %r" % grupos
    assert max(grupos) == 5, "seis no mesmo ponto têm de virar 5 + 1: %r" % grupos
    # o alerta (95 km/h) continua sozinho, com a borda de alerta
    assert pg.evaluate("() => !!document.querySelector('#tvMapa .tv-vmk.alerta')")


def test_a_legenda_explica_cor_e_tracao(pagina):
    pg, base = pagina
    _abre(pg, base)
    leg = pg.evaluate("() => document.getElementById('tvope-legenda').innerText")
    for termo in ("Frota e locação", "Agregado", "Terceiro", "90 km/h", "até 5"):
        assert termo in leg, (termo, leg)
    assert "4x2 2" in leg and "6x2 7" in leg and "truck 1" in leg, leg
    # locação pinta igual à frota
    cores = pg.evaluate("""() => [...document.querySelectorAll('#tvope-legenda i')]
                                  .map(i => i.style.background)""")
    assert "Locação" not in leg
    assert len(set(cores[:3])) == 3


def test_o_tour_nasce_de_onde_a_frota_esta(pagina):
    pg, base = pagina
    _abre(pg, base)
    vistas = pg.evaluate("() => TV_VISTAS.map(v => v.nome)")
    assert vistas[0].startswith("Visão geral · %d veículos" % len(POSICOES)), vistas
    # 6 veículos na Grande São Paulo: o polo entra, com a contagem
    assert any(v.startswith("Grande São Paulo · 6") for v in vistas), vistas
    # polo com menos de 3 não gasta 20 s de parede
    assert not any(v.startswith("Joinville") for v in vistas), vistas


def test_o_zoom_do_polo_enquadra_os_veiculos_dele(pagina):
    """O polo abria num centro fixo com zoom 9: concentrado virava pilha de
    círculos, espalhado ficava cortado. Agora a vista é a CAIXA dos veículos
    do polo, com teto de zoom — e o zoom anda em quartos de nível."""
    pg, base = pagina
    _abre(pg, base)
    polo = pg.evaluate("""() => TV_VISTAS.find(v => v.nome.startsWith('Grande São Paulo'))""")
    assert polo and polo.get("caixa") and polo.get("maxZoom") == 12, polo
    assert "z" not in polo, "o polo voltou a ter zoom fixo: %r" % polo
    # os 6 veículos do polo estão no mesmo ponto: a caixa é o próprio ponto
    (la1, lo1), (la2, lo2) = polo["caixa"]
    assert abs(la1 - la2) < 0.01 and abs(lo1 - lo2) < 0.01, polo["caixa"]
    assert pg.evaluate("() => tvMap.options.zoomSnap") == 0.25
