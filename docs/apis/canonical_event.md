---
type: API
title: CanonicalEvent (modelo canônico)
description: Contrato de evento único para o qual todos os conectores normalizam os dados de fornecedores.
resource: docs/INTEGRACOES.md §3
tags: [integracoes, contrato, modelo-canonico, api]
timestamp: 2026-07-11
---

# Definition

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class CanonicalEvent:
    tipo: str            # 'posicao'|'telemetria'|'seguranca'|'abastecimento'|
                         # 'pedagio'|'doc_fiscal'|'titulo_financeiro'
    fonte: str           # nome do conector
    chave_idem: str      # chave de idempotência (evita duplicar)
    ocorrido_em: datetime
    payload: dict        # já no formato canônico do tipo
```

# Notes

- `tipo` enumera os eventos suportados: `posicao`, `telemetria`, `seguranca`, `abastecimento`, `pedagio`, `doc_fiscal`, `titulo_financeiro`.
- `chave_idem` garante idempotência — persistida como UNIQUE em [int_raw_events](../tables/int_raw_events.md).
- Produzido pelo [connector_interface](connector_interface.md); mapeado aos módulos pelo [normalizer](../services/normalizer.md).
- `payload` já normalizado alimenta tabelas como [tel_sinais](../tables/tel_sinais.md), [tc_posicoes](../tables/tc_posicoes.md), [ts_eventos](../tables/ts_eventos.md), [fin_titulos](../tables/fin_titulos.md).
