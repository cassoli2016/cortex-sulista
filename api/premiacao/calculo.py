"""Regra de premiação por litros economizados (spec §1). Módulo PURO.

premio = max(0, km/meta - km/media) × preco_litro × pct_premiacao
Sem arredondamento intermediário: só o prêmio final arredonda a 2 casas
(o exemplo do MVP dava 300,60 por arredondar o valor economizado antes do
percentual; aqui o canônico é 300,75).
"""
from __future__ import annotations


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
        })

    linhas.sort(key=lambda l: (-l["premio"], -float(l.get("km") or 0)))
    eleg = [l for l in linhas if l["elegivel"]]
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
