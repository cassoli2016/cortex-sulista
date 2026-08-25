"""Lógica do comparador de `scripts/conferir_numeros.py`.

O script em si fala com o AVA e leva minutos; aqui se garante o que ele NÃO
pode errar: deixar passar divergência, ou pular uma conferência em silêncio.
Na primeira versão o bloco da DRE lia um campo que não existe (`valor` em vez
de `total`) e sumiu inteiro sem uma linha de aviso — um conferidor que se cala
é pior que nenhum, porque dá a sensação de que está tudo conferido.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import conferir_numeros as cn  # noqa: E402


@pytest.fixture(autouse=True)
def _limpa():
    cn.ACHADOS.clear()
    yield
    cn.ACHADOS.clear()


def test_iguais_nao_viram_achado():
    cn.conferir("x", "a", 100.0, "b", 100.0)
    assert cn.ACHADOS == []


def test_diferenca_de_um_centavo_ja_e_achado():
    """Divergência real nunca é arredondamento: os dois lados vêm da mesma
    base, então centavo a mais é regra diferente."""
    cn.conferir("x", "a", 100.00, "b", 100.02)
    assert len(cn.ACHADOS) == 1
    assert cn.ACHADOS[0][0] == "DIVERGE"


def test_none_vira_achado_e_nao_passa_batido():
    """Campo ausente era o modo de falha REAL do script: ler o nome errado
    devolvia None e a comparação sumia."""
    cn.conferir("x", "a", None, "b", 10.0)
    assert len(cn.ACHADOS) == 1
    assert cn.ACHADOS[0][0] == "VAZIO"

    cn.ACHADOS.clear()
    cn.conferir("x", "a", 10.0, "b", None)
    assert len(cn.ACHADOS) == 1


def test_soma_de_partes_confere_com_o_total():
    cn.conferir_soma("x", 300.0, [100.0, 200.0], rotulo_partes="linhas")
    assert cn.ACHADOS == []


def test_parte_faltando_na_soma_e_achado():
    """É o caso 'coluna zerada com KPI cheio': o total existe e o detalhe não
    fecha — quase sempre JOIN quebrado, não negócio."""
    cn.conferir_soma("x", 300.0, [100.0, 0.0], rotulo_partes="linhas")
    assert len(cn.ACHADOS) == 1


def test_parte_nula_conta_como_zero_e_nao_explode():
    cn.conferir_soma("x", 100.0, [100.0, None], rotulo_partes="linhas")
    assert cn.ACHADOS == []


def test_tolerancia_maior_e_respeitada():
    cn.conferir("x", "a", 100.0, "b", 100.04, tol=0.05)
    assert cn.ACHADOS == []


def test_percentual_aparece_no_detalhe():
    """Quem lê o relatório precisa saber se são centavos ou 40% do número."""
    cn.conferir("x", "a", 100.0, "b", 150.0)
    assert "33.3%" in cn.ACHADOS[0][2] or "33,3" in cn.ACHADOS[0][2]
