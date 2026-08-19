"""vehicle-statistics — consumo, velocidade e frenagens por veículo.

Aceita a frota inteira numa chamada, mas leva ~73 s: só é chamada pela
sincronização, nunca pelo carregamento de uma tela.
"""
from __future__ import annotations

from pathlib import Path

from api.gobrax import armazenamento
from api.gobrax.cliente import Cliente
from api.gobrax.periodo import mes_inteiro

CAMINHO = "/api/v1/vehicle-statistics"
COLECAO = "estatisticas"


def _num(valor):
    """Zero da API vira None: ausência de medida não é medida zero."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def coletar(competencia: str, cliente=None) -> list[dict]:
    ini, fim = mes_inteiro(competencia)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim,
                            "vehicleIdentification": ""}, timeout=240)
    saida = []
    for r in (corpo.get("records") or []):
        saida.append({
            "placa": (r.get("vehicleIdentification") or "").strip(),
            "km": _num(r.get("totalMileage")),
            "litros": _num(r.get("totalConsumption")),
            "km_l": _num(r.get("consumptionAverage")),
            "vel_media": _num(r.get("averageSpeed")),
            "odometro": _num(r.get("odometer")),
            "freadas": int(r.get("totalBreaking") or 0),
            "freadas_alta": int(r.get("totalBreakingOnHighSpeed") or 0),
        })
    return saida


def sincronizar(competencia: str, cliente=None, path: Path | None = None) -> dict:
    linhas = coletar(competencia, cliente)
    gravadas = armazenamento.gravar(COLECAO, competencia, linhas, path)
    return {"competencia": competencia, "gravadas": gravadas}
