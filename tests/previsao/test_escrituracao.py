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


# ------------------------------------------------------------------- LOP 1
def test_o_lop1_vem_com_ancora_historica(fonte):
    """"-1,4 mi" nao decide nada sozinho. Com a mediana ao lado vira "4,6x pior
    que o mes tipico", que decide."""
    assert '"mediana_hist"' in fonte and '"vs_mediana"' in fonte


def test_a_ancora_e_MEDIANA_e_nao_media(fonte):
    """Maio fechou +R$ 1,98 mi contra uma faixa de -666k a +18k nos outros
    cinco. A media sobe para +17k por causa de um unico mes e passa a
    impressao de operacao equilibrada; a mediana (-295k) descreve o tipico."""
    i = fonte.index("def _kpi_lop1(")
    corpo = fonte[i:i + 1400]
    assert "motor.mediana(hist)" in corpo
    assert "MEDIANA e nao media" in corpo


def test_o_historico_do_lop1_usa_A_MESMA_cascata(fonte):
    """Recalcular a formula a mao criaria duas definicoes de LOP 1 que um dia
    divergiriam — e a comparacao passaria a medir a diferenca entre elas."""
    i = fonte.index("lop1_hist: list[float] = []")
    assert "motor.montar_cascata(diretas_m)" in fonte[i:i + 600]


def test_multiplo_so_existe_com_os_dois_do_mesmo_sinal(fonte):
    """Dividir -1,3 mi por um historico positivo produz um multiplo sem
    significado nenhum."""
    i = fonte.index('"vs_mediana"')
    assert "(med < 0) == (ln[\"previsto\"] < 0)" in fonte[i:i + 300]


def test_o_semaforo_do_lop1_compara_com_a_mediana_e_nao_com_zero(html):
    """Prejuizo operacional e o normal nesta operacao: 5 dos 6 meses fecharam
    negativo. Vermelho por ser negativo diria alarme todo mes, e ai ninguem
    mais olha."""
    i = html.index("function fechLop1Classe(")
    corpo = html[i:i + 600]
    assert "l.vs_mediana >= 2" in corpo
    assert "mediana_hist==null" in corpo, "sem historico nao pode inventar cor"


def test_o_cartao_diz_o_que_o_lop1_NAO_inclui(html):
    """Sem isso alguem compara LOP 1 com resultado do exercicio e acha que um
    dos dois esta errado."""
    i = html.index("kpi('Resultado operacional (LOP 1)'")
    bloco = html[i:i + 1100]
    assert "NÃO inclui resultado financeiro" in bloco
