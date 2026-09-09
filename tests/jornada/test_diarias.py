"""Diária paga × jornada trabalhada — e os limites que a tela precisa dizer.

O QUE ESTE MÓDULO CRUZA
=======================
A folha (`sulista.diariaspagas_globus`, no AVA — 18.762 lançamentos desde
12/2020, R$ 11,1 milhões depois de tirada a duplicidade) contra os dias
efetivamente trabalhados (`jor_jornadas`, no Postgres local, vindo da
RasterJOR). Estão em BANCOS diferentes, então não há `JOIN`: o cruzamento é em
Python, pela chave que existe nos dois lados — o nome normalizado.

O DEFEITO QUE ESTES TESTES EXISTEM PARA IMPEDIR
===============================================
A mesma diária é gravada DUAS vezes na folha: o pagamento semanal
(`tipo_folha = 3`) e a folha mensal (`tipo_folha = 1`), que é a soma das
semanais da pessoa naquele mês. Até 08/09/2026 o módulo somava os dois lados —
R$ 868.421 a mais em doze meses, 31,3%. Ver `diarias._consolidar()`, que traz
as três provas.

E o que aquilo envenenava era a LEITURA. A folha mensal parou de ser carregada
em 02/2026, então os meses antigos vinham dobrados e os recentes vinham certos:
a série mostrava uma queda de 80% que era, na maior parte, o fim da
duplicidade. A queda real de set/25 a jul/26 é de 32%.

TRÊS COISAS QUE A MEDIÇÃO ENSINOU, E QUE VIRARAM REGRA
======================================================
1. **O total sozinho engana.** A diária caiu de R$ 233 mil (set/25) para
   R$ 159 mil (jul/26) — 32%. No mesmo período os motoristas com jornada caíram
   de 121 para 80. O número que compara é por pessoa e por dia trabalhado; o
   total é a conta do caixa, não a leitura.
2. **A quantidade de diárias NÃO EXISTE.** A folha tem a coluna `referencia`,
   que em folha costuma ser a quantidade — aqui ela é **0,00 em todos os
   lançamentos**. É a família do "mão de obra R$ 0 com 747 OSs" da Manutenção.
   Sem ela, e com a carga granular parada desde 12/02, dá para saber quanto se
   pagou e não quantas foram.
3. **Razão impossível é defeito, não imprecisão.** Estava escrito aqui que o
   R$/dia era "ordem de grandeza" por defasagem de competência. Ele marcava
   R$ 214 a R$ 267 por dia trabalhado nos meses dobrados, contra uma diária
   INTEIRA de R$ 107,44 — o dobro do teto físico, que nenhuma defasagem produz.
   Corrigido, dá R$ 99,92 e fica entre a meia e a inteira em todos os meses.

O ACHADO QUE NÃO DEPENDE DE RAZÃO NENHUMA é a reconciliação: 26 pessoas
receberam diária sem NENHUM dia de jornada (R$ 189.530) e são de cargo
MOTORISTA — carreteiro, truck, instrutor —, não é gente de escritório viajando.
E 18 têm jornada e não receberam diária. São perguntas, não veredito.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.jornada import diarias


# ── a duplicidade das duas réguas da folha ──────────────────────────────────


def test_a_folha_mensal_NAO_se_soma_ao_pagamento_semanal():
    """O defeito que esta aba teve até 08/09/2026.

    O evento DIARIAS PAGAS é gravado duas vezes: as semanais (`tipo_folha = 3`)
    e a folha mensal (`tipo_folha = 1`), que é a SOMA delas. Somar os dois
    lados contava o mesmo dinheiro duas vezes — R$ 868.421 em doze meses.
    """
    valor, duplicado = diarias._consolidar(1500.0, 1500.0)
    assert valor == 1500.0, "a mesma quantia foi contada duas vezes"
    assert duplicado == 1500.0, "o valor não somado precisa ficar visível"


def test_a_regra_vale_nos_QUATRO_regimes_que_a_tabela_ja_teve():
    """Sem lista de meses escrita à mão: a régua se sustenta pelo dado.

    Lista de meses envelheceria em silêncio no dia em que o ERP mudasse de
    regime outra vez — e ele já mudou três vezes desde 2020.
    """
    # até 07/2024: só folha mensal
    assert diarias._consolidar(2000.0, 0.0) == (2000.0, 0.0)
    # 08/2024 a 01/2026: as duas, iguais
    assert diarias._consolidar(2000.0, 2000.0) == (2000.0, 2000.0)
    # 2023-2024: a semanal era PARCIAL, a mensal é a completa
    assert diarias._consolidar(2000.0, 450.0) == (2000.0, 450.0)
    # de 02/2026 em diante: só semanal
    assert diarias._consolidar(0.0, 2000.0) == (2000.0, 0.0)


def test_a_mensal_residual_NAO_derruba_o_total_do_mes():
    """07/2026 deixou 29 linhas mensais de R$ 32 a R$ 65 ao lado de semanais de
    milhares. Ficar com a mensal ali apagaria 99% do mês."""
    valor, _ = diarias._consolidar(43.44, 2392.20)
    assert valor == 2392.20


def test_a_duplicidade_evitada_e_PUBLICADA():
    """Escolha de régua que não se mostra vira verdade do sistema: quem
    conferir contra a folha precisa achar a diferença, não desconfiar do
    total."""
    dados = _dados([{"competencia": "2026-01", "nome": "A", "valor": 1500.0,
                     "duplicado": 1500.0, "lancamentos": 3, "dias": 12,
                     "horas": 100.0, "tem_jornada": True, "quantidade": None}])
    m = diarias.mensal(dados)
    assert m[0]["duplicado"] == 1500.0
    assert diarias.resumo(dados, m)["duplicidade_evitada"] == 1500.0


def test_a_consulta_da_folha_SEPARA_os_dois_tipos_em_vez_de_somar_tudo():
    """Guard estrutural, contra a regressão mais provável: alguém "simplifica"
    a consulta de volta para um `sum(valor_total)` só, e a duplicidade volta
    sem sintoma nenhum — o total dobra e continua parecendo um total."""
    sql = " ".join(diarias.FOLHA_SQL.split())
    assert "tipo_folha" in sql, "a consulta perdeu a distinção entre as réguas"
    assert "tipo = 1 THEN valor ELSE 0" in sql, (
        "os dois lados precisam vir separados para `_consolidar` escolher")
    assert "tipo = 1 THEN 0 ELSE valor" in sql, (
        "o lado do detalhe virou `tipo <> 1`: linha de tipo NULO sairia dos "
        "DOIS lados e o dinheiro sumiria do total em silêncio")
    assert "sum(valor_total)::float8                 AS valor" not in sql, (
        "voltou a somar as duas réguas numa coluna só")


def test_o_tipo_de_folha_que_consolida_e_o_MESMO_no_SQL_e_na_constante():
    """String escrita à mão que descreve o código precisa ser conferida CONTRA
    o código: o SQL filtra por `tipo = 1` literal (o 9.3 não aceita parâmetro
    ali sem virar texto), e a constante é o que a documentação cita."""
    assert diarias.TIPO_FOLHA_MENSAL == 1
    sql = " ".join(diarias.FOLHA_SQL.split())
    assert "tipo = %d THEN valor" % diarias.TIPO_FOLHA_MENSAL in sql


# ── a chave do cruzamento ───────────────────────────────────────────────────


def test_o_nome_e_normalizado_dos_DOIS_lados():
    """As fontes vêm de sistemas e digitações diferentes. Sem normalizar,
    "JOSÉ DA SILVA" e "JOSE  DA SILVA" viram duas pessoas — e a reconciliação
    acusaria as duas, uma sem jornada e outra sem diária."""
    assert diarias._norm("José  da Silva ") == diarias._norm("JOSE DA SILVA")
    assert diarias._norm("  ANA   PAULA  ") == "ANA PAULA"


# ── os meses são GERADOS ────────────────────────────────────────────────────


def test_o_intervalo_de_meses_e_GERADO_e_nao_colhido():
    """`GROUP BY` não devolve o mês sem lançamento, e ele sumiria do gráfico —
    emendando o anterior com o seguinte e desenhando continuidade sobre um
    buraco. É a lição da série mensal da jornada."""
    m = diarias._competencias(date(2025, 11, 1), date(2026, 2, 15))
    assert m == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_o_mes_SEM_DADO_aparece_marcado_e_nao_some():
    dados = {"linhas": [{"competencia": "2026-01", "nome": "A", "valor": 100.0,
                         "lancamentos": 1, "dias": 2, "horas": 10.0,
                         "tem_jornada": True, "quantidade": None}],
             "sem_diaria": [], "competencias": ["2026-01", "2026-02", "2026-03"]}
    m = diarias.mensal(dados)
    assert [x["competencia"] for x in m] == ["2026-01", "2026-02", "2026-03"]
    assert m[1]["sem_dado"] is True and m[1]["valor"] == 0.0


def test_a_competencia_ABERTA_e_marcada():
    """A folha do mês corrente não fechou. Sem marcar, ela aparece como queda —
    o erro do mês parcial desenhado como barra cheia."""
    dados = {"linhas": [], "sem_diaria": [], "competencias": ["2026-07", "2026-08"]}
    m = diarias.mensal(dados, competencia_aberta="2026-08")
    assert m[0]["aberta"] is False and m[1]["aberta"] is True


# ── os denominadores ────────────────────────────────────────────────────────


def _dados(linhas, sem=(), comps=("2026-01",)):
    return {"linhas": list(linhas), "sem_diaria": list(sem),
            "competencias": list(comps)}


def test_SEM_dia_trabalhado_nao_ha_razao():
    """Preencher com zero faria a pessoa parecer barata; dividir por zero
    estouraria. `None` é a resposta certa para "não dá para dividir"."""
    dados = _dados([{"competencia": "2026-01", "nome": "A", "valor": 500.0,
                     "lancamentos": 1, "dias": 0, "horas": 0.0,
                     "tem_jornada": False, "quantidade": None}])
    m = diarias.mensal(dados)
    assert m[0]["por_dia"] is None
    assert m[0]["por_pessoa"] == 500.0, "por pessoa continua existindo"


def test_a_media_mensal_so_conta_MES_FECHADO():
    """O mês aberto puxaria a média para baixo e pareceria queda."""
    dados = _dados([
        {"competencia": "2026-06", "nome": "A", "valor": 300.0, "lancamentos": 1,
         "dias": 3, "horas": 20.0, "tem_jornada": True, "quantidade": None},
        {"competencia": "2026-07", "nome": "A", "valor": 300.0, "lancamentos": 1,
         "dias": 3, "horas": 20.0, "tem_jornada": True, "quantidade": None},
        {"competencia": "2026-08", "nome": "A", "valor": 20.0, "lancamentos": 1,
         "dias": 1, "horas": 5.0, "tem_jornada": True, "quantidade": None},
    ], comps=("2026-06", "2026-07", "2026-08"))
    m = diarias.mensal(dados, competencia_aberta="2026-08")
    r = diarias.resumo(dados, m)
    assert r["media_mensal"] == 300.0, (
        "o mês aberto entrou na média e a puxou para baixo")


def test_o_resumo_diz_a_COBERTURA_do_cruzamento():
    """Sem ela, "R$ 150 por dia trabalhado" pareceria valer para todo mundo
    quando vale só para quem a jornada conhece."""
    dados = _dados([
        {"competencia": "2026-01", "nome": "COM", "valor": 300.0,
         "lancamentos": 1, "dias": 3, "horas": 20.0, "tem_jornada": True,
         "quantidade": None},
        {"competencia": "2026-01", "nome": "SEM", "valor": 500.0,
         "lancamentos": 1, "dias": 0, "horas": 0.0, "tem_jornada": False,
         "quantidade": None},
    ])
    r = diarias.resumo(dados, diarias.mensal(dados))
    assert r["com_jornada"] == 1 and r["sem_jornada"] == 1
    assert r["valor_sem_jornada"] == 500.0
    # a razão usa SÓ quem tem jornada: 300/3, e não 800/3
    assert r["por_dia"] == 100.0


def test_quem_tem_jornada_e_NAO_recebeu_tambem_e_contado():
    """O outro lado da reconciliação. Sem ele a tela só olha para um lado."""
    dados = _dados([], sem=[{"competencia": "2026-01", "nome": "ZE",
                             "dias": 12, "horas": 90.0}])
    r = diarias.resumo(dados, diarias.mensal(dados))
    assert r["com_jornada_sem_diaria"] == 1


# ── a quantidade que não existe ─────────────────────────────────────────────


def test_a_COBERTURA_da_quantidade_e_reportada():
    """`referencia` vem 0,00 em 100% das linhas. O número zero aqui é o que
    autoriza a tela a dizer "não dá para saber quantas" em vez de estimar."""
    dados = _dados([{"competencia": "2026-01", "nome": "A", "valor": 100.0,
                     "lancamentos": 1, "dias": 1, "horas": 8.0,
                     "tem_jornada": True, "quantidade": None}])
    assert diarias.resumo(dados, diarias.mensal(dados))["com_quantidade"] == 0


# ── o ranking ───────────────────────────────────────────────────────────────


def test_o_ranking_ordena_por_VALOR_e_nao_por_razao():
    """Ordenar por R$/dia sem piso poria no topo quem trabalhou um dia e
    recebeu uma diária — o erro do ranking por percentual da DRE por Cliente."""
    dados = _dados([
        {"competencia": "2026-01", "nome": "MUITO", "valor": 5000.0,
         "lancamentos": 9, "dias": 40, "horas": 300.0, "tem_jornada": True,
         "matricula": "1", "cargo": "MOT", "quantidade": None},
        {"competencia": "2026-01", "nome": "POUCO", "valor": 200.0,
         "lancamentos": 1, "dias": 1, "horas": 8.0, "tem_jornada": True,
         "matricula": "2", "cargo": "MOT", "quantidade": None},
    ])
    top, n = diarias.por_motorista(dados)
    assert n == 2
    assert top[0]["nome"] == "MUITO"
    assert top[1]["por_dia"] == 200.0, "o de baixo volume aparece, só não lidera"


def test_a_data_em_que_a_carga_granular_parou_e_uma_CONSTANTE():
    """A tela diz a data, e não "faz tempo" — o mesmo cuidado da RasterJOR que
    ficou 136 dias fora do ar."""
    assert diarias.GRANULAR_PAROU_EM == "2026-02-12"
    dados = _dados([])
    assert diarias.resumo(dados, [])["granular_parou_em"] == "2026-02-12"
