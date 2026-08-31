# -*- coding: utf-8 -*-
"""Validação de pedágio sobre o que o ERP já tem — sem depender de fornecedor.

OS TRÊS NÚMEROS QUE EXISTEM, E QUE NÃO BATEM (12 meses, medidos em 30/08/2026)
=============================================================================
    conhecimento.valortaxapedagio   R$ 4,86 mi   em 43.803 CT-e   (cobrado do cliente)
    coleta.valorpedagio             R$ 5,69 mi   em 33.628 coletas (86,6% preenchido)
    valepedagio.valorcartao         R$ 1,76 mi   em  9.521 vales  (adiantado ao transportador)

O vale cobre 36% do que se cobra do cliente, e a quebra por modalidade explica
a maior parte: **AGR R$ 1,26 mi (71%)**, LOC R$ 307 mil, TER R$ 143 mil e frota
própria só R$ 56 mil. É coerente com a Lei 10.209/2001 — o vale-pedágio é
obrigação do embarcador para com o transportador autônomo/terceiro, e a frota
própria passa por tag. Mas os R$ 3,1 mi de diferença precisam de dono, e é o
que esta tela nomeia.

CAMPOS QUE EXISTEM E NUNCA SÃO USADOS — a tela diz isso, não os soma
====================================================================
    conhecimento.valorpedagiodestacado    0 de 68.367 CT-e  (0,0%)
    coleta.valorpedagiocompra             0 de 38.840       (0,0%)
    coleta.valorpedagiocontratadocalculado 0 de 38.840      (0,0%)

É a família do "mão de obra R$ 0 com 747 OSs": campo que existe, parece número
e não é. Somá-los produziria zero com cara de dado.

O VALE É QUASE SEMPRE MAIOR QUE O PEDÁGIO DA COLETA, E ISSO É SISTEMÁTICO
=========================================================================
Nos 8.868 vales ligados a uma coleta (tipo de documento 27), a comparação dá:

    iguais ao centavo ......    70  ( 0,8%)
    vale MAIOR .............. 7.832  (88,3%)
    vale menor ..............   966  (10,9%)
    coleta com pedágio zero ..   24  ( 0,3%)

Não é cauda: é regra. A tela mostra a RAZÃO e a quebra, não um veredito — a
explicação provável (o vale cobre ida e volta, a coleta lança o trecho
carregado) é hipótese de quem opera, não conclusão do painel. Mesma regra do
plano de manutenção com marcador furado: mostrar a evidência ao lado do número
acusado e deixar o veredito com quem mantém o cadastro.

O JOIN É COMPOSTO, E ERRAR ISSO INFLA TUDO
==========================================
`coleta.numero` NÃO é único — a chave é `grupo, empresa, filial, unidade,
numero`. Ligando só pelo número, os 8.868 vales viravam **24.803 linhas**, quase
três vezes. É o espelho do "coluna zerada com KPI cheio": ali o join não casava
nada, aqui casa demais. Quando o total muda de ordem de grandeza ao ligar duas
tabelas, é o join, não o negócio.
"""
from __future__ import annotations

import logging

from .. import db

log = logging.getLogger(__name__)

# COLETA = 27, PROGRAMAÇÃO DE EMBARQUE = 200 (`tipodocumento` do ERP). São os
# dois únicos tipos que aparecem em 12 meses; nomear em vez de deixar o código
# cru é o que separa esta tela da coluna "Tipo (cód.)" da Manutenção, que ficou
# crua porque ali NÃO havia tabela de domínio.
TIPO_COLETA = 27
TIPO_PROGRAMACAO = 200

# ── as três séries, por mês ─────────────────────────────────────────────────
#
# Os meses são GERADOS, não colhidos: `GROUP BY` não devolve o mês sem
# lançamento, e o gráfico emendaria o anterior com o seguinte desenhando
# continuidade sobre um buraco. É a lição da série mensal da jornada.
MENSAL_SQL = """
SELECT to_char(m.mes, 'YYYY-MM') AS competencia,
       coalesce(cte.valor, 0)::float8   AS cte_taxa,
       coalesce(cte.n, 0)::int          AS cte_n,
       coalesce(col.valor, 0)::float8   AS coleta_pedagio,
       coalesce(col.n, 0)::int          AS coleta_n,
       coalesce(vp.valor, 0)::float8    AS vale,
       coalesce(vp.n, 0)::int           AS vale_n,
       coalesce(vp.cancelados, 0)::int  AS vale_cancelados
  FROM (SELECT generate_series(date_trunc('month', %(de)s::date),
                               date_trunc('month', %(ate)s::date),
                               '1 month')::date AS mes) m
  LEFT JOIN (
      SELECT date_trunc('month', dtemissao)::date mes,
             sum(coalesce(valortaxapedagio, 0)) valor, count(*) n
        FROM conhecimento
       WHERE dtemissao >= %(de)s AND dtemissao < %(ate)s::date + 1
         AND dtcancelamento IS NULL
         AND coalesce(valortaxapedagio, 0) > 0
       GROUP BY 1) cte ON cte.mes = m.mes
  LEFT JOIN (
      SELECT date_trunc('month', dtinc)::date mes,
             sum(coalesce(valorpedagio, 0)) valor, count(*) n
        FROM coleta
       WHERE dtinc >= %(de)s AND dtinc < %(ate)s::date + 1
         AND dtcancelamento IS NULL
         AND coalesce(valorpedagio, 0) > 0
       GROUP BY 1) col ON col.mes = m.mes
  LEFT JOIN (
      SELECT date_trunc('month', dtemissao)::date mes,
             sum(CASE WHEN dtcancelamento IS NULL THEN valorcartao ELSE 0 END) valor,
             sum(CASE WHEN dtcancelamento IS NULL THEN 1 ELSE 0 END) n,
             sum(CASE WHEN dtcancelamento IS NOT NULL THEN 1 ELSE 0 END) cancelados
        FROM valepedagio
       WHERE dtemissao >= %(de)s AND dtemissao < %(ate)s::date + 1
       GROUP BY 1) vp ON vp.mes = m.mes
 ORDER BY 1
"""

