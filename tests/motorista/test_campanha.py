# -*- coding: utf-8 -*-
"""A campanha no celular do motorista: o que ele vê e o que não vê.

- o escopo vem da SESSÃO (não há parâmetro de motorista);
- ele acha a si mesmo pela chave OPACA — o CPF não trafega, e o agregado casa
  pelo código do ERP, que É o CPF;
- ele vê o painel do GRUPO dele, sem nome nem nota de colega;
- quem não concorre vê O QUE FALTA em frase inteira, e quantos ciclos restam;
- sem campanha em andamento não é falha: é o intervalo entre trimestres.
"""
from __future__ import annotations

import inspect
import json

import pytest

from api import queries
from api.campanha import armazenamento as arm, base
from api.motorista import campanha as mcamp
from api.premiacao import identidade

CICLO = "2026-11"
EU = {"motorista_codigo": "111", "motorista_id": 7, "nome": "EU MESMO",
      "telefone": "", "sessao_id": 1, "mestre": False}
CAMP = {"id": 1, "nome": "3º trimestre", "de_ciclo": "2026-10",
        "ate_ciclo": "2026-12", "premio": "Moto elétrica",
        "onde": "Matriz", "sorteio_em": "2026-12-20",
        "peso_gobrax": 50.0, "peso_conduta": 30.0, "peso_gr": 20.0,
        "cat_elite": 90.0, "cat_ouro": 85.0, "cat_prata": 75.0,
        "exige_gobrax": True, "situacao": "aberta"}


@pytest.fixture(autouse=True)
def cache_limpo():
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


def _linha(chave, nome, **extra):
    d = {"chave": chave, "nome": nome, "grupo": "AGREGADO", "gobrax": 92.0,
         "conduta": 100.0, "gr": 88.0, "nota": 93.6,
         "pilares": ["gobrax", "conduta", "gr"], "ausentes": [],
         "categoria": "ELITE", "viagens": 10, "venc_cnh": "2030-01-01",
         "ativo": True, "desvios": 0, "elegivel": True, "faltas": [],
         "faltas_de_medicao": [], "motivo": "", "posicao": 1}
    d.update(extra)
    return d


@pytest.fixture
def cenario(monkeypatch):
    """Eu (agregado) e um colega. A campanha e o ciclo sob controle."""
    eu = _linha(base.chave(1, "111"), "EU MESMO")
    colega = _linha("outra", "COLEGA QUE NAO ME INTERESSA", nota=99.0, posicao=2)
    estado = {"vigente": dict(CAMP), "ciclo": {
        "campanha": dict(CAMP), "ciclo": CICLO, "rotulo": "16/10 a 15/11 de 2026",
        "encerramento": False, "ciclos": ["2026-10", "2026-11", "2026-12"],
        "grupos": {
            "FROTA": {"linhas": [], "motivo": "", "kpis": {
                "participantes": 0, "com_nota": 0, "sem_gobrax": 0,
                "elegiveis": 0, "por_categoria": {}, "nota_mediana": None}},
            "AGREGADO": {"linhas": [eu, colega], "motivo": "", "kpis": {
                "participantes": 2, "com_nota": 2, "sem_gobrax": 0,
                "elegiveis": 2, "por_categoria": {"ELITE": 2},
                "nota_mediana": 96.0}}},
        "fontes": {}}}
    monkeypatch.setattr(arm, "vigente", lambda *a, **k: estado["vigente"])
    monkeypatch.setattr(mcamp, "_ciclo_montado", lambda c, ciclo: estado["ciclo"])
    monkeypatch.setattr(identidade, "cpf_do_cadastro", lambda c: None)
    return estado


def test_NAO_existe_parametro_de_motorista(cenario):
    assert list(inspect.signature(mcamp.minha).parameters) == ["sessao"]


def test_ele_se_acha_pela_chave_OPACA_e_o_CPF_nao_trafega(cenario):
    """O código do motorista agregado no ERP é o CPF: a ponte é feita no
    servidor, e o que sai é a chave."""
    d = mcamp.minha(EU)
    assert d["tem_dado"] is True and d["categoria"] == "ELITE"
    assert "111" not in json.dumps(d).replace('"111"', "")  # nem como chave
    assert "chave" not in d


