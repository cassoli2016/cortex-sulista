---
type: Table
title: jor_jornadas
description: Jornada diária consolidada por motorista (horas de direção/descanso e violações) — compliance Lei 13.103/2015.
resource: sql/schema.sql
tags: [jornada, compliance, lei-13103]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE jor_jornadas (
    id              serial PRIMARY KEY,
    motorista_id    int REFERENCES rh_motoristas(id),
    data            date NOT NULL,
    horas_direcao   interval,
    horas_descanso  interval,
    violacoes       jsonb
);
```

# Notes

- Tabela regular (não é hypertable). `horas_*` do tipo `interval`.
- `violacoes` (jsonb) — considerado "com violação" quando não é `NULL` nem `'[]'`.
- Base da view [vw_compliance_jornada](../views/vw_compliance_jornada.md). Limites: direção contínua ≤5h30, descanso interjornada 11h, intervalo 1h, descanso semanal 35h.
- Liga a [rh_motoristas](rh_motoristas.md).
