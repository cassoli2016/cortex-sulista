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
7. o quadrante da telemetria virou MANUTENÇÃO DA FROTA (15/09/2026):
   revisões, parados e oficina longa, cavalo e semirreboque lado a lado;
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


# 6 PARADOS NO MESMO PONTO: um circulo so, de 6 -- o teto de 5 da primeira
# versao os empilhava em "5" + "1" no mesmo lugar. E 2 EM VIAGEM no mesmo
# ponto (as placas das duas primeiras viagens): viram o SEU circulo, sem se
# misturar com os parados.
MESMO_PONTO = [_pos(100 + i, "AGREGADOS", "6x2", -23.55, -46.63) for i in range(6)]
EM_VIAGEM_JUNTOS = [{**_pos(200 + i, "AGREGADOS", "6x2", -23.55, -46.63, vel=60),
                     "placa": "AAA%dA%02d" % (i, i)} for i in range(2)]
POSICOES = MESMO_PONTO + EM_VIAGEM_JUNTOS + [
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


# O QUADRANTE DE MANUTENÇÃO, na ordem de grandeza do dia real (15/09/2026):
# 66 cavalos e 175 semirreboques na preventiva, 80 e 228 na frota.
MANUT = {"revisoes": {"cavalos": {"vencidas": 1, "a_vencer": 3, "avaliados": 66},
                      "semirreboques": {"vencidas": 2, "a_vencer": 12, "avaliados": 175},
                      "horizonte_dias": 30,
                      "vencidas": [{"frota": "C901", "km": 1557},
                                   {"frota": "S902", "dias": 15},
                                   {"frota": "S903", "dias": 1}]},
         "oficina": {"cavalos": {"frota": 80, "parados": 6, "longa": 3},
                     "semirreboques": {"frota": 228, "parados": 15, "longa": 6},
                     "longa_dias": 7},
         "mes": {"preventivas": 26, "corretivas": 62, "socorro": 15,
                 "socorro_ant": 12, "dia": 15, "mes_ant": "2026-08"}}


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


def _abre(pg, base, *, com_hoje=False, prog=None, posicoes=None, estradas=None,
          manut=MANUT):
    """`manut=None` faz a rota da manutenção FALHAR (500)."""
    pedidos = []

    def rota(r):
        url = r.request.url
        pedidos.append(url)
        if "/api/auth/me" in url:
            corpo = ADMIN
        elif "/api/operacao/manutencao" in url:
            if manut is None:
                r.fulfill(status=500, content_type="application/json",
                          body=json.dumps({"erro": "erro_consulta"}))
                return
            corpo = manut
        elif "/api/operacao/torre/estradas" in url:
            corpo = {}
        elif "/api/tv/estradas" in url:
            corpo = estradas or {}
        elif "/api/operacao/torre" in url:
            corpo = {"kpis": {"em_transito": len(TRANSITO), "atrasadas": 2, "criticas": 2,
                              "saidas_hoje": 3, "chegadas_previstas_hoje": 1},
                     "posicoes": posicoes or POSICOES, "transito": TRANSITO,
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
    pg.route("**/api.tomtom.com/**", lambda r: r.abort())   # o trânsito, quando ligado
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


def _animacao_dos_selos(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#tvope-cheg .tv-badge')]
        .map(b => ({crit: b.classList.contains('crit'),
                    nome: getComputedStyle(b).animationName,
                    vezes: getComputedStyle(b).animationIterationCount}))""")


def test_o_selo_da_carga_critica_pisca_e_os_outros_nao(pagina):
    """Pedido de quem opera (15/09/2026): o selo CRÍTICA "precisa apenas
    piscar". Lido no que o NAVEGADOR aplica, não no texto do CSS — regra que
    existe e perde a briga de especificidade não pisca nada."""
    pg, base = pagina
    _abre(pg, base)
    pg.emulate_media(reduced_motion="no-preference")
    selos = _animacao_dos_selos(pg)
    crit = [s for s in selos if s["crit"]]
    assert len(crit) == 2, selos        # as duas críticas do dublê
    assert all(s["nome"] == "tvCritPisca" and s["vezes"] == "infinite" for s in crit), crit
    outros = [s for s in selos if not s["crit"]]
    assert outros and all(s["nome"] == "none" for s in outros), (
        "selo de trânsito piscando dilui o da carga crítica: %r" % outros)


def test_com_reduzir_movimento_o_selo_critico_fica_aceso_e_parado(pagina):
    """A preferência do sistema vale também na parede: a regra global da casa
    congela a animação (uma volta instantânea) e o selo fica ACESO, com a
    opacidade cheia — não some nem fica a meio caminho."""
    pg, base = pagina
    _abre(pg, base)                    # _abre já emula reduced-motion
    crit = [s for s in _animacao_dos_selos(pg) if s["crit"]]
    assert crit and all(s["vezes"] == "1" for s in crit), crit
    opac = pg.evaluate("() => getComputedStyle(document.querySelector("
                       "'#tvope-cheg .tv-badge.crit')).opacity")
    assert opac == "1", opac


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
    # o número grande é o % DISPONÍVEL; a contagem vai no subtítulo
    assert c and c["nums"] == ["90%", "45%"], c
    assert "72 de 80" in c["texto"] and "52 de 116" in c["texto"], c["texto"]
    assert _barras(pg, "tvope-k1", "Tração disponível") == [90, 45]


@pytest.mark.parametrize("disp, esperado", [
    (72, "ruim"),     # 90% da frota parada: o dia do pedido
    (40, "ruim"),     # 50%: o corte do vermelho
    (32, "warn"),     # 40%
    (24, "warn"),     # 30%: o corte do amarelo
    (16, "ok"),       # 20%: a frota rodando
])
def test_frota_parada_acende_o_cartao(pagina, disp, esperado):
    """Quanto MAIS frota disponível (parada), pior: a regra antiga acendia só
    a FALTA de tração. O agregado mostra o % sem cor."""
    pg, base = pagina
    _abre(pg, base, prog={**PROG_KPIS, "tracao_disp": disp})
    cls = pg.evaluate("""() => {
        const c = [...document.querySelectorAll('#tvope-k1 .tv-card')]
          .find(x => x.querySelector('.tv-label').innerText.trim().toUpperCase() === 'TRAÇÃO DISPONÍVEL');
        return [...c.querySelectorAll('.tv-num')].map(n => n.className); }""")
    assert esperado in cls[0], cls
    assert not any(k in cls[1] for k in ("ok", "warn", "ruim")), "o agregado ganhou cor: %r" % cls


def test_motoristas_traz_o_percentual_de_proprios_livres(pagina):
    pg, base = pagina
    _abre(pg, base)
    # só a frota (14/09/2026): 4 em viagem, e não os 67 que somavam o agregado
    c = _cartao(pg, "tvope-k1", "Motoristas da frota")
    assert c and c["nums"] == ["4", "94%"], c
    assert _barras(pg, "tvope-k1", "Motoristas da frota") == [94]


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
                   === 'MOTORISTAS DA FROTA').className""")
    if destaque:
        assert destaque in classe, classe
    else:
        # no normal, nenhuma borda de ALERTA -- só a branca de número sem cor
        assert "destaque-warn" not in classe and "destaque-ruim" not in classe, classe
        assert "destaque-neutro" in classe, classe


def test_o_cartao_de_motoristas_e_so_da_frota(pagina):
    """Quem opera, 14/09/2026: "o card de motoristas precisa ser somente
    motorista frota". O dublê tem 67 em viagem no total -- 4 da frota e 63
    agregados --: o cartão mostra 4, e o % de ociosos vem com a conta."""
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => { const c = [...document.querySelectorAll('#tvope-k1 .tv-card')]
        .find(c => c.querySelector('.tv-label').innerText.trim().toUpperCase().startsWith('MOTORISTAS'));
        return {rot: c.querySelector('.tv-label').innerText.trim().toUpperCase(),
                nums: [...c.querySelectorAll('.tv-num')].map(n => n.innerText.trim()),
                txt: c.innerText}; }""")
    assert r["rot"] == "MOTORISTAS DA FROTA", r
    assert r["nums"][:2] == ["4", "94%"], r
    assert "67" not in r["txt"] and "63" not in r["txt"], "agregado no cartão da frota: %r" % r
    assert "64 de 68" in r["txt"], r


def test_o_quadrante_de_manutencao_substitui_a_telemetria(pagina):
    """Quem opera, 15/09/2026: "no quadrante onde tem a telemetria vamos
    mudar para indicadores de manutenção, revisões vencidas, a vencer, tanto
    de cavalo quanto de semirreboque, veículos parados em manutenção". Cada
    cartão leva cavalo e semirreboque lado a lado, com o seu denominador."""
    pg, base = pagina
    _abre(pg, base)
    rotulos = pg.evaluate("""() => [...document.querySelectorAll('#tvope-k2 .tv-label')]
                                   .map(l => l.innerText.trim().toUpperCase())""")
    assert rotulos == ["REVISÕES VENCIDAS", "REVISÕES A VENCER", "PARADOS EM MANUTENÇÃO",
                       "NA OFICINA HÁ +7 DIAS", "PREVENTIVAS NO MÊS",
                       "QUEBRA EM ROTA NO MÊS"], rotulos
    c = _cartao(pg, "tvope-k2", "Revisões vencidas")
    assert c["nums"] == ["1", "2"] and "de 66" in c["texto"] and "de 175" in c["texto"], c
    assert _cartao(pg, "tvope-k2", "Revisões a vencer")["nums"] == ["3", "12"]
    # parados: a barra é a fração da FROTA (6 de 80, 15 de 228)
    assert _cartao(pg, "tvope-k2", "Parados em manutenção")["nums"] == ["6", "15"]
    assert _barras(pg, "tvope-k2", "Parados em manutenção") == [8, 7]
    assert _cartao(pg, "tvope-k2", "Na oficina há +7 dias")["nums"] == ["3", "6"]
    # preventiva sobre preventiva + corretiva: 26 de 88 = 30%
    p = _cartao(pg, "tvope-k2", "Preventivas no mês")
    assert p["nums"] == ["30%"] and "26 de 88" in p["texto"], p
    # quebra em rota contra o mês anterior ATÉ O MESMO DIA
    q = _cartao(pg, "tvope-k2", "Quebra em rota no mês")
    assert q["nums"] == ["15"] and "ago até dia 15: 12" in q["texto"], q
    # cor só onde há régua: vencida vermelha, oficina longa amarela, o resto sem cor
    cls = pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#tvope-k2 .tv-card')]
        .map(c => [c.querySelector('.tv-label').innerText.trim().toUpperCase(),
                   [...c.querySelectorAll('.tv-num')].map(n => n.className.replace('tv-num', '').trim())]))""")
    assert cls["REVISÕES VENCIDAS"] == ["ruim", "ruim"], cls
    assert cls["NA OFICINA HÁ +7 DIAS"] == ["warn", "warn"], cls
    for neutro in ("REVISÕES A VENCER", "PARADOS EM MANUTENÇÃO", "PREVENTIVAS NO MÊS",
                   "QUEBRA EM ROTA NO MÊS"):
        assert all(x == "" for x in cls[neutro]), (neutro, cls[neutro])


def test_revisao_vencida_vai_para_o_rodape_com_o_quanto_passou(pagina):
    pg, base = pagina
    _abre(pg, base)
    rod = pg.evaluate("() => document.getElementById('tvope-ticker').textContent")
    assert "C901 revisão vencida — 1.557 km" in rod, rod[:400]
    assert "S902 revisão vencida — 15 dias" in rod, rod[:400]
    assert "S903 revisão vencida — 1 dia" in rod and "1 dias" not in rod, rod[:400]


def test_sem_leitura_de_manutencao_so_o_quadrante_diz(pagina):
    """A rota da manutenção falhar não derruba a parede: o quadrante diz que
    não leu, e o resto segue com os números dele."""
    pg, base = pagina
    _abre(pg, base, manut=None)
    k2 = pg.evaluate("() => document.getElementById('tvope-k2').innerText")
    assert "sem leitura" in k2.lower(), k2
    assert _cartao(pg, "tvope-k1", "Em trânsito")["nums"] == [str(len(TRANSITO))]


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


def test_todo_cartao_tem_borda_na_cor_do_numero(pagina):
    """Borda em todos os cartões, pela cor do PIOR número: vermelha, amarela,
    verde; o número neutro fica com a borda discreta — mas fica com borda."""
    pg, base = pagina
    _abre(pg, base)
    info = pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll(
        '#tvope-k1 .tv-card, #tvope-k2 .tv-card')].map(c => [
          c.querySelector('.tv-label').innerText.trim().toUpperCase(),
          {cls: c.className, sombra: getComputedStyle(c).boxShadow}]))""")
    for rot in ("REVISÕES VENCIDAS", "MOTORISTAS DA FROTA", "TRAÇÃO DISPONÍVEL"):
        assert "destaque-ruim" in info[rot]["cls"], (rot, info[rot])
    for rot in ("NA OFICINA HÁ +7 DIAS", "CHEGANDO 72H"):
        assert "destaque-warn" in info[rot]["cls"], (rot, info[rot])
    for rot in ("SEM SINAL HÁ +6H",):
        assert "destaque-ok" in info[rot]["cls"], (rot, info[rot])
    # número branco: borda BRANCA (e não a discreta azul-acinzentada)
    for rot in ("EM TRÂNSITO", "SAÍRAM HOJE", "PREVENTIVAS NO MÊS", "QUEBRA EM ROTA NO MÊS"):
        assert "destaque-neutro" in info[rot]["cls"], (rot, info[rot])
        assert "229, 237, 244" in info[rot]["sombra"], (rot, info[rot]["sombra"])
    # e TODOS têm borda de verdade no navegador (a regra pode existir e perder)
    sem = [r for r, v in info.items() if v["sombra"] in ("none", "")]
    assert not sem, sem
    # as bordas de estado não são a mesma cor da branca
    assert info["SEM SINAL HÁ +6H"]["sombra"] != info["EM TRÂNSITO"]["sombra"]


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


# ------------------------------------------------------------ o celular

@pytest.mark.parametrize("modo", ["navegador", "aplicativo"])
def test_no_celular_nada_se_espreme_nem_rola_para_o_lado(pagina, modo):
    """No modo aplicativo o celular conta como tela cheia, e as regras de
    parede cabiam o painel inteiro em 844 px (número cortado, 3 chegadas,
    medidor de 40 px). Os dois modos: "navegador" declara uma tela maior que a
    janela (a barra de endereço), "aplicativo" não."""
    pg, base = pagina
    if modo == "navegador":
        pg.add_init_script("Object.defineProperty(screen,'height',{get:()=>1000});")
    _abre(pg, base)
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.reload()
    pg.wait_for_function("() => document.querySelectorAll('#tvope-cheg tr').length > 1")
    pg.wait_for_timeout(2000)
    m = pg.evaluate("""() => {
        const r = s => document.querySelector(s).getBoundingClientRect();
        const cortados = [...document.querySelectorAll('#tvope-k1 .tv-card, #tvope-k2 .tv-card')]
          .filter(c => c.scrollHeight > c.clientHeight + 1)
          .map(c => c.querySelector('.tv-label').innerText);
        return {larg: document.documentElement.scrollWidth,
                cheia: document.body.classList.contains('tvfull'),
                cortados, mapa: r('#tvMapa'), leg: r('#tvope-legenda'),
                titulo: r('#view-tvope .tv-head h2').height,
                arco: r('#tvope-km .tvw-arco').width,
                linhas: document.querySelectorAll('#tvope-cheg tr').length,
                // horario da chegada inteiro ("14/09 06:00"), sem reticencias
                hora_cortada: [...document.querySelectorAll('#tvope-cheg tr td:nth-child(3)')]
                  .some(td => td.scrollWidth > td.clientWidth + 1),
                // cartao de meia largura sozinho na linha (buraco na grade)
                orfaos: [...document.querySelectorAll('#tvope-k1, #tvope-k2')].map(g => {
                  const cs = [...g.children].map(c => c.getBoundingClientRect());
                  const meia = cs.filter(c => c.width < g.clientWidth * 0.75);
                  return meia.filter(c => !meia.some(o => o !== c && Math.abs(o.top - c.top) < 2)).length;
                })}; }""")
    assert m["cheia"] == (modo == "aplicativo"), m
    assert m["larg"] <= 390, "a página rola para o lado: %r" % m
    assert not m["cortados"], m["cortados"]
    assert m["mapa"]["height"] >= 300, m["mapa"]
    assert m["leg"]["top"] >= m["mapa"]["bottom"] - 1, "a legenda cobre o mapa: %r" % m
    assert m["titulo"] < 30, "o título quebrou em mais de uma linha: %r" % m["titulo"]
    assert m["arco"] >= 100, "o medidor de meta ficou minúsculo: %r" % m["arco"]
    assert m["linhas"] == len(TRANSITO), "a lista de chegadas foi cortada: %r" % m["linhas"]
    assert not m["hora_cortada"], "o horário da chegada saiu com reticências"
    assert m["orfaos"] == [0, 0], "cartão sozinho na linha: %r" % m["orfaos"]


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


@pytest.mark.parametrize("tela", ["tvope", "tvfat", "tvdir", "tvcom", "tvcli", "tvjor", "tvprod", "tvcco"])
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

def _camadas(pg):
    return pg.evaluate("""() => tvLayer.getLayers().map(l => {
        const p = tvMap.latLngToLayerPoint(l.getLatLng());
        const h = (l.options.icon && l.options.icon.options.html) || '';
        return {n: l.options.veiculos || 1, x: p.x, y: p.y,
                tipo: h.includes('tv-vgrp viagem') ? 'viagem'
                    : (h.includes('tv-vgrp parado') ? 'parado' : 'avulso')}; })""")


def test_o_mapa_agrupa_por_lugar_sem_empilhar_e_separa_viagem_de_parado(pagina):
    pg, base = pagina
    _abre(pg, base)
    # zoom de polo, fixo: a conta de pixels do teste não depende da visão geral
    pg.evaluate("() => tvMap.setView([-23.55, -46.63], 9, {animate: false})")
    pg.wait_for_timeout(600)
    cam = _camadas(pg)
    assert sum(c["n"] for c in cam) == len(POSICOES), "o mapa perdeu veículo: %r" % cam
    grupos = [c for c in cam if c["tipo"] != "avulso"]
    assert {(c["tipo"], c["n"]) for c in grupos} == {("parado", 6), ("viagem", 2)}, grupos
    # nada da mesma camada sobreposto: a caixa do rótulo (60 x 22 px) de um
    # não pode encostar na do outro -- o que encostaria vira grupo
    w, h = pg.evaluate("() => [TV_GRUPO_W, TV_GRUPO_H]")
    for i, a in enumerate(cam):
        for b in cam[i + 1:]:
            if a["tipo"] == b["tipo"] and a["tipo"] != "avulso":
                assert max(abs(a["x"] - b["x"]) / w, abs(a["y"] - b["y"]) / h) > 1, (a, b)
    # o alerta (95 km/h) continua sozinho, com a borda de alerta
    assert pg.evaluate("() => !!document.querySelector('#tvMapa .tv-vmk.alerta')")
    # e o parado sozinho sai apagado
    assert pg.evaluate("() => !!document.querySelector('#tvMapa .tv-vmk.parado')")


def test_a_legenda_explica_cor_e_tracao(pagina):
    pg, base = pagina
    _abre(pg, base)
    leg = pg.evaluate("() => document.getElementById('tvope-legenda').innerText")
    for termo in ("Frota e locação", "Agregado", "Terceiro", "90 km/h",
                  "Parado (cor apagada)", "Em viagem", "Parados"):
        assert termo in leg, (termo, leg)
    assert "4x2 2" in leg and "6x2 9" in leg and "truck 1" in leg, leg
    # locação pinta igual à frota
    cores = pg.evaluate("""() => [...document.querySelectorAll('#tvope-legenda i')]
                                  .map(i => i.style.background)""")
    assert "Locação" not in leg
    assert len(set(cores[:3])) == 3


# O MAPA CHEIO DE 14/09/2026, copiado da tela de quem opera: 190 veículos com
# cinco trações (65 · 96 · 1 · 1 · 27), um sem cadastro e o trânsito ligado.
# Com o dublê magro a legenda de quatro colunas passou; com este, a coluna da
# tração era espremida, o título saía cortado e cada tipo caía numa linha.
MAPA_CHEIO = []
for _tr, _q in (("4x2", 65), ("6x2", 96), ("3/4", 1), ("toco", 1), ("truck", 27)):
    for _ in range(_q):
        _n = len(MAPA_CHEIO)
        MAPA_CHEIO.append(_pos(1000 + _n, (None, "FROTA", "AGREGADOS", "TERCEIROS", "LOCACAO")[_n % 5],
                               _tr, -20 - (_n % 40) * 0.2, -44 - (_n // 40) * 0.8))
TRANSITO_LIGADO = {"configurado": True, "key": "chave-de-teste"}


def _legenda(pg):
    return pg.evaluate("""() => {
        const leg = document.getElementById('tvope-legenda');
        const gs = [...leg.querySelectorAll(':scope > .lg')];
        const L = leg.getBoundingClientRect(), M = document.getElementById('tvMapa').getBoundingClientRect();
        return {tit: gs.map(g => g.querySelector('em').innerText.trim().toUpperCase()),
                topos: gs.map(g => Math.round(g.getBoundingClientRect().top)),
                vaza: [...leg.querySelectorAll('.lg-i, .lg-tr span, .lg > em')]
                  .filter(e => e.getBoundingClientRect().right > L.right + 1).length,
                espremido: gs.filter(g => g.scrollWidth > g.clientWidth + 1)
                  .map(g => g.querySelector('em').innerText),
                larguras: gs.map(g => Math.round(g.getBoundingClientRect().width)),
                caixa: Math.round(L.width), texto: leg.innerText,
                alt: L.height, mapa: M.height,
                dentro: L.left >= M.left - 1 && L.right <= M.right + 1 && L.bottom <= M.bottom + 1};
    }""")


def test_a_legenda_cabe_com_o_mapa_cheio_e_o_transito_ligado(pagina):
    """O caso REAL (tela de quem opera, 14/09/2026): trânsito ligado e cinco
    trações com contagem de dois dígitos. Nenhum grupo espremido, nada
    cortado, os quatro lado a lado."""
    pg, base = pagina
    _abre(pg, base, posicoes=MAPA_CHEIO, estradas=TRANSITO_LIGADO)
    r = _legenda(pg)
    assert "Trânsito" in r["texto"] and "Sem cadastro" in r["texto"], r["texto"]
    assert "truck 27" in r["texto"] and "6x2 96" in r["texto"], r["texto"]
    assert r["tit"] == ["VEÍCULO", "SITUAÇÃO", "NO MESMO PONTO", "TRAÇÃO NO MAPA"], r
    assert not r["espremido"] and r["vaza"] == 0 and r["dentro"], r
    assert len(set(r["topos"])) == 1, "os grupos têm de ficar lado a lado: %r" % r
    assert r["alt"] <= 0.25 * r["mapa"], r


def test_a_legenda_se_organiza_em_grupos_com_titulo(pagina):
    """Quem opera, 14/09/2026: "organize melhor a legenda". Era uma linha
    corrida misturando cor, alerta, número do círculo e tração; agora cada
    pergunta é uma coluna com título, lado a lado, inteira dentro do mapa e
    cobrindo no máximo um quarto dele."""
    pg, base = pagina
    _abre(pg, base)
    r = pg.evaluate("""() => {
        const leg = document.getElementById('tvope-legenda');
        const gs = [...leg.querySelectorAll(':scope > .lg')];
        const L = leg.getBoundingClientRect(), M = document.getElementById('tvMapa').getBoundingClientRect();
        return {tit: gs.map(g => g.querySelector('em').innerText.trim().toUpperCase()),
                topos: gs.map(g => Math.round(g.getBoundingClientRect().top)),
                vaza: [...leg.querySelectorAll('.lg-i, .lg-tr span, .lg > em')]
                  .filter(e => e.getBoundingClientRect().right > L.right + 1).length,
                alt: L.height, mapa: M.height,
                dentro: L.left >= M.left - 1 && L.right <= M.right + 1 && L.bottom <= M.bottom + 1};
    }""")
    assert r["tit"] == ["VEÍCULO", "SITUAÇÃO", "NO MESMO PONTO", "TRAÇÃO NO MAPA"], r
    assert len(set(r["topos"])) == 1, "os grupos têm de ficar lado a lado: %r" % r
    assert r["vaza"] == 0 and r["dentro"], r
    assert r["alt"] <= 0.25 * r["mapa"], r
    # no celular a legenda desce para baixo do mapa em duas colunas, e os
    # pares da tração não colam (o espaçamento em vw virava 3 px)
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(500)
    folgas = pg.evaluate("""() => {
        const cs = [...document.querySelectorAll('#tvope-legenda .lg-tr span')].map(e => e.getBoundingClientRect());
        const f = [];
        for (let i = 1; i < cs.length; i++) if (Math.abs(cs[i].top - cs[i-1].top) < 2) f.push(cs[i].left - cs[i-1].right);
        return f; }""")
    assert folgas and min(folgas) >= 8, folgas


def test_o_tour_nasce_de_onde_a_frota_esta(pagina):
    pg, base = pagina
    _abre(pg, base)
    vistas = pg.evaluate("() => TV_VISTAS.map(v => v.nome)")
    assert vistas[0].startswith("Visão geral · %d veículos" % len(POSICOES)), vistas
    # 8 veículos na Grande São Paulo (6 parados + 2 em viagem): o polo entra
    assert any(v.startswith("Grande São Paulo · 8") for v in vistas), vistas
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
    # os 8 veículos do polo estão no mesmo ponto: a caixa é o próprio ponto
    (la1, lo1), (la2, lo2) = polo["caixa"]
    assert abs(la1 - la2) < 0.01 and abs(lo1 - lo2) < 0.01, polo["caixa"]
    assert pg.evaluate("() => tvMap.options.zoomSnap") == 0.25
