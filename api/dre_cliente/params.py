"""Carga dos parametros de negocio versionados da DRE por cliente.

Os valores vivem em config/dre_cliente_params.yaml (versionado no git); NUNCA
hardcodar percentuais no codigo. Ver docs/superpowers/specs/2026-07-17-dre-por-cliente-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "dre_cliente_params.yaml"

_OBRIGATORIAS = ("deducoes_pct", "creditos_pct", "rateio_intra_viagem",
                 "taxa_km_janela_meses", "preco_diesel_fallback")
_DEDUCOES = ("federais", "estaduais", "municipais", "previdenciaria")
_CREDITOS = ("combustivel", "pneus", "manutencao", "frete_contratado")


@dataclass(frozen=True)
class Params:
    deducoes_pct: dict[str, float]
    creditos_pct: dict[str, float]
    rateio_intra_viagem: str
    taxa_km_janela_meses: int
    preco_diesel_fallback: float


def carregar_params(path: str | Path | None = None) -> Params:
    """Le e valida o YAML de parametros. Levanta ValueError se faltar chave."""
    p = Path(path) if path is not None else _DEFAULT_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    faltando = [k for k in _OBRIGATORIAS if k not in raw]
    if faltando:
        raise ValueError(f"parametros obrigatorios ausentes: {faltando}")

    deducoes = {k: float(raw["deducoes_pct"].get(k, 0.0)) for k in _DEDUCOES}
    creditos = {k: float(raw["creditos_pct"].get(k, 0.0)) for k in _CREDITOS}
    rateio = str(raw["rateio_intra_viagem"])
    if rateio not in ("peso", "receita"):
        raise ValueError(f"rateio_intra_viagem invalido: {rateio!r}")

    return Params(
        deducoes_pct=deducoes,
        creditos_pct=creditos,
        rateio_intra_viagem=rateio,
        taxa_km_janela_meses=int(raw["taxa_km_janela_meses"]),
        preco_diesel_fallback=float(raw["preco_diesel_fallback"]),
    )
