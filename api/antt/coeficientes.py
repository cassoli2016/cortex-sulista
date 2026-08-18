"""Coeficientes dos pisos mínimos da ANTT, resolvidos pela vigência da viagem.

A tabela muda duas vezes por ano. Conferir um acerto de março contra a tabela de
agosto reescreveria todo período fechado a cada reajuste — por isso a busca é
sempre pela data do fato, nunca pela data de hoje.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
YAML_PATH = ROOT / "config" / "antt_coeficientes.yaml"

TIPOS_CARGA: tuple[str, ...] = (
    "granel_solido", "granel_liquido", "frigorificada", "conteinerizada",
    "carga_geral", "neogranel", "perigosa_granel_solido",
    "perigosa_granel_liquido", "perigosa_frigorificada",
    "perigosa_conteinerizada", "perigosa_carga_geral", "granel_pressurizada",
)


@lru_cache(maxsize=1)
def carregar(path: Path | None = None) -> dict:
    p = path or YAML_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _vigencia(quando: date, dados: dict) -> dict | None:
    for v in dados.get("vigencias", []):
        inicio, fim = v["inicio"], v.get("fim")
        if quando >= inicio and (fim is None or quando <= fim):
            return v
    return None


def coeficiente(tipo_carga: str, eixos: int, quando: date,
                tabela: str = "A") -> dict | None:
    """CCD e CC vigentes na data, ou None se não há linha aplicável.

    Eixo sem linha própria usa o imediatamente INFERIOR, conforme a nota do
    Anexo II da Res. 5.867/2020 — é o que a calculadora oficial faz. Arredondar
    para cima cobraria um piso maior que o devido e marcaria como irregular um
    pagamento correto.

    None continua sendo resposta legítima para tipo de carga que não existe ou
    eixo abaixo do menor da tabela. Quem chama trata como 'não calculável',
    nunca como zero.
    """
    v = _vigencia(quando, carregar())
    if v is None:
        return None
    linhas = v["tabelas"].get(tabela, {}).get(tipo_carga) or {}
    aplicaveis = [e for e in linhas if e <= eixos]
    if not aplicaveis:
        return None
    linha = linhas[max(aplicaveis)]
    return {"ccd": float(linha["ccd"]), "cc": float(linha["cc"]),
            "resolucao": v["resolucao"]}
