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
8. mapa com legenda, tração no marcador e grupos de no máximo 5;
9. cartões e mapa INTERATIVOS (16/09/2026): cada cartão abre o detalhe do
   próprio número, e o caminhão e o grupo do mapa abrem a ficha — sempre da
   MESMA lista que fez o número, sem uma segunda consulta.
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
             "com_retorno": 25,
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
def _rev_cav(i, status):
    return {"frota": f"C9{i:02d}", "placa": f"CAV{i:04d}", "status": status,
            "km_faltante": -557 - i if status == "vencida" else 2000 + i,
            "intervalo": 50000, "odometro": 300000 + i}


def _rev_sem(i, status):
    return {"frota": f"S9{i:02d}", "placa": f"SEM{i:04d}", "status": status,
            "dias": -15 - i if status == "vencida" else 3 + i,
            "ultima": "2026-03-01", "limite": 180}


def _os(i, motor, dias):
    return {"placa": (f"CAV{i:04d}" if motor else f"SEM{i:04d}"), "utilizacao": "FROTA",
            "os_abertas": 1 + i % 2, "desde": "2026-09-0%d" % (1 + i % 9),
            "dias": dias, "longa": dias > 7}


MANUT = {"revisoes": {"cavalos": {"vencidas": 1, "a_vencer": 3, "avaliados": 66,
                                  "lista": [_rev_cav(0, "vencida")]
                                           + [_rev_cav(i, "proxima") for i in range(1, 4)]},
                      "semirreboques": {"vencidas": 2, "a_vencer": 12, "avaliados": 175,
                                        "lista": [_rev_sem(i, "vencida") for i in range(2)]
                                                 + [_rev_sem(i, "proxima") for i in range(2, 14)]},
                      "horizonte_dias": 30,
                      "vencidas": [{"frota": "C901", "km": 1557},
                                   {"frota": "S902", "dias": 15},
                                   {"frota": "S903", "dias": 1}]},
         "oficina": {"cavalos": {"frota": 80, "parados": 6, "longa": 3,
                                 "lista": [_os(i, True, 30 - 5 * i) for i in range(6)]},
                     "semirreboques": {"frota": 228, "parados": 15, "longa": 6,
                                       "lista": [_os(i, False, 20 - i) for i in range(15)]},
                     "longa_dias": 7},
         # 103 OS no mês: a lista é a mesma de onde saem as contagens
         "mes": {"preventivas": 26, "corretivas": 62, "socorro": 15,
                 "socorro_ant": 12, "dia": 15, "mes_ant": "2026-08",
                 "lista": [{"numero": 9000 + i, "filial": 1, "placa": f"CAV{i:04d}",
                            "utilizacao": "FROTA", "objetivo": obj,
                            "emissao": "2026-09-0%d 08:00" % (1 + i % 9),
                            "fechamento": None if i % 3 else "2026-09-10",
                            "com_motor": True}
                           for obj, qt in ((14, 26), (15, 62), (16, 15))
                           for i in range(qt)]}}

# AS LISTAS DA PROGRAMAÇÃO, com o CORTE do servidor: 20 ociosos de 72 e 20
# motoristas parados de 157 — é o que faz o contador do modal ter de dizer
# "de quantos", em vez de deixar 20 passar por total.
OCIOSOS = [{"placa": f"FRT{i:04d}", "utilizacao": "FROTA", "com_motor": i % 3 != 0,
            "ult_saida": "2026-09-01", "dias_parado": 30 - i} for i in range(20)]
MOT_PARADOS = [{"motorista": f"MOTORISTA PARADO {i}", "dias_parado": 20 - i,
                "ult_saida": "2026-08-26", "em_viagem": False, "venc_cnh": "2027-05-01",
                "cnh_vencida": False, "fonte_cnh": "cadastro"} for i in range(20)]
CNH_ALERTAS = [{"motorista": f"MOTORISTA CNH {i}", "dias_parado": i, "ult_saida": "2026-09-01",
                "em_viagem": i == 0, "venc_cnh": "2026-08-01", "cnh_vencida": True,
                "fonte_cnh": "cadastro"} for i in range(2)]
