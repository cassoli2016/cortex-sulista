---
name: metas-okr
description: Estrutura e acompanha metas, KPIs e OKRs — define objetivos, key results mensuráveis, calcula progresso e farol. Use para montar o ciclo de gestão e o painel de metas.
---

# Skill: Metas, KPIs e OKRs

## Estrutura de um OKR
```
Objetivo: qualitativo, inspirador, com prazo (trimestre).
Key Results: 2-4, mensuráveis, com baseline -> meta.
  KR = (atual - baseline) / (meta - baseline)   # 0..1 de progresso
```

## Cálculo de progresso e farol
```python
def progresso_kr(baseline: float, atual: float, meta: float) -> float:
    if meta == baseline:
        return 1.0 if atual >= meta else 0.0
    return max(0.0, min(1.0, (atual - baseline) / (meta - baseline)))

def farol(progresso: float, tempo_decorrido: float) -> str:
    # compara progresso com o tempo do ciclo já gasto
    folga = progresso - tempo_decorrido
    if folga >= -0.05: return "verde"
    if folga >= -0.20: return "amarelo"
    return "vermelho"
```

## Boas práticas
- KPI mede saúde contínua (ex.: % entregas no prazo); OKR mede mudança (ex.: reduzir CKM de X p/ Y).
- Cada KR tem dono. Sem dono, não acontece.
- OKR vermelho não é fracasso — é sinal para replanejar a ação (conectar com skill ata-reuniao).

## Exemplos para transportadora
- O: "Tornar a frota própria mais competitiva que o agregado."
  - KR1: reduzir CKM cheio de R$5,3 para R$4,9.
  - KR2: retorno vazio de 22% para 15%.
  - KR3: disponibilidade de frota de 88% para 93%.

## Fontes
ges_metas, ges_okr.
