---
type: Table
title: vw_fluxo_caixa
description: View materializada — fluxo de caixa por data de vencimento (receber, pagar, líquido) exceto títulos cancelados.
resource: sql/schema.sql
tags: [financeiro, view, materializada, caixa]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_fluxo_caixa AS
SELECT vencimento AS data,
       sum(CASE WHEN tipo='receber' AND status<>'cancelado' THEN valor ELSE 0 END) AS receber,
       sum(CASE WHEN tipo='pagar'   AND status<>'cancelado' THEN valor ELSE 0 END) AS pagar,
       sum(CASE WHEN tipo='receber' AND status<>'cancelado' THEN valor
                WHEN tipo='pagar'   AND status<>'cancelado' THEN -valor ELSE 0 END) AS liquido
FROM fin_titulos
GROUP BY vencimento;
```

# Notes

- View **materializada**; agrupa por `vencimento`. `liquido` = receber − pagar; ignora `status = 'cancelado'`.
- Fonte: [fin_titulos](../tables/fin_titulos.md). Usada pela skill `fluxo-de-caixa`.
