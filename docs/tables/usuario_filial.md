---
type: Table
title: usuario_filial
description: Tabela de junção usuário × filial (N:N) — define o escopo de linhas visível na RLS.
resource: sql/schema.sql
tags: [governanca, acesso, rls]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE usuario_filial (
    usuario_id  int REFERENCES usuarios(id) ON DELETE CASCADE,
    filial_id   int REFERENCES filiais(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, filial_id)
);
```

# Notes

- Alimenta o setting `app.user_filiais` usado por `app_filiais()` na RLS.
- Liga [usuarios](usuarios.md) a [filiais](filiais.md).
