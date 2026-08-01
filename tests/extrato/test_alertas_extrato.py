"""Alertas do extrato: divergência e extrato parado."""
from __future__ import annotations

from api import alertas


def _painel(contas):
    return {"kpis": {}, "contas": contas, "dias": [], "importacoes": []}


def test_divergencia_gera_alerta_critico():
    p = _painel([{"rotulo": "Itau 539349", "mapeada": True, "dias_divergentes": 2,
                  "farol": {"estado": "diverge", "dt": "2026-07-31", "delta": -1250.40,
                            "dias_sem_extrato": 1}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    nivel, titulo, texto = itens[0]
    assert nivel == "critico"
    assert "Itau 539349" in texto and "31/07/2026" in texto
    assert "1.250,40" in texto


def test_extrato_parado_gera_atencao():
    p = _painel([{"rotulo": "Bradesco 1239066", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "desatualizado", "dt": "2026-07-20", "delta": 0.0,
                            "dias_sem_extrato": 12}}])
    itens = alertas._alertas_extrato(p)
    assert itens and itens[0][0] == "atencao"
    assert "12 dias" in itens[0][2]


def test_conta_sem_vinculo_nao_alerta():
    p = _painel([{"rotulo": "CSV novo", "mapeada": False, "dias_divergentes": 0,
                  "farol": {"estado": "sem_mapa", "dt": None, "delta": None,
                            "dias_sem_extrato": None}}])
    assert alertas._alertas_extrato(p) == []


def test_tudo_ok_nao_alerta():
    p = _painel([{"rotulo": "Itau", "mapeada": True, "dias_divergentes": 0,
                  "farol": {"estado": "ok", "dt": "2026-07-31", "delta": 0.0,
                            "dias_sem_extrato": 1}}])
    assert alertas._alertas_extrato(p) == []
