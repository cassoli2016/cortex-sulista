"""Diária paga × jornada trabalhada — e os limites que a tela precisa dizer.

O QUE ESTE MÓDULO CRUZA
=======================
A folha (`sulista.diariaspagas_globus`, no AVA — 18.224 lançamentos desde
12/2020, R$ 14,3 milhões) contra os dias efetivamente trabalhados
(`jor_jornadas`, no Postgres local, vindo da RasterJOR). Estão em BANCOS
diferentes, então não há `JOIN`: o cruzamento é em Python, pela chave que
existe nos dois lados — o nome normalizado. Medido: 120 dos 134 nomes da folha
nos últimos 12 meses aparecem na jornada.

TRÊS COISAS QUE A MEDIÇÃO ENSINOU, E QUE VIRARAM REGRA
======================================================
1. **O total sozinho engana.** A diária caiu de R$ 466 mil (set/25) para R$ 91
   mil (jul/26) — 80%. No mesmo período os motoristas com jornada caíram de 127
   para 79. O número que compara é por pessoa e por dia trabalhado; o total é a
   conta do caixa, não a leitura.
2. **A quantidade de diárias NÃO EXISTE.** A folha tem a coluna `referencia`,
   que em folha costuma ser a quantidade — aqui ela é **0,00 em 4.833 de 4.833
   lançamentos**. É a família do "mão de obra R$ 0 com 747 OSs" da Manutenção.
   Sem ela, e com a carga granular parada desde 12/02, dá para saber quanto se
   pagou e não quantas foram.
3. **A competência da folha não é a data do trabalho.** A mediana de R$/dia dá
   R$ 132 contra uma diária inteira de R$ 102,58, e deslocar um ou dois meses
   não conserta (R$ 137 e R$ 123) — não é defasagem limpa. Então a razão é
   ORDEM DE GRANDEZA, e serve para comparar motoristas entre si na mesma
   janela, onde a distorção é a mesma para todos.

O ACHADO QUE NÃO DEPENDE DE RAZÃO NENHUMA é a reconciliação: 24 pessoas
receberam diária sem NENHUM dia de jornada (R$ 238.847) e todas têm cargo de
MOTORISTA — carreteiro, truck, instrutor —, não é gente de escritório viajando.
E 83 têm jornada e não receberam diária. São perguntas, não veredito.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.jornada import diarias


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
