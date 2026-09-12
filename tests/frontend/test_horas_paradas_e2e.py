"""A tela Horas Paradas, no navegador, com a API dublada.

O que só o navegador prova: que a linha AJUSTADA à mão se distingue da que
veio do ERP, que a carga fora da planilha continua na tela, que o modal de
ajuste oferece os seis horários, que a aba de regras desenha o que o perfil
tem — e que nada disso empurra a página para o lado.

O dublê tem a forma REAL do payload de `servico.montar` (12/09/2026), com
nomes e números inventados: condição comercial de cliente não entra no
repositório.
"""
from __future__ import annotations

import json

from tests.frontend.conftest import USUARIO

CASA = {**USUARIO, "admin": True, "perfil": "Administrador"}

CFG = {"inicio_carga": "maior", "inicio_descarga": "maior", "arredondamento_min": 0,
       "recorte": "fim_descarga", "periodo": "semana", "aba": "", "arquivo": "",
       "regras": [{"nome": "caixas: relógio na chegada", "perna": "carga",
                   "mercadorias": ["CAIXAS"], "destinos": [], "inicio": "chegada",
                   "clausula": None, "freetime_h": None, "valor_h": None}],
       "colunas": [{"campo": "coleta", "titulo": "Coleta"},
                   {"campo": "carga_valor", "titulo": "Total Carregamento"}]}
PERFIS = {"perfis": [{"id": 1, "cliente_codigo": 99, "cliente_nome": "CLIENTE EXEMPLO",
                      "config": CFG}],
          "catalogo_colunas": [{"campo": "coleta", "titulo": "Coleta", "tipo": "numero"},
                               {"campo": "carga_valor", "titulo": "Total Carregamento",
                                "tipo": "dinheiro"}],
          "padrao": CFG}


def _perna(janela, chegada, saida, tempo, ft, cobrado, valor, erp=None, regra=None,
           clausula="generico", inicio_de="chegada"):
    return {"janela": janela, "chegada": chegada, "saida": saida, "inicio": chegada,
            "inicio_de": inicio_de, "modo": "maior", "freetime_h": ft, "valor_h": 100.0,
            "clausula": clausula, "clausula_mercadoria": None, "regra": regra,
            "tempo_s": tempo, "excedente_s": cobrado, "cobrado_s": cobrado, "valor": valor,
            "estado": "ok", "erp": erp or {}}


LINHA = {"chave": "1|1|20|1|0|1|501", "coleta": 501, "filial": 20,
         "pedido": "6100000501CIF0000501", "pedido_num": "6100000501",
         "pedido_comp": "CIF0000501", "referencia": "CIF0000501",
         "mercadoria": "CAIXAS", "origem": "PLANTA A", "destino": "PLANTA B",
         "destinatario_codigo": "111", "cidade_origem": "", "cidade_destino": "",
         "frota_cavalo": "T100", "placa_cavalo": "AAA0A00", "frota_carreta": None,
         "placa_carreta": "BBB0B00", "ctes": "900001", "marco": "2026-09-09 19:00",
         "carga": _perna("2026-09-09 10:00", "2026-09-09 07:40", "2026-09-09 11:00",
                         12000, 3.0, 0.0, 0.0, erp={"chegada": "2026-09-09 08:30"},
                         regra="caixas: relógio na chegada"),
         "descarga": _perna("2026-09-09 15:00", "2026-09-09 15:00", "2026-09-09 19:00",
                            14400, 3.0, 3600.0, 100.0, clausula="mercadoria"),
         "valor": 100.0, "valor_erp": 100.0, "incluida": True,
         "ajustes": [{"campo": "carga_chegada", "valor": "2026-09-09T07:40",
                      "valor_erp": "2026-09-09 08:30", "motivo": "portaria anotou 07:40",
                      "autor": "a@x", "em": "2026-09-12T10:00:00"}],
         "avisos": []}
FORA = dict(LINHA, chave="1|1|20|1|0|1|502", coleta=502, incluida=False, valor=50.0,
            valor_erp=50.0, ajustes=[{"campo": "incluir", "valor": "nao", "valor_erp": "sim",
                                      "motivo": "cobrada em contrato próprio", "autor": "a@x",
                                      "em": "2026-09-12T10:00:00"}])
