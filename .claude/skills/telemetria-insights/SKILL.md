---
name: telemetria-insights
description: Transforma telemetria bruta (CAN/J1939) em insights acionáveis — consumo vs alvo, uso de ECO/embalo/freio-motor, detecção de veículo fora da curva e correlação com DTCs. Use para diagnóstico de eficiência e saúde mecânica.
---

# Skill: Telemetria → Insights

Não devolve só número: explica o PORQUÊ e o que fazer.

## Métricas
```
km_l_medio        = avg(km_l) no período (continuous aggregate)
pct_eco           = avg(eco_ativo)         # % do tempo em modo econômico
pct_embalo        = avg(embalo)            # aproveitamento de inércia
desvio_alvo       = (km_l_medio - km_l_alvo) / km_l_alvo
```

## Detecção de fora da curva
```python
import statistics as st

def fora_da_curva(consumos: dict[int, float], z_limite: float = 1.5) -> list[dict]:
    vals = list(consumos.values())
    media, dp = st.mean(vals), (st.pstdev(vals) or 1)
    out = []
    for veic, km_l in consumos.items():
        z = (km_l - media) / dp
        if z < -z_limite:
            out.append({"veiculo": veic, "km_l": round(km_l,2),
                        "z": round(z,2), "flag": "consumo ruim - investigar"})
    return sorted(out, key=lambda x: x["z"])
```

## Geração de insight (prompt para o agente)
Para cada veículo fora da curva, cruzar:
- uso de ECO/embalo/freio-motor baixo → comportamento de condução.
- DTCs ativos (tel_dtc) → causa mecânica (ex.: injeção, sensor de O2).
- rota/topografia → contexto.
Saída: frase única acionável. Ex.: "ABC1234 está 12% abaixo do alvo; baixo freio-motor em
descidas + DTC P0299 (turbo) — agendar diagnóstico e reforçar condução com o motorista."

## Fontes
vw_consumo_veiculo (continuous aggregate), tel_sinais (detalhe, 90d), tel_dtc.
