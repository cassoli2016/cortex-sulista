# -*- coding: utf-8 -*-
"""A montagem do ciclo da campanha — o que o e2e NÃO pode provar.

POR QUE ESTE ARQUIVO EXISTE: o dublê do e2e da guia entrega as linhas prontas,
com posição e categoria já calculadas — então sabotar o servidor não mudava um
pixel da tela e o guard passava verde. Dublê que reproduz a lógica testada não
testa a lógica; quem prova essas duas regras é aqui, com as fontes trocadas e a
montagem correndo de verdade.
"""
from __future__ import annotations

import pytest

from api.campanha import armazenamento as arm, base, servico
from api.premiacao import parametros, pilares

CAMP = {"nome": "trimestre", "de_ciclo": "2026-10", "ate_ciclo": "2026-12",
        "premio": "Moto", "onde": "Matriz"}
CICLO = "2026-11"


@pytest.fixture
def cenario(esquema_pg, monkeypatch):
    """Quatro pessoas: com tudo, sem telemetria, sem nada e uma da frota."""
    for mod in (arm, servico):
        monkeypatch.setattr(mod, "ESQUEMA", esquema_pg)
    import api.campanha as pacote
    monkeypatch.setattr(pacote, "ESQUEMA", esquema_pg)
    monkeypatch.setattr(parametros, "ESQUEMA", esquema_pg)

    pessoas = {
        "FROTA": [{"cpf": "111", "nome": "FROTA COMPLETO", "grupo": "FROTA",
                   "chave": "kf1", "viagens": None, "venc_cnh": None,
                   "ativo": True}],
        "AGREGADO": [
            {"cpf": "222", "nome": "AGREGADO COMPLETO", "grupo": "AGREGADO",
             "chave": "ka1", "viagens": 10, "venc_cnh": "2030-01-01",
             "ativo": True},
            {"cpf": "333", "nome": "AGREGADO SEM TELEMETRIA", "grupo": "AGREGADO",
             "chave": "ka2", "viagens": 8, "venc_cnh": "2030-01-01",
             "ativo": True},
            {"cpf": "444", "nome": "AGREGADO SEM NADA", "grupo": "AGREGADO",
             "chave": "ka3", "viagens": 1, "venc_cnh": "2030-01-01",
             "ativo": True}],
    }
    monkeypatch.setattr(base, "participantes",
                        lambda c, ciclo: {"por_grupo": pessoas,
                                          "motivos": {"FROTA": "", "AGREGADO": ""}})
    # A GOBRAX SÓ ENXERGA DOIS. É essa ausência que decide quem disputa.
    monkeypatch.setattr(pilares, "gobrax", lambda *a, **k: {
        "notas": {"111": {"nota": 70.0, "km": 100.0},
                  "222": {"nota": 96.0, "km": 100.0}},
        "mes_gobrax": "2026-10", "motivo": "", "ambiguos": [],
        "sem_cadastro": [], "coletado_em": "x", "parcial": False})
    monkeypatch.setattr(pilares, "comportamento_janela", lambda *a, **k: {
        "por_ciclo": {}, "nao_mapeados": [], "sem_codigo": 0, "motivo": ""})
    monkeypatch.setattr(pilares, "gr_janela", lambda *a, **k: {
        "por_ciclo": {CICLO: {"111": {"nota": 80.0, "viagens": 9},
                              "222": {"nota": 90.0, "viagens": 9},
                              "333": {"nota": 95.0, "viagens": 9}}},
        "motivo": ""})
    monkeypatch.setattr(parametros, "depara", lambda: {})
    monkeypatch.setattr(parametros, "pesos_gr", lambda c: {})
    return arm.criar(CAMP, autor="gestor")


def _por_nome(d, grupo):
    return {x["nome"]: x for x in d["grupos"][grupo]["linhas"]}


def test_a_CATEGORIA_nao_e_afirmada_sobre_quem_nao_foi_medido(cenario):
    """Sem telemetria, a conduta sem ocorrência dá 100 e a nota sobe — foi assim
    que, no ensaio com dado real, quem não foi medido apareceu em primeiro
    lugar como ELITE. Agora ele fica PENDENTE, com o motivo."""
    d = servico.montar(cenario["id"], CICLO)
    por = _por_nome(d, "AGREGADO")
    sem = por["AGREGADO SEM TELEMETRIA"]
    assert sem["nota"] is not None, "ele tem nota parcial e precisa vê-la"
    assert sem["categoria"] == "PENDENTE"
    assert sem["elegivel"] is False and "sem_gobrax" in sem["faltas"]
    # e quem foi medido recebe a categoria de verdade
    assert por["AGREGADO COMPLETO"]["categoria"] in ("ELITE", "OURO")


def test_a_POSICAO_e_de_quem_DISPUTA(cenario):
    """Numerar quem está fora do sorteio produziria um "3º lugar" que não
    concorre a nada — e, pior, ordenado acima de quem concorre, porque a nota
    de um pilar só costuma ser mais alta."""
    d = servico.montar(cenario["id"], CICLO)
    por = _por_nome(d, "AGREGADO")
    assert por["AGREGADO COMPLETO"]["posicao"] == 1
    assert por["AGREGADO SEM TELEMETRIA"]["posicao"] is None
    assert por["AGREGADO SEM NADA"]["posicao"] is None
    # e o primeiro da LISTA é quem disputa, não quem tem a nota mais alta
    assert d["grupos"]["AGREGADO"]["linhas"][0]["nome"] == "AGREGADO COMPLETO"


def test_os_dois_grupos_nao_se_misturam(cenario):
    d = servico.montar(cenario["id"], CICLO)
    assert [x["nome"] for x in d["grupos"]["FROTA"]["linhas"]] == ["FROTA COMPLETO"]
    assert len(d["grupos"]["AGREGADO"]["linhas"]) == 3
    assert d["grupos"]["FROTA"]["linhas"][0]["posicao"] == 1, \
        "cada grupo tem o seu 1º lugar"


def test_a_nota_sai_com_os_pesos_do_REGULAMENTO(cenario):
    """50% de 96 + 30% de 100 (conduta sem ocorrência) + 20% de 90 = 96."""
    d = servico.montar(cenario["id"], CICLO)
    assert _por_nome(d, "AGREGADO")["AGREGADO COMPLETO"]["nota"] == 96.0


def test_o_KPI_conta_quem_esta_fora_por_falta_de_telemetria(cenario):
    d = servico.montar(cenario["id"], CICLO)
    k = d["grupos"]["AGREGADO"]["kpis"]
    assert k["participantes"] == 3 and k["elegiveis"] == 1
    assert k["sem_gobrax"] == 2


def test_no_ciclo_do_MEIO_a_categoria_nao_tira_ninguem(cenario):
    """Cravar "não é Elite" em novembro seria decidir um resultado de
    dezembro."""
    d = servico.montar(cenario["id"], CICLO)
    frota = _por_nome(d, "FROTA")["FROTA COMPLETO"]
    assert frota["categoria"] == "PRATA" and frota["elegivel"] is True


def test_no_ciclo_de_ENCERRAMENTO_so_ELITE_concorre(cenario):
    d = servico.montar(cenario["id"], "2026-12")
    assert d["encerramento"] is True
    frota = _por_nome(d, "FROTA")["FROTA COMPLETO"]
    assert frota["elegivel"] is False and "categoria" in frota["faltas"]
