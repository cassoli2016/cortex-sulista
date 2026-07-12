---
type: Table
title: tel_dtc
description: Hypertable (TimescaleDB) de códigos de falha DTC por veículo.
resource: sql/schema.sql
tags: [telemetria, hypertable, timescaledb, dtc]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE tel_dtc (
    id          bigserial,
    veiculo_id  int NOT NULL,
    codigo      text NOT NULL,
    descricao   text,
    ts          timestamptz NOT NULL,
    ativo       boolean DEFAULT true,
    PRIMARY KEY (id, ts)
);

-- TimescaleDB
SELECT create_hypertable('tel_dtc', 'ts', if_not_exists => TRUE);
```

# Notes

- **Hypertable** particionada por `ts`; PK composta `(id, ts)` (exigência do Timescale).
- `codigo` = DTC (Diagnostic Trouble Code); `ativo` indica falha corrente.
- `veiculo_id` referencia [fro_veiculos](fro_veiculos.md).
