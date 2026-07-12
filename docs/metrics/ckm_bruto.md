---
type: Metric
title: CKM bruto
description: Custo operacional total por quilômetro total rodado (carregado + vazio).
resource: CLAUDE.md §4
tags: [metrica, operacional, custo, canonica]
timestamp: 2026-07-11
---

# Definition

```
CKM bruto = custo_operacional_total / km_total
```

# Notes

- Denominador é **km total** (inclui km vazio).
- Na view [vw_ckm_viagem](../views/vw_ckm_viagem.md) aproximado por `custo_variavel / nullif(km_total,0)`.
- Contraparte produtiva: [ckm_produtivo](ckm_produtivo.md). Fonte: [op_viagens](../tables/op_viagens.md).
