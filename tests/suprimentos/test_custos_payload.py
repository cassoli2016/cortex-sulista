"""get_custos: filtros em memória sobre as linhas cacheadas e o tamanho do universo."""
from __future__ import annotations

from datetime import datetime

from api import queries


def _linha(**kw):
    base = {"agrupador": "CV - MANUTENÇÃO", "status_nf": "COM NF", "conta_contabil": "PEÇAS",
            "fornecedor": "FORN A", "filial": "1 - FIL  MTZ", "placa": "ABC1D23", "frota": "101",
            "produto": "FILTRO", "valor": 100.0, "aprovacao": "APROVADA",
            "dtemissao": datetime(2026, 8, 10), "oc": 1}
    base.update(kw)
    return base


LINHAS = [
    _linha(),
    _linha(agrupador="CV - COMBUSTÍVEL", status_nf="ABASTECIMENTO INT", aprovacao=None, valor=500.0, fornecedor="POSTO"),
    _linha(status_nf="SEM NF", aprovacao="PENDENTE DE APROVAÇÃO", valor=40.0, filial="2 - FIL  CTB"),
    _linha(status_nf="SEM NF", valor=60.0, filial="2 - FIL  CTB", fornecedor="FORN B"),
]
META = {"ts": datetime(2026, 9, 1, 9, 0)}


def _dublar(monkeypatch):
    monkeypatch.setattr(queries, "_custos_rows", lambda de, ate: (list(LINHAS), META))


def test_kpis_e_totais(monkeypatch):
    _dublar(monkeypatch)
    d = queries.get_custos("2026-08-01", "2026-08-31")
    k = d["kpis"]
    assert k["total"] == 700.0 and k["itens"] == 4
    assert k["combustivel"] == 500.0 and k["manutencao"] == 200.0
    assert k["pendente_aprovacao"] == 40.0 and k["sem_nf"] == 100.0
    assert d["totais"] == {"agrupadores": 2, "fornecedores": 3, "filiais": 2, "status": 3}
    assert d["por_filial"][0]["rotulo"] == "1 - FIL MTZ"       # espaço duplo do ERP normalizado


def test_filtro_de_origem_e_case_insensitive(monkeypatch):
    _dublar(monkeypatch)
    d = queries.get_custos("2026-08-01", "2026-08-31", origem="sem nf")
    assert d["kpis"]["itens"] == 2 and d["kpis"]["total"] == 100.0
    assert d["kpis"]["sem_nf"] == d["kpis"]["total"]


def test_filtro_de_filial_casa_com_o_rotulo_normalizado(monkeypatch):
    _dublar(monkeypatch)
    d = queries.get_custos("2026-08-01", "2026-08-31", filial="2 - FIL CTB")
    assert d["kpis"]["itens"] == 2 and d["kpis"]["total"] == 100.0
    assert d["filtro"] == {"origem": None, "filial": "2 - FIL CTB"}


def test_lista_traz_placa_para_a_identidade_do_veiculo(monkeypatch):
    _dublar(monkeypatch)
    d = queries.get_custos("2026-08-01", "2026-08-31")
    assert d["itens_lista"][0]["placa"] == "ABC1D23"
    assert d["atualizado_em"].startswith("2026-09-01T09:00")
