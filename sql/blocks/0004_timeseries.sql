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
