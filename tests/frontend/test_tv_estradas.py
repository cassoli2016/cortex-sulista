"""Condição da estrada no painel de TV da Operação.

O QUE ESTA TELA JÁ TINHA, E POR QUE NÃO BASTAVA
===============================================
O ticker já mostrava ocorrência de trânsito, mas de uma REGIÃO: bboxes fixas,
incidentes em rodovia numerada, filtrados por gravidade. É contexto — não diz
nada sobre onde os NOSSOS caminhões estão.

O pedido era outro: a situação das estradas que os veículos estão rodando. Isso
vem do servidor (`/api/operacao/torre/estradas`), que consulta o trecho onde
cada viagem em curso está agora.

AS REGRAS DE TV QUE ISTO OBEDECE
================================
- **Não existe tooltip.** O badge precisa dizer QUANTO se está perdendo, senão
  "TRÂNSITO" é um aviso que não decide nada. Em MINUTOS — segundo é a unidade
  da API, não a de quem liga para o motorista.
- **Ordem de precedência é decisão:** ATRASADA vence tudo (o prazo já passou, é
  fato e não previsão); depois o TRÂNSITO, que é onde ainda dá para agir.
- **O número grande vem com o denominador:** "2 de 69", nunca "2".
- **A TomTom fora não pode apagar a tabela de chegadas**, que é o que a torre
  olha o dia inteiro.

E O CUSTO, que é uma regra de projeto e não um detalhe: a TV recarrega a cada
60 s e roda sozinha o dia todo. Ela pede `tolerancia=1200` — tolera 20 min de
atraso na leitura — porque com o TTL de 10 min da Torre só ela dispararia ~6
varreduras por hora, ~5.000 chamadas num dia de 12 h, e o teto do plano da
TomTom não é observável na resposta.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "api" / "static"
        / "index.html").read_text(encoding="utf-8")


def _fn(nome: str) -> str:
    i = HTML.index("function " + nome + "(")
    return HTML[i:i + 1400]


def test_a_TV_tolera_leitura_mais_VELHA_que_a_torre():
    """Sem isto o painel de TV passa a ditar o consumo da TomTom: ele recarrega
    a cada 60 s e roda o dia inteiro, enquanto a Torre é aberta por alguém."""
    assert "tolerancia=1200" in HTML, (
        "a TV precisa pedir tolerância maior — senão dispara a varredura a cada "
        "10 min o dia todo")


def test_a_TV_nao_dispara_coleta_PROPRIA():
    """Um segundo caminho de coleta divergiria do da Torre e dobraria o gasto —
    é o defeito dos dois armazéns de parâmetro da premiação, com API externa
    no meio."""
    i = HTML.index("async function loadTvOpe(")
    bloco = HTML[i:i + 9000]
    assert "forcar=1" not in bloco and "forcar: true" not in bloco


def test_o_badge_diz_QUANTOS_MINUTOS():
    """Em TV não há tooltip: "TRÂNSITO" sozinho é um aviso que não decide
    nada."""
    fn = _fn("tvBadgeChegada")
    assert "min" in fn and "atraso_s" in fn
    assert "/ 60" in fn, "tem de converter para minutos — segundo é a unidade da API"


def test_ATRASADA_vence_o_transito():
    """O prazo já vencido é FATO; o trânsito é previsão. Trocar a ordem faria
    uma viagem já atrasada aparecer como se o problema fosse a estrada."""
    fn = _fn("tvBadgeChegada")
    i_atr = fn.index("v.atrasada")
    i_tr = fn.index("tr.estado")
    assert i_atr < i_tr, "o teste de atrasada tem de vir primeiro"


def test_LIVRE_e_ND_nao_viram_badge_de_problema():
    """`nd` é "sem medida confiável" — pintá-lo de vermelho seria inventar
    estado a partir de "não sei"."""
    fn = _fn("tvBadgeChegada")
    assert "'livre'" in fn and "'nd'" in fn


def test_o_resumo_do_ticker_traz_o_DENOMINADOR():
    """"2 de 69" decide; "2" sozinho não."""
    i = HTML.index("em trânsito ruim")
    trecho = HTML[i - 300:i + 200]
    assert "medidos" in trecho and "com_problema" in trecho


def test_o_badge_AMBAR_existe_no_CSS():
    """`.tv-badge.warn` não existia: o estado "lento" sairia sem fundo nenhum,
    invisível numa TV vista de longe — que é o único jeito de ver essa tela."""
    assert re.search(r"\.tv-badge\.warn\{[^}]*background:", HTML)


def test_a_falha_da_TOMTOM_nao_apaga_a_tabela():
    """A tabela de chegadas é o que a torre olha o dia inteiro."""
    i = HTML.index("tolerancia=1200")
    trecho = HTML[i:i + 700]
    assert "catch" in trecho, "a busca tem de ter catch próprio"
    assert "tvope-cheg" in HTML[i:i + 2000], (
        "a tabela é montada depois, e não dentro do try da TomTom")
