---
type: Table
title: sup_agregados
description: Agregados (terceiros) com RKM acordado e rotas atendidas — insumo do make-vs-buy.
resource: sql/schema.sql
tags: [suprimentos, agregados, make-vs-buy]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE sup_agregados (
    id              serial PRIMARY KEY,
    fornecedor_id   int REFERENCES sup_fornecedores(id),
    rkm_acordado    numeric(10,4),
    rotas           int[]
);
```

# Notes

- `rkm_acordado` é o valor pago por km ao agregado — comparado ao CKM próprio no [spread make-vs-buy](../metrics/spread_make_vs_buy.md).
- `rotas` é `int[]` referenciando ids de [op_rotas](op_rotas.md).
- Liga a [sup_fornecedores](sup_fornecedores.md) (tipo `agregado`).
