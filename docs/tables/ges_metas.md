---
type: Table
title: ges_metas
description: Metas/indicadores por área e período, com responsável.
resource: sql/schema.sql
tags: [gestao, metas, kpi]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE ges_metas (
    id          serial PRIMARY KEY,
    area        text,
    indicador   text,
    meta        numeric(14,4),
    periodo     text,
    responsavel text
);
```

# Notes

- Estruturada/acompanhada pela skill `metas-okr`.
- Complementa os OKRs em [ges_okr](ges_okr.md).
