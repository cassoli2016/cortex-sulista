"""vehicle-odometer — hodômetro e data da última leitura.

Leva ~66 s para a frota: mesma regra das estatísticas, só pela sincronização.
O `lido_em` é tão útil quanto o número: leitura velha é sintoma de rastreador
mudo, o mesmo problema que a tela de Comunicação Rastreadora acompanha.
"""
from __future__ import annotations

from pathlib import Path

from api.gobrax import armazenamento
from api.gobrax.cliente import Cliente
from api.gobrax.periodo import mes_inteiro

CAMINHO = "/api/v2/vehicle-odometer"
COLECAO = "odometro"


def coletar(competencia: str, cliente=None) -> list[dict]:
    ini, fim = mes_inteiro(competencia)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim,
                            "vehicleIdentification": ""}, timeout=240)
    saida = []
    for r in (corpo.get("records") or []):
        try:
            odo = float(r.get("odometer") or 0)
        except (TypeError, ValueError):
            odo = 0
        saida.append({
            "placa": (r.get("vehicleIdentification") or "").strip(),
            "odometro": odo if odo > 0 else None,
            "lido_em": r.get("lastUpdated"),
        })
    return saida


def sincronizar(competencia: str, cliente=None, path: Path | None = None) -> dict:
    linhas = coletar(competencia, cliente)
    gravadas = armazenamento.gravar(COLECAO, competencia, linhas, path)
    return {"competencia": competencia, "gravadas": gravadas}