PAYLOAD = {
    "perfil": {"id": 1, "cliente_codigo": 99, "cliente_nome": "CLIENTE EXEMPLO", "config": CFG},
    "periodo": {"de": "2026-09-07", "ate": "2026-09-13", "semana": 37, "recorte": "fim_descarga"},
    "resumo": {"cargas": 1, "com_excedente": 1, "valor_carga": 0.0, "valor_descarga": 100.0,
               "valor_total": 100.0, "horas_carga": 0.0, "horas_descarga": 1.0,
               "ajustadas": 1, "efeito_ajustes": 0.0, "excluidas": 1, "sem_contrato": 0,
               "sem_apontamento": 0, "em_aberto": 1},
    "linhas": [LINHA, FORA],
    "abertas": [{"chave": "1|1|20|1|0|1|503", "coleta": 503, "filial": 20,
                 "mercadoria": "CAIXAS", "destino": "PLANTA B", "placa_cavalo": "CCC0C00",
                 "frota_cavalo": None, "carga_janela": "2026-09-12 10:00",
                 "carga_chegada": "2026-09-12 09:00", "carga_saida": "2026-09-12 10:30",
                 "descarga_janela": "2026-09-12 16:00", "descarga_chegada": None,
                 "descarga_saida": None, "erp": {}, "ajustes": []}],
    "contrato": [{"filial": 20, "mercadoria": "", "ft_carga_h": 3.0, "ft_descarga_h": 3.0,
                  "valor_coleta": 100.0, "valor_entrega": 100.0, "dtinicio": "2024-08-01",
                  "dtfim": None, "ativoinativo": 1, "vigente": True}],
    "lido_em": "2026-09-12T10:00:00", "fonte": "ERP AVA · leitura",
}
CATALOGO = {"mercadorias": [{"codigo": "CAIXAS", "nome": "CAIXAS", "n": 40}],
            "destinos": [{"codigo": "111", "nome": "PLANTA B", "n": 40}],
            "versoes": [{"id": 1, "autor": "a@x", "em": "2026-09-12T10:00:00"}]}


def _abrir(pg, base_url):
    def rota(route):
        u = route.request.url
        if "/api/auth/me" in u:
            corpo = CASA
        elif "/horas-paradas/perfis" in u:
            corpo = PERFIS
        elif "/horas-paradas/catalogo" in u:
            corpo = CATALOGO
        elif "/api/operacao/horas-paradas?" in u:
            corpo = PAYLOAD
        else:
            corpo = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))

    pg.route("**/api/**", rota)
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(base_url + "/static/index.html#hp")
    pg.wait_for_selector("#hp-cargas tr td button", state="attached", timeout=20000)
    return erros


def test_a_tela_abre_sem_erro_e_mostra_o_total(pagina):
    pg, base = pagina
    assert _abrir(pg, base) == []
    kpis = pg.inner_text("#kpis-hp")
    assert "A cobrar no período" in kpis and "100,00" in kpis


def test_o_horario_AJUSTADO_se_distingue_do_ERP(pagina):
    pg, base = pagina
    _abrir(pg, base)
    marca = pg.locator("#hp-cargas tr").first.locator(".hp-aj")
    assert marca.count() == 1
    assert "08:30" in marca.first.get_attribute("title"), "o valor do ERP tem de estar à mão"


def test_a_regra_que_respondeu_aparece_na_linha(pagina):
    pg, base = pagina
    _abrir(pg, base)
    assert "regra: caixas: relógio na chegada" in pg.inner_text("#hp-cargas tr:first-child")


def test_carga_FORA_da_planilha_continua_na_tela_atenuada(pagina):
    pg, base = pagina
    _abrir(pg, base)
    fora = pg.locator("#hp-cargas tr.hp-fora")
    assert fora.count() == 1 and "fora da planilha" in fora.inner_text()


def test_o_modal_de_ajuste_oferece_os_seis_horarios_e_o_motivo(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.locator("#hp-cargas tr").first.locator("button").click()
    pg.wait_for_selector("#hp-motivo", timeout=5000)
    assert pg.locator("#modalBox input[type=datetime-local]").count() == 6
    assert pg.input_value("#hpv-carga_chegada") == "2026-09-09T07:40"
    pg.click("#hp-gravar")
    assert "Nada mudou" in pg.inner_text("#m-err")


def test_a_aba_de_REGRAS_desenha_o_perfil(pagina):
    pg, base = pagina
    _abrir(pg, base)
    pg.click("#tabhp-regras")
    pg.wait_for_selector("#hp-salvar", timeout=10000)
    txt = pg.inner_text("#hp-regras")
    assert "caixas: relógio na chegada" in txt
    assert "Total Carregamento" in pg.eval_on_selector_all(
        "#hp-regras input[type=text]", "els => els.map(e => e.value).join('|')")
    assert pg.input_value("#hpc-ic") == "maior"


def test_nenhuma_aba_empurra_a_pagina_para_o_lado(pagina):
    pg, base = pagina
    _abrir(pg, base)
    for aba in ("cargas", "abertas", "regras"):
        pg.click("#tabhp-" + aba)
        pg.wait_for_timeout(300)
        excesso = pg.evaluate("() => document.documentElement.scrollWidth"
                              " - document.documentElement.clientWidth")
        assert excesso <= 0, "a aba %s empurrou a página %dpx para o lado" % (aba, excesso)