CHEGADAS = [{"placa": f"CHG{i:04d}", "utilizacao": "AGREGADOS", "cidade": f"CIDADE {i}",
             "uf": "SP", "eta": _fmt(AGORA + timedelta(hours=i + 1)), "n_cargas": 1 + i % 3}
            for i in range(25)]
# A LISTA DA FROTA, sem corte: 68 motoristas da casa, 4 em viagem e 2 com a
# CNH vencida — os mesmos números dos KPIs do cartão.
MOT_FROTA = ([{"motorista": f"MOTORISTA FROTA {i}", "dias_parado": None,
               "ult_saida": "2026-09-15", "em_viagem": True, "venc_cnh": "2027-05-01",
               "cnh_vencida": False, "fonte_cnh": "globus"} for i in range(4)]
             + [{"motorista": f"MOTORISTA FROTA {4 + i}", "dias_parado": 40 - i,
                 "ult_saida": "2026-08-26", "em_viagem": False,
                 "venc_cnh": "2026-08-01" if i < 2 else "2027-05-01",
                 "cnh_vencida": i < 2, "fonte_cnh": "cadastro"} for i in range(64)])
PROG_LISTAS = {"ociosos": OCIOSOS, "motoristas_parados": MOT_PARADOS,
               "motoristas_frota": MOT_FROTA,
               "cnh_alertas": CNH_ALERTAS, "casamentos": CHEGADAS,
               "sem_retorno": CHEGADAS[:5]}


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
            corpo = {"kpis": prog or PROG_KPIS, **PROG_LISTAS}
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
    # e os DOIS rótulos dizem a sua fatia (16/09/2026): só o vazio dizia
    labs = pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .klab')]
                                .map(l => l.innerText.trim().toUpperCase())""")
    assert labs[:3] == ["CARREGADO · 80%", "VAZIO · 20%", "TOTAL"], labs


def test_cada_modalidade_diz_e_PREENCHE_a_sua_fatia(pagina):
    """Quem opera, 16/09/2026: "coloque o % que cada uma representa e preencha
    elas com o % que corresponde". A barra era relativa à MAIOR modalidade — a
    primeira saía sempre cheia, e cheia se lê de longe como "tudo"."""
    pg, base = pagina
    _abre(pg, base)
    linhas = pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .mod')].map(m => ({
        rot: m.querySelector('b').innerText.trim(),
        larg: Math.round(parseFloat(m.querySelector('.trk i').style.width)),
        pct: m.querySelector('.kpct').innerText.trim(),
        km: m.querySelector('span').innerText.trim()}))""")
    # do km do mês (454 mil): agregado 365, frota 49+27, terceiro 12
    assert [(l["rot"], l["larg"], l["pct"], l["km"]) for l in linhas] == [
        ("Agregado", 80, "80%", "365 mil km"),
        ("Frota", 17, "17%", "76 mil km"),
        ("Terceiro", 3, "3%", "12 mil km")], linhas
    # a barra é o mesmo número que está escrito: o comprimento segue o %
    assert all(abs(l["larg"] - int(l["pct"].rstrip("%"))) <= 1 for l in linhas), linhas
    # a coluna do % não pode nascer com a largura da coluna de km (a regra de
    # cima também casa com ela): sem a qualificação, os dois textos afastam
    larguras = pg.evaluate("""() => [...document.querySelectorAll('#tvope-km .mod:first-child span')]
                                    .map(s => Math.round(s.getBoundingClientRect().width))""")
    assert larguras[1] < larguras[0], larguras


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


# ------------------------------------------- o detalhe dos cartões e do mapa

_ALVOS = """() => ({
    alvos: document.querySelectorAll('#view-tvope [data-tvope]').length,
    sem_rotulo: [...document.querySelectorAll('#view-tvope [data-tvope]')]
                  .filter(e => !e.getAttribute('aria-label')).length})"""

