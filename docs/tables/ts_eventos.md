---
type: Table
title: ts_eventos
description: Hypertable (TimescaleDB) de eventos de risco por motorista/veículo (freada, aceleração, excesso, fadiga, acidente) — Torre de Segurança.
resource: sql/schema.sql
tags: [torre_seguranca, hypertable, timescaledb, risco]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE ts_eventos (
    ts          timestamptz NOT NULL,
    motorista_id int,
    veiculo_id  int,
    tipo        text NOT NULL,                 -- freada|aceleracao|excesso|fadiga|acidente
    severidade  text
);
CREATE INDEX ix_ts_eventos_mot ON ts_eventos (motorista_id, ts DESC);

-- TimescaleDB
SELECT create_hypertable('ts_eventos', 'ts', if_not_exists => TRUE);
```

# Notes

- **Hypertable** por `ts`.
- `tipo` ∈ {`freada`,`aceleracao`,`excesso`,`fadiga`,`acidente`}.
- Base da view [vw_sinistralidade](../views/vw_sinistralidade.md) e do score de risco em [ts_scores](ts_scores.md).
