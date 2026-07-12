---
type: Table
title: int_credenciais
description: Referências de credenciais dos conectores — armazena SÓ a referência ao cofre, nunca o segredo.
resource: sql/schema.sql
tags: [integracoes, credenciais, seguranca]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE int_credenciais (
    id          serial PRIMARY KEY,
    conector_id int REFERENCES int_conectores(id) ON DELETE CASCADE,
    ref_cofre   text NOT NULL,                 -- REFERÊNCIA ao cofre, nunca o segredo
    escopo      text,
    expira_em   timestamptz
);
```

# Notes

- **Segurança:** `ref_cofre` guarda apenas o ponteiro para o cofre/secret manager — o segredo real **nunca** é persistido aqui nem versionado.
- ON DELETE CASCADE com [int_conectores](int_conectores.md).
