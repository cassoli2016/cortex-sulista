"""positions v2 — trilha do veículo.

Rápida ao contrário das outras: 0,7 s para a frota inteira num dia (medido em
19/08/2026), então é consultada ao vivo, sem cache.

O ponto pode vir sem velocidade; nesse caso ele entra na trilha mas não recebe
cor de velocidade no mapa.
"""
from __future__ import annotations

from datetime import date

from api.gobrax.cliente import Cliente, periodo_api

CAMINHO = "/api/v2/positions"


def coletar(dia: date, placa: str | None = None, cliente=None) -> list[dict]:
    ini, fim = periodo_api(dia, dia)
    c = cliente or Cliente()
    caminho = f"{CAMINHO}/{placa.strip()}" if (placa or "").strip() else CAMINHO
    corpo = c.get(caminho, {"startDate": ini, "endDate": fim}, timeout=120)
    saida = []
    for v in (corpo.get("data") or []):
        pontos = []
        for p in (v.get("positions") or []):
            try:
                lat, lon = float(p.get("lat")), float(p.get("lon"))
            except (TypeError, ValueError):
                continue          # ponto sem coordenada não vai para o mapa
            vel = p.get("speed")
            pontos.append({"quando": p.get("date"), "lat": lat, "lon": lon,
                           "velocidade": float(vel) if vel is not None else None})
        if pontos:
            saida.append({"placa": (v.get("identification") or "").strip(),
                          "pontos": pontos})
    return saida
