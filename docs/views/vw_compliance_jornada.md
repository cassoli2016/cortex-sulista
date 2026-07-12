---
type: Table
title: vw_compliance_jornada
description: View materializada — compliance de jornada por motorista/dia com flag de violação.
resource: sql/schema.sql
tags: [jornada, view, materializada, compliance]
timestamp: 2026-07-11
---

# Definition

```sql
CREATE MATERIALIZED VIEW vw_compliance_jornada AS
SELECT motorista_id, data,
       horas_direcao, horas_descanso,
       (violacoes IS NOT NULL AND violacoes <> '[]'::jsonb) AS tem_violacao
FROM jor_jornadas;
```

# Notes

- View **materializada**; `tem_violacao` é `true` quando `violacoes` não é nulo nem `'[]'`.
- Fonte: [jor_jornadas](../tables/jor_jornadas.md). Base do semáforo de compliance (Lei 13.103/2015).
