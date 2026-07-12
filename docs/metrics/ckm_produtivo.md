---
type: Metric
title: CKM produtivo
description: Custo operacional total por quilômetro carregado (produtivo).
resource: CLAUDE.md §4
tags: [metrica, operacional, custo, canonica]
timestamp: 2026-07-11
---

# Definition

```
CKM produtivo = custo_operacional_total / km_carregado
```

# Notes

- Denominador é **km carregado** — comparável ao [rkm](rkm.md) na mesma base.
- Na view [vw_ckm_viagem](../views/vw_ckm_viagem.md): `custo_variavel / nullif(km_carregado,0)`.
- Contraparte: [ckm_bruto](ckm_bruto.md).
