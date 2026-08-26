"""A tela de Fechamento tem de dizer QUANTO do mes ja esta no razao.

Descoberto validando os instantaneos que o proprio sistema guardou. Em
25/08/2026, com 81% do mes corrido: receita 81,1% escriturada, custo variavel
50,5%, custo fixo 44,5%.

E ISSO — nao uma falha do modelo — que faz o intervalo do resultado nao
encolher ao longo do mes. Medido nas 21 fotos de agosto: a amplitude entre
pessimista e otimista do RESULTADO foi de R$ 7,6 mi (dia 4) para R$ 9,9 mi
(dia 25), enquanto a da RECEITA caiu de R$ 1,27 mi para R$ 320 mil. A receita
converge porque e faturada em dia; o resultado nao, porque o custo chega tarde.

Julho e a prova final: na foto de 04/08 o mes aparecia com +R$ 1,73 mi e
fechou em -R$ 945 mil, depois de entrarem R$ 2,2 mi de custo. A previsao
daquele dia (-R$ 257 mil) estava MAIS PERTO do fechamento do que o proprio
"realizado" de entao.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SERVICO = RAIZ / "api" / "previsao" / "servico.py"
HTML = RAIZ / "api" / "static" / "index.html"


@pytest.fixture(scope="module")
def fonte() -> str:
    return SERVICO.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return HTML.read_text(encoding="utf-8")


def test_a_escrituracao_e_calculada_no_mes_CORRENTE(fonte):
    """Antes so era calculada no modo "fechando" e vinha NULA no mes corrente —
    justamente quando a pergunta importa. A tela mostrava "resultado previsto"
    sem dizer se falava de um mes quase escriturado ou de metade de um."""
    i = fonte.index("consolidacao = _consolidado(None)")
    trecho = fonte[max(0, i - 600):i]
    assert 'modo == "fechando"' not in trecho, (
        "o calculo nao pode voltar a ficar atras de um teste de modo")


def test_a_escrituracao_e_quebrada_POR_BLOCO(fonte):
    """O total esconde o que interessa: um mes 64% escriturado POR IGUAL e
    confiavel; com receita em 81% e custo em 45% nao e, tendo o mesmo total."""
    assert "consolidacao_blocos" in fonte
    for bloco in ("receita", "custo_variavel", "custo_fixo"):
        assert f'"{bloco}"' in fonte


def test_avisa_quando_o_custo_esta_atras_da_receita(fonte):
    """Vinte pontos de distancia ja bastam para o resultado virar de sinal
    quando o razao alcancar."""
    assert "_cr - _cf > 0.20" in fonte
    i = fonte.index("_cr - _cf > 0.20")
    aviso = fonte[i:i + 700]
    assert "PIORAR" in aviso, "o aviso tem de dizer para que lado o numero anda"


def test_o_semaforo_olha_a_DISTANCIA_e_nao_o_total(html):
    """Um mes 60% escriturado por igual e confiavel; um com receita 81% e custo
    45% nao e, mesmo tendo total parecido. O semaforo do cartao mede a
    distancia entre os dois."""
    i = html.index("function fechClasse(")
    corpo = html[i:i + 500]
    assert "b.receita - menor" in corpo
    assert "custo_variavel" in corpo and "custo_fixo" in corpo


def test_o_cartao_existe_e_explica_o_fenomeno(html):
    i = html.index("kpi('Mês escriturado'")
    bloco = html[i:i + 1200]
    assert "consolidacao_pct" in bloco and "consolidacao_blocos" in bloco
    # o tooltip precisa contar POR QUE isso importa, com o caso concreto
    assert "julho" in bloco.lower() and "945" in bloco


def test_percentual_sem_dado_nao_vira_zero(html):
    """Bloco sem previsto devolve None; imprimir 0% diria "nada escriturado"
    sobre algo que so nao foi medido."""
    i = html.index("function fechPct(")
    assert "v==null ? '—'" in html[i:i + 200]
