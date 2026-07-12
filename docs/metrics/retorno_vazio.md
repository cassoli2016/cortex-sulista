---
type: Metric
title: Retorno vazio (%)
description: Fração de km rodada sem carga — alerta acima de 20% em FTL.
resource: CLAUDE.md §4
tags: [metrica, operacional, eficiencia, canonica]
timestamp: 2026-07-11
---

# Definition

```
Retorno vazio (%) = (km_total - km_carregado) / km_total      # alerta > 20% FTL
```

# Notes

- **Alerta quando > 20%** na modalidade FTL (lotação).
- Na view [vw_ckm_viagem](../views/vw_ckm_viagem.md): `(km_total - km_carregado) / nullif(km_total,0)`.
- Fonte: [op_viagens](../tables/op_viagens.md).
