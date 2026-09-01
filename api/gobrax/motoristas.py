# -*- coding: utf-8 -*-
"""Evolução dos MOTORISTAS na telemetria — nota e km, mês a mês.

A fonte é o snapshot mensal que a premiação já coleta e guarda em
`data/premiacao/premiacao-AAAA-MM.json` (driversOverview da Gobrax:
driverId, driverName, km, nota). Este módulo só LÊ — a coleta continua
sendo a da premiação, e a regra `so_cache` vale: abrir a tela jamais
dispara chamada à Gobrax.

O RANKING TEM PISO: motorista com menos de 500 km no mês não é ranqueado
(nota de quem quase não rodou compara ninguém com ninguém) — ele aparece
CONTADO ("X abaixo do piso"), nunca escondido.

km/l POR MOTORISTA NÃO EXISTE e não é prometido: statistics é por veículo
e o driversOverview traz km+nota sem litros (medido na investigação de
01/09/2026). O que há é nota — e a evolução dela.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DIR_PREMIACAO = ROOT / "data" / "premiacao"
KM_PISO = 500.0


def _snapshots() -> list[dict]:
    out = []
    for f in sorted(DIR_PREMIACAO.glob("premiacao-????-??.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - arquivo furado não derruba a tela
            continue
        if d.get("month") and isinstance(d.get("drivers"), list):
            out.append(d)
    return out


def get_motoristas() -> dict:
    snaps = _snapshots()
    if not snaps:
        return {"competencias": [], "serie": [], "ranking": [],
                "fonte": "snapshots mensais da premiação (Gobrax driversOverview)"}

    serie = []
    historico: dict[str, list[float]] = {}
    for s in snaps:
        notas = [float(d["nota"]) for d in s["drivers"]
                 if d.get("nota") is not None and float(d.get("km") or 0) >= KM_PISO]
        serie.append({
            "competencia": s["month"],
            "parcial": bool(s.get("parcial")),
            "motoristas": len(s["drivers"]),
            "no_piso": len(notas),
            "nota_mediana": statistics.median(notas) if notas else None,
            "km_total": sum(float(d.get("km") or 0) for d in s["drivers"]),
        })
        for d in s["drivers"]:
            if d.get("nota") is not None:
                historico.setdefault(str(d.get("driverName") or "?"), []).append(
                    float(d["nota"]))

    ultimo = snaps[-1]
    ranking, abaixo_piso = [], 0
    for d in sorted(ultimo["drivers"], key=lambda x: -(x.get("nota") or 0)):
        km = float(d.get("km") or 0)
        if km < KM_PISO:
            abaixo_piso += 1
            continue
        nome = str(d.get("driverName") or "?")
        hist = historico.get(nome) or []
        ranking.append({
            "nome": nome, "km": km,
            "nota": float(d["nota"]) if d.get("nota") is not None else None,
            "meses": len(hist),
            "nota_media_hist": (sum(hist) / len(hist)) if hist else None,
        })

    return {
        "competencias": [s["month"] for s in snaps],
        "serie": serie,
        "ultima": ultimo["month"],
        "ultima_parcial": bool(ultimo.get("parcial")),
        "ranking": ranking,
        "abaixo_piso": abaixo_piso,
        "km_piso": KM_PISO,
        "fonte": ("snapshots mensais da premiação (Gobrax driversOverview, "
                  "cache local) · nota e km por motorista; km/l por "
                  "motorista não existe na fonte"),
    }
