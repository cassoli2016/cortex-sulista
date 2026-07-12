---
type: Table
title: sup_fornecedores
description: Fornecedores (posto, oficina, agregado, outro) com avaliação.
resource: sql/schema.sql
tags: [suprimentos, cadastro]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE sup_fornecedores (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    cnpj        text,
    tipo        text CHECK (tipo IN ('posto','oficina','agregado','outro')),
    avaliacao   numeric(3,1)
);
```

# Notes

- `tipo` restrito a `posto`, `oficina`, `agregado`, `outro`.
- Referenciado por [sup_agregados](sup_agregados.md), [sup_contratos](sup_contratos.md), [fin_titulos](fin_titulos.md), [fin_adiantamentos](fin_adiantamentos.md).
