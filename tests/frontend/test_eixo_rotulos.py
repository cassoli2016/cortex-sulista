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


def test_a_prioridade_e_do_ultimo_periodo(render):
    """Quando dois colidem, quem sai e o da ESQUERDA: o fim do horizonte e o
    rotulo que se procura no grafico."""
    m = re.search(r"for\(let k=idx\.length-2;k>=0;k--\)\{(.*?)\n  \}", render, re.S)
    assert m, "laco de colisao nao encontrado"
    assert "idx.splice(k,1)" in m.group(1), "deveria remover o vizinho da esquerda"


def test_o_ultimo_periodo_sempre_entra_na_lista(render):
    assert "if(idx[idx.length-1]!==n-1) idx.push(n-1);" in render
