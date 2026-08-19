"""vehicle-performance — indicadores de condução por veículo.

EXIGE placa: sem `vehicleIdentification` a API responde 404 "Veículo não
identificado". Cada chamada leva ~17 s, então a tela pede uma placa por vez e
avisa a demora — varrer a frota seriam mais de 20 minutos.

Traz também o motorista vinculado no período, que é o que liga o indicador à
nota da premiação.
"""
from __future__ import annotations

from api.gobrax.cliente import Cliente
from api.gobrax.periodo import mes_inteiro

CAMINHO = "/api/v1/vehicle-performance"

# rótulos dos indicadores que a API devolve, na ordem em que fazem sentido ler
INDICADORES = {
    "economicRange": "Faixa econômica",
    "cruiseControl": "Piloto automático",
    "ecoRoll": "Eco-roll (embalo)",
}


def _ind(bruto: dict, chave: str) -> dict:
    d = (bruto or {}).get(chave) or {}
    def num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f
    return {"chave": chave, "rotulo": INDICADORES.get(chave, chave),
            "duracao_h": num(d.get("duration")),
            "percentual": num(d.get("percentage")),
            "nota": num(d.get("score"))}


def coletar(placa: str, competencia: str, cliente=None) -> dict:
    if not (placa or "").strip():
        raise ValueError("informe a placa: a API de performance exige veículo")
    ini, fim = mes_inteiro(competencia)
    c = cliente or Cliente()
    corpo = c.get(CAMINHO, {"startDate": ini, "endDate": fim,
                            "vehicleIdentification": placa.strip()}, timeout=120)
    registros = corpo.get("records") or []
    if not registros:
        return {"placa": placa, "competencia": competencia,
                "motoristas": [], "indicadores": []}
    r = registros[0]
    motoristas = [{"nome": (m.get("driverName") or "").strip(),
                   "de": m.get("startDate"), "ate": m.get("endDate")}
                  for m in (r.get("drivers") or [])]
    # o CPF vem no vínculo e é descartado aqui: não tem uso nesta tela
    return {
        "placa": (r.get("vehicleIdentification") or placa).strip(),
        "competencia": competencia,
        "motoristas": motoristas,
        "indicadores": [_ind(r.get("indicators"), k) for k in INDICADORES],
    }
