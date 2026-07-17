"""Atribuicao de km vazio (tipo=3) ao cliente da viagem carregada que o originou.

Regra (spec): todo trecho vazio pertence ao cliente da carregada que o gerou.
Retorno vazio -> carregada anterior; posicionamento -> proxima carga. Operacional:
escolhe a carregada do MESMO veiculo com menor distancia temporal; no empate,
prefere a PROXIMA (regra de posicionamento). Sem carregada no veiculo -> None
(o custo do vazio cai em NAO_ALOCADO na reconciliacao).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def atribuir_vazio(viagens: list[dict[str, Any]]) -> dict[Any, Any]:
    por_veiculo: dict[Any, list[dict]] = defaultdict(list)
    for v in viagens:
        por_veiculo[v["veiculo"]].append(v)

    resultado: dict[Any, Any] = {}
    for vs in por_veiculo.values():
        # candidatas: carregadas com cliente E data (dados do AVA podem ter
        # dtsaida/dtchegada NULL -> nao dao para casar por tempo)
        carregadas = [c for c in vs
                      if c["tipo"] != 3 and c.get("cliente") is not None
                      and c.get("dtsaida") is not None]
        for v in vs:
            if v["tipo"] != 3:
                continue
            t = v.get("dtsaida")
            if t is None or not carregadas:
                resultado[v["id"]] = None
                continue
            # menor distancia temporal; empate -> prefere a proxima (dtsaida > t)
            melhor = min(carregadas,
                         key=lambda c: (abs(c["dtsaida"] - t), 0 if c["dtsaida"] > t else 1))
            resultado[v["id"]] = melhor["cliente"]
    return resultado
