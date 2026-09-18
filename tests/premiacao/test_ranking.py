# -*- coding: utf-8 -*-
"""A montagem do ciclo: as quatro fontes viram uma linha por motorista.

Aqui as fontes entram por substituição — o que se testa é a JUNÇÃO:

- a linha fala por CÓDIGO DO CADASTRO, nunca por CPF (é PII, e a regra vale
  para a premiação como vale para o GR e para o portal do cliente);
- a ordem é do PIOR para o melhor, e quem está sem nota vai para o fim: é
  pendência de cadastro ou de fonte, não desempenho ruim;
- cada GRUPO usa a régua dele;
- as PENDÊNCIAS saem no payload — número que vem de uma base com buraco tem de
  dizer o tamanho do buraco;
- fonte fora do ar não inventa nota: o pilar fica ausente e o motivo viaja.
"""
from __future__ import annotations

import pytest

from api.premiacao import identidade, parametros, pilares, ranking

CICLO = "2026-09"


def _motorista(codigo, nome, cpf, tipo="RODOVIARIO", filial="SBC",
               admissao="2020-01", origem="sugerido"):
    return {"cpf": cpf, "nome": nome, "cadastro_codigo": codigo, "tipo": tipo,
            "tipo_origem": origem, "filial": filial, "filial_origem": "folha",
            "admissao": admissao, "funcao": "MOT CARRETEIRO", "ativo": 1,
            "chapa": "C1", "gobrax_driver_id": None, "sincronizado_em": None,
            "atualizado_em": None, "atualizado_por": None}


@pytest.fixture
def fontes(monkeypatch):
    """Cadastro com dois motoristas e as três fontes sob controle do teste."""
    cad = [_motorista("111", "MOTORISTA UM", "11111111111"),
           _motorista("222", "MOTORISTA DOIS", "22222222222", tipo="MANOBRA")]
    monkeypatch.setattr(identidade, "listar", lambda ativos=True: cad)
    monkeypatch.setattr(parametros, "pesos_gr", lambda ciclo: {})
    monkeypatch.setattr(parametros, "depara", lambda: {1: "D01"})
    monkeypatch.setattr(parametros, "ler", lambda ciclo, grupo: {
        "valores": parametros.defaults(), "grupo": grupo, "ciclo": ciclo,
        "versao": None, "vigente_de": None})
    estado = {
        "conduta": {"por_ciclo": {}, "nao_mapeados": [], "sem_codigo": 0, "motivo": ""},
        "gr": {"por_ciclo": {}, "motivo": ""},
        "gobrax": {"mes_gobrax": "2026-08", "notas": {}, "ambiguos": [],
                   "sem_cadastro": [], "motivo": "", "coletado_em": "x",
                   "parcial": False},
        "gobrax_janela": {},
    }
    monkeypatch.setattr(pilares, "comportamento_janela",
                        lambda *a, **k: estado["conduta"])
    monkeypatch.setattr(pilares, "gr_janela", lambda *a, **k: estado["gr"])
    monkeypatch.setattr(pilares, "gobrax", lambda *a, **k: estado["gobrax"])
    monkeypatch.setattr(pilares, "gobrax_janela", lambda *a, **k: estado["gobrax_janela"])
    return estado


def test_a_linha_fala_por_codigo_do_cadastro_e_NUNCA_por_cpf(fontes):
    r = ranking.montar(CICLO)
    assert {x["motorista"] for x in r["linhas"]} == {"111", "222"}
    import json
    assert "11111111111" not in json.dumps(r), "o CPF vazou no payload"


def test_sem_ocorrencia_a_conduta_e_100_e_a_nota_sai_so_dela(fontes):
    r = ranking.montar(CICLO)
    linha = r["linhas"][0]
    assert linha["conduta"] == 100.0 and linha["nota"] == 100.0
    assert linha["pilares"] == ["conduta"]
    assert linha["ausentes"] == ["gobrax", "gr"]


def test_a_nota_junta_os_tres_pilares_quando_eles_existem(fontes):
    fontes["gobrax"]["notas"] = {"11111111111": {"nota": 80.0, "km": 5000.0}}
    fontes["conduta"]["por_ciclo"] = {CICLO: {"11111111111": {
        "desvios": [{"cod": "D01", "nome": "x", "grav": "GRAVE", "pts": 12,
                     "data": "2026-09-01"}], "meritos": [], "pontos": 12.0,
        "nota": 88.0}}}
    fontes["gr"]["por_ciclo"] = {CICLO: {"11111111111": {
        "nota": 60.0, "viagens": 12, "risco_por_viagem": 20.0,
        "insuficiente": False, "contadores": {}, "informativos": {}}}}
    linha = [x for x in ranking.montar(CICLO)["linhas"] if x["motorista"] == "111"][0]
    assert linha["nota"] == round(0.4 * 80 + 0.4 * 88 + 0.2 * 60, 1)
    assert linha["pilares"] == ["gobrax", "conduta", "gr"] and linha["ausentes"] == []
    assert linha["gr_viagens"] == 12 and linha["km"] == 5000.0
    assert linha["medida"]["nivel"] == "N1"


