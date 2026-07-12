---
type: Table
title: ges_acoes
description: Planos de ação (5W2H) ligados a atas e/ou OKRs, com status e prioridade.
resource: sql/schema.sql
tags: [gestao, acao, 5w2h]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE ges_acoes (
    id          serial PRIMARY KEY,
    ata_id      int REFERENCES ges_atas(id) ON DELETE SET NULL,
    okr_id      int REFERENCES ges_okr(id) ON DELETE SET NULL,
    o_que       text NOT NULL,
    quem        text NOT NULL,
    quando      date NOT NULL,
    como        text,
    status      text NOT NULL DEFAULT 'aberta', -- aberta|em_andamento|concluida|atrasada
    prioridade  text DEFAULT 'media'
);
```

# Notes

- Modelo 5W2H (`o_que`, `quem`, `quando`, `como`...).
- `status` ∈ {`aberta`,`em_andamento`,`concluida`,`atrasada`}.
- ON DELETE SET NULL para [ges_atas](ges_atas.md) e [ges_okr](ges_okr.md).
