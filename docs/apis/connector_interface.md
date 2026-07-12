---
type: API
title: Connector (interface de extensão)
description: Contrato Protocol que todo conector de fornecedor implementa — o ponto único de extensão da Central de Integrações.
resource: docs/INTEGRACOES.md §3
tags: [integracoes, contrato, plugin, api]
timestamp: 2026-07-11
---

# Definition

```python
from typing import Protocol, Iterable

class Connector(Protocol):
    name: str                       # identificador único, ex.: "ruptela"
    capabilities: list[str]         # tipos de evento que produz
    mode: str                       # 'pull' | 'push' | 'both'

    def authenticate(self) -> None: ...
    def fetch(self, cursor: str | None) -> tuple[Iterable[CanonicalEvent], str]:
        """Pull incremental. Retorna eventos + novo cursor."""
    def handle_webhook(self, headers: dict, body: bytes) -> Iterable[CanonicalEvent]:
        """Push. Valida assinatura e converte payload em eventos canônicos."""
    def normalize(self, raw: dict) -> CanonicalEvent:
        """Mapeia o schema do fornecedor para o canônico."""
    def health_check(self) -> dict:
        """Status do conector (auth ok, latência, última sync)."""
```

`BaseConnector` fornece resiliência embutida (`rate_limit_rps=5.0`, `max_retries=5`,
`_retry` com backoff exponencial teto 60s, `verify_hmac` com `compare_digest`).

# Notes

- Princípio: *open for extension, closed for modification* — fornecedor novo = novo arquivo `integrations/connectors/<nome>.py` com `@register`, zero mudança no core.
- `mode` ∈ {`pull`,`push`,`both`} — reflete em [int_conectores](../tables/int_conectores.md).
- Emite [canonical_event](canonical_event.md); estado de pull em [int_sync_state](../tables/int_sync_state.md).
- Registrado via [connector_registry](../services/connector_registry.md); operado pelo [integrations_worker](../services/integrations_worker.md). Skill: `connector-builder`.
