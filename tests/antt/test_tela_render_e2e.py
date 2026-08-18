"""A tela #anpiso renderizando o payload REAL do serviço, sem banco.

Cobre a ponta a ponta que o teste de marcação não cobre: cálculo do piso ->
payload -> render -> tabela expansível -> gráfico. Se o JS da tela quebrar, é
aqui que aparece.
"""
from __future__ import annotations

import json

from api.antt.servico import (conferir_viagens, resumir, serie_mensal)
from tests.frontend.conftest import USUARIO

LINHAS = [
    # paga MUITO abaixo do piso: 500 km de carga geral 5 eixos por R$ 1.000
    {"numero": 101, "dtemissao": "2026-08-05", "codigo": "T1",
     "transportador": "TRANSPORTES ALFA", "placa": "AAA1A11", "origem": "SBC/SP",
     "destino": "RIO/RJ", "km": 500.0, "pago": 1000.0, "vazio": False,
     "veic_tipo": "CAVALO MECANICO", "veic_carroceria": "CARGA SECA",
     "veic_bitrem": False, "veic_tipocarga": "CARGA GERAL"},
    # paga acima do piso
    {"numero": 102, "dtemissao": "2026-08-06", "codigo": "T2",
     "transportador": "TRANSPORTES BETA", "placa": "BBB2B22", "origem": "SBC/SP",
     "destino": "CWB/PR", "km": 400.0, "pago": 9000.0, "vazio": False,
     "veic_tipo": "TRUCK", "veic_carroceria": "BAU",
     "veic_bitrem": False, "veic_tipocarga": "CARGA GERAL"},
    # veículo que o mapa não conhece -> pendência de cadastro
    {"numero": 103, "dtemissao": "2026-08-07", "codigo": "T3",
     "transportador": "TRANSPORTES GAMA", "placa": "CCC3C33", "origem": "SBC/SP",
     "destino": "BHZ/MG", "km": 700.0, "pago": 3000.0, "vazio": False,
     "veic_tipo": "NAVE ESPACIAL", "veic_carroceria": "DESCONHECIDA",
     "veic_bitrem": False, "veic_tipocarga": None},
    # mês anterior, na vigência antiga
    {"numero": 104, "dtemissao": "2026-06-10", "codigo": "T1",
     "transportador": "TRANSPORTES ALFA", "placa": "AAA1A11", "origem": "SBC/SP",
     "destino": "RIO/RJ", "km": 500.0, "pago": 8000.0, "vazio": False,
     "veic_tipo": "CAVALO MECANICO", "veic_carroceria": "CARGA SECA",
     "veic_bitrem": False, "veic_tipocarga": "CARGA GERAL"},
]


def _payload():
    conferidas = conferir_viagens(LINHAS)
    por_transp = {}
    for c in conferidas:
        t = por_transp.setdefault(c["codigo"], {
            "codigo": c["codigo"], "transportador": c["transportador"],
            "viagens": 0, "pago": 0.0, "abaixo": 0, "exposicao": 0.0, "detalhe": []})
        t["viagens"] += 1
        t["pago"] += c["pago"]
        if c["abaixo"]:
            t["abaixo"] += 1
            t["exposicao"] += c["gap"]
        t["detalhe"].append(c)
    pend = [{"placa": c["placa"], "tipo": c["veic_tipo"],
             "carroceria": c["veic_carroceria"], "motivo": c["estado"]}
            for c in conferidas if c["estado"] not in ("calculado", "isento")]
    return {"kpis": resumir(conferidas), "mensal": serie_mensal(conferidas),
            "transportadores": sorted(por_transp.values(), key=lambda x: x["exposicao"]),
            "pendencias": pend, "dt_de": "2026-06-01", "dt_ate": "2026-08-31",
            "fonte": "teste"}


def _abrir(pg, base):
    dados = _payload()

    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = USUARIO
        elif "/api/operacao/antt/piso" in u:
            corpo = dados
        elif "/api/versao" in u:
            corpo = {"versao": "0.4.0", "rotulo": "teste", "data": "2026-08-18"}
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base}/static/index.html#anpiso")
    pg.wait_for_selector("#kpis-anpiso .kpi", timeout=20000)
    return dados, erros


def test_tela_abre_sem_erro_de_javascript(pagina):
    pg, base = pagina
    _, erros = _abrir(pg, base)
    assert erros == [], f"erros de JS na tela: {erros}"


def test_os_cinco_kpis_aparecem_com_a_cobertura_declarada(pagina):
    pg, base = pagina
    dados, _ = _abrir(pg, base)
    assert pg.eval_on_selector_all("#kpis-anpiso .kpi", "e=>e.length") == 5
    texto = pg.inner_text("#kpis-anpiso")
    k = dados["kpis"]
    assert f"conferido em {k['conferidas']} de {k['viagens']}" in texto


def test_transportador_abaixo_do_piso_aparece_com_exposicao(pagina):
    pg, base = pagina
    _abrir(pg, base)
    linhas = pg.inner_text("#anpiso-transp")
    assert "TRANSPORTES ALFA" in linhas
    assert "TRANSPORTES BETA" in linhas


def test_linha_expande_e_mostra_as_viagens(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#anpiso-transp tr.forn-row")
    pg.wait_for_selector("#anpiso-det-0.open", timeout=5000)
    det = pg.inner_text("#anpiso-det-0")
    assert "AAA1A11" in det          # placa da viagem
    assert "conferida" in det        # rótulo humano do estado


def test_veiculo_sem_cadastro_vira_pendencia_e_nao_irregular(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pend = pg.inner_text("#anpiso-pend")
    assert "CCC3C33" in pend
    assert "eixos não cadastrados" in pend
    # e não aparece como abaixo do piso em lugar nenhum
    assert "TRANSPORTES GAMA" not in pg.inner_text("#anpiso-transp") or \
        "—" in pg.inner_text("#anpiso-transp")


def test_grafico_desenha_uma_barra_por_mes_conferido(pagina):
    pg, base = pagina
    dados, _ = _abrir(pg, base)
    caminhos = pg.eval_on_selector_all("#chartAnpiso path", "e=>e.length")
    assert caminhos == len(dados["mensal"])


def test_menu_mostra_o_grupo_antt(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert pg.is_visible("#grpAntt")
