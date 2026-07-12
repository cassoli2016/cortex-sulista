---
type: Table
title: kb_documentos
description: Base de conhecimento para RAG (pgvector) — conteúdo + embedding vector(768), com tag de módulo para RBAC.
resource: sql/schema.sql
tags: [rag, pgvector, ia, embedding]
timestamp: 2026-07-11
---

# Schema

```sql
CREATE TABLE kb_documentos (
    id          serial PRIMARY KEY,
    titulo      text,
    modulo      text,                          -- tag de escopo p/ RBAC do RAG
    filial_id   int REFERENCES filiais(id),
    conteudo    text,
    embedding   vector(768)
);
CREATE INDEX ix_kb_embedding ON kb_documentos USING ivfflat (embedding vector_cosine_ops);
```

# Notes

- `embedding` é `vector(768)` (pgvector); índice `ivfflat` com `vector_cosine_ops`.
- `modulo` + `filial_id` aplicam escopo de RBAC também na recuperação do RAG.
- Alimenta o copiloto/agentes (IA local Gemma).
