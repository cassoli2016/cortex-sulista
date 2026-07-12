---
type: Table
title: fin_lancamentos
description: Lançamentos financeiros por conta/centro de custo (base contábil bruta).
resource: sql/schema.sql
tags: [financeiro, contabil, sensivel]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fin_lancamentos (
    id          serial PRIMARY KEY,
    conta       text,
    centro_custo text,
    valor       numeric(14,2) NOT NULL,
    data        date NOT NULL,
    origem      text
);
```

# Notes

- Classificado (conta/centro de custo/grupo DRE) pela skill `analista-contabil`; consolidado em [fin_dre](fin_dre.md).
- Dado financeiro sensível.
