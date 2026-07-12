---
type: Table
title: papel_modulo
description: Permissões por papel × módulo × tipo (read/write/approve) — o coração do RBAC por módulo.
resource: sql/schema.sql
tags: [governanca, acesso, rbac]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE papel_modulo (
    papel_id    int REFERENCES papeis(id) ON DELETE CASCADE,
    modulo      text NOT NULL,                -- financeiro, comercial, ...
    permissao   text NOT NULL CHECK (permissao IN ('read','write','approve')),
    PRIMARY KEY (papel_id, modulo, permissao)
);
```

# Notes

- `permissao` restrita a `read`, `write`, `approve`.
- `modulo` é texto livre alinhado aos módulos do portal (financeiro, comercial, operacional, programacao, torre_controle, torre_seguranca, telemetria, frota, jornada, suprimentos, gestao, integracoes, analytics, copiloto).
- Toda escrita exige confirmação humana e entra em [audit_log](audit_log.md).
