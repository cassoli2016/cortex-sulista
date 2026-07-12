---
type: Table
title: vw_consumo_veiculo
description: Continuous aggregate (TimescaleDB) — consumo por veículo em buckets de 1h (km/l médio, %ECO, %embalo).
resource: sql/schema.sql
tags: [telemetria, view, continuous-aggregate, timescaledb]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_consumo_veiculo
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts) AS hora, veiculo_id,
       avg(km_l)               AS km_l_medio,
       avg((eco_ativo)::int)   AS pct_eco,
       avg((embalo)::int)      AS pct_embalo
FROM tel_sinais
GROUP BY hora, veiculo_id;
```

# Notes

- **Continuous aggregate** do TimescaleDB (`WITH (timescaledb.continuous)`) — bucket de 1 hora via `time_bucket`.
- `pct_eco`/`pct_embalo` são médias de booleanos convertidos para int (fração 0–1).
- Fonte: [tel_sinais](../tables/tel_sinais.md). Base dos insights de eficiência (skill `telemetria-insights`).
