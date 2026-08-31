"""Superfície clara sem contraparte no tema escuro.

O DEFEITO QUE ORIGINOU ISTO (30/08/2026)
========================================
TODO modal do sistema, o menu do avatar e o card de login apareciam BRANCOS no
tema escuro, com o texto `#E9EEF4` por cima: contraste **1,06:1**, ilegível.
Medido, não suposto. Mesma família: o mapa ampliado do Milk run, os cards da
Gestão, o `.ppl-niv` do RH, o code do Copiloto, as linhas da contrapartida e os
chips do WhatsApp.

POR QUE A AUDITORIA DE TEMA NÃO PEGAVA
======================================
`scripts/auditar_tema.py` varre o que está NA TELA, e essas superfícies só
aparecem depois de um clique. Ela deu "0 achados em 68 telas" com o defeito na
tela — verde por vacuidade, que nesta casa é pior que conferência nenhuma.

E POR QUE ESTA VERSÃO É CONFIÁVEL
=================================
Duas tentativas anteriores devolviam ZERO com o defeito reposto de propósito:

1. um parser por regex sobre o texto do `<style>` — jogado fora em vez de ficar
   dando falso verde;
2. a leitura do CSSOM, que falhava por duas razões que só a sabotagem revelou:
   `CSSRuleList` não é iterável com `for...of` no Chrome (e o `try/catch` de
   fora engolia), e **`CSSStyleRule` também tem `cssRules`** desde o CSS
   aninhado — vazio, mas TRUTHY, então `if(r.cssRules) continue` pulava as
   1.003 regras de estilo do arquivo.

Antes de confiar num verde, sabotar o alvo e ver o teste falhar. Custa trinta
segundos e foi o que separou a versão que funciona das duas que não.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

pytest.importorskip("playwright.sync_api")
import auditar_superficies  # noqa: E402


def test_toda_superficie_clara_tem_contraparte_no_tema_escuro():
    """Cor de FUNDO clara escrita à mão não vira quando o tema vira, e o
    resultado é uma caixa branca com o texto claro do tema escuro por cima.

    Quem usa token (`var(--n0)`) está certo e não aparece aqui. As exceções
    declaradas em `DELIBERADAS` são brancas nos dois temas de propósito —
    marcador sobre ladrilho de mapa e a chapa da logo no botão de report, que
    existem para se destacar do que está ATRÁS deles, não da página.
    """
    achados = auditar_superficies.medir()
    assert not achados, (
        "superfície(s) clara(s) sem contraparte no escuro — vira caixa branca "
        "com texto claro: %s"
        % [(a["sel"][:60], a["cor"]) for a in achados])
