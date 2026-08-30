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


# ── cobertura: o documento não pode mentir em silêncio ──────────────────────
#
# `docs/RECONCILIACAO.md` lista o que é conferido, e é o critério 2 do 1.0.0.
# Sem um teste amarrando a lista ao script, alguém remove uma checagem e o
# documento passa a afirmar uma cobertura que não existe — a mesma família do
# conferidor que se cala.

FONTE = (Path(__file__).resolve().parents[2] / "scripts"
         / "conferir_numeros.py").read_text(encoding="utf-8")

# Trechos que TÊM de continuar no script. Não é a lista inteira: são as
# conferências que, se sumirem, deixam passar um erro que já aconteceu ou que
# decide dinheiro.
EXIGIDAS = [
    ("Saldo inicial", "o defeito de R$ 914 mil entre Visão Geral e Fluxo"),
    ("Km total = carregado + vazio", "base de todo CKM e retorno vazio"),
    ("Receita liquida = bruta - deducoes", "a cascata da DRE fechando"),
    ("Atingimento = realizado / meta", "o par que fecha — 96% x 91,3%"),
    ("Realizado = soma da serie diaria", "o cartão x o gráfico da mesma tela"),
    ("Meta acumulada = soma das metas ate hoje", "idem"),
    ("Atingimento do mes na mensagem", "o WhatsApp x a Visão Geral"),
    ("A pagar vencido", "duas definições de vencido"),
]


@pytest.mark.parametrize("trecho,porque", EXIGIDAS)
def test_a_conferencia_continua_no_script(trecho, porque):
    assert trecho in FONTE, (
        f"a conferência '{trecho}' sumiu do conferidor ({porque}). "
        "docs/RECONCILIACAO.md a lista — atualizar os dois, ou nenhum.")


def test_os_TRES_recortes_de_receita_sao_lidos():
    """Critério 3 do 1.0.0. Ler dois dos três deixaria justamente a régua da
    meta de fora — a que já produziu 96% de atingimento onde o real era 91,3%."""
    for campo in ("faturamento_mes", "receita_mes_cte", "realizado_acumulado"):
        assert f'vg.get("{campo}")' in FONTE, campo


def test_a_receita_e_lida_da_VISAO_GERAL_e_nao_do_overview():
    """`get_overview()` é o painel FINANCEIRO e não tem esses campos. Lê-los de
    lá devolvia None e a conferência passava por VACUIDADE — verde sem medir
    nada. Aconteceu em 30/08/2026."""
    assert "q.get_visao_geral()" in FONTE
    assert 'k.get("realizado_acumulado")' not in FONTE


def test_campo_de_receita_AUSENTE_vira_achado():
    """A defesa contra a vacuidade. Sem ela o bloco fica verde quando o campo
    some do payload, que é exatamente o modo de falha que ele já teve."""
    assert "Recorte de receita ausente" in FONTE
    assert "passa por vacuidade" in FONTE


def test_comparacao_de_TEXTO_existe_para_a_mensagem():
    """O que a pessoa LÊ na mensagem é o que importa: dois formatadores
    diferentes para o mesmo valor produzem telas que se contradizem."""
    assert "tol: float | None = TOL" in FONTE
    assert "if tol is None:" in FONTE
