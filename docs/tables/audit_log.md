---
type: Table
title: audit_log
description: Trilha de auditoria de todas as ações (read/write/approve/login) por usuário e módulo.
resource: sql/schema.sql
tags: [governanca, acesso, auditoria, seguranca]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    usuario_id  int REFERENCES usuarios(id),
    acao        text NOT NULL,                -- read|write|approve|login|...
    modulo      text,
    entidade    text,
    entidade_id text,
    detalhe     jsonb,
    ip          inet,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_criado ON audit_log (criado_em);
CREATE INDEX ix_audit_usuario ON audit_log (usuario_id, criado_em);
```

# Notes

- Regra de segurança: **toda escrita** exige confirmação humana explícita e gera registro aqui.
- `detalhe` em `jsonb`; `ip` do tipo `inet`.
- Índices por `criado_em` e por `(usuario_id, criado_em)` para consultas temporais.
