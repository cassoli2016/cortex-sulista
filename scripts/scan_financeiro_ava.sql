-- ============================================================================
-- Varredura do FINANCEIRO — banco legado "sulista" (ERP AVA, PostgreSQL 9.3)
-- SOMENTE LEITURA. Compatível com 9.3 (sem FILTER/RLS).
-- Rodar: scripts/db.sh file scripts/scan_financeiro_ava.sql
-- ============================================================================
\pset pager off
\timing on
SET statement_timeout = '240s';

\echo '################  CONTAS A PAGAR (contaapagar)  ################'
\echo '--- Panorama (contagem, datas, valores) ---'
SELECT count(*) AS titulos,
       min(dtemissaotitulo) AS emissao_min, max(dtemissaotitulo) AS emissao_max,
       min(dtvencimento)    AS venc_min,    max(dtvencimento)    AS venc_max,
       max(dtpagamento)     AS ult_pagamento,
       sum(valortitulo)   AS total_titulos,
       sum(valorpago)     AS total_pago,
       sum(valorpendente) AS total_pendente
FROM contaapagar;

\echo '--- Situacao: quitada x em aberto ---'
SELECT CASE WHEN coalesce(valorpendente,0) <= 0 THEN 'quitada' ELSE 'em_aberto' END AS situacao,
       count(*) AS qtd, sum(valortitulo) AS valor_titulo, sum(valorpendente) AS valor_pendente
FROM contaapagar GROUP BY 1 ORDER BY 1;

\echo '--- Em aberto: aging vs hoje ---'
SELECT CASE
    WHEN dtvencimento >= current_date        THEN '1_a_vencer'
    WHEN dtvencimento >= current_date - 30    THEN '2_vencido_ate_30'
    WHEN dtvencimento >= current_date - 90    THEN '3_vencido_31_90'
    WHEN dtvencimento >= current_date - 365   THEN '4_vencido_91_365'
    ELSE '5_vencido_mais_365' END AS faixa,
    count(*) AS qtd, sum(valorpendente) AS valor_pendente
FROM contaapagar WHERE coalesce(valorpendente,0) > 0
GROUP BY 1 ORDER BY 1;

\echo '--- Volume por ano de emissao (ultimos 12) ---'
SELECT extract(year from dtemissaotitulo)::int AS ano, count(*) AS qtd, sum(valortitulo) AS valor
FROM contaapagar WHERE dtemissaotitulo IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;

\echo '################  CONTAS A RECEBER (fatura)  ################'
\echo '-- OBS: valor do frete = valortitulo (valortotal NAO e o valor da fatura).'
\echo '--- Panorama (excluindo canceladas) ---'
SELECT count(*) AS faturas,
       (SELECT count(dtcancelamento) FROM fatura) AS canceladas,
       min(dtemissao) AS emissao_min, max(dtemissao) AS emissao_max,
       min(dtvencimento) AS venc_min, max(dtvencimento) AS venc_max,
       sum(valortitulo) AS total_faturado,
       sum(valorsaldoreceber) AS saldo_a_receber
FROM fatura WHERE dtcancelamento IS NULL;

\echo '--- A receber em aberto (nao cancelada): aging ---'
SELECT CASE
    WHEN dtvencimento >= current_date        THEN '1_a_vencer'
    WHEN dtvencimento >= current_date - 30    THEN '2_vencido_ate_30'
    WHEN dtvencimento >= current_date - 90    THEN '3_vencido_31_90'
    WHEN dtvencimento >= current_date - 365   THEN '4_vencido_91_365'
    ELSE '5_vencido_mais_365' END AS faixa,
    count(*) AS qtd, sum(valorsaldoreceber) AS saldo
FROM fatura
WHERE coalesce(valorsaldoreceber,0) > 0 AND dtcancelamento IS NULL
GROUP BY 1 ORDER BY 1;

\echo '--- Faturamento por ano (ultimos 12) ---'
SELECT extract(year from dtemissao)::int AS ano, count(*) AS qtd, sum(valortitulo) AS valor
FROM fatura WHERE dtemissao IS NOT NULL AND dtcancelamento IS NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;

\echo '################  BANCOS (extratobancario)  ################'
\echo '-- Sinal do movimento vem do campo tipo (C=credito/entrada, D=debito/saida).'
SELECT extract(year from dtmovimento)::int AS ano, count(*) AS mov,
       sum(CASE WHEN tipo = 'C' THEN valor ELSE 0 END) AS entradas,
       sum(CASE WHEN tipo = 'D' THEN valor ELSE 0 END) AS saidas
FROM extratobancario WHERE dtmovimento IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 10;

\echo '################  RAZAO CONTABIL (lancamento) — pode demorar  ################'
SELECT extract(year from dtlancamento)::int AS ano, count(*) AS lancamentos,
       sum(valordebito) AS debito, sum(valorcredito) AS credito
FROM lancamento WHERE dtlancamento IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 12;
