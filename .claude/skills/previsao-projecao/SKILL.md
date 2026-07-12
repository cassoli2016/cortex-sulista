---
name: previsao-projecao
description: Gera previsões e projeções a partir do histórico (caixa, demanda de cargas, manutenção, churn) sempre com cenários e premissas explícitas. Use para perguntas sobre o futuro ("quanto vou receber", "vai faltar caixa", "quando esse veículo vai quebrar").
---

# Skill: Previsão e Projeção

Previsão sem premissa e sem intervalo não decide nada. Toda saída traz **3 cenários**
(base / otimista / pessimista) e lista as premissas.

## Métodos por caso
| Caso | Método sugerido |
|---|---|
| Fluxo de caixa | títulos + probabilidade de pagamento por aging/score (skill fluxo-de-caixa) |
| Demanda de cargas | série temporal com sazonalidade (decomposição) por cliente/rota |
| Manutenção preditiva | regra sobre idade/km/custo + sinais de telemetria (DTC, consumo) |
| Churn de cliente | skill scoring-cliente + tendência de volume |

## Projeção de série (sazonalidade simples)
```python
import statistics as st

def projetar_serie(hist: list[float], passos: int, fator_saz: list[float] | None = None):
    # tendência por média móvel + sazonalidade multiplicativa opcional
    n = min(6, len(hist))
    base = st.mean(hist[-n:])
    cresc = (hist[-1] - hist[-n]) / n if len(hist) >= n else 0
    proj = []
    for i in range(1, passos + 1):
        val = base + cresc * i
        if fator_saz:
            val *= fator_saz[(len(hist) + i - 1) % len(fator_saz)]
        proj.append(round(val, 2))
    banda = st.pstdev(hist[-n:]) if len(hist) >= 2 else base * 0.1
    return {"base": proj,
            "otimista": [round(v + banda, 2) for v in proj],
            "pessimista": [round(v - banda, 2) for v in proj]}
```

## Regra de saída
Sempre: número(s) + cenário + premissas + o que muda a previsão. Para modelos mais
sofisticados (Prophet/ARIMA), rodar offline e materializar resultado em view; o agente lê a view.

## Fontes
Histórico em PostgreSQL + continuous aggregates do TimescaleDB.
