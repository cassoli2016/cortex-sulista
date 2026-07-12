-- ============================================================================
-- CÓRTEX — Varredura GERAL (panorama do banco)
-- Rodar: scripts/db.sh file scripts/scan_geral.sql
-- ============================================================================
\pset pager off
\set ON_ERROR_STOP off

\echo '=== 1. Servidor / versão ==='
SELECT version();

\echo '=== 2. Extensões instaladas (esperado: timescaledb, vector) ==='
SELECT extname, extversion FROM pg_extension ORDER BY extname;

\echo '=== 3. Versão de migration (alembic) ==='
SELECT version_num FROM alembic_version;

\echo '=== 4. Tabelas do schema public + estimativa de linhas + tamanho ==='
SELECT c.relname AS tabela,
       to_char(c.reltuples, 'FM999G999G999') AS linhas_estim,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS tamanho
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY c.relname;

\echo '=== 5. Views disponíveis ==='
SELECT table_name FROM information_schema.views
WHERE table_schema = 'public' ORDER BY table_name;

\echo '=== 6. Hypertables TimescaleDB (se houver) ==='
SELECT hypertable_name FROM timescaledb_information.hypertables;

\echo '=== 7. Contagem real das tabelas do FINANCEIRO ==='
SELECT 'fin_titulos'       AS tabela, count(*) FROM fin_titulos
UNION ALL SELECT 'fin_adiantamentos', count(*) FROM fin_adiantamentos
UNION ALL SELECT 'fin_lancamentos',   count(*) FROM fin_lancamentos
UNION ALL SELECT 'fin_dre',           count(*) FROM fin_dre;
