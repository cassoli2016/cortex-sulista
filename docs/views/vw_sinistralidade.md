---
type: Table
title: vw_sinistralidade
description: View materializada — sinistralidade mensal (acidentes e total de eventos) da Torre de Segurança.
resource: sql/schema.sql
tags: [torre_seguranca, view, materializada, sinistralidade]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_sinistralidade AS
SELECT date_trunc('month', ts) AS mes,
       count(*) FILTER (WHERE tipo='acidente') AS acidentes,
       count(*)                                AS eventos_total
FROM ts_eventos
GROUP BY date_trunc('month', ts);
```

# Notes

- View **materializada**; `acidentes` usa `FILTER (WHERE tipo='acidente')`.
- Fonte: [ts_eventos](../tables/ts_eventos.md).
