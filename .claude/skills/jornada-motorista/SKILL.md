---
name: jornada-motorista
description: Calcula a jornada do motorista e a conformidade com a Lei 13.103/2015 (tempo de direção, intervalos, descansos) e PREVÊ violações antes que ocorram. Use para compliance e para validar uma programação. Dado de motorista é PII — local.
---

# Skill: Jornada do Motorista (Lei 13.103/2015)

## Limites legais
```
DIRECAO_CONTINUA_MAX   = 5h30   # antes de parada obrigatória
PARADA_MINIMA          = 30 min # após direção contínua
INTERVALO_INTRA        = 1h     # refeição/descanso na jornada
DESCANSO_INTER         = 11h    # entre jornadas
DESCANSO_SEMANAL       = 35h
DIRECAO_DIARIA         = 8h (+2h extra excepcionais)
```

## Avaliação de compliance
```python
from datetime import timedelta

LIMITES = {"direcao_continua": timedelta(hours=5, minutes=30),
           "direcao_diaria": timedelta(hours=10)}  # 8h + 2h extra

def avaliar_jornada(eventos: list[dict]) -> dict:
    # eventos: [{tipo:'direcao'|'parada'|'descanso'|'refeicao', dur: timedelta}]
    violacoes, continua, diaria = [], timedelta(), timedelta()
    for e in eventos:
        if e["tipo"] == "direcao":
            continua += e["dur"]; diaria += e["dur"]
            if continua > LIMITES["direcao_continua"]:
                violacoes.append("direção contínua acima de 5h30 sem parada")
            if diaria > LIMITES["direcao_diaria"]:
                violacoes.append("direção diária acima do limite")
        elif e["tipo"] in ("parada", "descanso", "refeicao"):
            if e["dur"] >= timedelta(minutes=30):
                continua = timedelta()  # reseta a contagem contínua
    return {"violacoes": violacoes, "compliance": not violacoes}
```

## Preventivo (o que importa)
Dado o estado atual, calcular **quando** o motorista vai estourar o limite se continuar, e
alertar ANTES. Integra com programacao-cargas para rejeitar alocação que geraria violação.

## Fontes
jor_eventos (hypertable), jor_jornadas, vw_compliance_jornada.
