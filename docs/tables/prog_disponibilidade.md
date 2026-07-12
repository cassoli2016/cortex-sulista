---
type: Table
title: prog_disponibilidade
description: Janelas de (in)disponibilidade de veículos para a programação.
resource: sql/schema.sql
tags: [programacao, disponibilidade]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE prog_disponibilidade (
    id              serial PRIMARY KEY,
    veiculo_id      int REFERENCES fro_veiculos(id),
    inicio          timestamptz,
    fim             timestamptz,
    motivo          text
);
```

# Notes

- Usada para detectar ociosidade e gargalos na programação de cargas.
- Liga a [fro_veiculos](fro_veiculos.md).
