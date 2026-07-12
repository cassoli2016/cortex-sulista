---
type: Table
title: tel_sinais
description: Hypertable (TimescaleDB) de sinais de telemetria CAN/J1939 por veículo — consumo, RPM, ECO, embalo, freio motor.
resource: sql/schema.sql
tags: [telemetria, hypertable, timescaledb, timeseries]
timestamp: 2026-07-11
---

# Schema

```sql
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

-- TimescaleDB
SELECT create_hypertable('tel_sinais', 'ts', if_not_exists => TRUE);
SELECT add_retention_policy('tel_sinais', INTERVAL '90 days');
SELECT add_compression_policy('tel_sinais', INTERVAL '7 days');
```

# Notes

- **Hypertable** particionada por `ts`. Retenção **90 dias**; compressão após **7 dias**.
- Alta cadência — base do continuous aggregate [vw_consumo_veiculo](../views/vw_consumo_veiculo.md) e dos insights de eficiência (skill `telemetria-insights`).
- `payload` em `jsonb` guarda sinais brutos adicionais. `veiculo_id` referencia [fro_veiculos](fro_veiculos.md) (sem FK formal na hypertable).
