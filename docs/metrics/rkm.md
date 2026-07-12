---
type: Metric
title: RKM (receita por km)
description: Receita de frete por quilômetro carregado — métrica canônica de precificação/rentabilidade comercial.
resource: CLAUDE.md §4
tags: [metrica, comercial, canonica]
timestamp: 2026-07-11
---

# Definition

```
RKM (receita/km) = receita_frete / km_carregado
```

# Notes

- Fórmula canônica — toda query/agente usa exatamente esta.
- Denominador é **km carregado** (não km total).
- Calculada por cliente/mês em [vw_rkm_cliente](../views/vw_rkm_cliente.md); fonte [op_viagens](../tables/op_viagens.md).
- No modo agregado, o RKM pago ao terceiro (`sup_agregados.rkm_acordado`) entra no [spread_make_vs_buy](spread_make_vs_buy.md).
