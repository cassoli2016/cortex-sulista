---
type: Table
title: ges_okr
description: OKRs — objetivo + key result com baseline, atual, meta e prazo.
resource: sql/schema.sql
tags: [gestao, okr]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE ges_okr (
    id          serial PRIMARY KEY,
    objetivo    text NOT NULL,
    key_result  text NOT NULL,
    baseline    numeric(14,4),
    atual       numeric(14,4),
    meta        numeric(14,4),
    prazo       date,
    dono        text
);
```

# Notes

- Progresso de cada key result (atual × meta × prazo) exibido no painel de OKRs (farol).
- Ligado a ações via [ges_acoes](ges_acoes.md); skill `metas-okr`.
