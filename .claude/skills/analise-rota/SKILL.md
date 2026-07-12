---
name: analise-rota
description: Avalia uma rota específica calculando RKM, CKM, retorno vazio, margem de contribuição e resultado da viagem, com recomendação. Use para "essa rota vale a pena?" e para priorização de alocação de frota.
---

# Skill: Análise de Rota (FTL)

Consolida receita e custo de uma rota e devolve diagnóstico acionável.

## Métricas
```
rkm            = receita_frete / km_carregado
retorno_vazio  = (km_total - km_carregado) / km_total
mc_km          = rkm - ckm_variavel               # margem de contribuição por km
resultado      = (rkm * km_carregado) - (ckm_var * km_total) - fixo_rateado
```

## Implementação
```python
from decimal import Decimal as D

def analisar_rota(receita: D, km_carregado: D, km_total: D,
                  ckm_var: D, fixo_rateado: D) -> dict:
    rkm = receita / km_carregado if km_carregado else D("0")
    vazio = (km_total - km_carregado) / km_total if km_total else D("0")
    mc_km = rkm - ckm_var
    resultado = (rkm * km_carregado) - (ckm_var * km_total) - fixo_rateado

    alertas = []
    if vazio > D("0.20"):
        alertas.append(f"Retorno vazio alto: {vazio:.0%} (alvo < 20%)")
    if mc_km <= 0:
        alertas.append("Margem de contribuição negativa: rota não cobre nem o custo variável")
    if resultado < 0 and mc_km > 0:
        alertas.append("Cobre o variável mas não o fixo — aceitável só p/ ocupar frota ociosa")

    return {"rkm": round(rkm,4), "retorno_vazio": round(vazio,4),
            "mc_km": round(mc_km,4), "resultado": round(resultado,2),
            "alertas": alertas}
```

Regra FTL: rota com MC/km positiva mas resultado negativo só se justifica para preencher
frota que rodaria vazia de qualquer jeito. Caso contrário, repreçar ou repassar ao agregado.

## Fontes
vw_resultado_viagem, vw_ckm_viagem, op_rotas, op_viagens.