# ── vale × coleta, título a título ──────────────────────────────────────────
#
# O `%` de "88,3%" fica em comentário PYTHON, nunca dentro da string: dentro
# dela o psycopg o lê como placeholder e a consulta morre com
# `incomplete placeholder`.
CONFRONTO_SQL = """
SELECT vp.veiculo, vp.quantidadetotaleixos AS eixos,
       vp.valorcartao::float8              AS vale,
       coalesce(c.valorpedagio, 0)::float8 AS coleta,
       vp.dtemissao, vp.numerocomprovante,
       vp.uforigem, vp.ufdestino, vp.cidadeorigem, vp.cidadedestino,
       coalesce(v.utilizacaoveiculo, '?')  AS modalidade
  FROM valepedagio vp
  JOIN coleta c
    ON c.grupo = vp.grupodocumentoorigem AND c.empresa = vp.empresadocumentoorigem
   AND c.filial = vp.filialdocumentoorigem AND c.unidade = vp.unidadedocumentoorigem
   AND c.numero = vp.numerodocumentoorigem
  LEFT JOIN veiculo v ON v.placa = vp.veiculo
 WHERE vp.dtemissao >= %(de)s AND vp.dtemissao < %(ate)s::date + 1
   AND vp.dtcancelamento IS NULL
   AND vp.tipodocumentoorigem = %(tipo)s
"""

POR_EIXO_SQL = """
SELECT vp.quantidadetotaleixos AS eixos, count(*)::int AS vales,
       sum(vp.valorcartao)::float8 AS valor,
       avg(vp.valorcartao)::float8 AS medio
  FROM valepedagio vp
 WHERE vp.dtemissao >= %(de)s AND vp.dtemissao < %(ate)s::date + 1
   AND vp.dtcancelamento IS NULL
 GROUP BY 1 ORDER BY 2 DESC
"""

POR_MODALIDADE_SQL = """
SELECT coalesce(v.utilizacaoveiculo, '(sem cadastro)') AS modalidade,
       count(*)::int AS vales, sum(vp.valorcartao)::float8 AS valor,
       count(DISTINCT vp.veiculo)::int AS veiculos
  FROM valepedagio vp
  LEFT JOIN veiculo v ON v.placa = vp.veiculo
 WHERE vp.dtemissao >= %(de)s AND vp.dtemissao < %(ate)s::date + 1
   AND vp.dtcancelamento IS NULL
 GROUP BY 1 ORDER BY 3 DESC
"""

# COMPROVANTE é o número que vai no MDF-e (grupo `infANTT/valePed`). Vale
# medir a cobertura porque é ele que prova, numa fiscalização, que o
# vale-pedágio foi emitido — e 98,1% preenchido significa ~200 vales por ano
# sem a prova.
COBERTURA_SQL = """
SELECT count(*)::int AS vales,
       sum(CASE WHEN coalesce(vp.numerocomprovante, '') <> '' THEN 1 ELSE 0 END)::int AS com_comprovante,
       sum(CASE WHEN coalesce(vp.categoriaveiculoadministradora, '') <> '' THEN 1 ELSE 0 END)::int AS com_categoria,
       sum(CASE WHEN coalesce(vp.numerotag, '') <> '' THEN 1 ELSE 0 END)::int AS com_tag,
       sum(CASE WHEN coalesce(vp.idviagemadministradora, '') <> '' THEN 1 ELSE 0 END)::int AS com_idviagem,
       count(DISTINCT vp.cnpjcpfcodigoresponsavel)::int AS responsaveis
  FROM valepedagio vp
 WHERE vp.dtemissao >= %(de)s AND vp.dtemissao < %(ate)s::date + 1
   AND vp.dtcancelamento IS NULL
"""


