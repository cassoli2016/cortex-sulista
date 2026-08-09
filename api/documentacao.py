"""Documentação do sistema servida ao painel.

Duas fontes, nenhuma duplicada:
  - docs/versoes.yaml  — histórico de versões, escrito à mão
  - docs/manual.yaml   — a curadoria: o que é o sistema, o resumo de cada grupo
                         de telas e o glossário canônico
  - api/static/index.html — as telas e a PROCEDÊNCIA de cada card, extraídas do
                         próprio painel (ver extrair_telas). É o que impede a
                         documentação de envelhecer quando a tela muda: os
                         tooltips ⓘ já dizem a tabela e a regra de origem.
"""
from __future__ import annotations

import html as _html
import re
from datetime import date
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
VERSOES_YAML = RAIZ / "docs" / "versoes.yaml"
MANUAL_YAML = RAIZ / "docs" / "manual.yaml"
INDEX = RAIZ / "api" / "static" / "index.html"

_CAMPOS = ("adicionado", "alterado", "corrigido")


# --------------------------------------------------------------- versões
def versoes() -> list[dict]:
    """Histórico completo, mais recente primeiro. Normaliza as listas ausentes."""
    dados = yaml.safe_load(VERSOES_YAML.read_text(encoding="utf-8")) or []
    saida = []
    for v in dados:
        item = {"versao": str(v["versao"]), "data": str(v["data"])}
        for c in _CAMPOS:
            item[c] = list(v.get(c) or [])
        saida.append(item)
    return saida


def data_br(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def rotulo(versao: str) -> str:
    """CX-DD/MM/AAAA-vX.Y.Z — a data é a DA VERSÃO, não a de hoje."""
    for v in versoes():
        if v["versao"] == versao:
            return f"CX-{data_br(v['data'])}-v{versao}"
    return f"CX-{date.today().strftime('%d/%m/%Y')}-v{versao}"


def changelog_md() -> str:
    """Gera o CHANGELOG.md a partir do YAML. Um teste compara os dois."""
    linhas = [
        "# Changelog",
        "",
        "Gerado de `docs/versoes.yaml` por `scripts/gerar_changelog.py` — não editar à mão.",
        "Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),",
        "versionamento [SemVer](https://semver.org/lang/pt-BR/).",
        "",
    ]
    titulo = {"adicionado": "Adicionado", "alterado": "Alterado", "corrigido": "Corrigido"}
    for v in versoes():
        linhas.append(f"## [{v['versao']}] — {data_br(v['data'])}  ·  {rotulo(v['versao'])}")
        linhas.append("")
        for c in _CAMPOS:
            if not v[c]:
                continue
            linhas.append(f"### {titulo[c]}")
            for item in v[c]:
                linhas.append(f"- {item}")
            linhas.append("")
    return "\n".join(linhas).rstrip() + "\n"


# ------------------------------------------------- extração do painel
# <section class="view" id="view-dre"> … </section>  (o id dá a view)
_SECAO = re.compile(r'<section class="view" id="view-([a-z0-9]+)"', re.I)
# <h2>Título <span class="ihelp" … title="procedência">i</span></h2>
_H2 = re.compile(r"<h2>(.*?)</h2>", re.S | re.I)
_TITLE = re.compile(r'title="([^"]*)"', re.S)
_TAGS = re.compile(r"<[^>]+>")

_cache: dict = {}


def _texto(bruto: str) -> str:
    return " ".join(_html.unescape(_TAGS.sub(" ", bruto)).split())


def _titulos_views() -> dict[str, str]:
    """Lê o objeto VIEWS do index.html — a fonte dos nomes oficiais das telas."""
    h = INDEX.read_text(encoding="utf-8")
    m = re.search(r"const VIEWS = \{(.*?)\};", h, re.S)
    if not m:
        return {}
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", m.group(1)))


def extrair_telas() -> dict[str, dict]:
    """Telas do painel com o título de cada card e a procedência do ⓘ.

    Cacheado pelo mtime do index.html: o arquivo tem ~800 KB e a tela de
    documentação não precisa reparsear a cada request, mas também não pode
    servir conteúdo velho depois de um deploy.
    """
    mtime = INDEX.stat().st_mtime
    if _cache.get("mtime") == mtime:
        return _cache["telas"]

    h = INDEX.read_text(encoding="utf-8")
    nomes = _titulos_views()
    marcas = [(m.group(1), m.start()) for m in _SECAO.finditer(h)]
    telas: dict[str, dict] = {}
    for i, (view, ini) in enumerate(marcas):
        fim = marcas[i + 1][1] if i + 1 < len(marcas) else len(h)
        bloco = h[ini:fim]
        cards = []
        for m in _H2.finditer(bloco):
            bruto = m.group(1)
            t = _TITLE.search(bruto)
            titulo = _texto(bruto)
            if titulo.endswith(" i"):          # o "i" é o glifo do ⓘ
                titulo = titulo[:-2].strip()
            if not titulo:
                continue
            cards.append({"titulo": titulo, "fonte": _texto(t.group(1)) if t else None})
        telas[view] = {"titulo": nomes.get(view, view), "cards": cards}

    _cache.update(mtime=mtime, telas=telas)
    return telas


def montar() -> dict:
    """Payload da tela de Documentação."""
    manual = yaml.safe_load(MANUAL_YAML.read_text(encoding="utf-8")) or {}
    telas = extrair_telas()
    vs = versoes()
    corrente = vs[0]["versao"] if vs else "dev"
    grupos = [
        {"nome": g["nome"], "resumo": g["resumo"],
         "telas": [v for v in g["telas"] if v in telas]}
        for g in manual.get("grupos", [])
    ]
    return {
        "versao": corrente,
        "rotulo": rotulo(corrente),
        "sistema": manual.get("sistema", ""),
        "glossario": manual.get("glossario", []),
        "grupos": grupos,
        "telas": telas,
        "versoes": vs,
    }
