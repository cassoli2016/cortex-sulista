"""O freetime contratado casa pela MERCADORIA, e para de ser sorteado.

O PEDIDO, de quem opera em 10/09/2026: "o freetime contratado na Minha
Operação precisa validar com o SAC / Freetime".

O QUE A VALIDAÇÃO ACHOU
=======================

O contrato (`sulista.sac_freetimecliente`) tem UMA LINHA POR TIPO DE
MERCADORIA, e um cliente pode ter várias ativas ao mesmo tempo, TODAS com o
mesmo `dtinicio`:

    IOCHPE MAXION  4 linhas, mesma data: genérica 3h · CONJUNTOS/RODAS/
                   ESCADAS 6,5h
    LEAR           4 linhas, mesma data: PEÇAS e EMBALAGENS 3h · ESPUMA 5h
    VOLVO          2 linhas, datas DIFERENTES (1h -> 2h) — revisão de
                   contrato, e aí a mais nova manda mesmo

A tela `sac` resolvia isso com `DISTINCT ON (agrupamentocliente) ... ORDER BY
dtinicio DESC`. Com as datas empatadas, o banco escolhe UMA AO ACASO — e como
o `valor_est` multiplica a hora excedente pelo valor contratado, o sorteio
mexia em DINHEIRO.

Medido na hora, três execuções seguidas deram o MESMO resultado: a ordem
estava estável por acidente (ordem física da tabela), não por regra. É o pior
tipo de bug latente — ele não aparece em teste nenhum até um VACUUM, um índice
novo ou um plano diferente reordenarem as linhas.

O QUE MUDOU
===========

A permanência é medida na COLETA, e `coleta.mercadorias` está preenchida em
100% das 17.269 coletas de 180 dias (80 valores distintos) com o MESMO
vocabulário do contrato. Então não é preciso escolher: casa-se.

    linha da mercadoria -> linha genérica -> último recurso (maior freetime)

Efeito medido em 60 dias: R$ 877.771,15 -> R$ 949.714,50 (+R$ 71.943). O
aumento é TODO de dois clientes, e por construção:

    IOCHPE MAXION  +R$ 71.244,35  (usava 6,5h para tudo; 75,7% das coletas
                                   são de mercadoria sem cláusula e valem 3h)
    LEAR           +R$    699,00
    todos os demais       0,00    (têm uma cláusula só — nada a escolher)
"""
from __future__ import annotations

import re

from api import queries as q


# ────────────────────────────────────────────── a normalização do texto

def test_a_normalizacao_tira_acento_e_plural_dos_DOIS_lados():
    """O contrato escreve "ESPUMA PARA BANCOS" e a coleta "ESPUMAS PARA
    BANCO"; um lado tem "PEÇAS" com cedilha e o outro "PECAS" sem. É a mesma
    mercadoria, e um `=` cru diz que não."""
    for expr in (q.SQL_MERC_CONTRATO, q.SQL_MERC_COLETA):
        assert "upper(" in expr, "sem maiúscula o casamento morre na primeira grafia"
        assert "translate(" in expr, "sem tirar acento, PEÇAS nunca casa com PECAS"
        assert "regexp_replace(" in expr, "sem tirar o plural, BANCOS nunca casa com BANCO"
    # cada um olha a SUA coluna — trocar as duas casaria o contrato com ele mesmo
    assert "observacao" in q.SQL_MERC_CONTRATO
    assert "c.mercadorias" in q.SQL_MERC_COLETA


def test_a_normalizacao_NAO_aproxima_o_que_e_decisao_comercial():
    """"CONJUNTO PHEVUS" (382 coletas da Maxion em 180 dias) não é
    "CONJUNTOS". Pode ser a mesma coisa comercialmente — e se for, o freetime
    passa de 3h para 6,5h e a estadia cai. Isso é decisão de quem negocia o
    contrato, não de uma heurística de texto escondida numa query.

    O guard existe para o dia em que alguém tentar resolver isso com um LIKE:
    a aproximação tem de ser DECLARADA, não inventada aqui dentro.
    """
    for expr in (q.SQL_MERC_CONTRATO, q.SQL_MERC_COLETA):
        assert "%" not in expr and "LIKE" not in expr.upper(), (
            "casamento por prefixo/parcial entrou na normalização — isso "
            "decide dinheiro e precisa ser decisão comercial declarada")


# ────────────────────────────────────────────── a ordem de resolução

