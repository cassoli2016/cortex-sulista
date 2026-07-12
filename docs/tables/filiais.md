---
type: Table
title: filiais
description: Unidades/filiais da transportadora — âncora do escopo de RLS (Row-Level Security) por filial.
resource: sql/schema.sql
tags: [governanca, acesso, rls]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE filiais (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    uf          char(2)
);
```

# Notes

- Referenciada por praticamente todas as tabelas de negócio via `filial_id` para RLS.
- A política de RLS usa `app_filiais()` e o setting de sessão `app.user_filiais` (ex.: `'1,2,3'`). CEO/auditor recebem todas as filiais.
- Tabelas com RLS por filial: [com_clientes](com_clientes.md), [rh_motoristas](rh_motoristas.md), [fro_veiculos](fro_veiculos.md), [op_viagens](op_viagens.md), [fin_titulos](fin_titulos.md).