def test_a_ordem_e_do_PIOR_para_o_melhor_e_sem_nota_vai_para_o_FIM(fontes, monkeypatch):
    cad = [_motorista("111", "PIOR", "11111111111"),
           _motorista("222", "MELHOR", "22222222222"),
           _motorista("333", "SEM NOTA", "33333333333")]
    monkeypatch.setattr(identidade, "listar", lambda ativos=True: cad)
    fontes["conduta"]["por_ciclo"] = {CICLO: {
        "11111111111": {"desvios": [], "meritos": [], "pontos": 0, "nota": 40.0},
        "22222222222": {"desvios": [], "meritos": [], "pontos": 0, "nota": 95.0}}}
    # o terceiro fica sem nenhum pilar: peso zero em tudo o deixa sem nota
    monkeypatch.setattr(parametros, "ler", lambda ciclo, grupo: {
        "valores": {**parametros.defaults(),
                    **({"peso_gobrax": 0, "peso_conduta": 0, "peso_gr": 0}
                       if grupo == "MANOBRA" else {})},
        "grupo": grupo, "ciclo": ciclo, "versao": None, "vigente_de": None})
    cad[2]["tipo"] = "MANOBRA"
    linhas = ranking.montar(CICLO)["linhas"]
    assert [x["motorista"] for x in linhas] == ["111", "222", "333"]
    assert linhas[-1]["nota"] is None and linhas[-1]["status"] == "PENDENTE"


def test_cada_GRUPO_usa_a_regua_dele(fontes, monkeypatch):
    """Rodoviário e manobrista têm pesos diferentes — a linha tem de sair com
    a régua do grupo DELA."""
    def ler(ciclo, grupo):
        v = parametros.defaults()
        if grupo == "MANOBRA":
            v = {**v, "peso_gobrax": 0, "peso_conduta": 100, "peso_gr": 0}
        return {"valores": v, "grupo": grupo, "ciclo": ciclo, "versao": None,
                "vigente_de": None}
    monkeypatch.setattr(parametros, "ler", ler)
    fontes["gobrax"]["notas"] = {"11111111111": {"nota": 50.0, "km": 1.0},
                                 "22222222222": {"nota": 50.0, "km": 1.0}}
    por = {x["motorista"]: x for x in ranking.montar(CICLO)["linhas"]}
    # rodoviário: sem GR, os 40/40 viram 50/50 — (50 + 100) / 2
    assert por["111"]["nota"] == 75.0
    assert por["222"]["nota"] == 100.0         # manobrista: só conduta pesa
    assert por["222"]["pilares"] == ["conduta"]


def test_as_PENDENCIAS_saem_no_payload(fontes, monkeypatch):
    fontes["conduta"]["nao_mapeados"] = [{"codigo": 79, "descricao": "AVARIA", "vezes": 2}]
    fontes["conduta"]["sem_codigo"] = 5
    fontes["gobrax"]["ambiguos"] = ["JOSE SANTOS"]
    fontes["gobrax"]["sem_cadastro"] = ["FULANO", "CICRANO"]
    cad = [_motorista("111", "UM", "11111111111", filial=None)]
    monkeypatch.setattr(identidade, "listar", lambda ativos=True: cad)
    p = ranking.montar(CICLO)["pendencias"]
    assert p["codigos_sem_depara"][0]["codigo"] == 79
    assert p["ocorrencias_sem_codigo"] == 5
    assert p["gobrax_ambiguos"] == ["JOSE SANTOS"]
    assert p["gobrax_fora_do_cadastro"] == 2
    assert p["sem_filial"] == 1 and p["tipo_sugerido"] == 1


def test_fonte_fora_do_ar_nao_inventa_nota_e_o_motivo_VIAJA(fontes):
    fontes["gobrax"]["motivo"] = "sem leitura da Gobrax para 2026-08"
    fontes["gr"]["motivo"] = "gerenciamento de risco indisponível"
    fontes["conduta"]["motivo"] = "ERP indisponível"
    r = ranking.montar(CICLO)
    assert r["fontes"]["gobrax"]["motivo"].startswith("sem leitura")
    assert r["fontes"]["gr"]["motivo"] and r["fontes"]["conduta"]["motivo"]
    assert all(x["gobrax"] is None and x["gr"] is None for x in r["linhas"])


def test_o_KPI_diz_quantas_notas_sairam_com_pilar_FALTANDO(fontes):
    """Hoje metade da base não tem nota da Gobrax. Isso não pode ser nota de
    rodapé: é o tamanho do buraco de onde o número saiu."""
    fontes["gobrax"]["notas"] = {"11111111111": {"nota": 80.0, "km": 1.0}}
    k = ranking.montar(CICLO)["kpis"]
    assert k["motoristas"] == 2 and k["com_nota"] == 2
    assert k["com_pilar_faltando"] == 2       # um sem GR, outro sem Gobrax nem GR


def test_o_ciclo_invalido_e_recusado():
    with pytest.raises(ValueError, match="Ciclo inválido"):
        ranking.montar("setembro")


def test_o_cabecalho_diz_o_periodo_e_de_que_mes_veio_a_gobrax(fontes):
    r = ranking.montar(CICLO)
    assert r["rotulo"] == "16/08 a 15/09 de 2026"
    assert r["mes_gobrax"] == "2026-08"
