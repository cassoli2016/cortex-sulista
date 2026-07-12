---
name: fluxo-de-caixa
description: Projeta o fluxo de caixa (recebimentos − pagamentos − adiantamentos) por janela temporal e identifica gaps (saldo projetado negativo). Use para perguntas sobre caixa futuro, capacidade de pagamento e necessidade de capital de giro. Dado sensível — processamento local.
---

# Skill: Projeção de Fluxo de Caixa

Projeta o saldo de caixa dia a dia (ou por semana) a partir de títulos a receber, a pagar
e adiantamentos, e aponta o primeiro GAP (saldo negativo) — a informação que o controller
precisa ver primeiro.

## Lógica

```
saldo_dia[d] = saldo_dia[d-1]
             + recebimentos_previstos[d]
             - pagamentos_previstos[d]
             - adiantamentos[d]
```

Recebimento previsto usa a **data de vencimento**; aplique haircut por aging/score do cliente
para a versão realista (clientes com histórico de atraso entram com probabilidade < 1).

## Implementação de referência

```python
from decimal import Decimal as D
from datetime import date, timedelta

def projetar_caixa(saldo_inicial: D, titulos: list[dict],
                   dias: int = 60, realista: bool = True) -> dict:
    """
    titulos: [{tipo: 'receber'|'pagar'|'adiantamento', valor: D,
               data: date, prob: D (0..1, default 1)}]
    """
    hoje = date.today()
    fluxo = {hoje + timedelta(d): D("0") for d in range(dias + 1)}
    for t in titulos:
        d = t["data"]
        if d not in fluxo:
            continue
        prob = D(str(t.get("prob", 1))) if realista else D("1")
        v = D(str(t["valor"]))
        if t["tipo"] == "receber":
            fluxo[d] += v * prob
        else:  # pagar | adiantamento
            fluxo[d] -= v

    saldo, serie, primeiro_gap, menor = saldo_inicial, [], None, saldo_inicial
    for d in sorted(fluxo):
        saldo += fluxo[d]
        serie.append({"data": d.isoformat(), "saldo": round(saldo, 2)})
        if saldo < 0 and primeiro_gap is None:
            primeiro_gap = d.isoformat()
        menor = min(menor, saldo)

    return {
        "serie": serie,
        "primeiro_gap": primeiro_gap,        # None = caixa positivo no horizonte
        "menor_saldo": round(menor, 2),
        "necessidade_giro": round(-menor, 2) if menor < 0 else D("0"),
    }
```

## Saída esperada (exemplo)

```json
{
  "primeiro_gap": "2026-07-09",
  "menor_saldo": -84200.00,
  "necessidade_giro": 84200.00
}
```

Sempre destacar: **data do primeiro gap** e **necessidade de giro** (quanto falta no pior dia).
Oferecer alavancas: antecipar recebíveis, renegociar adiantamentos, escalonar pagamentos.

## Fontes
`fin_titulos`, `fin_adiantamentos`, `vw_fluxo_caixa`, score do cliente (`com_clientes.score`).
