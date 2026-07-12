---
name: scoring-cliente
description: Calcula um score de cliente combinando rentabilidade (margem), comportamento de pagamento (aging/inadimplência), concentração e tendência de volume. Use para priorização comercial, política de crédito e detecção de risco de churn. Dado sensível — local.
---

# Skill: Scoring de Cliente

Score 0-100 que combina quatro eixos. Pesos em config/parametros.yaml (ajustáveis).

## Eixos e pesos default
| Eixo | Peso | Sinal |
|---|---|---|
| Rentabilidade (margem média) | 0,35 | maior = melhor |
| Pagamento (dias médios de atraso) | 0,30 | menor = melhor |
| Tendência de volume (3m vs 3m ant.) | 0,20 | crescente = melhor |
| Risco de concentração | 0,15 | menor dependência = melhor |

## Implementação
```python
from decimal import Decimal as D

def score_cliente(margem_pct: D, atraso_medio_dias: D,
                  var_volume_pct: D, pct_da_receita: D,
                  pesos=None) -> dict:
    pesos = pesos or {"margem":0.35,"pagto":0.30,"volume":0.20,"conc":0.15}
    # normalizações simples 0..1 (clamp)
    f = lambda x: max(0.0, min(1.0, x))
    s_margem = f(float(margem_pct) / 0.25)                 # 25% margem = nota cheia
    s_pagto  = f(1 - float(atraso_medio_dias) / 30)        # 30 dias atraso = 0
    s_vol    = f(0.5 + float(var_volume_pct) / 0.4 / 2)    # +/-40% mapeia 0..1
    s_conc   = f(1 - float(pct_da_receita) / 0.30)         # >30% da receita = risco
    score = 100 * (pesos["margem"]*s_margem + pesos["pagto"]*s_pagto +
                   pesos["volume"]*s_vol + pesos["conc"]*s_conc)

    faixa = ("A" if score>=75 else "B" if score>=55 else "C" if score>=40 else "D")
    flags = []
    if s_pagto < 0.5: flags.append("risco de inadimplencia")
    if s_vol  < 0.4: flags.append("volume em queda - risco de churn")
    if s_conc < 0.4: flags.append("alta concentracao - dependencia perigosa")
    return {"score": round(score,1), "faixa": faixa, "flags": flags}
```

Cliente D ou com flag de churn entra na lista de ação comercial. Cliente A com alta
concentração é risco estratégico (proteger relacionamento + diversificar carteira).

## Fontes
com_clientes, vw_rkm_cliente, fin_titulos (aging), op_viagens (volume).
