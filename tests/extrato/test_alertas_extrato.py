"""Alertas do extrato: divergência e extrato parado."""
from __future__ import annotations

from datetime import date

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


def test_divergencia_do_mes_anterior_ainda_alerta_no_dia_1():
    """Regressão do FINDING 1 (fix round 1): no dia 1º de um mês, uma
    divergência do fechamento do mês ANTERIOR não pode desaparecer do digest.
    `_alertas_extrato` é pura e não sabe que dia é "hoje" - quem decidia (e
    apagava) essa divergência era a janela passada para `painel()` em
    `build_alertas()` (`hoje.replace(day=1)`, cobrida por `_janela_alerta`
    abaixo). Este teste documenta que, uma vez que o farol aponte para o
    último dia do mês anterior, o alerta crítico sai normalmente - a
    responsabilidade de INCLUIR essa data na consulta é da janela, não desta
    função."""
    p = _painel([{"rotulo": "Itau 539349", "mapeada": True, "dias_divergentes": 1,
                  "farol": {"estado": "diverge", "dt": "2026-07-31", "delta": -50.0,
                            "dias_sem_extrato": 1}}])
    itens = alertas._alertas_extrato(p)
    assert len(itens) == 1
    nivel, _, texto = itens[0]
    assert nivel == "critico"
    assert "31/07/2026" in texto


def test_janela_alerta_atravessa_virada_de_mes():
    """`_janela_alerta` é o que de fato corrige o FINDING 1: 30 dias corridos
    terminando hoje, não `hoje.replace(day=1)`. No dia 1º de agosto, a janela
    tem de alcançar o fechamento de julho - "mês corrente" reduziria isso a
    um único dia (hoje) e apagaria a divergência mais recente e mais
    importante (a do fechamento do mês anterior)."""
    hoje = date(2026, 8, 1)
    dt_de, dt_ate = alertas._janela_alerta(hoje)
    assert dt_ate == "2026-08-01"
    # cobre pelo menos 30 dias corridos
    dias = (date.fromisoformat(dt_ate) - date.fromisoformat(dt_de)).days
    assert dias >= 30
    # e de fato atravessa a virada do mês - não é "desde o dia 1 do mês corrente"
    assert dt_de < "2026-08-01"
    assert dt_de.startswith("2026-07")
