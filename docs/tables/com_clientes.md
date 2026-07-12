---
type: Table
title: com_clientes
description: Clientes (embarcadores) — cadastro comercial com score, limite de crédito e filial. RLS por filial.
resource: sql/schema.sql
tags: [comercial, cadastro, rls, pii]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE com_clientes (
    id              serial PRIMARY KEY,
    nome            text NOT NULL,
    cnpj            text UNIQUE,
    segmento        text,
    score           numeric(5,1),
    limite_credito  numeric(14,2) DEFAULT 0,
    filial_id       int REFERENCES filiais(id),
    criado_em       timestamptz NOT NULL DEFAULT now()
);
```

# Notes

- **RLS habilitada** (política `p_clientes_filial`): visível só se `filial_id IS NULL OR filial_id = ANY(app_filiais())`.
- `cnpj` é PII/dado de cliente — sujeito às regras de segurança (não roteia para Claude API).
- `score` (0–999,9) alimentado pela skill `scoring-cliente`.
- Referenciado por [op_viagens](op_viagens.md), [fin_titulos](fin_titulos.md), [prog_cargas](prog_cargas.md) e pela view [vw_rkm_cliente](../views/vw_rkm_cliente.md).
