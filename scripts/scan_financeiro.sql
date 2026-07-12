-- ============================================================================
-- CÓRTEX — Varredura do FINANCEIRO
-- Rodar: scripts/db.sh file scripts/scan_financeiro.sql
-- Obs.: fin_titulos tem RLS por filial. Como superuser, o RLS é ignorado.
--       A linha abaixo garante escopo amplo caso rode como cortex_app.
-- ============================================================================
\pset pager off
\set ON_ERROR_STOP off
SELECT set_config('app.user_filiais', '1,2,3,4,5,6,7,8,9,10', false);

\echo '========================================================'
\echo ' TÍTULOS (fin_titulos) — base de caixa e aging'
\echo '========================================================'
\echo '--- Por tipo x status (contagem e valor) ---'
SELECT tipo, status, count(*) AS qtd, sum(valor) AS valor_total
FROM fin_titulos GROUP BY tipo, status ORDER BY tipo, status;

\echo '--- Janela de datas (emissão / vencimento / baixa) ---'
SELECT min(emissao) AS emissao_min, max(emissao) AS emissao_max,
       min(vencimento) AS venc_min, max(vencimento) AS venc_max,
       count(*) FILTER (WHERE baixa IS NOT NULL) AS baixados
FROM fin_titulos;

\echo '--- A RECEBER em aberto: aging vs hoje ---'
SELECT
  CASE
    WHEN vencimento >= current_date THEN 'a_vencer'
    WHEN vencimento >= current_date - 30 THEN 'venc_1_30'
    WHEN vencimento >= current_date - 60 THEN 'venc_31_60'
    WHEN vencimento >= current_date - 90 THEN 'venc_61_90'
    ELSE 'venc_90_mais'
  END AS faixa,
  count(*) AS qtd, sum(valor) AS valor
FROM fin_titulos
WHERE tipo = 'receber' AND status IN ('aberto','atrasado')
GROUP BY 1 ORDER BY 1;

\echo '--- A PAGAR em aberto por faixa de vencimento ---'
SELECT
  CASE WHEN vencimento < current_date THEN 'vencido' ELSE 'a_vencer' END AS faixa,
  count(*) AS qtd, sum(valor) AS valor
FROM fin_titulos
WHERE tipo = 'pagar' AND status IN ('aberto','atrasado')
GROUP BY 1 ORDER BY 1;

\echo '--- Top 10 títulos a receber em aberto por valor ---'
SELECT id, cliente_id, filial_id, valor, vencimento, status, cte_id
FROM fin_titulos
WHERE tipo = 'receber' AND status IN ('aberto','atrasado')
ORDER BY valor DESC LIMIT 10;

\echo '========================================================'
\echo ' ADIANTAMENTOS (fin_adiantamentos)'
\echo '========================================================'
SELECT status, count(*) AS qtd, sum(valor) AS valor_total,
       count(*) FILTER (WHERE viagem_id IS NOT NULL) AS vinculados_viagem
FROM fin_adiantamentos GROUP BY status ORDER BY status;

\echo '========================================================'
\echo ' LANÇAMENTOS (fin_lancamentos)'
\echo '========================================================'
SELECT min(data) AS data_min, max(data) AS data_max,
       count(*) AS qtd, sum(valor) AS valor_total
FROM fin_lancamentos;
\echo '--- Por centro de custo (top 15) ---'
SELECT centro_custo, count(*) AS qtd, sum(valor) AS valor
FROM fin_lancamentos GROUP BY centro_custo ORDER BY valor DESC NULLS LAST LIMIT 15;

\echo '========================================================'
\echo ' DRE (fin_dre) — competência x grupo'
\echo '========================================================'
SELECT min(competencia) AS comp_min, max(competencia) AS comp_max, count(*) AS linhas
FROM fin_dre;
\echo '--- Soma por grupo (todas as competências) ---'
SELECT grupo, count(*) AS linhas, sum(valor) AS valor
FROM fin_dre GROUP BY grupo ORDER BY valor DESC;
\echo '--- DRE por competência (últimas 6) ---'
SELECT competencia, grupo, sum(valor) AS valor
FROM fin_dre
WHERE competencia >= (SELECT max(competencia) FROM fin_dre) - INTERVAL '6 months'
GROUP BY competencia, grupo ORDER BY competencia DESC, grupo;

\echo '========================================================'
\echo ' VIEWS financeiras (amostra)'
\echo '========================================================'
\echo '--- vw_fluxo_caixa (10 linhas) ---'
SELECT * FROM vw_fluxo_caixa LIMIT 10;
\echo '--- vw_dre_mensal (10 linhas) ---'
SELECT * FROM vw_dre_mensal LIMIT 10;
