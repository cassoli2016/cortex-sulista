"""Ingestão da base aberta do RNTRC (dados.antt.gov.br, CC-BY).

O arquivo mensal tem ~158 MB e 1,16 milhão de linhas. Ele é varrido em
streaming e 99,98% das linhas são descartadas na hora: só interessam os
transportadores que a Sulista contrata, identificados pelo número de registro
que o próprio AVA já guarda.

Nenhuma credencial é usada — a fonte é aberta.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.request

from api import tls as _tls

from api.antt.armazenamento import gravar_lote, normalizar_rntrc

URL_PACOTE = "https://dados.antt.gov.br/api/3/action/package_show?id=rntrc"

# colunas que o layout precisa ter para a varredura fazer sentido
_OBRIGATORIAS = {"nome_transportador", "numero_rntrc", "situacao_rntrc",
                 "categoria_transportador", "uf", "municipio",
                 "data_situacao_rntrc"}


class LayoutInesperado(Exception):
    """O CSV mudou de formato. Melhor parar do que gravar lixo por cima."""


_COMPETENCIA = re.compile(r"transportadores_rntrc_(\d{2})_(\d{4})\.csv", re.I)


def competencia_da_url(url: str) -> str | None:
    """'..._07_2026.csv' -> '2026-07'. None se o padrão mudar."""
    m = _COMPETENCIA.search(url or "")
    return f"{m.group(2)}-{m.group(1)}" if m else None


def descobrir_recurso(timeout: int = 60) -> tuple[str, str]:
    """URL e competência do CSV mais recente publicado.

    A escolha é pela competência extraída do nome do arquivo, não pela posição
    na lista: a ordem que o CKAN devolve não é contrato, e pegar o último item
    silenciosamente traria um mês velho no dia em que ela mudar. O rótulo do
    recurso ('Jul26 - RNTRC') não serve como chave — não ordena.
    """
    with urllib.request.urlopen(URL_PACOTE, timeout=timeout, context=_tls.contexto()) as r:
        pacote = json.load(r)
    candidatos = []
    for x in pacote["result"]["resources"]:
        if (x.get("format") or "").upper() != "CSV":
            continue
        comp = competencia_da_url(x.get("url", ""))
        if comp:
            candidatos.append((comp, x["url"]))
    if not candidatos:
        raise LayoutInesperado(
            "nenhum CSV do RNTRC com nome no padrão transportadores_rntrc_MM_AAAA.csv")
    comp, url = max(candidatos)
    return url, comp


def varrer(fonte, interessantes: set[str]) -> list[dict]:
    if not interessantes:
        return []
    leitor = csv.DictReader(fonte, delimiter=";")
    campos = set(leitor.fieldnames or [])
    if not _OBRIGATORIAS <= campos:
        raise LayoutInesperado(
            f"colunas ausentes no CSV do RNTRC: {sorted(_OBRIGATORIAS - campos)}")
    achadas = []
    for linha in leitor:
        num = normalizar_rntrc(linha.get("numero_rntrc"))
        if num not in interessantes:
            continue
        achadas.append({
            "rntrc": num,
            "nome": (linha.get("nome_transportador") or "").strip().strip('"'),
            "situacao": (linha.get("situacao_rntrc") or "").strip().strip('"').upper(),
            "categoria": (linha.get("categoria_transportador") or "").strip().strip('"'),
            "uf": (linha.get("uf") or "").strip().strip('"'),
            "municipio": (linha.get("municipio") or "").strip().strip('"'),
            "data_situacao": (linha.get("data_situacao_rntrc") or "").strip().strip('"'),
        })
    return achadas


def _baixar_padrao():
    url, competencia = descobrir_recurso()
    req = urllib.request.Request(url, headers={"User-Agent": "cortex-sulista"})
    resposta = urllib.request.urlopen(req, timeout=900, context=_tls.contexto())
    return io.TextIOWrapper(resposta, encoding="latin-1", newline=""), competencia


def sincronizar(interessantes: set[str], baixar=None,
                esquema: str | None = None) -> dict:
    """Baixa, varre e grava. Devolve o que aconteceu, para a tela mostrar."""
    fonte, competencia = (baixar or _baixar_padrao)()
    achadas = varrer(fonte, interessantes)
    gravadas = gravar_lote(achadas, competencia, esquema)  # BaseVazia se vier 0
    return {"competencia": competencia, "gravadas": gravadas,
            "procurados": len(interessantes)}
