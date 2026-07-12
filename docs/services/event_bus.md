---
type: Service
title: Event Bus (Redis Streams)
description: Barramento de eventos que desacopla ingestão de processamento na Central de Integrações; persiste o bruto em int_raw_events.
resource: docs/INTEGRACOES.md §2, §6
tags: [integracoes, redis, event-bus, servico]
timestamp: 2026-07-11
---

# Definition

Fila de eventos sobre **Redis Streams**. Todo [canonical_event](../apis/canonical_event.md)
produzido por um conector entra no bus e é persistido bruto em [int_raw_events](../tables/int_raw_events.md).

# Notes

- **Backpressure:** desacopla a ingestão (conectores) do processamento ([normalizer](normalizer.md)) — um pico de um fornecedor não trava o resto.
- Idempotência garantida por `chave_idem` UNIQUE em [int_raw_events](../tables/int_raw_events.md).
- Consumido pelo [integrations_worker](integrations_worker.md).
