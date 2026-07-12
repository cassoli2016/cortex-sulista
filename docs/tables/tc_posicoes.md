---
type: Table
title: tc_posicoes
description: Hypertable (TimescaleDB) de posições em tempo real (lat/lng, velocidade, status, ETA) — Torre de Controle.
resource: sql/schema.sql
tags: [torre_controle, hypertable, timescaledb, tempo-real]
timestamp: 2026-07-11
---

# Schema

```sql
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

-- TimescaleDB
SELECT create_hypertable('tc_posicoes', 'ts', if_not_exists => TRUE);
SELECT add_retention_policy('tc_posicoes', INTERVAL '180 days');
```

# Notes

- **Hypertable** por `ts`; retenção **180 dias**.
- Última posição por viagem alimenta a view [vw_viagens_ativas](../views/vw_viagens_ativas.md) (LATERAL).
- Tempo real via LISTEN/NOTIFY → WebSocket. `viagem_id` → [op_viagens](op_viagens.md).
