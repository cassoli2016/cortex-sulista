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


def custear_deducoes(
    receita_por_viagem: dict[Any, float],
    pct: dict[str, float],
) -> dict[str, dict[Any, float]]:
    """Deducao efetiva por imposto: -(receita x pct) por viagem (negativo)."""
    return {
        imposto: {vid: -(receita * p) for vid, receita in receita_por_viagem.items()}
        for imposto, p in pct.items()
    }


def custear_creditos(
    custos_geradores_por_viagem: dict[str, dict[Any, float]],
    pct: dict[str, float],
) -> dict[Any, float]:
    """Credito tributario (redutor, POSITIVO): soma por viagem de
    abs(custo_gerador) x pct, so das naturezas com pct definido."""
    creditos: dict[Any, float] = defaultdict(float)
    for natureza, por_viagem in custos_geradores_por_viagem.items():
        p = pct.get(natureza)
        if not p:
            continue
        for vid, custo in por_viagem.items():
            creditos[vid] += abs(custo) * p
    return dict(creditos)


# campo direto da viagem -> linha da DRE (todos custos/deducoes = negativos)
_DIRETOS_CV = ("pedagio", "diarias", "carga_desc", "motoristas_px", "seguro_carga")


def custear_diretos(viagens: list[dict[str, Any]]) -> dict[str, dict[Any, float]]:
    """Linhas diretas por viagem: receita bruta (valorfrete), repasse de frete
    para AGR/TER (valorfretecompra, so quando NAO proprio) e campos diretos
    opcionais. Tudo que nao existir na viagem vira residuo (NAO_ALOCADO na
    reconciliacao). Repasse e campos de custo rolam em CUSTO VARIAVEL."""
    receita: dict[Any, float] = {}
    custo_var: dict[Any, float] = {}
    anulacoes: dict[Any, float] = {}
    descontos: dict[Any, float] = {}

    for v in viagens:
        vid = v["id"]
        receita[vid] = float(v.get("valorfrete", 0.0) or 0.0)
        cv = 0.0
        if not v.get("is_proprio", True):
            cv += -float(v.get("valorfretecompra", 0.0) or 0.0)
        for campo in _DIRETOS_CV:
            if v.get(campo):
                cv += -float(v[campo])
        custo_var[vid] = cv
        if v.get("anulacoes"):
            anulacoes[vid] = -float(v["anulacoes"])
        if v.get("descontos"):
            descontos[vid] = -float(v["descontos"])

    out: dict[str, dict[Any, float]] = {
        "RECEITA BRUTA": receita,
        "CUSTO VARIAVEL": custo_var,
    }
    if anulacoes:
        out["ANULACOES"] = anulacoes
    if descontos:
        out["DESCONTOS"] = descontos
    return out


_BASES_CF = ("proprio", "locado", "ativo")


def alocar_fixo(
    cf_por_base: dict[str, float],
    dias_por_cliente: dict[Any, dict[str, float]],
) -> dict[Any, float]:
    """Aloca o custo fixo do ativo por dia-veiculo (v2). Cada base (proprio=
    depreciacao/juros, locado=locacao, ativo=demais CF do ativo) e distribuida
    entre os clientes proporcional aos dias-veiculo daquela base. Valores
    negativos (custo). Base sem dias nao e alocada (fica no plug NAO_ALOCADO)."""
    totais = {b: sum(d.get(b, 0.0) for d in dias_por_cliente.values()) for b in _BASES_CF}
    out: dict[Any, float] = {}
    for cli, d in dias_por_cliente.items():
        v = 0.0
        for b in _BASES_CF:
            if totais[b] > 0:
                v += cf_por_base.get(b, 0.0) * d.get(b, 0.0) / totais[b]
        out[cli] = v
    return out
