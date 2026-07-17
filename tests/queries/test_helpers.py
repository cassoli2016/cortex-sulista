"""Testes de regressão dos cálculos PUROS do queries.py (sem banco).

Travam as regras de negócio críticas contra alterações acidentais:
competência, alocação de linha da DRE, máscara de PII, status de OC,
ponto de equilíbrio, previsão sazonal e o merge da heurística de clientes.
"""
from __future__ import annotations

from api import queries as q


# ---------------- _comp_bounds (competência -> [de, ate)) ----------------
def test_comp_bounds_periodo():
    assert q._comp_bounds("2026-01", "2026-03") == ("2026-01-01", "2026-04-01")


def test_comp_bounds_virada_de_ano():
    assert q._comp_bounds("2026-12", "2026-12") == ("2026-12-01", "2027-01-01")


def test_comp_bounds_mes_unico():
    assert q._comp_bounds("2026-06", "2026-06") == ("2026-06-01", "2026-07-01")


# ---------------- _dre_aloca (agrupador -> linha da DRE) ----------------
def test_dre_aloca_prefixos():
    assert q._dre_aloca("CV - COMBUSTIVEL") == "CUSTO VARIAVEL"
    assert q._dre_aloca("CF - FOLHA MOT") == "CUSTO FIXO"
    assert q._dre_aloca("CR - CREDITO ICMS") == "CREDITOS TRIBUTARIOS"


def test_dre_aloca_nome_e_acento():
    assert q._dre_aloca("IMPOSTOS FEDERAIS") == "IMPOSTOS FEDERAIS"
    # normaliza acento/caixa
    assert q._dre_aloca("CV - COMBUSTÍVEL") == "CUSTO VARIAVEL"


def test_dre_aloca_desconhecido():
    assert q._dre_aloca("QUALQUER COISA SEM MATCH") is None


# ---------------- _mask_doc (PII) ----------------
def test_mask_doc_cnpj():
    assert q._mask_doc("12345678000199") == "12" + "•" * 10 + "99"


def test_mask_doc_formatado_so_alfanumerico():
    assert q._mask_doc("12.345.678/0001-99") == "12" + "•" * 10 + "99"


def test_mask_doc_curto_e_vazio():
    assert q._mask_doc("1234") == "••••"
    assert q._mask_doc("") == ""
    assert q._mask_doc(None) == ""


# ---------------- _oc_status ----------------
def test_oc_status():
    assert q._oc_status({"sem_aprovacao": True, "valor_pendente": 0, "previsao_vencida": False}) == "aprovacao"
    assert q._oc_status({"sem_aprovacao": False, "valor_pendente": 100, "previsao_vencida": True}) == "atrasada"
    assert q._oc_status({"sem_aprovacao": False, "valor_pendente": 100, "previsao_vencida": False}) == "aguardando"
    assert q._oc_status({"sem_aprovacao": False, "valor_pendente": 0, "previsao_vencida": True}) == "recebida"


# ---------------- _ponto_equilibrio ----------------
def test_ponto_equilibrio():
    g = {"receita_bruta": 1000.0, "deducoes": -100.0, "custo_var": -200.0,
         "custo_motorista": -100.0, "fixo": -90.0, "adm": 0.0, "depreciacao": 0.0}
    r = q._ponto_equilibrio(g)
    assert r is not None
    assert abs(r["mc_pct"] - (2 / 3 * 100)) < 1e-6         # (900-300)/900
    assert abs(r["fixos_mes"] - 7.5) < 1e-6                # 90/12
    assert abs(r["faturamento_minimo_mes"] - 12.5) < 1e-6  # (135*1000/900)/12


def test_ponto_equilibrio_sem_receita():
    assert q._ponto_equilibrio({"receita_bruta": 0.0, "deducoes": 0.0}) is None


# ---------------- _previsao_sazonal ----------------
def test_previsao_sazonal_poucos_meses_runrate():
    hist = [{"mnum": m, "valor": 100.0} for m in range(1, 6)]  # 5 meses
    fn, metodo = q._previsao_sazonal(hist, fallback=123.0)
    assert metodo == "runrate"
    assert fn(3) == 123.0


def test_previsao_sazonal_serie_estavel():
    hist = [{"mnum": (i % 12) + 1, "valor": 100.0} for i in range(24)]  # 24 meses uniformes
    fn, metodo = q._previsao_sazonal(hist, fallback=0.0)
    assert metodo == "sazonal"
    assert abs(fn(7) - 100.0) < 1e-6   # índice 1.0, nível 100


# ---------------- _merge_heuristica (recuperação de cliente sem coleta) ----------------
def test_merge_heuristica_soma_no_cliente_e_abate_do_sem():
    clientes = [{"codigo": "(sem)", "cliente": "(sem cliente)", "ctes": 10, "receita": 1000.0},
                {"codigo": "AG1", "cliente": "ACME", "ctes": 5, "receita": 500.0}]
    heur = [{"codigo": "AG1", "cliente": "ACME", "ctes": 3, "receita": 300.0}]
    out = q._merge_heuristica(clientes, heur, ("receita",))
    acme = next(c for c in out if c["codigo"] == "AG1")
    sem = next(c for c in out if c["codigo"] == "(sem)")
    assert acme["receita"] == 800.0 and acme["ctes"] == 8
    assert sem["receita"] == 700.0 and sem["ctes"] == 7


def test_merge_heuristica_cria_cliente_novo():
    clientes = [{"codigo": "(sem)", "cliente": "(sem cliente)", "ctes": 10, "receita": 1000.0}]
    heur = [{"codigo": "AG2", "cliente": "BETA", "ctes": 2, "receita": 200.0}]
    out = q._merge_heuristica(clientes, heur, ("receita",))
    beta = next((c for c in out if c["codigo"] == "AG2"), None)
    assert beta is not None and beta["receita"] == 200.0
    sem = next((c for c in out if c["codigo"] == "(sem)"), None)
    assert sem is not None and sem["receita"] == 800.0
