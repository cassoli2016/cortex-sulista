"""Conciliação linha a linha: extrato do banco × razão do ERP (função pura)."""
from __future__ import annotations

import pytest

from api.extrato.conciliacao import casar


def b(dt: str, valor: float, hist: str = "", ref: str = "") -> dict:
    return {"dt": dt, "valor": valor, "historico": hist, "ref": ref or f"b{dt}{valor}"}


def e(dt: str, valor: float, hist: str = "", ref: str = "") -> dict:
    return {"dt": dt, "valor": valor, "historico": hist, "ref": ref or f"e{dt}{valor}"}


# ------------------------------------------------------- casamento exato

def test_mesmo_dia_e_mesmo_valor_casa():
    r = casar([b("2026-08-03", 1500.00)], [e("2026-08-03", 1500.00)])
    assert r["resumo"]["casados"] == 1
    assert r["casados"][0]["criterio"] == "dia_valor"
    assert r["casados"][0]["distancia"] == 0
    assert r["sobra_banco"] == [] and r["sobra_erp"] == []


def test_credito_nao_casa_com_debito_de_mesmo_valor():
    """Casar os dois esconderia exatamente o erro de sentido que a conciliação
    existe para achar."""
    r = casar([b("2026-08-03", 500.00)], [e("2026-08-03", -500.00)])
    assert r["resumo"]["casados"] == 0
    assert len(r["sobra_banco"]) == 1 and len(r["sobra_erp"]) == 1


def test_um_lancamento_do_erp_serve_a_um_so_do_banco():
    r = casar([b("2026-08-03", 100.0, ref="b1"), b("2026-08-03", 100.0, ref="b2")],
              [e("2026-08-03", 100.0, ref="e1")])
    assert r["resumo"]["casados"] == 1
    assert len(r["sobra_banco"]) == 1


def test_valor_quebrado_casa():
    """A chave é em centavos inteiros: por float, 1234.5599999999999 != 1234.56
    no índice e o par certo passaria batido - justamente nos valores quebrados,
    que são a maioria de um extrato."""
    r = casar([b("2026-08-03", 1234.56)], [e("2026-08-03", 0.56 + 1234.0)])
    assert r["resumo"]["casados"] == 1


# --------------------------------------------------------- janela de data

def test_mesmo_valor_com_atraso_casa_dentro_da_janela():
    """Caso real do Sicredi: débito de R$ 1.431,61 que o banco lança em 07/08 e
    o ERP em 10/08. Sem a janela, a conta fica com duas linhas órfãs e dois
    dias falsamente divergentes."""
    r = casar([b("2026-08-07", -1431.61)], [e("2026-08-10", -1431.61)])
    assert r["resumo"]["casados"] == 1
    assert r["casados"][0]["criterio"] == "valor_janela"
    assert r["casados"][0]["distancia"] == 3
    assert r["resumo"]["por_janela"] == 1


def test_fora_da_janela_nao_casa():
    r = casar([b("2026-08-07", -1431.61)], [e("2026-08-14", -1431.61)])
    assert r["resumo"]["casados"] == 0


def test_janela_prefere_o_candidato_mais_proximo():
    r = casar([b("2026-08-10", 900.0)],
              [e("2026-08-07", 900.0, ref="longe"), e("2026-08-09", 900.0, ref="perto")])
    assert r["casados"][0]["erp"]["ref"] == "perto"


def test_o_exato_tem_prioridade_sobre_a_janela():
    """O estágio 1 roda inteiro antes do 2: senão uma linha do banco poderia
    levar por janela o par que era o exato de outra."""
    r = casar([b("2026-08-10", 900.0, ref="bA")],
              [e("2026-08-09", 900.0, ref="eJanela"), e("2026-08-10", 900.0, ref="eExato")])
    assert r["casados"][0]["erp"]["ref"] == "eExato"
    assert r["casados"][0]["distancia"] == 0


# ------------------------------------------------------ estados do dia

def test_dia_com_tudo_casado_e_conciliado():
    r = casar([b("2026-08-03", 10.0)], [e("2026-08-03", 10.0)])
    assert r["dias"][0]["estado"] == "conciliado"


def test_dia_que_o_erp_nao_lancou():
    """Bradesco, 26/08: o banco tem R$ 1,2 mi e o razão não tem UMA linha.
    Não é divergência de valor - é lançamento que não foi feito, com outro
    dono e outra ação."""
    r = casar([b("2026-08-26", 1212725.46)], [])
    d = r["dias"][0]
    assert d["estado"] == "erp_nao_lancou"
    assert d["erp_linhas"] == 0


