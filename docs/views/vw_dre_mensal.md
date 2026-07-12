---
type: Table
title: vw_dre_mensal
description: View materializada — DRE por competência e grupo (soma de valor).
resource: sql/schema.sql
tags: [financeiro, view, materializada, dre]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_dre_mensal AS
SELECT competencia, grupo, sum(valor) AS valor
FROM fin_dre
GROUP BY competencia, grupo;
```

# Notes

- View **materializada**; `grupo` ∈ {receita, custo_var, custo_motorista, fixo, adm, fin}.
- Fonte: [fin_dre](../tables/fin_dre.md). Usada pela skill `dre-analise` (DRE em cascata).
