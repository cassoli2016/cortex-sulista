---
type: Table
title: int_raw_events
description: Trilha bruta de eventos recebidos dos conectores, com chave de idempotência.
resource: sql/schema.sql
tags: [integracoes, eventos, idempotencia]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE int_raw_events (
    id          bigserial PRIMARY KEY,
    conector    text NOT NULL,
    chave_idem  text UNIQUE NOT NULL,          -- idempotência
    tipo        text NOT NULL,
    recebido_em timestamptz NOT NULL DEFAULT now(),
    payload     jsonb NOT NULL
);
CREATE INDEX ix_raw_conector ON int_raw_events (conector, recebido_em DESC);
```

# Notes

- `chave_idem` UNIQUE garante idempotência (não reprocessa o mesmo evento).
- `payload` (jsonb) é o dado bruto pré-normalização; event bus em Redis Streams.
- Falhas de processamento vão para [int_dead_letter](int_dead_letter.md).
