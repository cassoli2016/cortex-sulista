---
type: Table
title: prog_alocacao
description: Alocação (proposta/confirmada) de carga a veículo + motorista.
resource: sql/schema.sql
tags: [programacao, alocacao]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE prog_alocacao (
    id              serial PRIMARY KEY,
    carga_id        int REFERENCES prog_cargas(id) ON DELETE CASCADE,
    veiculo_id      int REFERENCES fro_veiculos(id),
    motorista_id    int REFERENCES rh_motoristas(id),
    status          text NOT NULL DEFAULT 'proposta',
    criado_em       timestamptz NOT NULL DEFAULT now()
);
```

# Notes

- ON DELETE CASCADE com [prog_cargas](prog_cargas.md).
- Liga [fro_veiculos](fro_veiculos.md) e [rh_motoristas](rh_motoristas.md) a uma carga programada.
- `status` inicia em `proposta`.
