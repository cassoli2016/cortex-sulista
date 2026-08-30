"""Rotulos do eixo X do Saldo projetado nao podem se sobrepor.

O bug: `i%passo===0||i===n-1` forcava o ultimo rotulo a aparecer mesmo quando
n-1 nao caia no passo, entao ele nascia colado no anterior. Com granularidade
SEMANA acontecia quase sempre — 26 semanas, passo 2, o indice 25 desenhado ao
lado do 24 com rotulos de ~66 px em bandas de 33 px.
"""
import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def render() -> str:
    s = HTML.read_text(encoding="utf-8")
    i = s.index("function chartFcRender(")
    return s[i:s.index("\n}", i)]


@pytest.fixture(scope="module")
def codigo(render) -> str:
    """So o CODIGO: os comentarios citam a regra antiga de proposito, para
    explicar o que era errado nela, e um teste que le comentario acusa a
    propria documentacao."""
    return re.sub(r"/\*.*?\*/", "", render, flags=re.S)


def test_o_ultimo_rotulo_nao_e_mais_forcado_as_cegas(codigo):
    assert "i%passo===0||i===n-1" not in codigo, (
        "a regra antiga voltou: ela desenha o ultimo rotulo mesmo colado no "
        "anterior")


def test_existe_teste_de_colisao_entre_vizinhos(render):
    """A decisao tem de comparar as CAIXAS dos dois rotulos, nao so o indice."""
    assert "larg(linhas[b].rotulo)" in render and "larg(linhas[a].rotulo)" in render


# ── comportamento, nao texto-fonte ──────────────────────────────────────────
#
# As duas asserçoes abaixo eram sobre o CODIGO ESCRITO (`idx.splice(k,1)`,
# `if(idx[idx.length-1]!==n-1) idx.push(n-1);`) e quebraram na conversao para
# ECharts sem que a regra tivesse mudado: so o espacamento era outro. Um teste
# que quebra quando nada quebrou treina quem mantem a ignora-lo.
#
# Agora medem o que a regra PROMETE, no grafico desenhado: o ultimo rotulo
# aparece, e quem sai na colisao e o vizinho da ESQUERDA.

SEMANAS = [
    {"rotulo": f"SEM {k+1:02d}", "saldo_inicial": 0.0, "entradas": 0.0,
     "saidas": 0.0, "saldo_final": 1_000_000.0 - 20_000.0*k,
     "necessidade": 0.0, "sem_receber": False}
    for k in range(26)
]


@pytest.fixture
def eixo(pagina):
    """Desenha o Fluxo consolidado com 26 semanas e devolve os rotulos vistos.

    26 semanas com passo 2 e o caso que originou a regra: o indice 25 (ultimo)
    nao cai no passo, entao ele e acrescentado a lista e passa a colidir com o
    24 -- rotulos de ~43 px em bandas de ~33 px.
    """
    import json
    pg, base = pagina
    pg.set_viewport_size({"width": 1500, "height": 900})
    pg.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"nome": "T", "email": "t@s.local", "admin": True,
                         "perfil": "Administrador", "telas": []}
                        if "/api/auth/me" in r.request.url else {})))
    pg.goto(f"{base}/static/index.html#fluxcon")
    pg.wait_for_timeout(1200)
    pg.evaluate("(linhas) => chartFcRender(linhas)", SEMANAS)
    pg.wait_for_timeout(1800)
    return " ".join(pg.inner_text("#chartFc").split())


def test_o_ultimo_periodo_sempre_aparece(eixo):
    """E o fim do horizonte -- o rotulo que se procura no grafico."""
    assert "SEM 26" in eixo, (
        f"o ultimo periodo sumiu do eixo. Rotulos vistos: {eixo!r}")


def test_na_colisao_quem_sai_e_o_vizinho_da_ESQUERDA(eixo):
    """A prioridade e do ultimo: 25 e 26 nao cabem lado a lado, e quem cede e
    o 25."""
    assert "SEM 25" not in eixo, (
        "o penultimo rotulo ficou colado no ultimo -- e o borrao que a regra "
        f"existe para evitar. Rotulos vistos: {eixo!r}")


def test_o_eixo_nao_desenha_todos_os_26(eixo):
    """Se nenhum fosse descartado, nao haveria regra nenhuma sendo aplicada e
    os dois testes acima passariam por acidente."""
    vistos = [s for s in SEMANAS if s["rotulo"] in eixo]
    assert len(vistos) < len(SEMANAS), (
        "todos os 26 rotulos foram desenhados: a selecao nao rodou")
