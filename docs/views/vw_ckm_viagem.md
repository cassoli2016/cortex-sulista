---
type: Table
title: vw_ckm_viagem
description: View materializada — CKM bruto/produtivo e retorno vazio por viagem.
resource: sql/schema.sql
tags: [operacional, view, materializada, ckm]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_ckm_viagem AS
SELECT id AS viagem_id, rota_id, modo,
       km_total, km_carregado,
       custo_variavel / nullif(km_total,0)       AS ckm_bruto,
       custo_variavel / nullif(km_carregado,0)   AS ckm_produtivo,
       (km_total - km_carregado) / nullif(km_total,0) AS retorno_vazio
FROM op_viagens
WHERE custo_variavel IS NOT NULL;
```

# Notes

- View **materializada** — só viagens com `custo_variavel IS NOT NULL`.
- Métricas: [ckm_bruto](../metrics/ckm_bruto.md), [ckm_produtivo](../metrics/ckm_produtivo.md), [retorno_vazio](../metrics/retorno_vazio.md).
- Fonte: [op_viagens](../tables/op_viagens.md).
