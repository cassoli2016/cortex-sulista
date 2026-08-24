"""Simulador de antecipação de recebíveis (`_antec_simular`).

Testa a REGRA, sem banco: a função é pura (recebe dicionários, devolve
linhas e operações). É ela que decide quanto dinheiro antecipar, então
cada invariante aqui vale um erro de tesouraria.
"""
from __future__ import annotations

from datetime import date, timedelta

from api.queries import _antec_simular

D0 = date(2026, 1, 5)          # segunda-feira
TAXA_DIA = (2.0 / 100) / 30    # 2% a.m.


def _dias(n):
    return [D0 + timedelta(days=i) for i in range(n)]


def test_caixa_sobrando_nao_antecipa_nada():
    linhas, ops = _antec_simular(_dias(5), {}, {}, 1000.0, 0.0, TAXA_DIA)
    assert ops == []
    assert all(l["saldo"] == 1000.0 for l in linhas)


def test_buraco_e_coberto_antecipando_recebivel_futuro():
    pag = {D0: 500.0}                       # gasta hoje
    rec = {D0 + timedelta(days=10): 800.0}  # só recebe em 10 dias
    linhas, ops = _antec_simular(_dias(12), dict(rec), pag, 100.0, 0.0, TAXA_DIA)
    assert len(ops) == 1
    assert ops[0]["valor"] == 400.0          # exatamente o furo, não o título todo
    assert ops[0]["dias_antecipados"] == 10
    assert linhas[0]["saldo"] == 0.0         # ficou na reserva


def test_antecipa_o_vencimento_mais_proximo_porque_e_o_mais_barato():
    pag = {D0: 300.0}
    rec = {D0 + timedelta(days=3): 500.0, D0 + timedelta(days=30): 500.0}
    _, ops = _antec_simular(_dias(31), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    assert len(ops) == 1
    assert ops[0]["vencimento_origem"] == (D0 + timedelta(days=3)).isoformat()


def test_valor_antecipado_nao_entra_de_novo_no_vencimento_original():
    """O bug mais caro possível: contar o mesmo dinheiro duas vezes."""
    pag = {D0: 300.0, D0 + timedelta(days=5): 100.0}
    rec = {D0 + timedelta(days=3): 300.0}
    linhas, ops = _antec_simular(_dias(7), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    # os 300 foram puxados para o dia 0; no dia 3 não pode entrar nada
    assert linhas[3]["entrada"] == 0.0
    # e o gasto do dia 5 tem de gerar NOVA necessidade, não ser coberto por
    # dinheiro que já foi usado
    assert sum(o["valor"] for o in ops) == 300.0
    assert linhas[5]["saldo"] < 0 or len(ops) == 1


def test_custo_e_proporcional_aos_dias_adiantados():
    pag = {D0: 1000.0}
    rec = {D0 + timedelta(days=30): 1000.0}
    _, ops = _antec_simular(_dias(31), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    esperado = 1000.0 * TAXA_DIA * 30
    assert abs(ops[0]["custo"] - round(esperado, 2)) < 0.01


def test_reserva_minima_dispara_antecipacao_antes_de_zerar():
    pag = {D0: 900.0}
    rec = {D0 + timedelta(days=4): 5000.0}
    # sem reserva o saldo cairia para 100 e nada seria antecipado
    _, sem = _antec_simular(_dias(5), dict(rec), pag, 1000.0, 0.0, TAXA_DIA)
    assert sem == []
    # com reserva de 500, precisa completar 400
    _, com = _antec_simular(_dias(5), dict(rec), pag, 1000.0, 500.0, TAXA_DIA)
    assert len(com) == 1 and com[0]["valor"] == 400.0


def test_nao_antecipa_recebivel_do_proprio_dia_nem_do_passado():
    """Antecipar o que vence hoje não faz sentido: já está no saldo do dia."""
    pag = {D0 + timedelta(days=2): 500.0}
    rec = {D0 + timedelta(days=2): 100.0}     # mesmo dia do furo
    _, ops = _antec_simular(_dias(3), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    assert ops == [], "não há recebível futuro; não pode inventar operação"


def test_sem_recebivel_futuro_o_saldo_fica_negativo_e_nao_trava():
    pag = {D0: 1000.0}
    linhas, ops = _antec_simular(_dias(3), {}, pag, 0.0, 0.0, TAXA_DIA)
    assert ops == []
    assert linhas[0]["saldo"] == -1000.0, "sem fonte, o furo tem de aparecer"


def test_um_titulo_grande_cobre_varios_furos_sem_estourar_o_saldo():
    pag = {D0: 100.0, D0 + timedelta(days=1): 100.0, D0 + timedelta(days=2): 100.0}
    rec = {D0 + timedelta(days=9): 1000.0}
    linhas, ops = _antec_simular(_dias(10), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    assert len(ops) == 3
    assert sum(o["valor"] for o in ops) == 300.0
    # sobra do título entra normalmente no vencimento
    assert linhas[9]["entrada"] == 700.0
