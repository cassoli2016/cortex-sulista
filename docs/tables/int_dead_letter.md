---
type: Table
title: int_dead_letter
description: Dead-letter queue dos conectores — eventos que falharam no processamento, com erro e tentativas.
resource: sql/schema.sql
tags: [integracoes, dead-letter, resiliencia]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE int_dead_letter (
    id          bigserial PRIMARY KEY,
    conector    text NOT NULL,
    erro        text,
    tentativas  int DEFAULT 0,
    payload     jsonb,
    criado_em   timestamptz NOT NULL DEFAULT now()
);
```

# Notes

- Recebe eventos que esgotaram retry/backoff. Monitorada pelo agente `integracoes` (saúde dos conectores).
- Contraparte do fluxo feliz em [int_raw_events](int_raw_events.md).
