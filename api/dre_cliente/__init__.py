"""Modulo DRE por cliente (v1: ate Margem de Contribuicao).

Orquestra: fetch (AVA) -> custeio por viagem -> atribuicao de km vazio ->
agregacao por cliente -> reconciliacao contra a DRE oficial (get_dre).
Live-compute + snapshot para periodos fechados. Ver
docs/superpowers/specs/2026-07-17-dre-por-cliente-design.md.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from .. import db
from ..queries import _comp_bounds, cached
from . import snapshot, sql
from .agregacao import agregar
from .custeio import (
    custear_combustivel,
    custear_creditos,
    custear_deducoes,
    custear_diretos,
    custear_taxa_km,
)
from .modelo import IMPOSTO_PARAM, classificar_cv
from .params import carregar_params
from .reconciliacao import reconciliar
from .vazio import atribuir_vazio


def _merge(*fontes: dict[Any, float]) -> dict[Any, float]:
    out: dict[Any, float] = defaultdict(float)
    for f in fontes:
        for vid, val in f.items():
            out[vid] += val
    return dict(out)


def _dias(dtsaida, dtchegada) -> int:
    if dtsaida and dtchegada:
        try:
            return max(1, (dtchegada - dtsaida).days + 1)
        except TypeError:
            return 1
    return 1


def _viagem_meta(viagens: list[dict]) -> dict[Any, dict]:
    return {
        v["id"]: {
            "km": v["km"], "tipo": v["tipo"], "is_proprio": v["is_proprio"],
            "tipo_operacao": v["tipo_operacao"],
            "dias": _dias(v["dtsaida"], v["dtchegada"]),
        }
        for v in viagens
    }


def _calcular(cur, comp_de: str, comp_ate: str, filial: int | None, params) -> dict:
    de, ate = _comp_bounds(comp_de, comp_ate)
    viagens = sql.fetch_viagens(cur, de, ate, filial)
    abastec = sql.fetch_abastecimentos(cur, de, ate)
    de_jan, ate_jan = sql.janela_bounds(comp_ate, params.taxa_km_janela_meses)
    taxa = sql.fetch_taxa_km(cur, de_jan, ate_jan)
    dre_oficial = sql.fetch_dre_oficial(comp_de, comp_ate)
    cv_detalhe = sql.fetch_cv_detalhe(comp_de, comp_ate)

    # cliente por viagem: carregadas via join; vazias via atribuicao ao originador
    viagem_cliente: dict[Any, Any] = {}
    base_vazio = []
    for v in viagens:
        nome = v["cliente_nome"] or v["cliente_codigo"]
        viagem_cliente[v["id"]] = nome
        base_vazio.append({"id": v["id"], "veiculo": v["placa"],
                           "dtsaida": v["dtsaida"], "tipo": v["tipo"],
                           "cliente": nome, "km": v["km"]})
    for vid, cli in atribuir_vazio(base_vazio).items():
        if viagem_cliente.get(vid) is None:
            viagem_cliente[vid] = cli

    km_por_viagem = [{"id": v["id"], "placa": v["placa"], "km": v["km"],
                      "is_proprio": v["is_proprio"]} for v in viagens]

    diretos = custear_diretos(viagens)
    comb = custear_combustivel(abastec, km_por_viagem)
    real_taxa = sum(d["total"] for d in cv_detalhe
                    if classificar_cv(d["agrupador"]) == "taxa_km")
    taxa_absorvido, variacao_cv = custear_taxa_km(taxa, km_por_viagem, real_taxa)

    custos_geradores = {
        "combustivel": comb,
        "manutencao": taxa_absorvido,
        "frete_contratado": {v["id"]: -v["valorfretecompra"]
                             for v in viagens if not v["is_proprio"]},
    }
    creditos = custear_creditos(custos_geradores, params.creditos_pct)
    deducoes = custear_deducoes(diretos["RECEITA BRUTA"], params.deducoes_pct)

    linhas_por_viagem: dict[str, dict[Any, float]] = {
        "RECEITA BRUTA": diretos["RECEITA BRUTA"],
        "CUSTO VARIAVEL": _merge(diretos.get("CUSTO VARIAVEL", {}), comb, taxa_absorvido),
        "CREDITOS TRIBUTARIOS": creditos,
    }
    for rotulo, chave in IMPOSTO_PARAM.items():
        linhas_por_viagem[rotulo] = deducoes.get(chave, {})
    for extra in ("ANULACOES", "DESCONTOS"):
        if extra in diretos:
            linhas_por_viagem[extra] = diretos[extra]

    agg = agregar(linhas_por_viagem, viagem_cliente, _viagem_meta(viagens))
    recon = reconciliar(agg["consolidado_leaf"], dre_oficial,
                        {"CUSTO VARIAVEL": variacao_cv})

    cobertura = {k: v["cobertura_pct"] for k, v in recon.items()}
    return {
        "clientes": agg["clientes"],
        "reconciliacao": recon,
        "cobertura": cobertura,
        "comp_de": comp_de, "comp_ate": comp_ate, "filial": filial,
        "fonte": "ERP AVA - viagens (custeio bottom-up) + razao (DRE oficial) - leitura",
    }


def _periodo_fechado(comp_ate: str) -> bool:
    _, ate = _comp_bounds(comp_ate, comp_ate)
    hoje = date.today()
    return date.fromisoformat(ate) <= date(hoje.year, hoje.month, 1)


@cached(ttl=600)
def get_dre_cliente(comp_de: str, comp_ate: str, filial: int | None = None) -> dict:
    chave = f"{comp_de}_{comp_ate}_{filial if filial is not None else 'all'}"
    if _periodo_fechado(comp_ate):
        snap = snapshot.ler(chave)
        if snap is not None:
            return snap
    params = carregar_params()
    with db.get_conn() as conn, conn.cursor() as cur:
        resultado = _calcular(cur, comp_de, comp_ate, filial, params)
    if _periodo_fechado(comp_ate):
        snapshot.gravar(chave, resultado)
    return resultado
