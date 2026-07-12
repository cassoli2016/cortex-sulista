---
type: Table
title: int_conectores
description: Registro de conectores da Central de Integrações (nome, modo pull/push/both, capabilities).
resource: sql/schema.sql
tags: [integracoes, conector]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE int_conectores (
    id          serial PRIMARY KEY,
    name        text UNIQUE NOT NULL,
    mode        text CHECK (mode IN ('pull','push','both')),
    capabilities text[],
    ativo       boolean NOT NULL DEFAULT true,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
```

# Notes

- `mode` ∈ {`pull`,`push`,`both`}; `capabilities` é `text[]`.
- Um conector implementa a interface padrão `Connector` (authenticate/fetch/handle_webhook/normalize/health_check) — skill `connector-builder`, doc `docs/INTEGRACOES.md`.
- Relaciona-se com [int_credenciais](int_credenciais.md) e [int_sync_state](int_sync_state.md).
