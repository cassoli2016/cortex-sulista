---
name: dre-analise
description: Monta a DRE gerencial em cascata (waterfall) e analisa margem, estrutura de custo e variações vs período/orçamento. Use para análises financeiras de resultado. Dado sensível — local.
---

# Skill: Análise de DRE

DRE gerencial da transportadora, em cascata, com foco no que move a margem.

## Estrutura (cascata)
```
(+) Receita bruta de frete
(-) Impostos sobre frete (ISS/ICMS conforme operação)
(=) Receita líquida
(-) Custos operacionais variáveis (combustível, pedágio, manutenção, pneus, agregados)
(-) Custos com motoristas
(=) Margem de contribuição
(-) Custos fixos (depreciação, seguro, licenciamento, telemetria)
(=) Resultado operacional (EBIT)
(+) Depreciação
(=) EBITDA
(-) Despesas administrativas
(-) Resultado financeiro
(=) Resultado líquido
```

## Análise
```python
from decimal import Decimal as D

def analisar_dre(linhas: dict) -> dict:
    rl = linhas["receita_liquida"]
    pct = lambda v: round(D(v) / rl * 100, 1) if rl else D("0")
    mc = rl - linhas["custos_variaveis"] - linhas["custos_motorista"]
    ebitda = mc - linhas["custos_fixos"] + linhas.get("depreciacao", D("0"))
    return {
        "margem_contribuicao": mc, "margem_contribuicao_pct": pct(mc),
        "ebitda": ebitda, "ebitda_pct": pct(ebitda),
        "peso_combustivel_pct": pct(linhas.get("combustivel", D("0"))),
        "peso_motorista_pct": pct(linhas["custos_motorista"]),
    }
```

## Leitura para o CEO
- Onde está concentrado o custo (combustível costuma ser 30-40%).
- Variação vs orçamento e vs mês anterior — explicar o delta, não só mostrar.
- Conectar com operacional: queda de margem geralmente é RKM caindo ou CKM subindo.

## Fontes
fin_dre, vw_dre_mensal, fin_lancamentos.