def test_a_resolucao_tenta_MERCADORIA_depois_generica_depois_o_resto():
    """A ordem é a regra, e ela está no `coalesce`. Invertê-la faria a
    genérica atropelar a cláusula específica — 6,5h de RODAS viraria 3h."""
    m = re.search(r"coalesce\(esp\.freetimedescarga,\s*ger\.freetimedescarga,\s*"
                  r"ft\.freetimedescarga\)", q.SAC_DET_SQL)
    assert m, "a ordem mercadoria -> generica -> ultimo recurso saiu do SQL"
    mc = re.search(r"coalesce\(esp\.freetimecarga,\s*ger\.freetimecarga,\s*"
                   r"ft\.freetimecarga\)", q.SAC_DET_SQL)
    assert mc, "a carga ficou com outra ordem de resolução que a descarga"


def test_a_tela_sabe_QUAL_clausula_respondeu():
    """"3h porque o contrato diz 3h para RODAS" e "3h porque não há cláusula
    para esta mercadoria" são afirmações diferentes, e a segunda é a que
    alguém precisa ir resolver. Sem `origem_ft` as duas viram o mesmo número.
    """
    # calculado E publicado — são dois lugares, e conferir só a palavra
    # aprovaria o `CASE` com outro nome, porque o `SELECT` externo ainda a
    # escreve. (Este guard nasceu verde com o alvo sabotado, por isso.)
    assert "END AS origem_ft" in q.SAC_DET_SQL, "o CASE que decide a origem sumiu"
    assert re.search(r"^SELECT .*\borigem_ft\b", q.SAC_DET_SQL, re.M), (
        "a origem é calculada e não sai na linha — a tela não a recebe")
    for estado in ("'mercadoria'", "'generico'", "'sem_clausula'"):
        assert estado in q.SAC_DET_SQL, (
            "o estado %s sumiu — a tela perde a distinção" % estado)
    assert "AS mercadoria" in q.SAC_DET_SQL, (
        "sem a mercadoria na linha, ninguém confere por que aquele freetime "
        "foi aplicado")


def test_o_ultimo_recurso_e_o_MAIOR_freetime_e_nao_um_sorteio():
    """Quando nada casa e não há genérica, ainda é preciso um número. O maior
    é o único defensável: com ele, só vira excedente a hora que excede sob
    QUALQUER cláusula do contrato — a estimativa é um piso do que se pode
    afirmar. O menor inflaria a cobrança com horas talvez contratadas.
    """
    ft = q.SAC_FT_REP
    assert "freetimedescarga DESC" in ft and "freetimecarga DESC" in ft, (
        "o desempate voltou a depender da ordem física da tabela")
    # e o desempate final é TOTAL: sem ele, duas linhas iguais em tudo o mais
    # voltam a empatar e o banco escolhe
    assert "coalesce(observacao,'')" in ft, "falta o desempate final"


def test_o_desempate_por_MERCADORIA_e_dentro_da_mesma_clausula():
    """O `DISTINCT ON` continua existindo, e agora ele desempata dentro da
    MESMA mercadoria — o que é revisão de contrato de verdade (a VOLVO tem
    duas datas para a mesma cláusula), e não sorteio entre cláusulas
    diferentes."""
    assert "DISTINCT ON (agrupamentocliente, merc)" in q.SAC_FT_MERC
    assert "dtinicio DESC" in q.SAC_FT_MERC, (
        "sem a data, a revisão de contrato deixa de valer sobre a anterior")


def test_as_duas_CTEs_entram_na_estimativa():
    """`SAC_FT_MERC` só serve se estiver na consulta — constante definida e
    não usada é o defeito que passa despercebido."""
    assert "{SAC_FT_MERC}" not in q.SAC_DET_SQL, "a f-string não foi resolvida"
    assert "ftm AS (" in q.SAC_DET_SQL
    assert "LEFT JOIN ftm esp" in q.SAC_DET_SQL
    assert "LEFT JOIN ftm ger" in q.SAC_DET_SQL


def test_a_consulta_continua_valida_no_postgres_93_do_ERP():
    """O AVA é 9.3: `FILTER (WHERE …)` não existe lá, e o erro aponta para o
    meio do agregado em vez de para a versão. Esta regra já custou uma sessão
    à casa; o guard é barato."""
    assert "FILTER (WHERE" not in q.SAC_DET_SQL
    assert "FILTER (WHERE" not in q.SAC_FT_MERC