_DET = """() => {
    const box = document.getElementById('modalBox');
    const ab = box.querySelector('.ccm-aba[aria-pressed="true"]');
    return {aberto: document.getElementById('modalBg').classList.contains('aberto'),
            titulo: (box.querySelector('h3') || {}).textContent,
            aba: ab ? ab.dataset.estado : null,
            abas: [...box.querySelectorAll('.ccm-aba')].map(b => b.textContent.trim()),
            linhas: box.querySelectorAll('.ccm-lista tbody tr').length,
            cont: (document.getElementById('ccm-cont') || {}).textContent,
            texto: box.innerText}; }"""


def _detalhe(pg):
    pg.wait_for_selector("#modalBox .ccm-lista table")
    return pg.evaluate(_DET)


def test_todo_cartao_da_operacao_abre_um_detalhe(pagina):
    """Pedido de quem opera (16/09/2026). Cada cartão tem alvo com rótulo — e
    continua tendo depois da recarga de 60 s, que redesenha os cartões: o
    ouvinte é um só, na tela, e não um por cartão."""
    pg, base = pagina
    _abre(pg, base)
    # 6 cartões do bloco da esquerda + as duas metades dos 4 cartões de
    # manutenção com dois números + os 2 cartões inteiros de OS
    esperado = {"alvos": 16, "sem_rotulo": 0}
    assert pg.evaluate(_ALVOS) == esperado
    pg.evaluate("loadTvOpe()")
    pg.wait_for_timeout(600)
    assert pg.evaluate(_ALVOS) == esperado


def test_o_detalhe_do_cartao_lista_o_MESMO_numero(pagina):
    pg, base = pagina
    _abre(pg, base)
    pg.click("#tvope-k1 > .tv-card:nth-child(1)")          # Em trânsito
    d = _detalhe(pg)
    assert d["aberto"] and d["titulo"] == "Viagens em trânsito", d
    # abre na primeira situação com linha: as atrasadas do próprio painel
    assert (d["aba"], d["linhas"], d["cont"]) == ("atrasadas", 2, "2 viagens"), d
    assert d["abas"] == ["Atrasadas2", "Cargas críticas2", "Todas%d" % len(TRANSITO)], d
    # a régra do cartão vai escrita: numa TV não há tooltip
    assert "sem a chegada na última entrega apontada" in d["texto"], d["texto"][:300]


def test_a_metade_do_cartao_abre_o_lado_dela(pagina):
    """Cavalo e semirreboque são duas regras de revisão: cada metade do cartão
    abre a sua."""
    pg, base = pagina
    _abre(pg, base)
    pg.click("#tvope-k2 > .tv-card:nth-child(1) .tv-duo > div:nth-child(2)")
    d = _detalhe(pg)
    assert (d["titulo"], d["aba"], d["linhas"]) == ("Revisões vencidas", "semirreboques", 2), d
    assert "vencida há 15 dias" in d["texto"], d["texto"][:400]


_TRACAO = "#tvope-k1 > .tv-card:nth-child(2) .tv-duo > div:nth-child(%d)"


def test_so_a_metade_da_frota_abre_o_detalhe_da_tracao(pagina):
    """Quem opera, 16/09/2026. O outro lado do cartão é o AGREGADO, e não há
    lista de veículo agregado para mostrar: a metade que abrisse a lista da
    casa prometeria o que não tem — pior do que metade que não abre nada."""
    pg, base = pagina
    _abre(pg, base)
    alvos = pg.evaluate("""() => [...document.querySelectorAll(
        '#tvope-k1 > .tv-card:nth-child(2) .tv-duo > div')].map(d => d.dataset.tvope || null)""")
    assert alvos == ["tracao", None], alvos
    # e o cartão inteiro deixou de ser alvo: clicar no lado do agregado (ou na
    # borda) não pode abrir a lista da frota
    assert pg.evaluate("""() => !!document.querySelector(
        '#tvope-k1 > .tv-card:nth-child(2)').dataset.tvope""") is False
    pg.click(_TRACAO % 2)
    assert not pg.evaluate("document.getElementById('modalBg').classList.contains('aberto')")


