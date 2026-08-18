"""Ponte entre o cadastro de veículo do AVA e a tabela de coeficientes.

O AVA descreve o veículo por tipo, carroceria e um flag de bitrem; a ANTT cobra
número de eixos e uma das 12 classes de carga. Nada aqui adivinha: o que o mapa
não conhece volta None e a tela mostra como pendência de cadastro.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
YAML_PATH = ROOT / "config" / "antt_eixos.yaml"


@lru_cache(maxsize=1)
def _mapa(path: Path | None = None) -> dict:
    p = path or YAML_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto.strip().upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.split())


def resolver_eixos(tipo: str | None, carroceria: str | None,
                   bitrem: bool) -> int | None:
    m = _mapa().get("eixos", {})
    if bitrem:
        return m.get("bitrem")
    return m.get("por_tipo", {}).get(normalizar(tipo))


def resolver_carga(tipo_carga_veiculo: str | None,
                   carroceria: str | None) -> str | None:
    m = _mapa().get("carga", {})
    achado = m.get("por_tipo_carga", {}).get(normalizar(tipo_carga_veiculo))
    if achado:
        return achado
    return m.get("por_carroceria", {}).get(normalizar(carroceria))
