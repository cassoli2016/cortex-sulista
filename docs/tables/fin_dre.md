---
type: Table
title: fin_dre
description: Base da DRE gerencial por competência, conta e grupo (receita/custo_var/custo_motorista/fixo/adm/fin).
resource: sql/schema.sql
tags: [financeiro, dre, sensivel]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fin_dre (
    id          serial PRIMARY KEY,
    competencia date NOT NULL,
    conta       text NOT NULL,
    grupo       text NOT NULL,                 -- receita|custo_var|custo_motorista|fixo|adm|fin
    valor       numeric(14,2) NOT NULL,
    centro_custo text
);
CREATE INDEX ix_dre_comp ON fin_dre (competencia, grupo);
```

# Notes

- `grupo` ∈ {`receita`,`custo_var`,`custo_motorista`,`fixo`,`adm`,`fin`} — usado na DRE em cascata (skill `dre-analise`).
- Base da view [vw_dre_mensal](../views/vw_dre_mensal.md).
- Dado financeiro sensível.
