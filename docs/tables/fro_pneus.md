---
type: Table
title: fro_pneus
description: Controle de pneus por veículo (posição, custo de jogo/recapes, km de vida).
resource: sql/schema.sql
tags: [frota, pneus]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fro_pneus (
    id              serial PRIMARY KEY,
    veiculo_id      int REFERENCES fro_veiculos(id),
    posicao         text,
    custo_jogo      numeric(14,2),
    custo_recapes   numeric(14,2) DEFAULT 0,
    km_vida         numeric(12,0),
    instalado_em    date
);
```

# Notes

- Componente relevante do CKM variável (custo por km de pneu).
- Liga a [fro_veiculos](fro_veiculos.md).
