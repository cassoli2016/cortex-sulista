---
type: Metric
title: Spread make-vs-buy
description: Diferença entre CKM próprio e RKM pago ao agregado — decide fazer (frota própria) vs comprar (agregado).
resource: CLAUDE.md §4
tags: [metrica, suprimentos, make-vs-buy, canonica]
timestamp: 2026-07-11
---

# Definition

```
Spread make-vs-buy = CKM_proprio - rkm_pago_agregado
```

# Notes

- **Frota mista:** curto prazo compara o agregado contra o **CKM marginal** (variável + motorista); longo prazo (comprar veículo) compara contra o **CKM cheio** (com fixo + depreciação).
- `rkm_pago_agregado` vem de [sup_agregados](../tables/sup_agregados.md) (`rkm_acordado`); skill `make-vs-buy`.
- Relaciona-se a [ckm_produtivo](ckm_produtivo.md)/[ckm_bruto](ckm_bruto.md).
