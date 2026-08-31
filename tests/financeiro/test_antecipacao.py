"""Simulador de antecipação de recebíveis (`_antec_simular`).

Testa a REGRA, sem banco: a função é pura (recebe dicionários, devolve
linhas, operações e o que a antecipação NÃO cobriu). É ela que decide
quanto dinheiro antecipar, então
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
    linhas, ops, descoberto = _antec_simular(_dias(5), {}, {}, 1000.0, 0.0, TAXA_DIA)
    assert ops == []
    assert all(l["saldo"] == 1000.0 for l in linhas)


def test_buraco_e_coberto_antecipando_recebivel_futuro():
    pag = {D0: 500.0}                       # gasta hoje
    rec = {D0 + timedelta(days=10): 800.0}  # só recebe em 10 dias
    linhas, ops, descoberto = _antec_simular(_dias(12), dict(rec), pag, 100.0, 0.0, TAXA_DIA)
    assert len(ops) == 1
    assert ops[0]["valor"] == 400.0          # exatamente o furo, não o título todo
    assert ops[0]["dias_antecipados"] == 10
    assert linhas[0]["saldo"] == 0.0         # ficou na reserva


def test_antecipa_o_vencimento_mais_proximo_porque_e_o_mais_barato():
    pag = {D0: 300.0}
    rec = {D0 + timedelta(days=3): 500.0, D0 + timedelta(days=30): 500.0}
    _, ops, _desc = _antec_simular(_dias(31), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    assert len(ops) == 1
    assert ops[0]["vencimento_origem"] == (D0 + timedelta(days=3)).isoformat()


def test_valor_antecipado_nao_entra_de_novo_no_vencimento_original():
    """O bug mais caro possível: contar o mesmo dinheiro duas vezes."""
    pag = {D0: 300.0, D0 + timedelta(days=5): 100.0}
    rec = {D0 + timedelta(days=3): 300.0}
    linhas, ops, descoberto = _antec_simular(_dias(7), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    # os 300 foram puxados para o dia 0; no dia 3 não pode entrar nada
    assert linhas[3]["entrada"] == 0.0
    # e o gasto do dia 5 tem de gerar NOVA necessidade, não ser coberto por
    # dinheiro que já foi usado
    assert sum(o["valor"] for o in ops) == 300.0
    assert linhas[5]["saldo"] < 0 or len(ops) == 1


def test_custo_e_proporcional_aos_dias_adiantados():
    pag = {D0: 1000.0}
    rec = {D0 + timedelta(days=30): 1000.0}
    _, ops, _desc = _antec_simular(_dias(31), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    esperado = 1000.0 * TAXA_DIA * 30
    assert abs(ops[0]["custo"] - round(esperado, 2)) < 0.01


def test_reserva_minima_dispara_antecipacao_antes_de_zerar():
    pag = {D0: 900.0}
    rec = {D0 + timedelta(days=4): 5000.0}
    # sem reserva o saldo cairia para 100 e nada seria antecipado
    _, sem, _desc = _antec_simular(_dias(5), dict(rec), pag, 1000.0, 0.0, TAXA_DIA)
    assert sem == []
    # com reserva de 500, precisa completar 400
    _, com, _desc = _antec_simular(_dias(5), dict(rec), pag, 1000.0, 500.0, TAXA_DIA)
    assert len(com) == 1 and com[0]["valor"] == 400.0


def test_nao_antecipa_recebivel_do_proprio_dia_nem_do_passado():
    """Antecipar o que vence hoje não faz sentido: já está no saldo do dia."""
    pag = {D0 + timedelta(days=2): 500.0}
    rec = {D0 + timedelta(days=2): 100.0}     # mesmo dia do furo
    _, ops, _desc = _antec_simular(_dias(3), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    assert ops == [], "não há recebível futuro; não pode inventar operação"


def test_sem_recebivel_futuro_o_saldo_fica_negativo_e_nao_trava():
    pag = {D0: 1000.0}
    linhas, ops, descoberto = _antec_simular(_dias(3), {}, pag, 0.0, 0.0, TAXA_DIA)
    assert ops == []
    assert linhas[0]["saldo"] == -1000.0, "sem fonte, o furo tem de aparecer"


def test_um_titulo_grande_cobre_varios_furos_sem_estourar_o_saldo():
    pag = {D0: 100.0, D0 + timedelta(days=1): 100.0, D0 + timedelta(days=2): 100.0}
    rec = {D0 + timedelta(days=9): 1000.0}
    linhas, ops, descoberto = _antec_simular(_dias(10), dict(rec), pag, 0.0, 0.0, TAXA_DIA)
    assert len(ops) == 3
    assert sum(o["valor"] for o in ops) == 300.0
    # sobra do título entra normalmente no vencimento
    assert linhas[9]["entrada"] == 700.0


# ---------------------------------------------------------------------------
# Elegibilidade: nem todo cliente aceita antecipação. Antes desta regra o
# plano puxava de qualquer recebível e por isso fechava SEMPRE — um plano que
# não existe na mesa de crédito.
# ---------------------------------------------------------------------------

def test_so_antecipa_o_que_e_elegivel():
    """Há R$ 800 a receber, mas só R$ 300 são de cliente com convênio."""
    pag = {D0: 500.0}
    venc = D0 + timedelta(days=10)
    rec = {venc: 800.0}
    linhas, ops, descoberto = _antec_simular(
        _dias(12), dict(rec), pag, 100.0, 0.0, TAXA_DIA,
        eleg_por_dia={venc: 300.0})
    assert sum(o["valor"] for o in ops) == 300.0, "não pode puxar além do elegível"
    assert descoberto, "o buraco que sobrou tem de ser reportado"
    assert descoberto[0]["valor"] == 100.0   # 500 pagos - 100 saldo - 300 antecipados


def test_sem_elegivel_nenhum_nao_ha_operacao_mas_ha_descoberto():
    """O caso de quem ainda não cadastrou nenhum convênio: a tela precisa
    dizer que não dá para antecipar, e não fingir que está tudo certo."""
    pag = {D0: 500.0}
    venc = D0 + timedelta(days=5)
    linhas, ops, descoberto = _antec_simular(
        _dias(7), {venc: 800.0}, pag, 0.0, 0.0, TAXA_DIA,
        eleg_por_dia={})
    assert ops == []
    assert descoberto and descoberto[0]["valor"] == 500.0


def test_sem_filtro_de_elegibilidade_o_comportamento_e_o_antigo():
    """`eleg_por_dia=None` = elegibilidade desligada. Mantém o resultado de
    antes para quem não usa portal nenhum."""
    pag = {D0: 500.0}
    venc = D0 + timedelta(days=10)
    _, ops, _desc = _antec_simular(_dias(12), {venc: 800.0}, pag, 0.0, 0.0, TAXA_DIA)
    assert sum(o["valor"] for o in ops) == 500.0


def test_elegivel_e_consumido_junto_com_o_recebivel():
    """Antecipar duas vezes o mesmo título contaria o dinheiro em dobro —
    o teto elegível tem de cair junto com o recebível."""
    pag = {D0: 300.0, D0 + timedelta(days=1): 300.0}
    venc = D0 + timedelta(days=8)
    linhas, ops, descoberto = _antec_simular(
        _dias(10), {venc: 1000.0}, pag, 0.0, 0.0, TAXA_DIA,
        eleg_por_dia={venc: 400.0})
    assert sum(o["valor"] for o in ops) == 400.0
    assert descoberto, "os R$ 200 restantes ficam descobertos"


def test_documentos_da_operacao_somam_o_valor_antecipado():
    """O rateio por título não pode perder nem sobrar centavo."""
    pag = {D0: 500.0}
    venc = D0 + timedelta(days=10)
    tit = {venc: [
        {"cliente": "A", "tipo": "CTE", "documento": "1", "valor": 300.0, "saldo": 300.0},
        {"cliente": "B", "tipo": "CTE", "documento": "2", "valor": 300.0, "saldo": 300.0},
    ]}
    _, ops, _desc = _antec_simular(_dias(12), {venc: 600.0}, pag, 0.0, 0.0,
                                   TAXA_DIA, tit_por_dia=tit)
    o = ops[0]
    assert round(sum(d["valor"] for d in o["documentos"]), 2) == o["valor"]
    # o segundo documento sai parcial: a simulação corta no centavo do que falta
    assert any(d["parcial"] for d in o["documentos"])
    assert o["documentos_total"] == 2
    assert {c["cliente"] for c in o["por_cliente"]} == {"A", "B"}


# ── lastro: convênio × planilha do portal (30/08/2026) ──────────────────────
#
# A regra estrita — só antecipar título JÁ LANÇADO num portal, provado pela
# planilha importada — está certa para a mesa do banco e continua disponível.
# Mas ela deixava a tela responder a pergunta errada: dos R$ 16,6 milhões a
# receber em 90 dias, só R$ 594 mil estavam em planilha (3,6%), enquanto
# R$ 8,2 milhões eram de cliente COM convênio assinado — TUPY, MWM-Tupy,
# Iochpe Maxion e Adient. Quem pergunta "quanto dá para antecipar" quer saber
# dos 8,2; o caminho dos que faltam é pedir o arquivo, não negociar convênio.
#
# O que estes testes amarram é o que NÃO pode mudar junto: convênio continua
# obrigatório nos dois modos, e cada documento continua dizendo se já está no
# portal — sem isso a tela mandaria levar à mesa um título que ela recusaria.


def _titulos(dia, itens):
    """[(cliente, documento, valor, no_portal)] no formato da simulação."""
    return {dia: [{"cliente": c, "tipo": "CTE", "documento": d, "valor": v,
                   "saldo": v, "no_portal": p} for c, d, v, p in itens]}


def test_o_documento_diz_se_ja_esta_no_portal():
    """Sem esta marca, afrouxar a exigência do portal apagaria a diferença
    entre "leve ao banco hoje" e "peça o arquivo ao cliente"."""
    from api.queries import _consumir_titulos
    pilha = [{"cliente": "TUPY", "tipo": "CTE", "documento": "1",
              "valor": 100.0, "saldo": 100.0, "no_portal": False},
             {"cliente": "MAXION", "tipo": "CTE", "documento": "2",
              "valor": 50.0, "saldo": 50.0, "no_portal": True}]
    usados = _consumir_titulos(pilha, 150.0)
    assert [u["no_portal"] for u in usados] == [False, True]


def test_documento_sem_a_marca_e_tratado_como_JA_no_portal():
    """Ausência de marca não pode virar pendência inventada: quem não diz nada
    é o caminho antigo, em que tudo que entrava já vinha filtrado."""
    from api.queries import _consumir_titulos
    pilha = [{"cliente": "X", "tipo": "CTE", "documento": "9",
              "valor": 10.0, "saldo": 10.0}]
    assert _consumir_titulos(pilha, 10.0)[0]["no_portal"] is True


def test_o_resumo_por_cliente_conta_quantos_faltam_e_quanto():
    """É esse par que vira a ação: "peça a planilha da TUPY, são R$ 100 em 1
    documento". Só a contagem não diz se vale o telefonema."""
    from api.queries import _antec_simular
    from datetime import date, timedelta
    hoje = date(2026, 9, 1)
    dias = [hoje + timedelta(days=i) for i in range(4)]
    venc = hoje + timedelta(days=2)
    tit = _titulos(venc, [("TUPY", "1", 100.0, False), ("MAXION", "2", 50.0, True)])
    _linhas, ops, _d = _antec_simular(
        dias, {venc: 150.0}, {hoje: 150.0}, 0.0, 0.0, 0.0,
        tit_por_dia=tit, eleg_por_dia={venc: 150.0})
    assert ops, "a simulação não gerou operação"
    porcli = {c["cliente"]: c for c in ops[0]["por_cliente"]}
    assert porcli["TUPY"]["fora_do_portal"] == 1
    assert porcli["TUPY"]["valor_fora"] == 100.0
    assert porcli["MAXION"]["fora_do_portal"] == 0
    assert porcli["MAXION"]["valor_fora"] == 0.0


