---
type: Runbook
title: Setup de desenvolvimento (arranque no Claude Code)
description: Passo a passo para subir a infra, aplicar o schema (migrations 0001–0006) e abrir o Claude Code no CÓRTEX.
resource: docs/GUIA_CLAUDE_CODE.md, CLAUDE.md §9
tags: [runbook, setup, dev, alembic, docker, ollama]
timestamp: 2026-07-11
---

# Procedure

## 1. Preparar o repositório
```bash
unzip cortex.zip && cd cortex
cp .env.example .env          # preencha os segredos depois
git init && git add . && git commit -m "chore: bootstrap CÓRTEX"
```
Atalho: `bash scripts/bootstrap.sh` faz git + estrutura + infra + migrations de uma vez.

## 2. Subir a infra e aplicar o schema
```bash
docker compose up -d postgres redis ollama   # postgres = imagem TimescaleDB
ollama pull gemma2:9b

uv sync                       # instala deps (pyproject na raiz)
uv run alembic upgrade head   # cria todo o schema (governança → views)
```
Confira: `uv run alembic current` deve mostrar `0006 (head)`. O schema completo está em `sql/schema.sql` (referência) e é aplicado pelas 6 migrations (`sql/blocks/` via `migrations/versions/`).

## 3. Instalar e abrir o Claude Code
```bash
npm install -g @anthropic-ai/claude-code   # requer Node LTS recente
claude                                      # na raiz do projeto
```
Doc oficial: https://docs.claude.com/en/docs/claude-code/overview

## 4. Rodar app (dev)
```bash
uv run uvicorn api.main:app --reload
cd web && pnpm i && pnpm dev
```

# Notes

- Ordem das migrations: `0001` extensions/governance → `0002` cadastros/operacional → `0003` financeiro/gestão → `0004` timeseries → `0005` integrações/RAG → `0006` RLS/views.
- Desenvolvimento por fases (roadmap em `CLAUDE.md §10`): Fase 1 = auth + RBAC + RLS + audit + financeiro. Prompts prontos por fase estão em `docs/GUIA_CLAUDE_CODE.md §4`.
- Regra: **parâmetros, não números mágicos** — tudo de negócio vive em [parametros_negocio](../concepts/parametros_negocio.md).
- Nada exposto antes do [go_live](go_live.md).
- Topologia dos containers em [infra_topologia](../services/infra_topologia.md).
