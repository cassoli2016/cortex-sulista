---
type: Table
title: ts_scores
description: Score de risco por motorista e período, com componentes em jsonb — Torre de Segurança.
resource: sql/schema.sql
tags: [torre_seguranca, score, risco]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE ts_scores (
    id          bigserial PRIMARY KEY,
    motorista_id int REFERENCES rh_motoristas(id),
    periodo     date,
    score       numeric(5,1),
    componentes jsonb
);
```

# Notes

- Tabela regular (não é hypertable).
- `componentes` (jsonb) detalha o cálculo do `score`.
- Deriva de [ts_eventos](ts_eventos.md); liga a [rh_motoristas](rh_motoristas.md).
