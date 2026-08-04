# api/previsao/sql.py
"""SQL novos da previsão — PostgreSQL 9.3, LATIN-1, somente leitura.

O razão por agrupador (mês corrente e histórico) REUSA queries.DRE_AG_SQL /
DRE_AJUSTADAS_SQL (mesma pergunta, janelas diferentes). Aqui ficam só as
perguntas que a base ainda não fazia.
"""
from __future__ import annotations

from api.orcamento.sql import meses_fechados as meses_fechados_prev  # noqa: F401

# Curva de completude: |movimento| por (mes de competencia, agrupador,
# dias desde o 1o dia do mes em que o lancamento foi INCLUIDO - dtinc).
COMPLETUDE_SQL = """
SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
       coalesce(ag.descricao, 'CLASSIFICAR') AS agrupador,
       greatest(0, least(45,
         (l.dtinc - date_trunc('month', l.dtlancamento)::date)))::int AS dia_rel,
       sum(abs(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0)))::float8 AS valor_abs
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
GROUP BY 1, 2, 3
"""

# Razao por agrupador COMO ERA VISIVEL em uma data passada (backtest as-of).
RAZAO_ASOF_SQL = """
SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
       coalesce(ag.descricao, 'CLASSIFICAR') AS agrupador,
       sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS valor
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND l.dtinc <= %(asof)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
GROUP BY 1, 2
"""

# Atingimento realizado/meta por mes (3 fontes oficiais x meta diaria tipo=1).
# Mesmos filtros fiscais do VG_DIARIO_SQL, agregados por mes para a janela pedida.
ATING_HIST_SQL = """
SELECT mes, sum(realizado)::float8 AS realizado, sum(meta)::float8 AS meta FROM (
  SELECT to_char(dtemissao,'YYYY-MM') AS mes,
         coalesce(valortotalprestacao,0) AS realizado, 0::numeric AS meta
  FROM conhecimento
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
    AND grupo = 1 AND empresa = 1 AND unidade = 1 AND numero < 1000000
    AND dtcancelamento IS NULL AND situacaocte = 3 AND tipo IN (1,4)
  UNION ALL
  SELECT to_char(dtemissao,'YYYY-MM'), coalesce(valor_cte,0), 0
  FROM sulista.faturamentokmm
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
  UNION ALL
  SELECT to_char(dtemissao,'YYYY-MM'), coalesce(valortotalbruto,0), 0
  FROM notafiscalservico
  WHERE dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date
    AND grupo = 1 AND empresa = 1 AND numero < 1000000
    AND dtcancelamento IS NULL
    AND (emissaoeletronica = 2 OR (emissaoeletronica = 1 AND situacaonfse = 3))
  UNION ALL
  SELECT to_char(dt,'YYYY-MM'), 0, coalesce(valor,0)
  FROM sulista.metafaturamento_agrupamentoclientedia
  WHERE dt >= %(de)s::date AND dt < %(ate)s::date AND tipo = 1
) t GROUP BY 1 ORDER BY 1
"""

# Frete de compra das viagens no periodo (proxy antecipada do custo de
# agregados+terceiros JUNTOS; o acerto contabil chega ~6 dias depois).
# Sem join com veiculo de proposito: o split agregado x terceiro e feito pela
# participacao historica das duas linhas no razao (premissa declarada no motor).
VFC_MTD_SQL = """
SELECT count(*)::int AS viagens,
       sum(coalesce(valorfrete,0))::float8 AS receita_viagens,
       sum(coalesce(valorfretecompra,0))::float8 AS frete_compra
FROM programacaoembarque
WHERE dtcancelamento IS NULL AND semaforo = 1
  AND dtsaida >= %(de)s::date AND dtsaida < %(ate)s::date
"""

# Combustivel dos abastecimentos (validacao cruzada do CV - COMBUSTIVEL).
# Filtra veiculos de agregado/terceiro (custo deles e repassado no acerto,
# nao e a linha de combustivel do razao). Convencao CANONICA (mesma de
# api/queries.py, ~linhas 2002/2047): propria exige PLACA CASADA no veiculo;
# placa nao casada (v.placa IS NULL) segue a convencao do repo e fica FORA do
# proprio (conta como terceiro/desconhecido), nunca vira propria por default.
CTAPLUS_MTD_SQL = """
SELECT sum(coalesce(c.custo,0))::float8 AS custo,
       count(*)::int AS abastecimentos
FROM sulista.ctaplus_abastecimentos c
LEFT JOIN veiculo v ON v.placa = c.veiculo_placa
WHERE c.data_inicio_abastecimento >= %(de)s::date
  AND c.data_inicio_abastecimento < %(ate)s::date
  AND v.placa IS NOT NULL
  AND coalesce(v.utilizacaoveiculo, '') NOT IN ('AGR', 'TER')
"""

# Contas a pagar com vencimento no mes (contexto de caixa, so KPI informativo).
CAP_MES_SQL = """
SELECT count(*)::int AS titulos,
       sum(coalesce(valorpendente,0))::float8 AS valor
FROM contaapagar
WHERE valorpendente > 0
  AND dtvencimento >= %(de)s::date AND dtvencimento < %(ate)s::date
"""
