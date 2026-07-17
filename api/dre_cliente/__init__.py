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
    alocar_fixo,
    custear_combustivel,
    custear_creditos,
    custear_deducoes,
    custear_diretos,
    custear_taxa_km,
)
from .modelo import IMPOSTO_PARAM, classificar_cf, classificar_cv
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

    # cliente por viagem: (1) join direto da coleta; (2) heuristica por CT-e do
    # mesmo veiculo p/ carregadas sem coleta; (3) km vazio -> cliente originador.
    heur = sql.fetch_heuristica_cliente(cur, de, ate, filial)
    viagem_cliente: dict[Any, Any] = {}
    for v in viagens:
        nome = v["cliente_nome"] or v["cliente_codigo"]
        if nome is None and v["tipo"] != 3:
            nome = heur.get(v["id"])
        viagem_cliente[v["id"]] = nome
    base_vazio = [{"id": v["id"], "veiculo": v["placa"], "dtsaida": v["dtsaida"],
                   "tipo": v["tipo"], "cliente": viagem_cliente[v["id"]], "km": v["km"]}
                  for v in viagens]
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

    # v2: custo fixo do ativo alocado por dia-veiculo -> Margem Direta do Cliente
    cf_por_base = {"proprio": 0.0, "locado": 0.0, "ativo": 0.0}
    for d in sql.fetch_cf_detalhe(comp_de, comp_ate):
        base = classificar_cf(d["agrupador"])
        if base in cf_por_base:
            cf_por_base[base] += d["total"]
    dias_por_cliente = {c["cliente"]: {
        "proprio": c["indicadores"]["dias_proprio"],
        "locado": c["indicadores"]["dias_locado"],
        "ativo": c["indicadores"]["dias_proprio"] + c["indicadores"]["dias_locado"],
    } for c in agg["clientes"]}
    cf_por_cliente = alocar_fixo(cf_por_base, dias_por_cliente)
    for c in agg["clientes"]:
        cf = cf_por_cliente.get(c["cliente"], 0.0)
        mc = c["linhas"].get("MARGEM DE CONTRIBUICAO", 0.0)
        c["linhas"]["CUSTO FIXO"] = cf
        c["linhas"]["MARGEM DIRETA DO CLIENTE"] = mc + cf
        c["indicadores"]["margem_direta"] = mc + cf

    consolidado = dict(agg["consolidado_leaf"])
    consolidado["CUSTO FIXO"] = sum(cf_por_cliente.values())
    recon = reconciliar(consolidado, dre_oficial, {"CUSTO VARIAVEL": variacao_cv})

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
