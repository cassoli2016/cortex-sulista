"""Funcoes puras de custeio por viagem da DRE por cliente.

CONVENCAO DE SINAL (igual a get_dre = credito - debito):
  receita e creditos tributarios -> POSITIVO
  deducoes e custos variaveis     -> NEGATIVO
Assim o valor descido por linha compara direto com a DRE oficial e o plug de
reconciliacao (NAO_ALOCADO) fecha por construcao.

Entradas sao dados operacionais (magnitudes positivas em R$); a conversao para
a convencao de sinal acontece aqui.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def custear_combustivel(
    custo_por_veiculo: dict[Any, float],
    km_por_viagem: list[dict[str, Any]],
) -> dict[Any, float]:
    """Rateia o custo mensal de combustivel de cada veiculo proprio as suas
    viagens, proporcional ao km (carregado+vazio). AGR/TER recebem 0 (o
    combustivel deles esta no repasse). Retorno negativo (custo)."""
    km_por_placa: dict[Any, float] = defaultdict(float)
    for v in km_por_viagem:
        if v["is_proprio"]:
            km_por_placa[v["placa"]] += v["km"]

    resultado: dict[Any, float] = {}
    for v in km_por_viagem:
        if not v["is_proprio"]:
            resultado[v["id"]] = 0.0
            continue
        total = km_por_placa.get(v["placa"], 0.0)
        custo = custo_por_veiculo.get(v["placa"], 0.0)
        resultado[v["id"]] = -(custo * v["km"] / total) if total else 0.0
    return resultado


def custear_taxa_km(
    taxa_por_veiculo: dict[Any, float],
    km_por_viagem: list[dict[str, Any]],
    real_do_razao: float,
) -> tuple[dict[Any, float], float]:
    """Absorve manutencao/pneus por taxa rolling R$/km x km da viagem (proprio).
    AGR/TER recebem 0. Retorna (absorvido_por_viagem, variacao_de_absorcao),
    com variacao = real_do_razao - soma(absorvido) (tudo em convencao de sinal).
    """
    absorvido: dict[Any, float] = {}
    for v in km_por_viagem:
        if not v["is_proprio"]:
            absorvido[v["id"]] = 0.0
            continue
        taxa = taxa_por_veiculo.get(v["placa"], 0.0)
        absorvido[v["id"]] = -(taxa * v["km"])
    variacao = real_do_razao - sum(absorvido.values())
    return absorvido, variacao
