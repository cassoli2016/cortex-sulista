---
type: Service
title: Orquestração de IA (LangGraph)
description: Camada que classifica a demanda, roteia ao agente da área e consolida a resposta citando fonte.
resource: docs/ARQUITETURA.md §2
tags: [ia, orquestracao, langgraph, agentes, servico]
timestamp: 2026-07-11
---

# Definition

Fluxo **classifica → roteia → consolida** sobre LangGraph, na camada de API (FastAPI).
Entrada única (agente `orquestrador`) que direciona aos 13 agentes de área e junta o resultado.

# Notes

- Cada agente herda o RBAC do usuário e só acessa seu(s) módulo(s).
- Toda resposta numérica cita fonte (tabela/view/query) e timestamp (CLAUDE.md §5/§8).
- Usa o [gemma_gateway](gemma_gateway.md) para inferência; bloqueia rota externa se houver PII.
