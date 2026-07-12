---
type: Table
title: vw_resultado_viagem
description: View materializada — resultado por viagem (receita − custo variável − fixo rateado).
resource: sql/schema.sql
tags: [operacional, view, materializada, resultado]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_resultado_viagem AS
SELECT id AS viagem_id, cliente_id, rota_id,
       receita_frete,
       coalesce(custo_variavel,0)      AS custo_variavel,
       coalesce(custo_fixo_rateado,0)  AS custo_fixo_rateado,
       receita_frete - coalesce(custo_variavel,0) - coalesce(custo_fixo_rateado,0) AS resultado
FROM op_viagens
WHERE status = 'concluida';
```

# Notes

- View **materializada** — só `status = 'concluida'`; `coalesce(...,0)` trata custos nulos.
- Métrica relacionada: [resultado_viagem](../metrics/resultado_viagem.md). Fonte: [op_viagens](../tables/op_viagens.md).
