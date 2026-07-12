---
type: Table
title: ges_atas
description: Atas de reunião (participantes, pauta, decisões).
resource: sql/schema.sql
tags: [gestao, ata]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE ges_atas (
    id          serial PRIMARY KEY,
    reuniao     text,
    data        date,
    participantes text[],
    pauta       text,
    decisoes    text
);
```

# Notes

- `participantes` é `text[]`.
- Gerada pela skill `ata-reuniao` (ata estruturada + plano de ação 5W2H).
- Ações derivadas ficam em [ges_acoes](ges_acoes.md).