def test_dia_que_so_existe_no_erp():
    r = casar([], [e("2026-08-26", 500.0)])
    assert r["dias"][0]["estado"] == "so_no_erp"


def test_granularidade_quando_sobra_dos_dois_lados_mas_o_valor_fecha():
    """O caso dominante: na Caixa, 03/08 tem 15 linhas no banco contra 372 no
    razão. Exigir par para toda linha seria exigir o impossível; o que decide
    é o resíduo."""
    banco = [b("2026-08-03", 300.0, ref="b1")]
    erp = [e("2026-08-03", 100.0, ref="e1"), e("2026-08-03", 200.0, ref="e2")]
    r = casar(banco, erp)
    d = r["dias"][0]
    assert r["resumo"]["casados"] == 0
    assert d["estado"] == "granularidade"
    assert d["residuo"] == 0.0
    assert d["sobra_banco_linhas"] == 1 and d["sobra_erp_linhas"] == 2


def test_diverge_quando_o_residuo_nao_fecha():
    r = casar([b("2026-08-03", 300.0)], [e("2026-08-03", 250.0)])
    d = r["dias"][0]
    assert d["estado"] == "diverge"
    assert d["residuo"] == pytest.approx(50.0)


def test_residuo_de_centavo_e_divergencia_mas_com_materialidade_relativa():
    """Três centavos sobre R$ 885 mil e R$ 292 mil sobre R$ 300 mil são os dois
    `diverge` - o estado não mente - mas a tela precisa saber qual abrir
    primeiro."""
    r = casar([b("2026-08-03", 885435.84)], [e("2026-08-03", 885435.81)])
    d = r["dias"][0]
    assert d["estado"] == "diverge"
    assert d["residuo"] == pytest.approx(0.03)
    assert d["residuo_pct"] < 0.001


# ------------------------------------------------------------- resumo

def test_valor_sem_explicacao_ignora_os_dias_que_fecham():
    """Somar o resíduo de todos os dias diluiria o número: os dias de
    granularidade trazem ruído de centavos com os dois sinais, e um total que
    some por compensação é pior que total nenhum."""
    # Os valores do dia 04 são diferentes de tudo do dia 03 de propósito: com
    # um valor repetido, a janela de ±3 dias casaria entre os dois dias e o
    # teste mediria outra coisa (ver `test_janela_pode_casar_entre_dias`).
    banco = [b("2026-08-03", 300.0, ref="b1"), b("2026-08-04", 777.0, ref="b2")]
    erp = [e("2026-08-03", 100.0, ref="e1"), e("2026-08-03", 200.0, ref="e2")]
    r = casar(banco, erp)
    est = r["resumo"]["dias_por_estado"]
    assert est.get("granularidade") == 1, "03/08: 1 linha do banco = 2 do razão"
    assert est.get("erp_nao_lancou") == 1, "04/08: o razão não tem o dia"
    assert r["resumo"]["valor_sem_explicacao"] == pytest.approx(777.0)
    assert r["resumo"]["dias_a_tratar"] == 1


def test_janela_pode_casar_entre_dias():
    """Consequência assumida da janela: um valor repetido em dias vizinhos pode
    ser casado atravessado. É o preço de tratar atraso de compensação, e o
    resíduo do dia continua contando a verdade dos dois lados."""
    r = casar([b("2026-08-04", 100.0, ref="b2")], [e("2026-08-03", 100.0, ref="e1")])
    assert r["resumo"]["casados"] == 1
    assert r["casados"][0]["criterio"] == "valor_janela"


def test_percentual_de_casados():
    r = casar([b("2026-08-03", 10.0, ref="b1"), b("2026-08-03", 20.0, ref="b2")],
              [e("2026-08-03", 10.0, ref="e1")])
    assert r["resumo"]["casados_pct"] == 50.0


def test_sem_lancamento_nenhum_nao_estoura():
    r = casar([], [])
    assert r["resumo"]["casados_pct"] == 0.0
    assert r["dias"] == []
    assert r["resumo"]["valor_sem_explicacao"] == 0.0


def test_resultado_e_estavel_entre_execucoes():
    """O casamento é guloso: sem ordem fixa, quem fica com quem muda a cada
    execução e a tela mudaria sozinha entre dois cliques."""
    banco = [b("2026-08-03", 50.0, ref=f"b{i}") for i in range(5)]
    erp = [e("2026-08-03", 50.0, ref=f"e{i}") for i in range(3)]
    pares = [{(c["banco"]["ref"], c["erp"]["ref"]) for c in casar(banco, erp)["casados"]}
             for _ in range(3)]
    assert pares[0] == pares[1] == pares[2]
    assert len(pares[0]) == 3
