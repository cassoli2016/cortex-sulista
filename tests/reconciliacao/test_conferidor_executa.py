"""O conferidor tem de RODAR, nao so conter as linhas certas.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR, achado em 06/09/2026:

`scripts/conferir_numeros.py` e a prova do CRITERIO 2 do `1.0.0` -- "o mesmo
conceito da o mesmo numero em todas as telas". Ele estava MORRENDO com
`KeyError: 'kpis'` desde 02/09, quando o payload das Ordens de Compra desceu um
nivel (`oc["kpis"]` virou `oc["sem_nota"]["kpis"]`, v0.210.0).

Quatro dias quebrado, calado. E o que morre junto e pior que o proprio bloco de
OC: tudo o que vem DEPOIS dele nunca rodava -- a cascata da DRE, a mensagem de
faturamento do WhatsApp e **os tres recortes de receita**, que sao o criterio 3
do mesmo `1.0.0`. O `CLAUDE.md` seguia dizendo "hoje sem divergencia" sobre um
verificador que nao chegava ao fim.

POR QUE NINGUEM VIU: o guard que existia (`test_a_conferencia_continua_no_script`)
le o TEXTO-FONTE e confere que a linha da checagem continua escrita. Ela
continuava -- so nao executava. E o classico verde que nunca ficaria vermelho:
protege contra alguem APAGAR a checagem, e nao contra ela QUEBRAR.

ESTE TESTE CUSTA UM ERP e uns minutos, e vale: e a unica forma de pegar
mudanca de forma de payload, que e como o conferidor quebra na vida real. Pula
quando o ERP nao responde -- ausencia de infraestrutura nao e falha de codigo.

O QUE ELE NAO FAZ: falhar por DIVERGENCIA. Divergencia e o produto do script e
uma conversa de negocio (recorte diferente, ou bug de regra); transformar isso
em teste vermelho tornaria a suite refem do dado do dia.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))


@pytest.fixture(scope="module")
def erp_responde():
    """Sem ERP nao ha o que conferir -- e dizer por que, em vez de falhar."""
    try:
        from api import db
        db.query("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ERP inacessivel ({type(exc).__name__})")
    return True


def test_o_conferidor_roda_ate_o_fim(erp_responde, capsys):
    """A prova do criterio 2 precisa CHEGAR AO FIM.

    Qualquer excecao aqui e a mesma familia do `KeyError: 'kpis'`: alguem mudou
    a forma de um payload e o conferidor ficou para tras, em silencio.
    """
    import conferir_numeros as cn

    try:
        codigo = cn.main()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"o conferidor morreu no meio ({type(exc).__name__}: {exc}). "
            "E a prova do criterio 2 do 1.0.0 -- e tudo o que vem depois do "
            "ponto da quebra deixa de ser conferido, inclusive os tres "
            "recortes de receita.")

    saida = capsys.readouterr().out
    assert "RECEITA: os tres recortes" in saida, (
        "o conferidor terminou sem chegar ao bloco das tres receitas")
    assert "MENSAGEM DE FATURAMENTO" in saida, (
        "o conferidor terminou sem conferir a mensagem que sai da empresa")
    assert isinstance(codigo, int), "main() deixou de devolver codigo de saida"


def test_as_secoes_do_criterio_1_0_0_estao_todas_na_saida(erp_responde, capsys):
    """As secoes que o `docs/RECONCILIACAO.md` promete.

    Separado do teste acima de proposito: aquele garante que NAO MORREU, este
    garante que nao encolheu. Um `return` cedo passaria no primeiro.
    """
    import conferir_numeros as cn

    cn.main()
    saida = capsys.readouterr().out
    for secao in ("SALDO BANCARIO", "A RECEBER / A PAGAR EM ABERTO",
                  "FLUXO CONSOLIDADO", "ANTECIPACAO", "KM:",
                  "ORDENS DE COMPRA", "DRE: cascata fecha",
                  "RECEITA: os tres recortes", "MENSAGEM DE FATURAMENTO",
                  "VENCIDOS"):
        assert secao in saida, f"a secao '{secao}' sumiu do conferidor"
