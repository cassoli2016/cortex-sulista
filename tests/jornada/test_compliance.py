"""Testes de regressão dos cálculos PUROS de jornada (sem banco).

Travam as regras de compliance Lei 13.103 derivadas no backend: status da
CNH, semáforo de risco, conversão de intervalo em horas e o token opaco que
protege o CPF do motorista (PII).
"""
from __future__ import annotations

from datetime import date, timedelta

from api import queries as q


# ---------------- _jor_cnh_status (vencida/vencendo/ok/None) ----------------
def test_cnh_vencida():
    hoje = date(2026, 7, 17)
    assert q._jor_cnh_status(date(2026, 3, 11), hoje) == "vencida"


def test_cnh_vencendo_dentro_de_30d():
    hoje = date(2026, 7, 17)
    assert q._jor_cnh_status(hoje + timedelta(days=10), hoje) == "vencendo"
    assert q._jor_cnh_status(hoje + timedelta(days=30), hoje) == "vencendo"  # limite


def test_cnh_ok_e_sem_data():
    hoje = date(2026, 7, 17)
    assert q._jor_cnh_status(hoje + timedelta(days=31), hoje) == "ok"
    assert q._jor_cnh_status(None, hoje) is None


# ---------------- _jor_risco (semáforo) ----------------
def test_risco_critico_por_excesso_direcao():
    assert q._jor_risco(2, 0, "ok") == "critico"


def test_risco_critico_por_cnh_vencida():
    assert q._jor_risco(0, 0, "vencida") == "critico"


def test_risco_atencao_por_intervalo_ou_cnh_vencendo():
    assert q._jor_risco(0, 1, "ok") == "atencao"
    assert q._jor_risco(0, 0, "vencendo") == "atencao"


def test_risco_ok():
    assert q._jor_risco(0, 0, "ok") == "ok"
    assert q._jor_risco(0, 0, None) == "ok"


def test_risco_direcao_vence_intervalo():
    # excesso de direção (crítico) prevalece sobre intervalo (atenção)
    assert q._jor_risco(1, 5, "ok") == "critico"


# ---------------- _iv_horas (interval -> horas decimais) ----------------
def test_iv_horas_5h30():
    assert q._iv_horas(timedelta(hours=5, minutes=30)) == 5.5


def test_iv_horas_zero_none_e_negativo():
    assert q._iv_horas(timedelta(0)) == 0.0
    assert q._iv_horas(None) == 0.0
    assert q._iv_horas(timedelta(hours=-3)) == 0.0   # banco de horas negativo -> 0


# ---------------- _jor_token (PII: opaco e determinístico) ----------------
def test_token_deterministico_e_distinto():
    cpf = "12345678901"
    t1, t2 = q._jor_token(cpf), q._jor_token(cpf)
    assert t1 == t2                      # determinístico no processo
    assert q._jor_token("98765432100") != t1


def test_token_nao_revela_cpf():
    cpf = "12345678901"
    tok = q._jor_token(cpf)
    assert cpf not in tok                # o CPF não aparece no token
    assert len(tok) == 16 and all(c in "0123456789abcdef" for c in tok)
