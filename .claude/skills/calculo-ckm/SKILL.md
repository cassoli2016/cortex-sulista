---
name: calculo-ckm
description: Calcula o CKM (custo por km) da frota própria, desmembrado por componente, a partir de parâmetros operacionais reais. Use quando precisar apurar custo de operação de veículo próprio, comparar contra benchmark, ou alimentar a decisão make-vs-buy.
---

# Skill: Cálculo de CKM (frota própria)

Calcula o custo por km desmembrado. Todos os parâmetros vêm de `config/parametros.yaml`
ou dos dados reais do veículo/rota — nada hardcoded.

## Fórmulas (canônicas)

```
combustivel_km   = preco_diesel / km_por_litro
arla_km          = combustivel_km * pct_arla            # ~0,05
motorista_km     = custo_motorista_mes / km_mes
manutencao_km    = custo_manutencao / km                # prev + corr
pneu_cpk         = (custo_jogo + custo_recapes) / km_vida_pneu
pedagio_km       = pedagio_rota / km_rota
seguro_km        = seguro_anual / km_ano
deprec_km        = (valor_compra - valor_residual) / vida_km
fixos_km         = (licenciamento + antt + telemetria + overhead_rateado) / km_ano

CKM_variavel = combustivel_km + arla_km + manutencao_km + pneu_cpk + pedagio_km
CKM_cheio    = CKM_variavel + motorista_km + seguro_km + deprec_km + fixos_km
CKM_marginal = CKM_variavel + motorista_km     # p/ decisão de curto prazo
```

## Implementação de referência

```python
from decimal import Decimal as D
from dataclasses import dataclass, asdict

@dataclass
class ParamsCKM:
    preco_diesel: D
    km_por_litro: D
    pct_arla: D = D("0.05")
    custo_motorista_mes: D = D("0")
    km_mes: D = D("12000")
    custo_manutencao: D = D("0")     # no período de km abaixo
    km_periodo: D = D("12000")
    custo_jogo_pneu: D = D("0")
    custo_recapes: D = D("0")
    km_vida_pneu: D = D("120000")
    pedagio_rota: D = D("0")
    km_rota: D = D("1")
    seguro_anual: D = D("0")
    km_ano: D = D("144000")
    valor_compra: D = D("0")
    valor_residual: D = D("0")
    vida_km: D = D("1000000")
    fixos_anuais: D = D("0")          # licenc + antt + telemetria + overhead

def calcular_ckm(p: ParamsCKM) -> dict:
    comb = p.preco_diesel / p.km_por_litro
    arla = comb * p.pct_arla
    motor = p.custo_motorista_mes / p.km_mes if p.km_mes else D("0")
    manut = p.custo_manutencao / p.km_periodo if p.km_periodo else D("0")
    pneu = (p.custo_jogo_pneu + p.custo_recapes) / p.km_vida_pneu if p.km_vida_pneu else D("0")
    pedagio = p.pedagio_rota / p.km_rota if p.km_rota else D("0")
    seguro = p.seguro_anual / p.km_ano if p.km_ano else D("0")
    deprec = (p.valor_compra - p.valor_residual) / p.vida_km if p.vida_km else D("0")
    fixos = p.fixos_anuais / p.km_ano if p.km_ano else D("0")

    variavel = comb + arla + manut + pneu + pedagio
    marginal = variavel + motor
    cheio = marginal + seguro + deprec + fixos

    comp = {"combustivel": comb, "arla": arla, "motorista": motor,
            "manutencao": manut, "pneu_cpk": pneu, "pedagio": pedagio,
            "seguro": seguro, "depreciacao": deprec, "fixos": fixos}
    return {
        "componentes": {k: round(v, 4) for k, v in comp.items()},
        "ckm_variavel": round(variavel, 4),
        "ckm_marginal": round(marginal, 4),   # decisão curto prazo
        "ckm_cheio": round(cheio, 4),          # decisão longo prazo
    }
```

## Benchmark de sanidade (cavalo rodoviário, ~12k km/mês)

| Componente | R$/km típico |
|---|---|
| Combustível | 2,30–2,70 |
| Motorista | 0,55–0,75 |
| Manutenção | 0,40–0,55 |
| Pneu (CPK) | 0,20–0,30 |
| Pedágio | 0,25–0,40 |
| Depreciação | 0,40–0,60 |
| **CKM cheio** | **~5,0–5,5** |

Se o resultado sair muito fora disso, revise os parâmetros antes de usar em decisão.
