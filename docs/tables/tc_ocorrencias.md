---
type: Table
title: tc_ocorrencias
description: Ocorrências operacionais por viagem (tipo, severidade, abertura/fechamento) — Torre de Controle.
resource: sql/schema.sql
tags: [torre_controle, ocorrencia]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE tc_ocorrencias (
    id          bigserial PRIMARY KEY,
    viagem_id   int,
    tipo        text,
    severidade  text,
    abertura    timestamptz NOT NULL DEFAULT now(),
    fechamento  timestamptz
);
```

# Notes

- Tabela regular (não é hypertable).
- Ocorrências abertas (sem `fechamento`) aparecem no painel da Torre de Controle.
- `viagem_id` → [op_viagens](op_viagens.md).