def test_a_lista_cortada_pelo_servidor_diz_quantas_de_quantas(pagina):
    """A programação publica 20 ociosos (13 com motor) de 72 tratores
    disponíveis: sem o contador, os 13 da tela passariam por todos — a regra
    de Top-N da casa."""
    pg, base = pagina
    _abre(pg, base)
    pg.click(_TRACAO % 1)                                  # Tração · a metade da frota
    d = _detalhe(pg)
    assert (d["aba"], d["linhas"]) == ("disponivel", 13), d
    assert d["cont"] == "13 de 72 veículos · o servidor publica as 13 primeiras", d
    pg.click('#modalBox .ccm-aba[data-estado="em_os"]')
    assert pg.evaluate(_DET)["linhas"] == 6          # os cavalos na oficina
    pg.keyboard.press("Escape")
    assert not pg.evaluate("document.getElementById('modalBg').classList.contains('aberto')")


def test_o_detalhe_dos_motoristas_e_SO_DA_FROTA(pagina):
    """Quem opera, 16/09/2026: "precisa trazer somente motoristas Frota como o
    card". O detalhe vinha das listas gerais da programação — agregado e
    terceiro juntos, e cortadas em 20 — enquanto o cartão mede só a casa. As
    três situações agora saem da lista da frota, e somam o total do cartão."""
    pg, base = pagina
    _abre(pg, base)
    pg.click("#tvope-k1 > .tv-card:nth-child(5)")          # Motoristas da frota
    d = _detalhe(pg)
    assert d["abas"] == ["Em viagem4", "Ociosos64", "CNH vencida2"], d
    assert (d["aba"], d["linhas"], d["cont"]) == ("em_viagem", 4, "4 motoristas"), d
    pg.click('#modalBox .ccm-aba[data-estado="ociosos"]')
    m = pg.evaluate(_DET)
    assert (m["linhas"], m["cont"]) == (64, "64 motoristas"), m
    # os nomes do dublê das listas GERAIS não podem aparecer aqui
    for fora in ("MOTORISTA PARADO", "MOTORISTA CNH"):
        assert fora not in m["texto"].upper(), (fora, m["texto"][:300])
    assert "MOTORISTA FROTA" in m["texto"].upper(), m["texto"][:300]
    pg.fill("#modalBox .ccm-busca", "FROTA 7")
    assert pg.evaluate(_DET)["linhas"] == 1


def _clicar_no_mapa(pg, seletor, i=0):
    """Clica no marcador pelo EVENTO, e não pelo ponteiro.

    O mapa mantém no DOM os marcadores que estão fora do enquadramento, e a
    checagem de "está clicável" do Playwright briga com isso — o clique
    expira com "element is outside of the viewport" mesmo depois de centrar o
    mapa no ponto. O que estes testes provam é a LIGAÇÃO marcador → ficha, e o
    Leaflet escuta o clique no próprio elemento do marcador: disparar o evento
    nele é o mesmo caminho, com as coordenadas do elemento junto.
    """
    return pg.evaluate("""([sel, i]) => {
        const el = document.querySelectorAll(sel)[i];
        if(!el) return null;
        const b = el.getBoundingClientRect();
        el.dispatchEvent(new MouseEvent('click', {bubbles: true, clientX: b.left + b.width / 2,
                                                  clientY: b.top + b.height / 2}));
        // só o RÓTULO, sem a tração do <small>: no marcador os dois são
        // textos irmãos, e `textContent` os cola ("4" + "3/4" = "43/4")
        return (el.childNodes[0].textContent || '').trim(); }""", [seletor, i])


def test_o_caminhao_do_mapa_abre_a_ficha(pagina):
    pg, base = pagina
    _abre(pg, base)
    rot = _clicar_no_mapa(pg, "#tvMapa .tv-vmk")
    assert rot, "nenhum caminhão no mapa"
    d = _detalhe(pg)
    assert d["titulo"] == rot + " — ficha do veículo", (rot, d["titulo"])
    # os rótulos da ficha saem em CAIXA ALTA pelo CSS da casa
    texto = d["texto"].upper()
    for campo in ("PLACA", "MODALIDADE", "ESTADO", "ÚLTIMA POSIÇÃO"):
        assert campo in texto, (campo, d["texto"][:300])
    # e a ficha é a DAQUELE veículo: a placa do dublê do mapa
    assert "POS" in texto or "AAA" in texto, d["texto"][:300]


