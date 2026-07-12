---
type: Table
title: int_sync_state
description: Estado de sincronização por conector × capability (cursor de polling, última sync, status).
resource: sql/schema.sql
tags: [integracoes, sync]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE int_sync_state (
    conector_id int REFERENCES int_conectores(id) ON DELETE CASCADE,
    capability  text NOT NULL,
    cursor      text,
    ultima_sync timestamptz,
    status      text DEFAULT 'ok',             -- ok|atrasado|circuit_open
    PRIMARY KEY (conector_id, capability)
);
```

# Notes

- PK composta `(conector_id, capability)`. `cursor` = ponto de retomada do polling incremental (pull).
- `status` ∈ {`ok`,`atrasado`,`circuit_open`} — reflete o circuit breaker por conector.
- ON DELETE CASCADE com [int_conectores](int_conectores.md).
