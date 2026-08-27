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


def test_nenhum_numero_de_versao_se_repete():
    """Duas sessoes trabalhando em paralelo escolhem o proximo numero cada uma
    do seu lado e acabam nas duas no mesmo - aconteceu TRES vezes em
    27/08/2026, e uma delas so foi descoberta dias depois, com dois blocos
    diferentes disputando o mesmo rotulo no historico.

    O merge nem sempre acusa: se os dois blocos entram em pontos distintos do
    arquivo, o git junta os dois sem conflito e o numero repetido passa.

    Para escolher o proximo numero com seguranca:
        uv run python scripts/proxima_versao.py
    """
    numeros = [v["versao"] for v in documentacao.versoes()]
    repetidos = sorted({n for n in numeros if numeros.count(n) > 1})
    assert not repetidos, (
        "numero de versao repetido em docs/versoes.yaml: " + ", ".join(repetidos)
        + " - rode `uv run python scripts/proxima_versao.py` para achar um livre")


def test_toda_versao_tem_data_e_ao_menos_uma_mudanca():
    for v in documentacao.versoes():
        assert v["data"], v
        assert v["adicionado"] or v["alterado"] or v["corrigido"], v


def test_endpoint_exige_sessao():
    """/api/versao NAO esta em auth._PUBLICAS: sem cookie tem de dar 401."""
    r = TestClient(app).get("/api/versao")
    assert r.status_code == 401, r.status_code


def test_endpoint_devolve_a_versao():
    """Chama a funcao direto: com TestClient sem sessao a resposta e sempre 401,
    e um `assert status in (200, 401)` seguido de `if status == 200:` nao testa
    absolutamente nada -- era exatamente o caso antes."""
    import json

    from api.main import versao

    corpo = json.loads(versao().body)
    assert corpo["versao"] == VERSAO
    assert corpo["rotulo"] == ROTULO
    assert corpo["data"] == documentacao.versoes()[0]["data"]


def test_toda_versao_traz_o_rotulo_pronto():
    """O formato CX-... e contrato do CLAUDE.md 5.1 e mora SO no backend; o
    front nao pode remontar."""
    for v in documentacao.versoes():
        assert v["rotulo"] == f"CX-{documentacao.data_br(v['data'])}-v{v['versao']}"


def test_versoes_vem_ordenada_da_mais_nova_para_a_mais_velha():
    """Quem acrescentar o bloco novo no FIM do YAML (o natural num changelog) nao
    pode fazer o rodape anunciar a versao mais velha."""
    vs = [documentacao._chave_versao(v["versao"]) for v in documentacao.versoes()]
    assert vs == sorted(vs, reverse=True), vs


def test_ordenacao_de_versao_e_numerica_nao_alfabetica():
    assert documentacao._chave_versao("1.10.0") > documentacao._chave_versao("1.9.0")


def test_toda_tela_do_menu_existe_no_drawer_do_celular():
    """O drawer do MOBILE tem lista FIXA de telas — não é gerado do menu.
    Tela nova que entra só na barra lateral simplesmente NÃO EXISTE no
    celular, e foi o que aconteceu com Portais de Antecipação e Milk Run:
    o usuário abriu no telefone e não achou nenhuma das duas.
    """
    import re
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent.parent
            / "api" / "static" / "index.html").read_text(encoding="utf-8")
    i = html.index('<div class="drawer"')
    drawer = html[i:i + 45_000]

    no_menu = set(re.findall(r'data-view="(\w+)"', html))
    no_drawer = set(re.findall(r'<a href="#(\w+)"', drawer))
    faltando = sorted(no_menu - no_drawer)
    assert not faltando, (
        f"telas no menu lateral e ausentes no drawer do celular: {faltando}")
