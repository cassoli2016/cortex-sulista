"""Agregacao por cliente x linha, resolucao das formulas e ranking por MC%.

Recebe as contribuicoes ja mescladas por linha-folha e por viagem (convencao de
sinal da DRE), o mapa viagem->cliente e a metadata por viagem (km, tipo, etc.),
e monta a DRE por cliente (linhas folha + formulas), os indicadores e o ranking.
Tambem devolve o consolidado por linha-folha (soma de TODAS as viagens) para a
reconciliacao contra a DRE oficial.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .modelo import LINHAS_CLIENTE

_POR_ROTULO = {l.rotulo: l for l in LINHAS_CLIENTE}
_LEAF = [l.rotulo for l in LINHAS_CLIENTE if l.metodo != "formula"]
_SEM_CLIENTE = "(sem cliente)"


def _resolver_formulas(leaf: dict[str, float]) -> dict[str, float]:
    memo: dict[str, float] = dict(leaf)

    def val(rotulo: str) -> float:
        if rotulo in memo:
            return memo[rotulo]
        linha = _POR_ROTULO[rotulo]
        if linha.metodo == "formula":
            memo[rotulo] = sum(val(c) for c in linha.componentes)
        else:
            memo[rotulo] = 0.0
        return memo[rotulo]

    for l in LINHAS_CLIENTE:
        val(l.rotulo)
    return memo


def _mix_bucket(tipo_operacao: str) -> str:
    t = (tipo_operacao or "").upper()
    if t in ("FROTA", "LOCACAO"):
        return "proprio"
    if t == "AGR":
        return "agregado"
    if t == "TER":
        return "terceiro"
    return "outro"


def agregar(
    linhas_por_viagem: dict[str, dict[Any, float]],
    viagem_cliente: dict[Any, Any],
    viagem_meta: dict[Any, dict],
) -> dict:
    def cli(vid: Any) -> Any:
        c = viagem_cliente.get(vid)
        return _SEM_CLIENTE if c is None else c

    # leaf por cliente e consolidado
    leaf_por_cliente: dict[Any, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    consolidado_leaf: dict[str, float] = defaultdict(float)
    for linha, por_viagem in linhas_por_viagem.items():
        for vid, valor in por_viagem.items():
            leaf_por_cliente[cli(vid)][linha] += valor
            consolidado_leaf[linha] += valor

    # indicadores por cliente
    ind: dict[Any, dict] = defaultdict(lambda: {
        "km_carregado": 0.0, "km_vazio": 0.0, "viagens": 0, "dias_veiculo": 0,
        "mix": defaultdict(float),
    })
    for vid, meta in viagem_meta.items():
        c = cli(vid)
        km = float(meta.get("km", 0.0) or 0.0)
        if meta.get("tipo") == 3:
            ind[c]["km_vazio"] += km
        else:
            ind[c]["km_carregado"] += km
            ind[c]["viagens"] += 1
        ind[c]["dias_veiculo"] += int(meta.get("dias", 0) or 0)
        ind[c]["mix"][_mix_bucket(meta.get("tipo_operacao", ""))] += km

    clientes = []
    for c, leaf in leaf_por_cliente.items():
        linhas = _resolver_formulas(dict(leaf))
        rl = linhas.get("RECEITA LIQUIDA", 0.0)
        mc = linhas.get("MARGEM DE CONTRIBUICAO", 0.0)
        i = ind.get(c, {"km_carregado": 0.0, "km_vazio": 0.0, "viagens": 0,
                        "dias_veiculo": 0, "mix": {}})
        km_tot = i["km_carregado"] + i["km_vazio"]
        clientes.append({
            "cliente": c,
            "linhas": linhas,
            "indicadores": {
                "km_carregado": i["km_carregado"],
                "km_vazio": i["km_vazio"],
                "pct_km_vazio": (i["km_vazio"] / km_tot) if km_tot else 0.0,
                "viagens": i["viagens"],
                "dias_veiculo": i["dias_veiculo"],
                "mc": mc,
                "mc_pct": (mc / rl) if rl else None,
                "mix": dict(i["mix"]),
            },
        })

    # ranking por MC% desc; None (rl=0) vai para o fim
    clientes.sort(key=lambda c: (c["indicadores"]["mc_pct"] is None,
                                 -(c["indicadores"]["mc_pct"] or 0.0)))
    return {"clientes": clientes, "consolidado_leaf": dict(consolidado_leaf)}
