---
type: Table
title: jor_eventos
description: Hypertable (TimescaleDB) de eventos de jornada do motorista (direção, parada, descanso, refeição).
resource: sql/schema.sql
tags: [jornada, hypertable, timescaledb, lei-13103]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE jor_eventos (
    ts          timestamptz NOT NULL,
    motorista_id int NOT NULL,
    tipo        text NOT NULL,                 -- direcao|parada|descanso|refeicao
    duracao     interval
);
CREATE INDEX ix_jor_eventos_mot ON jor_eventos (motorista_id, ts DESC);

-- TimescaleDB
SELECT create_hypertable('jor_eventos', 'ts', if_not_exists => TRUE);
```

# Notes

- **Hypertable** por `ts`. `duracao` do tipo `interval`.
- `tipo` ∈ {`direcao`,`parada`,`descanso`,`refeicao`}.
- Base do cálculo de compliance Lei 13.103/2015 consolidado em [jor_jornadas](jor_jornadas.md) (skill `jornada-motorista`).
