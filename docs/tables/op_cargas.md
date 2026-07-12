---
type: Table
title: op_cargas
description: Cargas de cada viagem (peso, valor da mercadoria, NF).
resource: sql/schema.sql
tags: [operacional, carga]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE op_cargas (
    id              serial PRIMARY KEY,
    viagem_id       int REFERENCES op_viagens(id) ON DELETE CASCADE,
    peso            numeric(12,2),
    valor_mercadoria numeric(14,2),
    nf_id           text
);
```

# Notes

- ON DELETE CASCADE com [op_viagens](op_viagens.md).
- `nf_id` referencia a NF-e (fonte fiscal da carga); `valor_mercadoria` relevante para ad valorem/GRIS.
