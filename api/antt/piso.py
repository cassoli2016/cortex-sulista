"""Piso mínimo de frete por viagem — Lei 13.703/2018, Res. ANTT 5.867/2020.

piso = (distância × CCD) + CC

Deslocamento sem carga com pagamento obrigatório (contêiner e frota dedicada
por razão sanitária ou certificação) vale 92% do CCD pela distância, sem CC:
não há carga nem descarga a remunerar. A fórmula é a que a própria calculadora
oficial da ANTT imprime — "Valor do retorno vazio = 0,92 x Distância x CCD".

A função nunca devolve zero para dado ausente. Zero é um piso de verdade e
faria uma viagem parecer regular; ausência tem estado próprio.
"""
from __future__ import annotations

from datetime import date

from api.antt.coeficientes import coeficiente

ESTADOS: tuple[str, ...] = (
    "calculado", "sem_eixos", "sem_carga", "sem_km", "sem_tabela", "isento")

FATOR_VAZIO = 0.92


def _sem_valor(estado: str) -> dict:
    return {"estado": estado, "piso": None, "ccd": None, "cc": None,
            "resolucao": None}


def calcular_piso(km: float, tipo_carga: str | None, eixos: int | None,
                  quando: date, vazio: bool = False,
                  vazio_obrigatorio: bool = False, tabela: str = "A") -> dict:
    if vazio and not vazio_obrigatorio:
        return _sem_valor("isento")
    if not km or km <= 0:
        return _sem_valor("sem_km")
    if eixos is None:
        return _sem_valor("sem_eixos")
    if not tipo_carga:
        return _sem_valor("sem_carga")
    c = coeficiente(tipo_carga, eixos, quando, tabela)
    if c is None:
        return _sem_valor("sem_tabela")
    if vazio:
        return {"estado": "calculado", "piso": FATOR_VAZIO * c["ccd"] * km,
                "ccd": c["ccd"], "cc": None, "resolucao": c["resolucao"]}
    return {"estado": "calculado", "piso": km * c["ccd"] + c["cc"],
            "ccd": c["ccd"], "cc": c["cc"], "resolucao": c["resolucao"]}


def avaliar(pago: float, piso_calc: dict) -> dict:
    """Acrescenta gap e a marca de abaixo-do-piso ao resultado do cálculo.

    Só julga o que foi calculado: viagem sem eixo mapeado não é irregular, é
    desconhecida — e acusar transportador com base em desconhecido é pior do
    que não medir.
    """
    out = dict(piso_calc)
    if piso_calc.get("piso") is None:
        out["gap"] = None
        out["abaixo"] = False
        return out
    gap = float(pago) - float(piso_calc["piso"])
    out["gap"] = gap
    out["abaixo"] = gap < 0
    return out
