---
type: Service
title: integrations-worker
description: Worker dedicado da Central de Integrações — roda o scheduler de polling (pull) e consome o event bus.
resource: docs/INTEGRACOES.md §2, docs/ARQUITETURA.md §8
tags: [integracoes, worker, servico]
timestamp: 2026-07-11
---

# Definition

Processo separado da API que:
- Executa o **scheduler de polling incremental** — chama `fetch(cursor)` de cada conector em modo `pull`, avançando o cursor em [int_sync_state](../tables/int_sync_state.md).
- **Consome o event bus** ([event_bus](event_bus.md)) e dispara o [normalizer](normalizer.md).

# Notes

- Aplica as regras de resiliência do hub: retry/backoff, circuit breaker por conector, rate limit (config em `config/parametros.yaml`), dead-letter ([int_dead_letter](../tables/int_dead_letter.md)).
- Webhooks (push) NÃO passam por aqui na entrada — chegam pelo [webhook_receiver](../apis/webhook_receiver.md); mas seus eventos são consumidos deste worker via bus.
- Opera conectores descobertos pelo [connector_registry](connector_registry.md).
