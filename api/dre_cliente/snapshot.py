"""Snapshots por mes fechado da DRE por cliente (data/dre_cliente/<YYYY-MM>.json).

Idempotencia + historico + reload rapido: meses fechados sao gravados uma vez e
relidos; mes aberto e ultimos 2 meses sao sempre recalculados ao vivo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parents[2] / "data" / "dre_cliente"


def caminho(mes: str) -> Path:
    return _DIR / f"{mes}.json"


def ler(mes: str) -> dict[str, Any] | None:
    p = caminho(mes)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - snapshot corrompido -> recalcula
        return None


def gravar(mes: str, payload: dict[str, Any]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    tmp = caminho(mes).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, caminho(mes))  # troca atomica
