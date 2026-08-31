# -*- coding: utf-8 -*-
"""Cartões lado a lado terminam na mesma altura.

O guard existe porque a regra volta sem ele. `.grid2` carregava
`align-items:start` e deixava 17 das 57 linhas de cartão irregulares — a pior
com 250px de diferença, um rasgo branco no meio do painel. Uma linha de CSS
resolveu; uma linha de CSS desfaz.

E ele mede o que `test_espacos.py` NÃO mede: aquele cuida do vão VERTICAL
entre componentes (a escala 9/18/25), e não vê nada de errado numa linha em que
um cartão tem 323px e o vizinho 73 — os dois estão a 18px do de cima, cada um
na sua coluna.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

pytest.importorskip("playwright.sync_api")
import auditar_alinhamento  # noqa: E402


@pytest.fixture(scope="module")
def linhas():
    return auditar_alinhamento.medir()


def test_a_medicao_alcanca_as_linhas_de_cartao(linhas):
    """Sonda que não acha nada passaria por vacuidade.

    Antes de confiar no verde do teste abaixo, este confirma que houve o que
    medir — sem ele, um seletor errado deixaria os dois verdes para sempre.
    """
    assert len(linhas) >= 40, (
        "a sonda achou só %d linhas de cartão; o seletor deve ter mudado"
        % len(linhas))


def test_cartoes_lado_a_lado_terminam_na_mesma_altura(linhas):
    """`align-items:start` num grid de cartões deixa o fundo da linha irregular.

    O padrão do CSS grid é `stretch`, e ele é o certo aqui: a altura da linha já
    é a do cartão mais alto de qualquer forma, então esticar o menor alinha o
    fundo sem crescer a tela — foi conferido contra a régua de uma tela.
    """
    ruins = [(a["tela"], a["aba"], a["alturas"], a["delta"]) for a in linhas
             if a["delta"] > auditar_alinhamento.TOLERANCIA]
    assert not ruins, (
        "linha(s) de cartão com fundo irregular: %s" % ruins[:10])
