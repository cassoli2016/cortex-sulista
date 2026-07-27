"""Parâmetros da premiação — data/premiacao_params.json, editáveis pela tela."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_PATH = ROOT / "data" / "premiacao_params.json"

DEFAULTS = {"meta": 2.0, "preco_litro": 4.93, "pct_premiacao": 0.20, "km_minimo": 500.0}


def _valida(p: dict) -> None:
    if p["meta"] <= 0:
        raise ValueError("A meta (km/l) tem de ser maior que zero.")
    if p["preco_litro"] <= 0:
        raise ValueError("O preço do litro tem de ser maior que zero.")
    if not (0 <= p["pct_premiacao"] <= 1):
        raise ValueError("O percentual de premiação vai de 0 a 1 (ex.: 0,20 = 20%).")
    if p["km_minimo"] < 0:
        raise ValueError("O km mínimo não pode ser negativo.")


def ler_params(path: Path | None = None) -> dict:
    path = Path(path or PARAMS_PATH)
    atual = dict(DEFAULTS)
    if path.exists():
        try:
            gravado = json.loads(path.read_text(encoding="utf-8"))
            atual.update({k: float(gravado[k]) for k in DEFAULTS if k in gravado})
            _valida(atual)  # arquivo com valores inválidos volta aos defaults
        except (json.JSONDecodeError, TypeError, ValueError):
            atual = dict(DEFAULTS)  # arquivo corrompido ou inválido: volta aos defaults
    return atual


def salvar_params(novos: dict, path: Path | None = None) -> dict:
    path = Path(path or PARAMS_PATH)
    efetivo = ler_params(path)
    efetivo.update({k: float(novos[k]) for k in DEFAULTS if k in novos})
    _valida(efetivo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(efetivo, ensure_ascii=False, indent=2), encoding="utf-8")
    return efetivo
