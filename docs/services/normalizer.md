---
type: Service
title: Normalizer
description: Componente que lê o evento canônico da trilha bruta e o grava no modelo de dados dos módulos do PostgreSQL.
resource: docs/INTEGRACOES.md §2, §5
tags: [integracoes, normalizacao, etl, servico]
timestamp: 2026-07-11
---

# Definition

Lê de [int_raw_events](../tables/int_raw_events.md) e mapeia o [canonical_event](../apis/canonical_event.md)
para as tabelas de módulo (verdade única) — ex.: `posicao` → [tc_posicoes](../tables/tc_posicoes.md),
`telemetria` → [tel_sinais](../tables/tel_sinais.md), `seguranca` → [ts_eventos](../tables/ts_eventos.md),
`titulo_financeiro` → [fin_titulos](../tables/fin_titulos.md).

# Notes

- A trilha bruta em `int_raw_events` permite auditoria e **reprocessamento** sem rechamar o fornecedor.
- Cada conector já entrega no formato canônico via seu método `normalize` ([connector_interface](../apis/connector_interface.md)); este serviço faz o roteamento canônico → módulo.
