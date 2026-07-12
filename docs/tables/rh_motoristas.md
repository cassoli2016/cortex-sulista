---
type: Table
title: rh_motoristas
description: Cadastro de motoristas (CNH, categoria, admissão). RLS por filial. Contém PII.
resource: sql/schema.sql
tags: [rh, cadastro, rls, pii]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE rh_motoristas (
    id          serial PRIMARY KEY,
    nome        text NOT NULL,
    cpf         text UNIQUE,
    cnh         text,
    categoria_cnh text,
    filial_id   int REFERENCES filiais(id),
    ativo       boolean NOT NULL DEFAULT true,
    admissao    date
);
```

# Notes

- **RLS habilitada** (`p_motoristas_filial`) por `filial_id`.
- `cpf`/`cnh` são PII — nunca roteiam para a Claude API (só Gemma local).
- Referenciado por [op_viagens](op_viagens.md), [prog_alocacao](prog_alocacao.md), [fin_adiantamentos](fin_adiantamentos.md), [ts_scores](ts_scores.md), [jor_jornadas](jor_jornadas.md).
