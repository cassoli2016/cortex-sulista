"""Traduz o tipo de carga do cadastro do AVA para as classes da tabela ANTT.

Os eixos NÃO passam por aqui: o AVA tem tipoveiculo.quantidadeeixos com
cobertura total, e o SQL já entrega a soma da composição. O que sobra é o tipo
de carga, e mesmo esse o cadastro quase não distingue — 'DIV' (DIVERSAS) cobre
1.352 dos 1.377 veículos de agregados e terceiros.

A escolha de mapear tudo o que se conhece para carga_geral é deliberada e
conservadora: carga geral tem o menor coeficiente entre as classes não
perigosas, então o piso calculado nunca fica maior que o devido. Errar para
cima acusaria de irregular quem pagou certo — o oposto do que esta tela existe
para fazer.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
YAML_PATH = ROOT / "config" / "antt_cargas.yaml"


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


def resolver_carga(codigo_tipocarga: str | None) -> str | None:
    """Classe da ANTT para o código de tipo de carga do AVA.

    Código desconhecido devolve None de propósito: entra como pendência de
    cadastro na tela, para que apareça e seja mapeado aqui, em vez de virar
    silenciosamente carga geral.
    """
    m = _mapa().get("carga", {})
    cod = normalizar(codigo_tipocarga)
    if not cod:
        return m.get("padrao")
    return m.get("por_codigo", {}).get(cod)
