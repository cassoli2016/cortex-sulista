# -*- coding: utf-8 -*-
"""Preço de Peças — a régua da mediana, sem banco.

As funções que decidem o que a tela mostra são puras de propósito (o AVA é
9.3 e não tem `percentile_cont`, então a mediana já ia sair em Python). O que
estes testes prendem é o JULGAMENTO, não a aritmética:

- média inocentaria o próprio outlier que a tela existe para achar;
- produto com poucas compras não tem régua, e afirmar "sem desvio" sobre ele
  seria inventar uma;
- item barato demais não é economia, é unidade trocada — e não pode disputar
  o topo de uma tela cujo assunto é o que se pagou A MAIS;
- a economia "conservadora" tem de excluir o código que mistura peças, senão
  vira um número que não se leva a uma negociação.
"""
from __future__ import annotations

from api import suprimentos_pecas as sp


def _item(produto="P1", preco=100.0, qtd=1.0, fornecedor="F1", data="2026-01-10",
          valor=None, descricao="PECA"):
    return {"filial": 1, "solicitacao": 1, "data": data, "os": None,
            "produto": produto, "descricao": descricao,
            "fornecedor_doc": "12345678000199", "fornecedor": fornecedor,
            "quantidade": qtd, "preco": preco,
            "valor": preco * qtd if valor is None else valor}


# ---------------------------------------------------------------- mediana

def test_mediana_de_lista_par_e_impar():
    assert sp.mediana([10, 20, 30]) == 20
    assert sp.mediana([10, 20, 30, 40]) == 25
    assert sp.mediana([]) == 0.0


def test_mediana_nao_se_deixa_mover_pelo_outlier():
    """É a razão de não usar média: com um item a 100x, a média sobe tanto que
    o próprio outlier passa a caber dentro da faixa e sai do alerta."""
    precos = [100.0] * 9 + [10000.0]
    assert sp.mediana(precos) == 100.0
    media = sum(precos) / len(precos)
    assert media == 1090.0          # o outlier sozinho multiplicou a régua por 11

    # 30x a mediana é alerta grave; pela média o MESMO item cai para "atenção",
    # e um item a 1.500 (15x a mediana) sai do alerta por completo.
    assert sp.classificar(3000.0, sp.mediana(precos)) == "grave"
    assert sp.classificar(3000.0, media) == "atencao"
    assert sp.classificar(1500.0, sp.mediana(precos)) == "grave"
    assert sp.classificar(1500.0, media) == "normal"


# ---------------------------------------------------------------- faixas

def test_faixas_de_classificacao():
    assert sp.classificar(400, 100) == "grave"        # > 3x
    assert sp.classificar(200, 100) == "atencao"      # 1,5x a 3x
    assert sp.classificar(120, 100) == "normal"
    assert sp.classificar(30, 100) == "barato"        # < 1/3
    assert sp.classificar(100, 0) == "sem_regua"


# ---------------------------------------------------------------- régua

def test_produto_com_poucas_compras_nao_tem_regua():
    """Quatro compras não fazem mediana: o item fica FORA dos alertas, não
    entra como 'normal'. Dizer 'sem desvio' aí seria inventar régua."""
    itens = [_item(preco=p) for p in (100, 100, 100, 5000)]
    assert len(itens) < sp.MIN_COMPRAS
    assert sp.alertas_de_preco(itens) == []

    itens.append(_item(preco=100))
    alertas = sp.alertas_de_preco(itens)
    assert [a["preco"] for a in alertas] == [5000]
    assert alertas[0]["compras_do_produto"] == 5


def test_cobertura_da_regua_conta_so_quem_tem_base():
    itens = ([_item(produto="COM", preco=100) for _ in range(6)]
             + [_item(produto="SEM", preco=100) for _ in range(2)])
    r = sp.resumo(itens, sp.alertas_de_preco(itens), [])
    assert r["itens"] == 8
    assert r["itens_com_regua"] == 6


# ---------------------------------------------------------------- ordenação

def test_o_topo_da_lista_e_o_que_se_pagou_a_mais():
    """O item barato tem impacto ABSOLUTO maior, e mesmo assim não pode abrir
    a tela: o assunto é sobrepreço. Ordenar por |impacto| punha um item de
    R$ 0,62 em segundo lugar."""
    itens = [_item(preco=100) for _ in range(9)]
    itens.append(_item(preco=0.5, qtd=1000))    # barato, impacto -99.500
    itens.append(_item(preco=400, qtd=1))       # grave, impacto +300
    alertas = sp.alertas_de_preco(itens)
    assert [a["classe"] for a in alertas] == ["grave", "barato"]
    assert alertas[0]["impacto"] > 0
    assert alertas[1]["impacto"] < 0


