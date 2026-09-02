# -*- coding: utf-8 -*-
"""A tela de Ordens de Compra e o Painel de Custos no navegador, com dublê da
API na ordem de grandeza do real (payload copiado da forma que o backend
devolve em 01/09/2026).

O que só se prova AQUI:
1. A tela não estoura no boot (um erro derruba o app inteiro).
2. Os contadores das abas dizem o TAMANHO DO ASSUNTO (fila + rascunhos, total
   de fornecedores, OCs sem nota), não as linhas desenhadas.
3. A fila mostra quem espera decisão, o aprovador inativo e o nome da filial
   (não "Filial 1").
4. O filtro de status chega à API — e, no Painel de Custos, origem e filial
   chegam à API (ficaram cinco semanas sem chegar).
5. Falha do bloco em aberto é DITA nos cartões, não engolida.
6. O preset de período descreve o recorte que voltou da API.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

ADMIN = {**USUARIO, "admin": True, "perfil": "Administrador"}
HOJE = "2026-09-01"

FILTROS = {"empresa": "TRANSPORTADORA SULISTA S/A",
           "filiais": [{"codigo": 1, "nome": "MATRIZ", "uf": "SC"}, {"codigo": 20, "nome": "FIL CRUZEIRO", "uf": "SP"}]}


def _ordem(n, status, **kw):
    o = {"numero": n, "filial": 1, "tipo": 3, "emissao": "2026-08-20", "aprovada_em": "2026-08-20",
         "suspensa_em": None, "prazo": None, "dias_aberta": 12, "criador": "ANA CRIADORA",
         "aprovador": "BETO APROVADOR", "aprovador2": None, "valor": 1000.0, "valor_pendente": 0.0,
         "parcial": False, "acima_alcada": False, "status": status}
    o.update(kw)
    return o


OC = {
    "kpis": {"ocs": 2455, "valor": 15092504.02, "recebidas": 2127, "recebidas_valor": 14436814.87, "parciais": 9,
             "fila": 60, "fila_valor": 69714.0, "rascunhos": 4, "rascunhos_valor": 15682.65,
             "aguardando": 98, "aguardando_valor": 136681.52, "atrasadas": 2, "atrasadas_valor": 698.4,
             "suspensas": 152, "suspensas_valor": 408587.25, "reprovadas": 14, "reprovadas_valor": 25023.73,
             "cadastro_sem_data": 0, "cadastro_sem_data_valor": 0, "acima_alcada": 0, "acima_alcada_valor": 0,
             "com_segundo_aprovador": 3, "prazo_informado": 618},
    "tempo_aprovacao": {"n": 2225, "mediana_h": 4.15, "p90_h": 30.16, "max_h": 145.6},
    "por_aprovador": [
        {"cod": 23, "ocs": 1722, "valor": 9000000.0, "com_segundo": 3, "acima_alcada": 0, "nome": "BETO APROVADOR",
         "ativo": True, "n": 1722, "mediana_h": 5.7, "p90_h": 39.1, "max_h": 145.6, "alcada": 2000000.0},
        {"cod": 518, "ocs": 12, "valor": 3000.0, "com_segundo": 0, "acima_alcada": None, "nome": "CARLA INATIVA",
         "ativo": False, "n": 12, "mediana_h": 1.0, "p90_h": 2.0, "max_h": 3.0, "alcada": None},
    ],
    "fornecedores": [
        {"fornecedor": "FORNECEDOR ALFA", "ocs": 4, "valor": 5000.0, "valor_pendente": 790.0, "atrasadas": 2,
         "em_aprovacao": 1, "suspensas": 1, "doc": "11••••••••••••49", "ocultas": 0,
         "ordens": [_ordem(1, "atrasada", valor_pendente=700.0, dias_aberta=40),
                    _ordem(2, "atrasada", valor_pendente=90.0, prazo="2026-08-25", dias_aberta=8),
                    _ordem(3, "aprovacao", aprovador=None, aprovada_em=None),
                    _ordem(4, "suspensa", aprovador=None, suspensa_em="2026-08-28")]},
        {"fornecedor": "FORNECEDOR BETA", "ocs": 1, "valor": 100.0, "valor_pendente": 0.0, "atrasadas": 0,
         "em_aprovacao": 0, "suspensas": 0, "doc": "22••••••••••••01", "ocultas": 0,
         "ordens": [_ordem(5, "recebida", aprovador2="DANI SEGUNDA", parcial=True, valor_pendente=30.0)]},
    ],
    "fornecedores_total": 361, "fornecedores_top_valor": 12427670.61,
    "mensal": [{"mes": f"2025-{m:02d}", "ocs": 900, "valor": 4000000.0} for m in range(10, 13)]
              + [{"mes": f"2026-{m:02d}", "ocs": 900, "valor": 4000000.0 + m} for m in range(1, 10)],
    "criadores": [{"codigo": 10, "nome": "ANA CRIADORA", "ocs": 2000}],
    "aprovadores": [{"codigo": 23, "nome": "BETO APROVADOR", "ocs": 1722}],
    "dt_de": "2026-06-03", "dt_ate": HOJE, "filial": None, "status": None, "fornecedor": None,
    "criador": None, "aprovador": None, "dias_parada": 30,
    "atualizado_em": HOJE + "T23:38:00", "fonte": "ERP AVA · ordemcompra · leitura",
}

PEND = {
    "sem_nota": {
        "kpis": {"ocs": 104, "valor": 173592.52, "paradas": 6, "paradas_valor": 36911.0, "prazo_vencido": 2,
                 "prazo_vencido_valor": 698.4, "prazo_informado": 82, "cita_nf": 9, "cita_nf_valor": 56695.19,
                 "suspensas": 3223, "suspensas_valor": 15339576.0, "mais_antiga": "2025-06-10"},
        "faixas": [{"faixa": "1_ate_7", "ocs": 95, "valor": 135405.12, "prazo_vencido": 0},
                   {"faixa": "2_8_30", "ocs": 3, "valor": 1276.4, "prazo_vencido": 2},
                   {"faixa": "4_91_180", "ocs": 4, "valor": 35668.0, "prazo_vencido": 0},
                   {"faixa": "5_mais_180", "ocs": 2, "valor": 1243.0, "prazo_vencido": 0}],
        "lista": [{"numero": 2699, "filial": 20, "tipo": 3, "dias": 448, "emissao": "2025-06-10",
                   "aprovada_em": "2025-06-10", "prazo": None, "prazo_vencido": False, "cita_nf": True,
                   "valor": 994.4, "observacao": "NF 4567", "fornecedor": "POUSADA EXEMPLO", "acao": "suspender"},
                  {"numero": 31, "filial": 1, "tipo": 6, "dias": 3, "emissao": "2026-08-29", "aprovada_em": "2026-08-29",
                   "prazo": "2026-08-30", "prazo_vencido": True, "cita_nf": False, "valor": 10.0, "observacao": "",
                   "fornecedor": "FORNECEDOR BETA", "acao": "validar"},
                  {"numero": 32, "filial": 1, "tipo": 6, "dias": 1, "emissao": "2026-08-31", "aprovada_em": "2026-08-31",
                   "prazo": None, "prazo_vencido": False, "cita_nf": False, "valor": 10.0, "observacao": "",
                   "fornecedor": "FORNECEDOR BETA", "acao": "cobrar"}],
        "lista_total": 104,
        "fornecedores": [{"fornecedor": "POUSADA EXEMPLO", "ocs": 2, "pendente": 1243.0, "dias_max": 448}],
        "fornecedores_total": 2,
    },
    "fila": {
        "kpis": {"fila": 60, "fila_valor": 69714.0, "fila_horas_max": 36, "fila_direcionado_inativo": 1,
                 "rascunhos": 41, "rascunhos_valor": 158251.3, "rascunho_mais_antigo": "2023-06-03"},
        "itens": [{"numero": 25714, "filial": 1, "tipo": 6, "emissao": "2026-08-31", "encaminhada": True,
                   "encaminhada_em": "2026-08-31 11:24", "horas": 36, "criador_cod": 10, "direcionado_cod": None,
                   "valor": 85.0, "fornecedor": "FORNECEDOR ALFA", "criador": "ANA CRIADORA", "direcionado": None,
                   "direcionado_ativo": None, "situacao": "fila"},
                  {"numero": 25715, "filial": 20, "tipo": 6, "emissao": "2026-09-01", "encaminhada": True,
                   "encaminhada_em": "2026-09-01 08:00", "horas": 2, "criador_cod": 10, "direcionado_cod": 518,
                   "valor": 15.0, "fornecedor": "FORNECEDOR ALFA", "criador": "ANA CRIADORA",
                   "direcionado": "CARLA INATIVA", "direcionado_ativo": False, "situacao": "fila"},
                  {"numero": 7, "filial": 1, "tipo": 3, "emissao": "2023-06-03", "encaminhada": False,
                   "encaminhada_em": None, "horas": 28473, "criador_cod": 10, "direcionado_cod": None,
                   "valor": 123.0, "fornecedor": "FORNECEDOR BETA", "criador": "ANA CRIADORA", "direcionado": None,
                   "direcionado_ativo": None, "situacao": "rascunho"}],
    },
    "dias_min": 30, "atualizado_em": HOJE + "T23:41:00",
    "fonte": "ERP AVA · não segue os filtros da tela · leitura",
}

CUSTOS = {
    "kpis": {"total": 186549.0, "itens": 201, "combustivel": 21364.0, "manutencao": 30000.0,
             "pendente_aprovacao": 53501.0, "sem_nf": 141184.0},
    "por_agrupador": [{"rotulo": f"AGR {i}", "n": 10, "valor": 10000.0 - i} for i in range(19)],
    "por_status": [{"rotulo": "SEM NF", "n": 100, "valor": 141184.0}, {"rotulo": "COM NF", "n": 90, "valor": 24001.0},
                   {"rotulo": "ABASTECIMENTO INT", "n": 11, "valor": 21364.0}],
    "filtro": {"origem": None, "filial": None},
    "por_fornecedor": [{"rotulo": f"FORN {i}", "n": 5, "valor": 9000.0 - i} for i in range(20)],
    "por_filial": [{"rotulo": "1 - FIL MTZ", "n": 150, "valor": 150000.0}, {"rotulo": "2 - FIL CTB", "n": 51, "valor": 36549.0}],
    "totais": {"agrupadores": 19, "fornecedores": 57, "filiais": 4, "status": 3},
    "serie": [], "itens_lista": [{"agrupador": "AGR 1", "status": "SEM NF", "conta": "PEÇAS", "fornecedor": "FORN 1",
                                  "filial": "1 - FIL MTZ", "placa": "ABC1D23", "frota": "101", "produto": "FILTRO",
                                  "valor": 9000.0, "aprovacao": "APROVADA", "data": "2026-08-10T00:00:00", "oc": 1}],
    "de": "2026-09-01", "ate": HOJE, "atualizado_em": HOJE + "T23:41:00",
    "fonte": "ERP AVA · custos consolidados · leitura",
}


def _rota(urls, pend_status=200):
    def rota(route):
        u = route.request.url
        urls.append(u)
        if "/api/auth/me" in u:
            corpo = ADMIN
        elif "ordens-compra" in u:
            corpo = OC
        elif "oc-pendentes" in u:
            if pend_status != 200:
                route.fulfill(status=pend_status, content_type="application/json",
                              body=json.dumps({"erro": "banco_inacessivel", "mensagem": "Sem conexão com o banco."}))
                return
            corpo = PEND
        elif "suprimentos/custos" in u:
            corpo = CUSTOS
        elif "financeiro/filtros" in u:
            corpo = FILTROS
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
    return rota


def _abrir(pg, base_url, tela="oc", pend_status=200):
    urls = []
    pg.route("**/api/**", _rota(urls, pend_status))
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{base_url}/static/index.html#{tela}")
    pg.wait_for_selector(f"#view-{tela}.on", timeout=15000)
    pg.wait_for_selector(f"#kpis-{tela} .kpi", timeout=15000)
    if tela == "oc":
        # a fila vive numa aba escondida: `wait_for_selector` espera VISIBILIDADE
        pg.wait_for_selector("#oc-fila tr", state="attached", timeout=15000)
    return erros, urls


# ------------------------------------------------------------------- boot

def test_tela_abre_sem_estourar_e_separa_os_estados(pagina):
    pg, base_url = pagina
    erros, _ = _abrir(pg, base_url)
    assert erros == [], erros
    txt = pg.inner_text("#kpis-oc")
    assert "Em aprovação" in txt and "4 rascunhos" in txt
    assert "Aguardando nota" in txt and "2 atrasadas (2%)" in txt
    assert "Suspensas e reprovadas" in txt and "14 reprovadas" in txt
    assert "2.127 recebidas (87%)" in txt


def test_grafico_nasce_aberto_e_o_hint_diz_que_nao_segue_o_filtro(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.wait_for_selector("#chartOc svg", timeout=15000)
    assert pg.evaluate("() => document.querySelector('#chartOc svg').getBoundingClientRect().width") > 300
    assert "não segue o filtro de período" in pg.inner_text("#hintOc")


def test_contadores_dizem_o_tamanho_do_assunto(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    n = pg.evaluate("() => ['ocNAprov','ocNAprovadores','ocNForn','ocNSemnota'].map(i => document.getElementById(i).textContent)")
    assert n == ["101", "2", "361", "104"]          # fila+rascunhos · aprovadores · fornecedores TOTAL · sem nota


def test_fila_mostra_quem_espera_o_inativo_e_o_nome_da_filial(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    fila = pg.inner_text("#oc-fila")
    assert "na fila" in fila and "rascunho" in fila
    assert "inativo" in fila and "qualquer aprovador" in fila
    assert "MATRIZ" in fila and "FIL CRUZEIRO" in fila and "Filial 1" not in fila
    banda = pg.inner_text("#kpis-ocfila")
    assert "60 OCs" in banda and "36 h" in banda and "41 OCs" in banda
    assert "Tempo de aprovação" in banda and "4 h" in banda
    assert "0 OCs" in banda                          # acima da alçada, verde porque houve aprovação com alçada


def test_radar_gradua_a_acao_e_diz_o_prazo(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    radar = pg.inner_text("#ocpend-radar")
    for acao in ("suspender", "validar", "cobrar"):
        assert acao in radar
    assert "cita NF" in radar and "vencido" in radar
    assert "3 de 104" in pg.inner_text("#hintOcRadar")
    assert "9 de 104" in pg.inner_text("#kpis-ocpend")


def test_fornecedor_abre_e_mostra_o_status_de_cada_ordem(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url)
    pg.click("#taboc-forn")
    pg.wait_for_selector("#oc-forn .forn-row", timeout=5000)
    # o dublê traz 2 dos 361: o hint diz o universo, não as linhas desenhadas
    assert "2 de 361 fornecedores" in pg.inner_text("#hintOcLista") and "(82%)" in pg.inner_text("#hintOcLista")
    pg.click("#oc-forn .forn-row")
    assert pg.get_attribute("#oc-forn .forn-row", "aria-expanded") == "true"
    det = pg.inner_text("#forn-det-0")
    assert "Atrasada" in det and "Em aprovação" in det and "Suspensa" in det
    assert "na fila" in det and "susp. 28/08/2026" in det


def test_filtro_de_status_chega_a_api(pagina):
    pg, base_url = pagina
    _, urls = _abrir(pg, base_url)
    urls.clear()
    pg.select_option("#fOcStatus", "atrasada")
    pg.wait_for_timeout(800)
    assert any("ordens-compra" in u and "status=atrasada" in u for u in urls), urls


def test_preset_de_periodo_descreve_o_recorte_que_voltou(pagina):
    """A API devolve hoje−90 → o select tem de dizer 'Últimos 90 dias', não
    'Personalizado'. Dublê acompanha o relógio da página."""
    pg, base_url = pagina
    _abrir(pg, base_url)
    de, ate = pg.evaluate("() => { const r = emiRange('d90'); return [_iso(r[0]), _iso(r[1])]; }")
    OC["dt_de"], OC["dt_ate"] = de, ate
    try:
        pg.evaluate("() => { document.getElementById('fEmiDe').value=''; document.getElementById('fEmiAte').value=''; }")
        pg.evaluate("() => loadOc()")
        pg.wait_for_timeout(800)
        assert pg.evaluate("() => document.getElementById('fEmiPreset').value") == "d90"
    finally:
        OC["dt_de"], OC["dt_ate"] = "2026-06-03", HOJE


def test_falha_do_bloco_em_aberto_e_dita_nos_cartoes(pagina):
    pg, base_url = pagina
    urls = []
    pg.route("**/api/**", _rota(urls, pend_status=503))
    pg.goto(f"{base_url}/static/index.html#oc")
    pg.wait_for_selector("#kpis-oc .kpi", timeout=15000)
    pg.wait_for_selector("#oc-fila tr", state="attached", timeout=15000)
    assert "n/d" in pg.inner_text("#kpis-ocpend")
    assert "não foi possível" in pg.inner_text("#oc-fila")
    assert "n/d" in pg.inner_text("#kpis-ocfila")
    assert "indisponível" in pg.inner_text("#hintOcAlertas")


# ------------------------------------------------------------ custos

def test_custos_manda_origem_e_filial_para_a_api(pagina):
    pg, base_url = pagina
    erros, urls = _abrir(pg, base_url, tela="custos")
    assert erros == []
    urls.clear()
    pg.select_option("#fCustOrigem", "SEM NF")
    pg.wait_for_timeout(800)
    assert any("suprimentos/custos" in u and "origem=SEM+NF" in u for u in urls), urls
    urls.clear()
    pg.wait_for_selector("#fCustFilial option[value='2 - FIL CTB']", state="attached", timeout=5000)
    pg.select_option("#fCustFilial", "2 - FIL CTB")
    pg.wait_for_timeout(800)
    assert any("filial=2+-+FIL+CTB" in u for u in urls), urls


def test_custos_em_abas_com_fonte_hora_e_universo(pagina):
    pg, base_url = pagina
    _abrir(pg, base_url, tela="custos")
    assert pg.evaluate("() => document.querySelectorAll('#view-custos .subtabs button[data-aba]').length") == 4
    assert pg.is_visible("#aba-custos-geral") and not pg.is_visible("#aba-custos-itens")
    assert "atualizado" in pg.inner_text("#custosFonte")
    n = pg.evaluate("() => ['custNDim','custNOri','custNItens'].map(i => document.getElementById(i).textContent)")
    assert n == ["19", "4", "201"]
    pg.click("#tabcustos-dim")
    assert "20 de 57 fornecedores" in pg.inner_text("#hintCustForn")
    pg.click("#tabcustos-itens")
    assert "1 de 201 itens" in pg.inner_text("#hintCustLista")
    lista = pg.inner_text("#custos-lista").upper()      # o cabeçalho sai em caixa alta pelo CSS
    assert "VEÍCULO" in lista and "ABC1D23" in lista and "FROTA" not in lista.split("\n")[0]
