---
type: Table
title: int_webhook_log
description: Log de webhooks recebidos (push) com validação de assinatura HMAC.
resource: sql/schema.sql
tags: [integracoes, webhook, hmac]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE int_webhook_log (
    id              bigserial PRIMARY KEY,
    conector        text NOT NULL,
    assinatura_valida boolean,
    recebido_em     timestamptz NOT NULL DEFAULT now(),
    status          text
);
```

# Notes

- `assinatura_valida` registra a verificação HMAC do webhook (modo push).
- Eventos válidos seguem para [int_raw_events](int_raw_events.md).
