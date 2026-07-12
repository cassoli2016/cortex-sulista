---
name: make-vs-buy
description: Compara o custo de rodar uma rota com frota própria (CKM) versus pagar um agregado (R$/km), nas óticas de curto e longo prazo. Use para a decisão central da operação mista — alocar carga entre frota própria e agregados por rota.
---

# Skill: Make-vs-Buy (próprio vs agregado)

A decisão mais valiosa da operação mista. Não existe "próprio é sempre melhor" — depende
do horizonte e da rota.

## Regra de decisão

```
spread = CKM_proprio - rkm_agregado

CURTO PRAZO  (frota já existe, fixo afundado):
    referência = CKM_marginal  (variável + motorista)
    se rkm_agregado > CKM_marginal  → rodar PRÓPRIO gera mais margem de contribuição
    se rkm_agregado < CKM_marginal  → repassar ao AGREGADO

LONGO PRAZO  (decisão de comprar veículo p/ a rota):
    referência = CKM_cheio  (inclui fixo + depreciação + custo de capital)
    se rkm_agregado < CKM_cheio (de forma consistente) → NÃO comprar; usar agregado
    se rkm_agregado > CKM_cheio  → frota própria cria valor
```

## Implementação de referência

```python
from decimal import Decimal as D

def make_vs_buy(ckm_marginal: D, ckm_cheio: D, rkm_agregado: D) -> dict:
    curto = "proprio" if rkm_agregado > ckm_marginal else "agregado"
    longo = "proprio" if rkm_agregado > ckm_cheio else "agregado"

    if curto == "proprio" and longo == "agregado":
        leitura = ("Rodar próprio AGORA (cobre o marginal e sobra margem), mas NÃO comprar "
                   "veículo novo para esta rota — o agregado bate o custo cheio.")
    elif curto == longo == "proprio":
        leitura = "Próprio vence nas duas óticas: rodar e investir nesta rota faz sentido."
    elif curto == longo == "agregado":
        leitura = "Agregado vence nas duas óticas: repassar e não alocar frota própria aqui."
    else:
        leitura = "Caso de borda: agregado abaixo do marginal mas acima do cheio — revisar dados."

    return {
        "rkm_agregado": rkm_agregado,
        "ckm_marginal": ckm_marginal,
        "ckm_cheio": ckm_cheio,
        "spread_marginal": round(ckm_marginal - rkm_agregado, 4),
        "spread_cheio": round(ckm_cheio - rkm_agregado, 4),
        "decisao_curto_prazo": curto,
        "decisao_longo_prazo": longo,
        "leitura": leitura,
    }
```

## Uso por rota (em escala)

Rodar para TODAS as rotas e ordenar pelo `spread_cheio`:
- rotas onde agregado é muito mais barato que o CKM cheio → candidatas a terceirizar.
- rotas onde a frota própria domina → priorizar alocação da frota nelas.

Isso vira uma view/relatório de **alocação ótima de frota** — o output mais estratégico
do módulo de suprimentos para o CEO.

## Fontes
`vw_ckm_viagem` (CKM por rota), `sup_agregados.rkm_acordado`, `op_rotas`.
Combinar com a skill `calculo-ckm` para o CKM próprio e `analise-rota` para a margem.
