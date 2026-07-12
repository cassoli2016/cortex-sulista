---
type: Table
title: usuarios
description: Usuários do portal CÓRTEX; base de autenticação e do RBAC.
resource: sql/schema.sql
tags: [governanca, acesso, rbac]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE usuarios (
    id          serial PRIMARY KEY,
    email       text UNIQUE NOT NULL,
    nome        text NOT NULL,
    ativo       boolean NOT NULL DEFAULT true,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
```

# Notes

- `email` é único e serve de identificador de login.
- Vínculos: papéis via [usuario_papel](usuario_papel.md); filiais (escopo RLS) via [usuario_filial](usuario_filial.md).
- Ações do usuário são registradas em [audit_log](audit_log.md).
