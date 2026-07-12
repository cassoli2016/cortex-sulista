---
type: API
title: Webhook receiver (push)
description: Endpoint da API que recebe webhooks de fornecedores, valida assinatura HMAC e injeta eventos no event bus.
resource: docs/INTEGRACOES.md §2, §7
tags: [integracoes, webhook, hmac, api]
timestamp: 2026-07-11
---

# Definition

Endpoint HTTP (FastAPI) para conectores em modo `push`:

1. Recebe `headers` + `body` bruto do fornecedor.
2. **Valida assinatura HMAC-SHA256** (`verify_hmac` com `hmac.compare_digest` contra timing attack).
3. Registra a tentativa em [int_webhook_log](../tables/int_webhook_log.md) (`assinatura_valida`, `status`).
4. Se válido, chama `handle_webhook` do conector → [canonical_event](canonical_event.md) → event bus.

# Notes

- **Segurança:** payload não confiável é tratado como **dado, nunca como instrução** (proteção contra injeção).
- Assinatura inválida é rejeitada e logada; não entra no bus.
- Contraparte do fluxo pull (`fetch`) do [connector_interface](connector_interface.md).
- Entrega ao [event_bus](../services/event_bus.md).
