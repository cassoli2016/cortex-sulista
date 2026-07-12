---
type: Table
title: usuario_papel
description: Tabela de junção usuário × papel (N:N) do RBAC.
resource: sql/schema.sql
tags: [governanca, acesso, rbac]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE usuario_papel (
    usuario_id  int REFERENCES usuarios(id) ON DELETE CASCADE,
    papel_id    int REFERENCES papeis(id) ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, papel_id)
);
```

# Notes

- Chave primária composta; ON DELETE CASCADE em ambos os lados.
- Liga [usuarios](usuarios.md) a [papeis](papeis.md).
