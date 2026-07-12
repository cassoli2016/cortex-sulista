---
type: Table
title: fro_veiculos
description: Ativos da frota (cavalo, truck, frigorífico...) com dados de compra, residual e vida útil em km. RLS por filial.
resource: sql/schema.sql
tags: [frota, cadastro, rls]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE fro_veiculos (
    id              serial PRIMARY KEY,
    placa           text UNIQUE NOT NULL,
    tipo            text,                      -- cavalo, truck, frigorifico...
    ano             int,
    valor_compra    numeric(14,2),
    valor_residual  numeric(14,2),
    vida_km         numeric(12,0),
    status          text DEFAULT 'ativo',      -- ativo|parado|manutencao|vendido
    filial_id       int REFERENCES filiais(id)
);
```

# Notes

- **RLS habilitada** (`p_veiculos_filial`) por `filial_id`.
- `valor_compra`, `valor_residual` e `vida_km` alimentam o cálculo de depreciação (CKM cheio).
- Referenciado por [op_viagens](op_viagens.md), [prog_alocacao](prog_alocacao.md), [prog_disponibilidade](prog_disponibilidade.md), [fro_manutencao](fro_manutencao.md), [fro_pneus](fro_pneus.md).