def _classificar(linha: dict) -> str:
    """Onde cada vale cai na comparação com a coleta.

    `coleta_zero` é categoria PRÓPRIA e não "vale maior": pedágio zero na
    coleta é ausência de lançamento, não desempenho — e misturá-lo com a
    diferença real inflaria o achado com um problema de outra natureza. Mesma
    regra do zero que era `n/d` em cinza na Análise de KM.
    """
    coleta = linha["coleta"] or 0.0
    vale = linha["vale"] or 0.0
    if coleta <= 0:
        return "coleta_zero"
    d = vale - coleta
    if abs(d) < 0.01:
        return "igual"
    return "vale_maior" if d > 0 else "vale_menor"


def confronto(de: str, ate: str, tipo: int = TIPO_COLETA) -> dict:
    """Vale × pedágio da coleta, com a distribuição e os maiores desvios."""
    linhas = [dict(r) for r in db.query(CONFRONTO_SQL,
                                        {"de": de, "ate": ate, "tipo": tipo})]
    for l in linhas:
        l["classe"] = _classificar(l)
        l["diferenca"] = round((l["vale"] or 0) - (l["coleta"] or 0), 2)
        # A RAZÃO SAI DOS VALORES, não de valores já arredondados: arredondar
        # antes de dividir move o número de lado da fronteira, e aqui o
        # limiar de leitura é 1,00.
        l["razao"] = (round((l["vale"] or 0) / l["coleta"], 3)
                      if (l["coleta"] or 0) > 0 else None)
    quadro = {"igual": 0, "vale_maior": 0, "vale_menor": 0, "coleta_zero": 0}
    for l in linhas:
        quadro[l["classe"]] += 1
    razoes = sorted(l["razao"] for l in linhas if l["razao"] is not None)
    return {
        "linhas": linhas,
        "quadro": quadro,
        "total": len(linhas),
        "vale_total": round(sum(l["vale"] or 0 for l in linhas), 2),
        "coleta_total": round(sum(l["coleta"] or 0 for l in linhas), 2),
        # MEDIANA, não média: um punhado de vales de valor alto puxaria a média
        # e diria que a diferença é maior do que a maioria dos casos mostra.
        "razao_mediana": (razoes[len(razoes) // 2] if razoes else None),
    }


def mensal(de: str, ate: str) -> list[dict]:
    """As três séries no mesmo eixo do tempo, com o mês sem dado MARCADO.

    Mês vazio volta com `sem_dado`, e a tela desenha a barra em cinza com a
    linha ABERTA — barra zerada diria "não houve pedágio", que é outra coisa.
    """
    fora = []
    for r in db.query(MENSAL_SQL, {"de": de, "ate": ate}):
        d = dict(r)
        d["sem_dado"] = not (d["cte_n"] or d["coleta_n"] or d["vale_n"])
        # O que o vale cobre do que se cobrou do cliente. `None` quando não há
        # denominador — dividir por zero ou preencher com 0% faria o mês sem
        # CT-e parecer o pior de todos.
        d["cobertura_vale"] = (round(100.0 * d["vale"] / d["cte_taxa"], 1)
                               if d["cte_taxa"] > 0 else None)
        fora.append(d)
    return fora


def por_eixo(de: str, ate: str) -> list[dict]:
    return [dict(r) for r in db.query(POR_EIXO_SQL, {"de": de, "ate": ate})]


def por_modalidade(de: str, ate: str) -> list[dict]:
    """A quebra por modalidade, com o nome POR EXTENSO.

    `utilizacaoveiculo` vem como "AGR"/"TER"/"LOC"/"TRA" e vazava cru para a
    tela. Quem opera sabe de cor; quem lê o painel uma vez por mês, não — e
    num card que decide dinheiro a sigla obriga a perguntar em vez de ler.
    O código fica ao lado em `modalidade_cod`, porque é ele que aparece no
    ERP e é por ele que alguém vai procurar lá.
    """
    from api import frota_identidade
    linhas = []
    for r in db.query(POR_MODALIDADE_SQL, {"de": de, "ate": ate}):
        d = dict(r)
        d["modalidade_cod"] = d["modalidade"]
        d["modalidade"] = frota_identidade.modalidade(d["modalidade"])
        linhas.append(d)
    return linhas


def cobertura(de: str, ate: str) -> dict:
    """Quanto de cada campo está preenchido — a tela DIZ isso, não presume.

    O comprovante é o número que vai no MDF-e: sem ele não há prova de que o
    vale foi emitido. Os outros três são baixos de verdade (categoria 9,7%,
    tag 11,5%, id de viagem 16,1%) e por isso NÃO viram KPI: viram a linha que
    explica por que certas conferências não dão para fazer.
    """
    r = dict(db.query(COBERTURA_SQL, {"de": de, "ate": ate})[0])
    n = r["vales"] or 1
    for campo in ("com_comprovante", "com_categoria", "com_tag", "com_idviagem"):
        r["pct_" + campo[4:]] = round(100.0 * r[campo] / n, 1)
    return r
