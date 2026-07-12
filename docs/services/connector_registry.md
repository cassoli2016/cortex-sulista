---
type: Service
title: Connector Registry
description: Registro de auto-descoberta de conectores via decorator @register — o core conhece só a interface, não os fornecedores.
resource: docs/INTEGRACOES.md §4
tags: [integracoes, registry, plugin, servico]
timestamp: 2026-07-11
---

# Definition

```python
_REGISTRY: dict[str, type] = {}

def register(cls):                     # decorator
    _REGISTRY[cls.name] = cls
    return cls

def get_connector(name: str):
    return _REGISTRY[name]()

@register
class RuptelaConnector(BaseConnector):
    name = "ruptela"
    capabilities = ["telemetria", "posicao"]
    mode = "pull"
```

# Notes

- Conectores se **auto-registram** ao serem importados; adicionar fornecedor = novo arquivo em `integrations/connectors/<nome>.py` com `@register`.
- Implementa o [connector_interface](../apis/connector_interface.md); usado pelo [integrations_worker](integrations_worker.md) para instanciar conectores.