# ==================================== filtro por cliente (raiz de CNPJ) ==

"""O contrato da ROTA. O filtro escolhe DE QUEM antecipar, e a chave é a raiz
do CNPJ — nunca o nome: o ERP fatura por filial ("IOCHPE MAXION - CRUZEIRO/SP"
e "- RESENDE/RJ" são duas linhas) e o convênio é da matriz, então casar por
nome deixaria metade do recebível do mesmo cliente de fora."""
import json

import pytest

from api import main


def _chamar(**kw):
    r = main.antecipacao(**kw)
    return r.status_code, json.loads(bytes(r.body).decode("utf-8"))


def test_raiz_que_nao_e_numero_e_recusada_dizendo_o_formato():
    st, d = _chamar(sacados="tupy")
    assert st == 422
    assert "raiz do CNPJ (8 dígitos)" in d["mensagem"]


def test_raiz_sem_convenio_e_RECUSA_e_nao_filtro_vazio(monkeypatch):
    """Aceitar em silêncio devolveria a tela zerada, que se lê como "não há o
    que antecipar" em vez de "você escolheu quem não pode"."""
    from api.antecipacoes import registro
    monkeypatch.setattr(registro, "raizes_elegiveis", lambda: {"84683374"})
    st, d = _chamar(sacados="99999999")
    assert st == 422
    assert "Sem convênio" in d["mensagem"] and "99999999" in d["mensagem"]


def test_cnpj_completo_vira_RAIZ_e_repetido_nao_duplica(monkeypatch):
    """A tela manda a raiz, mas um link colado à mão traz os 14 dígitos — e as
    filiais do mesmo cliente colapsam na mesma raiz."""
    from api.antecipacoes import registro
    from api import queries
    monkeypatch.setattr(registro, "raizes_elegiveis",
                        lambda: {"84683374", "02162259"})
    visto = {}

    def falso(**kw):
        visto.update(kw)
        return {"ok": True}

    monkeypatch.setattr(queries, "get_antecipacao", falso)
    st, _ = _chamar(sacados="84683374000300,84683374000100,02162259000164")
    assert st == 200
    assert visto["sacados"] == ("84683374", "02162259")


def test_sem_o_parametro_o_comportamento_e_o_de_antes(monkeypatch):
    """Filtro ausente é universo inteiro, não pilha vazia."""
    from api import queries
    visto = {}
    monkeypatch.setattr(queries, "get_antecipacao",
                        lambda **kw: visto.update(kw) or {"ok": True})
    st, _ = _chamar()
    assert st == 200 and visto["sacados"] == ()