def test_ele_NAO_ve_nome_nem_nota_de_colega(cenario):
    texto = json.dumps(mcamp.minha(EU), ensure_ascii=False)
    assert "COLEGA QUE NAO ME INTERESSA" not in texto
    assert "99.0" not in texto


def test_ele_ve_o_painel_do_GRUPO_dele_sem_nomes(cenario):
    d = mcamp.minha(EU)
    assert d["grupo"] == "AGREGADO" and d["grupo_rotulo"] == "agregados"
    assert d["no_grupo"] == {"participantes": 2, "concorrendo": 2,
                             "por_categoria": {"ELITE": 2}}


def test_os_pilares_saem_com_o_PESO_DO_REGULAMENTO(cenario):
    por = {x["chave"]: x for x in mcamp.minha(EU)["pilares"]}
    assert por["gobrax"]["peso"] == 50.0 and por["gobrax"]["rotulo"] == "Condução"
    assert por["conduta"]["peso"] == 30.0 and por["gr"]["peso"] == 20.0
    assert all(x["entrou"] for x in por.values())


def test_quem_NAO_concorre_ve_o_que_falta_em_FRASE_e_quantos_ciclos_restam(cenario):
    """Uma lista de códigos ("sem_gobrax") não diz nada a quem dirige."""
    cenario["ciclo"]["grupos"]["AGREGADO"]["linhas"][0] = _linha(
        base.chave(1, "111"), "EU MESMO", elegivel=False, posicao=None,
        pilares=["conduta", "gr"], gobrax=None, categoria="PENDENTE",
        faltas=["sem_gobrax"], faltas_de_medicao=["sem_gobrax"],
        motivo="sem leitura da telemetria")
    d = mcamp.minha(EU)
    assert d["concorre"] is False and d["posicao"] is None
    assert d["faltas"] and "metade do regulamento" in d["faltas"][0]
    assert d["faltam_ciclos"] == 1, "novembro para dezembro"


def test_o_prazo_e_o_premio_vao_junto(cenario):
    d = mcamp.minha(EU)
    assert d["campanha"]["premio"] == "Moto elétrica"
    assert d["campanha"]["sorteio_em"] == "2026-12-20"
    assert d["campanha"]["ate_ciclo"] == "2026-12"


def test_sem_campanha_NAO_e_falha_e_sim_o_intervalo_entre_trimestres(monkeypatch):
    monkeypatch.setattr(arm, "vigente", lambda *a, **k: None)
    d = mcamp.minha(EU)
    assert d["tem_dado"] is False and d["fora_do_escopo"] is True
    assert "Não há campanha em andamento" in d["motivo"]


def test_fonte_fora_do_ar_NAO_e_fora_do_escopo(cenario, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("erp fora")
    monkeypatch.setattr(mcamp, "_ciclo_montado", explode)
    d = mcamp.minha(EU)
    assert d["tem_dado"] is False and d["fora_do_escopo"] is False
    assert "Tente de novo" in d["motivo"]


def test_quem_nao_participa_recebe_FORA_DO_ESCOPO(cenario):
    d = mcamp.minha({**EU, "motorista_codigo": "999"})
    assert d["tem_dado"] is False and d["fora_do_escopo"] is True
    assert "não está participando" in d["motivo"]


def test_o_motorista_PROPRIO_casa_pelo_cpf_do_cadastro(cenario, monkeypatch):
    """O próprio não tem o CPF no código: quem faz a ponte é o cadastro da
    premiação, no servidor."""
    monkeypatch.setattr(identidade, "cpf_do_cadastro", lambda c: "55566677788")
    cenario["ciclo"]["grupos"]["FROTA"]["linhas"] = [
        _linha(base.chave(1, "55566677788"), "EU DA FROTA", grupo="FROTA")]
    cenario["ciclo"]["grupos"]["FROTA"]["kpis"] = {
        "participantes": 1, "com_nota": 1, "sem_gobrax": 0, "elegiveis": 1,
        "por_categoria": {"ELITE": 1}, "nota_mediana": 93.6}
    cenario["ciclo"]["grupos"]["AGREGADO"]["linhas"] = []
    d = mcamp.minha(EU)
    assert d["grupo"] == "FROTA" and d["grupo_rotulo"] == "frota"
    assert "55566677788" not in json.dumps(d)
