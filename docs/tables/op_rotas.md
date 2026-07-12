---
type: Table
title: op_rotas
description: Rotas (origem/destino por UF) com distância e pedágio estimado.
resource: sql/schema.sql
tags: [operacional, cadastro]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE op_rotas (
    id              serial PRIMARY KEY,
    origem_uf       char(2),
    destino_uf      char(2),
    distancia_km    numeric(10,1),
    pedagio_estimado numeric(12,2)
);
```

# Notes

- Base para análise de rota (skill `analise-rota`): RKM, CKM, retorno vazio, margem.
- Referenciado por [op_viagens](op_viagens.md) e agregados de [sup_agregados](sup_agregados.md) (`rotas int[]`).
