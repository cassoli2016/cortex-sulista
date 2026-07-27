"""Regra de premiação por litros economizados (spec §1). Módulo PURO.

premio = max(0, km/meta - km/media) × preco_litro × pct_premiacao
Sem arredondamento intermediário: só o prêmio final arredonda a 2 casas
(o exemplo do MVP dava 300,60 por arredondar o valor economizado antes do
percentual; aqui o canônico é 300,75).

Faixa física (achado I2 da revisão final): km <= 0 ou média acima de um teto
amplo (15 km/l — o piloto tem veículos leves de até ~9 km/l; caminhão pesado
faz 0,8-6) é leitura de telemetria implausível, não desempenho real. km <= 0
com média abaixo da meta chegava a gerar PRÊMIO POSITIVO (litros_meta negativo
menos um litros_consumidos ainda mais negativo). Essas linhas ganham
`suspeito: True`, continuam VISÍVEIS na lista (com o valor bruto calculado),
mas ficam fora de premio_total/litros_economizados_total/premiados — tratadas
como não-elegíveis para fins de KPI. `media <= 0` continua fora das linhas
(sem_media), sem mudança.
"""
from __future__ import annotations

TETO_MEDIA_KM_L = 15.0


def calcular(motoristas: list[dict], params: dict) -> dict:
    meta = float(params["meta"])
    preco = float(params["preco_litro"])
    pct = float(params["pct_premiacao"])
    km_min = float(params.get("km_minimo") or 0)

    linhas: list[dict] = []
    sem_media = 0
    for m in motoristas:
        media = m.get("media") or 0
        if media <= 0:
            sem_media += 1
            continue
        km = float(m.get("km") or 0)
        litros_meta = km / meta
        litros_cons = km / media
        econ = max(0.0, litros_meta - litros_cons)
        linhas.append({
            **m,
            "litros_meta": litros_meta,
            "litros_consumidos": litros_cons,
            "litros_economizados": econ,
            "premio": round(econ * preco * pct, 2),
            "elegivel": km >= km_min,
            "suspeito": km <= 0 or media > TETO_MEDIA_KM_L,
        })

    linhas.sort(key=lambda l: (-l["premio"], -float(l.get("km") or 0)))
    eleg = [l for l in linhas if l["elegivel"] and not l["suspeito"]]
    litros_cons_total = sum(l["litros_consumidos"] for l in linhas)
    km_total = sum(float(l.get("km") or 0) for l in linhas)
    kpis = {
        "premio_total": round(sum(l["premio"] for l in eleg), 2),
        "litros_economizados_total": round(sum(l["litros_economizados"] for l in eleg), 2),
        "premiados": sum(1 for l in eleg if l["premio"] > 0),
        "elegiveis": len(eleg),
        "com_media": len(linhas),
        "total_motoristas": len(motoristas),
        "media_frota": (km_total / litros_cons_total) if litros_cons_total else None,
        "meta": meta,
    }
    return {"linhas": linhas, "kpis": kpis, "sem_media": sem_media}
