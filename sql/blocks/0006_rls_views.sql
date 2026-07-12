-- 11. ROW-LEVEL SECURITY
-- Política por filial. O app seta:  SET app.user_filiais = '1,2,3';
-- CEO/auditor: app seta TODAS as filiais. current_setting(..., true) = missing_ok.
-- ============================================================================
CREATE OR REPLACE FUNCTION app_filiais() RETURNS int[] AS $$
  SELECT CASE
    WHEN coalesce(current_setting('app.user_filiais', true), '') = '' THEN ARRAY[]::int[]
    ELSE string_to_array(current_setting('app.user_filiais', true), ',')::int[]
  END;
$$ LANGUAGE sql STABLE;

ALTER TABLE com_clientes ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_clientes_filial ON com_clientes
  USING (filial_id IS NULL OR filial_id = ANY (app_filiais()));

ALTER TABLE rh_motoristas ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_motoristas_filial ON rh_motoristas
  USING (filial_id IS NULL OR filial_id = ANY (app_filiais()));

ALTER TABLE fro_veiculos ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_veiculos_filial ON fro_veiculos
  USING (filial_id IS NULL OR filial_id = ANY (app_filiais()));

ALTER TABLE op_viagens ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_viagens_filial ON op_viagens
  USING (filial_id IS NULL OR filial_id = ANY (app_filiais()));

ALTER TABLE fin_titulos ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_titulos_filial ON fin_titulos
  USING (filial_id IS NULL OR filial_id = ANY (app_filiais()));

-- ============================================================================
-- 12. VIEWS ANALÍTICAS (materializadas)
-- Custeio simplificado: op_viagens.custo_variavel/custo_fixo_rateado preenchidos pelo ETL.
-- ============================================================================
CREATE MATERIALIZED VIEW vw_rkm_cliente AS
SELECT cliente_id,
       date_trunc('month', inicio) AS mes,
       sum(receita_frete)                          AS receita,
       sum(km_carregado)                           AS km_carregado,
       sum(receita_frete) / nullif(sum(km_carregado),0) AS rkm
FROM op_viagens
WHERE status = 'concluida'
GROUP BY cliente_id, date_trunc('month', inicio);

CREATE MATERIALIZED VIEW vw_ckm_viagem AS
SELECT id AS viagem_id, rota_id, modo,
       km_total, km_carregado,
       custo_variavel / nullif(km_total,0)       AS ckm_bruto,
       custo_variavel / nullif(km_carregado,0)   AS ckm_produtivo,
       (km_total - km_carregado) / nullif(km_total,0) AS retorno_vazio
FROM op_viagens
WHERE custo_variavel IS NOT NULL;

CREATE MATERIALIZED VIEW vw_resultado_viagem AS
SELECT id AS viagem_id, cliente_id, rota_id,
       receita_frete,
       coalesce(custo_variavel,0)      AS custo_variavel,
       coalesce(custo_fixo_rateado,0)  AS custo_fixo_rateado,
       receita_frete - coalesce(custo_variavel,0) - coalesce(custo_fixo_rateado,0) AS resultado
FROM op_viagens
WHERE status = 'concluida';

CREATE MATERIALIZED VIEW vw_fluxo_caixa AS
SELECT vencimento AS data,
       sum(CASE WHEN tipo='receber' AND status<>'cancelado' THEN valor ELSE 0 END) AS receber,
       sum(CASE WHEN tipo='pagar'   AND status<>'cancelado' THEN valor ELSE 0 END) AS pagar,
       sum(CASE WHEN tipo='receber' AND status<>'cancelado' THEN valor
                WHEN tipo='pagar'   AND status<>'cancelado' THEN -valor ELSE 0 END) AS liquido
FROM fin_titulos
GROUP BY vencimento;

CREATE MATERIALIZED VIEW vw_dre_mensal AS
SELECT competencia, grupo, sum(valor) AS valor
FROM fin_dre
GROUP BY competencia, grupo;

CREATE MATERIALIZED VIEW vw_compliance_jornada AS
SELECT motorista_id, data,
       horas_direcao, horas_descanso,
       (violacoes IS NOT NULL AND violacoes <> '[]'::jsonb) AS tem_violacao
FROM jor_jornadas;

CREATE VIEW vw_viagens_ativas AS
SELECT v.id AS viagem_id, v.cliente_id, v.veiculo_id, v.status, v.fim AS previsao_fim,
       p.lat, p.lng, p.velocidade, p.eta, p.ts AS posicao_em
FROM op_viagens v
LEFT JOIN LATERAL (
    SELECT lat, lng, velocidade, eta, ts
    FROM tc_posicoes tp
    WHERE tp.viagem_id = v.id
    ORDER BY ts DESC LIMIT 1
) p ON true
WHERE v.status = 'ativa';

CREATE MATERIALIZED VIEW vw_sinistralidade AS
SELECT date_trunc('month', ts) AS mes,
       count(*) FILTER (WHERE tipo='acidente') AS acidentes,
       count(*)                                AS eventos_total
FROM ts_eventos
GROUP BY date_trunc('month', ts);

-- ============================================================================
