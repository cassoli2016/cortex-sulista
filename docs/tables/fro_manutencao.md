---
type: Table
title: fro_manutencao
description: Ordens de manutenção (preventiva/corretiva) por veículo, com custo e km.
resource: sql/schema.sql
tags: [frota, manutencao]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fro_manutencao (
    id          serial PRIMARY KEY,
    veiculo_id  int REFERENCES fro_veiculos(id),
    tipo        text CHECK (tipo IN ('prev','corr')),
    custo       numeric(14,2),
    data        date,
    km          numeric(12,0)
);
```

# Notes

- `tipo` ∈ {`prev`,`corr`} (preventiva/corretiva).
- Insumo de manutenção preditiva (agente `frota`) e componente do CKM.
- Liga a [fro_veiculos](fro_veiculos.md).
