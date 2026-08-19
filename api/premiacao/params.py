"""Parâmetros da premiação — data/premiacao_params.json, editáveis pela tela.

Regra vigente desde 19/08/2026: premio = km x valor_por_km x (nota/100).

O arquivo CARIMBA a regra que o gravou. Sem isso, parâmetro de nome igual em
duas regras diferentes atravessa a troca calado: o `km_minimo` da regra de
economia de combustível (500 km) sobreviveu na regra de nota x km, cujo default
é 1500 — e pagou prêmio a 10-11 motoristas por mês (~R$ 900/mês, medido em
junho e julho de 2026) que ninguém decidiu premiar. Regra gravada diferente da
vigente = arquivo inteiro descartado, nunca mesclado campo a campo.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PARAMS_PATH = ROOT / "data" / "premiacao_params.json"

REGRA = "nota_km"  # muda junto com a fórmula; invalida params de regra anterior
DEFAULTS = {"valor_por_km": 0.10, "nota_minima": 70.0, "km_minimo": 1500.0}


def _para_float(chave: str, valor) -> float:
    """Converte para float ou levanta ValueError com mensagem pt-BR — nunca deixa
    TypeError (None, lista, dict etc.) escapar para quem chama `salvar_params`."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"O parâmetro '{chave}' precisa ser um número.") from None


def _valida(p: dict) -> None:
    if p["valor_por_km"] <= 0:
        raise ValueError("O valor por km tem de ser maior que zero.")
    if not (0 <= p["nota_minima"] <= 100):
        raise ValueError("A nota mínima vai de 0 a 100.")
    if p["km_minimo"] < 0:
        raise ValueError("O km mínimo não pode ser negativo.")


def ler_params(path: Path | None = None) -> dict:
    path = Path(path or PARAMS_PATH)
    atual = dict(DEFAULTS)
    if path.exists():
        try:
            gravado = json.loads(path.read_text(encoding="utf-8"))
            if gravado.get("regra") != REGRA:
                return dict(DEFAULTS)  # params de outra regra não valem para esta
            atual.update({k: float(gravado[k]) for k in DEFAULTS if k in gravado})
            _valida(atual)  # arquivo com valores inválidos volta aos defaults
        except (json.JSONDecodeError, TypeError, ValueError):
            atual = dict(DEFAULTS)  # arquivo corrompido ou inválido: volta aos defaults
    return atual


def salvar_params(novos: dict, path: Path | None = None) -> dict:
    path = Path(path or PARAMS_PATH)
    efetivo = ler_params(path)
    efetivo.update({k: _para_float(k, novos[k]) for k in DEFAULTS if k in novos})
    _valida(efetivo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"regra": REGRA, **efetivo}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return efetivo
