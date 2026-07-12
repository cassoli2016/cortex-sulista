---
type: Table
title: fin_adiantamentos
description: Adiantamentos a motoristas/fornecedores, opcionalmente vinculados a uma viagem.
resource: sql/schema.sql
tags: [financeiro, adiantamento, sensivel]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fin_adiantamentos (
    id          serial PRIMARY KEY,
    motorista_id int REFERENCES rh_motoristas(id),
    fornecedor_id int REFERENCES sup_fornecedores(id),
    valor       numeric(14,2) NOT NULL,
    data        date NOT NULL,
    viagem_id   int REFERENCES op_viagens(id),
    status      text NOT NULL DEFAULT 'aberto'
);
```

# Notes

- Dado financeiro sensível.
- Liga a [rh_motoristas](rh_motoristas.md), [sup_fornecedores](sup_fornecedores.md) e [op_viagens](op_viagens.md).
