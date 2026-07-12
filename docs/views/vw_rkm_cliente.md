---
type: Table
title: vw_rkm_cliente
description: View materializada — RKM mensal por cliente (receita, km carregado e RKM) sobre viagens concluídas.
resource: sql/schema.sql
tags: [comercial, view, materializada, rkm]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_rkm_cliente AS
SELECT cliente_id,
       date_trunc('month', inicio) AS mes,
       sum(receita_frete)                          AS receita,
       sum(km_carregado)                           AS km_carregado,
       sum(receita_frete) / nullif(sum(km_carregado),0) AS rkm
FROM op_viagens
WHERE status = 'concluida'
GROUP BY cliente_id, date_trunc('month', inicio);
```

# Notes

- View **materializada** — considera apenas `status = 'concluida'`.
- `rkm` usa `nullif(...,0)` para evitar divisão por zero.
- Fonte: [op_viagens](../tables/op_viagens.md). Métrica: [rkm](../metrics/rkm.md).
