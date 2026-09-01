"""Painel de BI cabe em UMA tela — e a regra só vale enquanto alguém a cobra.

POR QUE ESTE TESTE EXISTE
=========================
A regra é do usuário, de 30/08/2026: painel é visual e se lê **sem rolar**; o
que não couber vai para sub-aba. Ela já foi quebrada antes de ser escrita —
esta casa produziu uma página de 16.000px (CRM) e outra de 8.602px (Custos), e
o que ficava embaixo era tão decisório quanto o topo.

Em 30/08/2026 as 68 telas foram medidas e 23 divididas em sub-abas. Sem um
teste, a próxima tela nasce alta e ninguém repara — porque o sintoma não é um
erro, é rolagem, e rolagem parece normal.

O QUE ELE COBRA, E O QUE ELE NÃO CONSEGUE COBRAR
================================================
Ele mede a tela SEM DADO (a API é dublada), então a altura aqui é o PISO: a
tela real é sempre mais alta. Um piso acima da régua é defeito certo; um piso
abaixo dela não é prova de que a tela cabe cheia. Por isso a segunda asserção,
sobre tabela sem `.tabroll` — é ela que pega o crescimento que este arranjo
não vê.

E ele mede CADA ABA, não a tela: ter aba não é cumprir a regra. Dividir 1.400px
numa aba de 1.300 e outra de 100 não resolveu nada, e a primeira versão do
medidor aprovava exatamente isso.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

pytest.importorskip("playwright.sync_api")
import medir_paineis  # noqa: E402


@pytest.fixture(scope="module")
def medidas():
    return medir_paineis.medir()


def test_nenhuma_aba_passa_da_altura_de_uma_tela(medidas):
    """A régua é a altura útil de uma 1080p com a barra do navegador."""
    altas = [(t, h) for t, h, _, _, _ in medidas
             if h > (medir_paineis.ALTURA_TV if t in medir_paineis.E_TV
                     else medir_paineis.ALTURA_UTIL)]
    assert not altas, (
        "tela(s) que não se leem sem rolar: %s — divida em sub-aba "
        "(scripts/dividir_em_abas.py) ou reduza a altura do gráfico" % altas)


def test_tabela_longa_rola_dentro_do_card(medidas):
    """Sem `.tabroll` a tabela cresce com o dado e leva a página junto — é a
    diferença entre a página de 16.000px do CRM e os 1.700px de hoje.

    O painel de TV fica fora: lá quem limita as linhas é o RENDERIZADOR
    (`slice(0,10)`), e rolagem dentro do card seria inútil numa tela que
    ninguém toca.
    """
    soltas = [(t, n) for t, _, n, _, _ in medidas
              if n > 0 and t not in medir_paineis.E_TV]
    assert not soltas, (
        "tabela(s) sem .tabroll — crescem sem limite quando o dado chega: %s"
        % soltas)


def test_nenhuma_aba_rola_na_horizontal(medidas):
    """Barra de rolagem INFERIOR é o irmão mudo da tela alta: a página fica
    mais larga que a janela e o card da direita nasce FORA da tela, sem erro
    nenhum. Aconteceu na aba Risco por viagem do GR (v0.207.0): duas tabelas
    de 9 e 8 colunas `nowrap` lado a lado numa `.grid2` cujo `1fr` não
    encolhe abaixo do min-content — 1.596px numa grade de 1.224. A régua de
    altura passava; ninguém medía largura.

    O painel de TV fica fora: é desenhado para 1920 e aqui a janela é 1500.
    """
    largas = [(t, w) for t, _, _, _, w in medidas
              if w > 0 and t not in medir_paineis.E_TV]
    assert not largas, (
        "tela(s) com rolagem horizontal (px além da janela): %s — o que não "
        "cabe lado a lado vai para sub-aba, e a trilha do grid tem de ser "
        "minmax(0,1fr)" % largas)
