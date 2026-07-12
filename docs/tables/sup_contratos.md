---
type: Table
title: sup_contratos
description: Contratos com fornecedores (vigência e termos em jsonb).
resource: sql/schema.sql
tags: [suprimentos, contratos]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE sup_contratos (
    id              serial PRIMARY KEY,
    fornecedor_id   int REFERENCES sup_fornecedores(id),
    inicio          date,
    fim             date,
    termos          jsonb
);
```

# Notes

- `termos` em `jsonb` (livre).
- Liga a [sup_fornecedores](sup_fornecedores.md).
