---
type: Metric
title: Resultado da viagem
description: Resultado financeiro de uma viagem = receita − custo variável (sobre km total) − fixo rateado.
resource: CLAUDE.md §4
tags: [metrica, operacional, resultado, canonica]
timestamp: 2026-07-11
---

# Definition

```
Resultado da viagem = (RKM * km_carregado) - (CKM_var * km_total) - fixo_rateado
```

# Notes

- Fórmula canônica do glossário. Note que o custo variável incide sobre **km total** e a receita sobre **km carregado**.
- Aproximação materializada em [vw_resultado_viagem](../views/vw_resultado_viagem.md): `receita_frete - custo_variavel - custo_fixo_rateado`.
- Fonte: [op_viagens](../tables/op_viagens.md).
