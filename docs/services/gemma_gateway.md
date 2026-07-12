---
type: Service
title: Gateway de IA (Gemma)
description: Roteia inferência entre Gemma local e Claude API por sensibilidade/complexidade, com guardrail de PII, RAG e cache semântico.
resource: docs/ARQUITETURA.md §6
tags: [ia, gateway, gemma, ollama, rag, seguranca, servico]
timestamp: 2026-07-11
---

# Definition

Gateway sobre Ollama (Gemma) que:
- **Roteia** Gemma local ↔ Claude API por sensibilidade e complexidade.
- **Guardrail de PII** antes de qualquer saída externa — PII/dado financeiro **nunca** sai para a Claude API.
- **RAG** sobre pgvector ([kb_documentos](../tables/kb_documentos.md)) com tags de escopo (políticas, contratos, manuais, atas).
- **Cache semântico** + rate limit + log de custo por área.

# Notes

- Regra de segurança (CLAUDE.md §8): o orquestrador bloqueia roteamento externo se detectar PII.
- Base do copiloto conversacional e dos agentes; orquestração de fluxo em [langgraph_orquestracao](langgraph_orquestracao.md).