def test_impacto_do_item_barato_fica_negativo():
    """Sinal preservado de propósito: comprar abaixo da mediana por erro de
    unidade não é economia, e a tela não pode somá-lo como se fosse."""
    itens = [_item(preco=100) for _ in range(9)] + [_item(preco=10, qtd=2)]
    a = sp.alertas_de_preco(itens)[0]
    assert a["classe"] == "barato"
    assert a["impacto"] == -180.0


# ---------------------------------------------------------------- dispersão

def test_dispersao_exige_dois_fornecedores_com_duas_compras_cada():
    """Uma compra isolada não é o preço praticado por um fornecedor."""
    itens = ([_item(fornecedor="A", preco=100) for _ in range(2)]
             + [_item(fornecedor="B", preco=300)])
    assert sp.dispersao_por_produto(itens) == []

    itens.append(_item(fornecedor="B", preco=300))
    d = sp.dispersao_por_produto(itens)
    assert len(d) == 1
    assert d[0]["melhor_preco"] == 100 and d[0]["pior_preco"] == 300
    assert d[0]["fornecedores"] == 2


def test_preco_do_fornecedor_e_mediana_nao_media():
    """Com média, uma compra atípica barata de um fornecedor viraria o 'melhor
    preço' e inflaria a economia de toda a linha."""
    itens = ([_item(fornecedor="A", preco=p) for p in (100, 100, 1)]
             + [_item(fornecedor="B", preco=p) for p in (120, 120)])
    d = sp.dispersao_por_produto(itens)[0]
    assert d["melhor_preco"] == 100          # mediana de A, não a média (67)
    assert d["melhor_fornecedor"] == "A"


def test_codigo_misto_sai_da_economia_conservadora():
    """Spread >= 3x é a marca do código que cobre peças diferentes. Ele conta
    no teto e NÃO conta no número que se leva para negociar."""
    misto = ([_item(produto="MIX", fornecedor="A", preco=10) for _ in range(2)]
             + [_item(produto="MIX", fornecedor="B", preco=100) for _ in range(2)])
    real = ([_item(produto="OK", fornecedor="A", preco=100) for _ in range(2)]
            + [_item(produto="OK", fornecedor="B", preco=120) for _ in range(2)])
    disp = sp.dispersao_por_produto(misto + real)
    por = {d["produto"]: d for d in disp}
    assert por["MIX"]["suspeito"] is True
    assert por["OK"]["suspeito"] is False

    r = sp.resumo(misto + real, [], disp)
    assert r["economia_conservadora"] == por["OK"]["economia"]
    assert r["economia_bruta"] > r["economia_conservadora"]


def test_economia_nunca_e_negativa():
    """Quando tudo já foi comprado no melhor preço, a economia é zero — nunca
    um número negativo que a tela mostraria como se fosse ganho."""
    itens = ([_item(fornecedor="A", preco=100) for _ in range(2)]
             + [_item(fornecedor="B", preco=100) for _ in range(2)])
    assert sp.dispersao_por_produto(itens)[0]["economia"] == 0.0


# ---------------------------------------------------------------- série e janela

def test_serie_mensal_agrupa_por_mes_de_emissao():
    itens = [_item(data="2026-01-05", preco=10), _item(data="2026-01-20", preco=20),
             _item(data="2026-02-02", preco=30)]
    assert sp.serie_mensal(itens) == [
        {"mes": "2026-01", "valor": 30.0, "itens": 2},
        {"mes": "2026-02", "valor": 30.0, "itens": 1}]


def test_periodo_padrao_comeca_no_dia_1_e_da_doze_meses():
    """Doze barras, não treze: 'hoje menos 365 dias' abria e fechava no mesmo
    mês pela metade, com a primeira e a última parciais sem nada dizer isso."""
    de, ate = sp.periodo_padrao()
    assert de.endswith("-01")
    ano_de, mes_de = int(de[:4]), int(de[5:7])
    ano_ate, mes_ate = int(ate[:4]), int(ate[5:7])
    assert (ano_ate - ano_de) * 12 + (mes_ate - mes_de) == 11