def test_o_grupo_do_mapa_lista_os_veiculos_e_dali_abre_a_ficha(pagina):
    """O círculo diz QUANTOS; o clique diz QUAIS — sem espalhar rótulo
    empilhado no mapa. O dublê tem 6 veículos parados no mesmo pátio."""
    pg, base = pagina
    _abre(pg, base)
    assert _clicar_no_mapa(pg, "#tvMapa .tv-vgrp.parado"), "nenhum grupo parado no mapa"
    d = _detalhe(pg)
    assert d["titulo"] == "6 veículos neste ponto" and d["linhas"] == 6, d
    pg.click("#modalBox tbody tr:nth-child(1)")
    assert "ficha do veículo" in pg.evaluate(_DET)["titulo"]


# ------------------------------------------------------------ o celular

def test_no_celular_o_mapa_nao_pinta_por_cima_da_gaveta(pagina):
    """No modo NAVEGADOR (a tela é maior que a janela, então não há `tvfull`)
    a gaveta de telas existe — e a etiqueta da região e a legenda do mapa
    saíam POR CIMA dela: são `position:absolute` com `z-index:500` na RAIZ, e
    500 vence os 70 da gaveta. Medido em 16/09/2026 com o painel aberto no
    celular: o menu abria com dois blocos escuros do mapa por cima dos itens.

    O teste mira o resultado, não a regra: pergunta ao navegador QUEM está no
    ponto, sobre o painel da gaveta. Com `tvfull` a gaveta nem existe (ela é
    escondida no modo parede), e por isso o modo importa aqui.
    """
    pg, base = pagina
    pg.add_init_script("Object.defineProperty(screen,'height',{get:()=>1000});")
    _abre(pg, base)
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.reload()
    pg.wait_for_function("() => document.querySelectorAll('#tvope-cheg tr').length > 1")
    pg.wait_for_timeout(1200)
    assert "tvfull" not in pg.evaluate("() => document.body.className"), (
        "sem gaveta não há o que testar: no modo parede ela é escondida")
    pg.evaluate("abrirDrawer()")
    pg.wait_for_timeout(300)
    r = pg.evaluate("""() => {
        const p = document.querySelector('#drawer .painel').getBoundingClientRect();
        const fora = [], cobertos = [];
        for(const id of ['tv-regiao', 'tvope-legenda']){
          const el = document.getElementById(id);
          if(!el) continue;
          const b = el.getBoundingClientRect();
          if(!(b.width && b.height && b.bottom > p.top && b.top < p.bottom
               && b.right > p.left && b.left < p.right)) continue;   // não se cruzam
          cobertos.push(id);
          /* o CENTRO DA INTERSEÇÃO, e não um ponto qualquer do painel: ponto
             amostrado longe do elemento devolve a gaveta e o teste passa por
             vacuidade (foi o que aconteceu na primeira versão deste guard) */
          const x = (Math.max(b.left, p.left) + Math.min(b.right, p.right)) / 2;
          const y = (Math.max(b.top, p.top) + Math.min(b.bottom, p.bottom)) / 2;
          const topo = document.elementFromPoint(x, y);
          if(!topo || !topo.closest('#drawer')) fora.push(id + ' → ' + (topo ? (topo.id || topo.className) : 'nada'));
        }
        return {painel: Math.round(p.height), cobertos, fora}; }""")
    assert r["painel"] > 200, r
    # SEM SOBREPOSIÇÃO NÃO HÁ O QUE PROVAR: a etiqueta da região é a que cai
    # dentro do painel nesta geometria (a legenda fica abaixo da dobra e, no
    # celular, é estática — não tem como vazar). Sem esta linha, o guard
    # passaria no dia em que ninguém mais se cruzasse com ninguém.
    assert "tv-regiao" in r["cobertos"], r
    assert r["fora"] == [], r

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
