---
type: Table
title: papeis
description: Papéis de RBAC (ceo, controller, fin_analista, ...) atribuídos a usuários.
resource: sql/schema.sql
tags: [governanca, acesso, rbac]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE papeis (
    id          serial PRIMARY KEY,
    nome        text UNIQUE NOT NULL          -- ceo, controller, fin_analista, ...
);
```

# Notes

- Cada papel concede permissões por módulo em [papel_modulo](papel_modulo.md).
- Atribuído a usuários via [usuario_papel](usuario_papel.md).
