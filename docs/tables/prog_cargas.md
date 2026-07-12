---
type: Table
title: prog_cargas
description: Cargas a programar (janelas de coleta/entrega como tstzrange) antes da alocação a veículos.
resource: sql/schema.sql
tags: [programacao, carga]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE prog_cargas (
    id              serial PRIMARY KEY,
    cliente_id      int REFERENCES com_clientes(id),
    origem          text,
    destino         text,
    janela_coleta   tstzrange,
    janela_entrega  tstzrange,
    peso            numeric(12,2),
    tipo_carga      text,
    status          text NOT NULL DEFAULT 'pendente' -- pendente|alocada|em_curso|entregue
);
```

# Notes

- `janela_coleta`/`janela_entrega` usam `tstzrange` (intervalo de timestamptz).
- `status` ∈ {`pendente`,`alocada`,`em_curso`,`entregue`}.
- Alocada a veículo/motorista via [prog_alocacao](prog_alocacao.md); skill `programacao-cargas`.
