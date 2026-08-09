"""A versao exposta pela API tem de ser a MESMA do pyproject.toml e do
docs/versoes.yaml, e o CHANGELOG.md tem de estar em dia com o YAML.

Tres fontes divergentes e pior que nenhuma: o rodape do painel diria uma coisa,
o repositorio outra e a checagem de deploy passaria a mentir.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from api import documentacao
from api.main import ROTULO, VERSAO, app

RAIZ = Path(__file__).resolve().parents[2]


def test_versao_bate_com_o_pyproject():
    dados = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert VERSAO == dados["project"]["version"]


def test_versao_e_a_primeira_do_versoes_yaml():
    vs = documentacao.versoes()
    assert vs, "docs/versoes.yaml vazio"
    assert vs[0]["versao"] == VERSAO, "a versao do topo do YAML tem de ser a corrente"


def test_rotulo_no_formato_cx():
    assert re.fullmatch(r"CX-\d{2}/\d{2}/\d{4}-v\d+\.\d+\.\d+", ROTULO), ROTULO
    assert ROTULO.endswith("-v" + VERSAO)


def test_changelog_esta_em_dia_com_o_yaml():
    md = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    gerado = documentacao.changelog_md()
    assert md.strip() == gerado.strip(), (
        "CHANGELOG.md desatualizado — rode: uv run python scripts/gerar_changelog.py")


def test_toda_versao_tem_data_e_ao_menos_uma_mudanca():
    for v in documentacao.versoes():
        assert v["data"], v
        assert v["adicionado"] or v["alterado"] or v["corrigido"], v


def test_endpoint_devolve_a_versao():
    cliente = TestClient(app)
    r = cliente.get("/api/versao")
    assert r.status_code in (200, 401)
    if r.status_code == 200:
        assert r.json()["versao"] == VERSAO
        assert r.json()["rotulo"] == ROTULO
