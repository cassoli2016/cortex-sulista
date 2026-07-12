-- ============================================================================
-- CÓRTEX — Schema consolidado (PostgreSQL 16 + TimescaleDB + pgvector)
-- Referência única do modelo. As migrations Alembic em migrations/versions/
-- aplicam este mesmo schema de forma versionada.
-- Dinheiro em NUMERIC. Timestamps em timestamptz. Timezone America/Sao_Paulo no app.
-- ============================================================================

-- ---- Extensões -------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector (RAG)

-- ============================================================================
-- 1. GOVERNANÇA / ACESSO
-- ============================================================================
CREATE TABLE filiais (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    uf          char(2)
);

CREATE TABLE usuarios (
    id          serial PRIMARY KEY,
    email       text UNIQUE NOT NULL,
    nome        text NOT NULL,
    ativo       boolean NOT NULL DEFAULT true,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE papeis (
    id          serial PRIMARY KEY,
    nome        text UNIQUE NOT NULL          -- ceo, controller, fin_analista, ...
);

CREATE TABLE usuario_papel (
    usuario_id  int REFERENCES usuarios(id) ON DELETE CASCADE,
    papel_id    int REFERENCES papeis(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, papel_id)
);

CREATE TABLE usuario_filial (
    usuario_id  int REFERENCES usuarios(id) ON DELETE CASCADE,
    filial_id   int REFERENCES filiais(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, filial_id)
);

CREATE TABLE papel_modulo (
    papel_id    int REFERENCES papeis(id) ON DELETE CASCADE,
    modulo      text NOT NULL,                -- financeiro, comercial, ...
    permissao   text NOT NULL CHECK (permissao IN ('read','write','approve')),
    PRIMARY KEY (papel_id, modulo, permissao)
);

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    usuario_id  int REFERENCES usuarios(id),
    acao        text NOT NULL,                -- read|write|approve|login|...
    modulo      text,
    entidade    text,
    entidade_id text,
    detalhe     jsonb,
    ip          inet,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_criado ON audit_log (criado_em);
CREATE INDEX ix_audit_usuario ON audit_log (usuario_id, criado_em);

-- ============================================================================
-- 2. CADASTROS BASE
-- ============================================================================
CREATE TABLE com_clientes (
    id              serial PRIMARY KEY,
    nome            text NOT NULL,
    cnpj            text UNIQUE,
    segmento        text,
    score           numeric(5,1),
    limite_credito  numeric(14,2) DEFAULT 0,
    filial_id       int REFERENCES filiais(id),
    criado_em       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rh_motoristas (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    cpf         text UNIQUE,
    cnh         text,
    categoria_cnh text,
    filial_id   int REFERENCES filiais(id),
    ativo       boolean NOT NULL DEFAULT true,
    admissao    date
);

CREATE TABLE fro_veiculos (
    id              serial PRIMARY KEY,
    placa           text UNIQUE NOT NULL,
    tipo            text,                      -- cavalo, truck, frigorifico...
    ano             int,
    valor_compra    numeric(14,2),
    valor_residual  numeric(14,2),
    vida_km         numeric(12,0),
    status          text DEFAULT 'ativo',      -- ativo|parado|manutencao|vendido
    filial_id       int REFERENCES filiais(id)
);

CREATE TABLE op_rotas (
    id              serial PRIMARY KEY,
    origem_uf       char(2),
    destino_uf      char(2),
    distancia_km    numeric(10,1),
    pedagio_estimado numeric(12,2)
);

CREATE TABLE sup_fornecedores (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    cnpj        text,
    tipo        text CHECK (tipo IN ('posto','oficina','agregado','outro')),
    avaliacao   numeric(3,1)
);

CREATE TABLE sup_agregados (
    id              serial PRIMARY KEY,
    fornecedor_id   int REFERENCES sup_fornecedores(id),
    rkm_acordado    numeric(10,4),
    rotas           int[]
);

CREATE TABLE sup_contratos (
    id              serial PRIMARY KEY,
    fornecedor_id   int REFERENCES sup_fornecedores(id),
    inicio          date,
    fim             date,
    termos          jsonb
);

-- ============================================================================
-- 3. OPERACIONAL
-- ============================================================================
CREATE TABLE op_viagens (
    id              serial PRIMARY KEY,
    cliente_id      int REFERENCES com_clientes(id),
    veiculo_id      int REFERENCES fro_veiculos(id),
    motorista_id    int REFERENCES rh_motoristas(id),
    rota_id         int REFERENCES op_rotas(id),
    km_carregado    numeric(10,1) NOT NULL DEFAULT 0,
    km_total        numeric(10,1) NOT NULL DEFAULT 0,
    receita_frete   numeric(14,2) NOT NULL DEFAULT 0,
    custo_variavel  numeric(14,2),             -- custo variável TOTAL apurado da viagem
    custo_fixo_rateado numeric(14,2),          -- fixo rateado p/ a viagem
    cte_id          text,
    modo            text NOT NULL DEFAULT 'proprio' CHECK (modo IN ('proprio','agregado')),
    status          text NOT NULL DEFAULT 'planejada', -- planejada|ativa|concluida|cancelada
    filial_id       int REFERENCES filiais(id),
    inicio          timestamptz,
    fim             timestamptz
);
CREATE INDEX ix_viagens_status ON op_viagens (status);
CREATE INDEX ix_viagens_cliente ON op_viagens (cliente_id, inicio);

CREATE TABLE op_cargas (
    id              serial PRIMARY KEY,
    viagem_id       int REFERENCES op_viagens(id) ON DELETE CASCADE,
    peso            numeric(12,2),
    valor_mercadoria numeric(14,2),
    nf_id           text
);

-- ============================================================================
-- 4. PROGRAMAÇÃO DE CARGAS
-- ============================================================================
CREATE TABLE prog_cargas (
    id              serial PRIMARY KEY,
    cliente_id      int REFERENCES com_clientes(id),
    origem          text,
    destino         text,
    janela_coleta   tstzrange,
    janela_entrega  tstzrange,
    peso            numeric(12,2),
    tipo_carga      text,
    status          text NOT NULL DEFAULT 'pendente' -- pendente|alocada|em_curso|entregue
);

CREATE TABLE prog_alocacao (
    id              serial PRIMARY KEY,
    carga_id        int REFERENCES prog_cargas(id) ON DELETE CASCADE,
    veiculo_id      int REFERENCES fro_veiculos(id),
    motorista_id    int REFERENCES rh_motoristas(id),
    status          text NOT NULL DEFAULT 'proposta',
    criado_em       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE prog_disponibilidade (
    id              serial PRIMARY KEY,
    veiculo_id      int REFERENCES fro_veiculos(id),
    inicio          timestamptz,
    fim             timestamptz,
    motivo          text
);

-- ============================================================================
-- 5. FROTA
-- ============================================================================
CREATE TABLE fro_manutencao (
    id          serial PRIMARY KEY,
    veiculo_id  int REFERENCES fro_veiculos(id),
    tipo        text CHECK (tipo IN ('prev','corr')),
    custo       numeric(14,2),
    data        date,
    km          numeric(12,0)
);

CREATE TABLE fro_pneus (
    id              serial PRIMARY KEY,
    veiculo_id      int REFERENCES fro_veiculos(id),
    posicao         text,
    custo_jogo      numeric(14,2),
    custo_recapes   numeric(14,2) DEFAULT 0,
    km_vida         numeric(12,0),
    instalado_em    date
);

-- ============================================================================
-- 6. FINANCEIRO
-- ============================================================================
CREATE TABLE fin_titulos (
    id          serial PRIMARY KEY,
    tipo        text NOT NULL CHECK (tipo IN ('receber','pagar')),
    cliente_id  int REFERENCES com_clientes(id),
    fornecedor_id int REFERENCES sup_fornecedores(id),
    valor       numeric(14,2) NOT NULL,
    emissao     date NOT NULL,
    vencimento  date NOT NULL,
    baixa       date,
    status      text NOT NULL DEFAULT 'aberto', -- aberto|pago|atrasado|cancelado
    cte_id      text,
    filial_id   int REFERENCES filiais(id)
);
CREATE INDEX ix_titulos_venc ON fin_titulos (vencimento, status);
CREATE INDEX ix_titulos_tipo ON fin_titulos (tipo, status);

CREATE TABLE fin_adiantamentos (
    id          serial PRIMARY KEY,
    motorista_id int REFERENCES rh_motoristas(id),
    fornecedor_id int REFERENCES sup_fornecedores(id),
    valor       numeric(14,2) NOT NULL,
    data        date NOT NULL,
    viagem_id   int REFERENCES op_viagens(id),
    status      text NOT NULL DEFAULT 'aberto'
);

CREATE TABLE fin_lancamentos (
    id          serial PRIMARY KEY,
    conta       text,
    centro_custo text,
    valor       numeric(14,2) NOT NULL,
    data        date NOT NULL,
    origem      text
);

CREATE TABLE fin_dre (
    id          serial PRIMARY KEY,
    competencia date NOT NULL,
    conta       text NOT NULL,
    grupo       text NOT NULL,                 -- receita|custo_var|custo_motorista|fixo|adm|fin
    valor       numeric(14,2) NOT NULL,
    centro_custo text
);
CREATE INDEX ix_dre_comp ON fin_dre (competencia, grupo);

-- ============================================================================
-- 7. GESTÃO (metas / OKR / atas / ações)
-- ============================================================================
CREATE TABLE ges_metas (
    id          serial PRIMARY KEY,
    area        text,
    indicador   text,
    meta        numeric(14,4),
    periodo     text,
    responsavel text
);

CREATE TABLE ges_okr (
    id          serial PRIMARY KEY,
    objetivo    text NOT NULL,
    key_result  text NOT NULL,
    baseline    numeric(14,4),
    atual       numeric(14,4),
    meta        numeric(14,4),
    prazo       date,
    dono        text
);

CREATE TABLE ges_atas (
    id          serial PRIMARY KEY,
    reuniao     text,
    data        date,
    participantes text[],
    pauta       text,
    decisoes    text
);

CREATE TABLE ges_acoes (
    id          serial PRIMARY KEY,
    ata_id      int REFERENCES ges_atas(id) ON DELETE SET NULL,
    okr_id      int REFERENCES ges_okr(id) ON DELETE SET NULL,
    o_que       text NOT NULL,
    quem        text NOT NULL,
    quando      date NOT NULL,
    como        text,
    status      text NOT NULL DEFAULT 'aberta', -- aberta|em_andamento|concluida|atrasada
    prioridade  text DEFAULT 'media'
);

-- ============================================================================
-- 8. SÉRIES TEMPORAIS (TimescaleDB hypertables) — ver bloco TIMESCALE no fim
-- ============================================================================
CREATE TABLE tel_sinais (
    ts              timestamptz NOT NULL,
    veiculo_id      int NOT NULL,
    km_l            numeric(6,2),
    rpm             int,
    velocidade      numeric(6,2),
    eco_ativo       boolean,
    embalo          boolean,
    freio_motor     boolean,
    combustivel_pct numeric(5,2),
    payload         jsonb
);
CREATE INDEX ix_tel_sinais_veic ON tel_sinais (veiculo_id, ts DESC);

CREATE TABLE tel_dtc (
    id          bigserial,
    veiculo_id  int NOT NULL,
    codigo      text NOT NULL,
    descricao   text,
    ts          timestamptz NOT NULL,
    ativo       boolean DEFAULT true,
    PRIMARY KEY (id, ts)
);

CREATE TABLE tc_posicoes (
    ts          timestamptz NOT NULL,
    viagem_id   int,
    veiculo_id  int NOT NULL,
    lat         numeric(9,6),
    lng         numeric(9,6),
    velocidade  numeric(6,2),
    status      text,
    eta         timestamptz
);
CREATE INDEX ix_tc_pos_veic ON tc_posicoes (veiculo_id, ts DESC);
CREATE INDEX ix_tc_pos_viagem ON tc_posicoes (viagem_id, ts DESC);

CREATE TABLE tc_ocorrencias (
    id          bigserial PRIMARY KEY,
    viagem_id   int,
    tipo        text,
    severidade  text,
    abertura    timestamptz NOT NULL DEFAULT now(),
    fechamento  timestamptz
);

CREATE TABLE ts_eventos (
    ts          timestamptz NOT NULL,
    motorista_id int,
    veiculo_id  int,
    tipo        text NOT NULL,                 -- freada|aceleracao|excesso|fadiga|acidente
    severidade  text
);
CREATE INDEX ix_ts_eventos_mot ON ts_eventos (motorista_id, ts DESC);

CREATE TABLE ts_scores (
    id          bigserial PRIMARY KEY,
    motorista_id int REFERENCES rh_motoristas(id),
    periodo     date,
    score       numeric(5,1),
    componentes jsonb
);

CREATE TABLE jor_eventos (
    ts          timestamptz NOT NULL,
    motorista_id int NOT NULL,
    tipo        text NOT NULL,                 -- direcao|parada|descanso|refeicao
    duracao     interval
);
CREATE INDEX ix_jor_eventos_mot ON jor_eventos (motorista_id, ts DESC);

CREATE TABLE jor_jornadas (
    id              serial PRIMARY KEY,
    motorista_id    int REFERENCES rh_motoristas(id),
    data            date NOT NULL,
    horas_direcao   interval,
    horas_descanso  interval,
    violacoes       jsonb
);

-- ============================================================================
-- 9. CENTRAL DE INTEGRAÇÕES
-- ============================================================================
CREATE TABLE int_conectores (
    id          serial PRIMARY KEY,
    name        text UNIQUE NOT NULL,
    mode        text CHECK (mode IN ('pull','push','both')),
    capabilities text[],
    ativo       boolean NOT NULL DEFAULT true,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE int_credenciais (
    id          serial PRIMARY KEY,
    conector_id int REFERENCES int_conectores(id) ON DELETE CASCADE,
    ref_cofre   text NOT NULL,                 -- REFERÊNCIA ao cofre, nunca o segredo
    escopo      text,
    expira_em   timestamptz
);

CREATE TABLE int_sync_state (
    conector_id int REFERENCES int_conectores(id) ON DELETE CASCADE,
    capability  text NOT NULL,
    cursor      text,
    ultima_sync timestamptz,
    status      text DEFAULT 'ok',             -- ok|atrasado|circuit_open
    PRIMARY KEY (conector_id, capability)
);

CREATE TABLE int_raw_events (
    id          bigserial PRIMARY KEY,
    conector    text NOT NULL,
    chave_idem  text UNIQUE NOT NULL,          -- idempotência
    tipo        text NOT NULL,
    recebido_em timestamptz NOT NULL DEFAULT now(),
    payload     jsonb NOT NULL
);
CREATE INDEX ix_raw_conector ON int_raw_events (conector, recebido_em DESC);

CREATE TABLE int_dead_letter (
    id          bigserial PRIMARY KEY,
    conector    text NOT NULL,
    erro        text,
    tentativas  int DEFAULT 0,
    payload     jsonb,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE int_webhook_log (
    id              bigserial PRIMARY KEY,
    conector        text NOT NULL,
    assinatura_valida boolean,
    recebido_em     timestamptz NOT NULL DEFAULT now(),
    status          text
);

-- ============================================================================
-- 10. RAG (pgvector) — base de conhecimento
-- ============================================================================
CREATE TABLE kb_documentos (
    id          serial PRIMARY KEY,
    titulo      text,
    modulo      text,                          -- tag de escopo p/ RBAC do RAG
    filial_id   int REFERENCES filiais(id),
    conteudo    text,
    embedding   vector(768)
);
CREATE INDEX ix_kb_embedding ON kb_documentos USING ivfflat (embedding vector_cosine_ops);

-- ============================================================================
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
-- 13. TIMESCALE (hypertables + agregados + políticas) — REQUER timescaledb
-- ============================================================================
SELECT create_hypertable('tel_sinais',  'ts', if_not_exists => TRUE);
SELECT create_hypertable('tel_dtc',     'ts', if_not_exists => TRUE);
SELECT create_hypertable('tc_posicoes', 'ts', if_not_exists => TRUE);
SELECT create_hypertable('ts_eventos',  'ts', if_not_exists => TRUE);
SELECT create_hypertable('jor_eventos', 'ts', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW vw_consumo_veiculo
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS hora, veiculo_id,
       avg(km_l)               AS km_l_medio,
       avg((eco_ativo)::int)   AS pct_eco,
       avg((embalo)::int)      AS pct_embalo
FROM tel_sinais
GROUP BY hora, veiculo_id;

SELECT add_retention_policy('tel_sinais', INTERVAL '90 days');
SELECT add_compression_policy('tel_sinais', INTERVAL '7 days');
SELECT add_retention_policy('tc_posicoes', INTERVAL '180 days');
