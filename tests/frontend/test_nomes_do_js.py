"""As declarações de JS que um corte já levou — e que não podem sumir de novo.

O QUE ACONTECEU
===============
Um único corte na conversão para ECharts (v0.144.0) levou junto três linhas de
declaração, e três telas ficaram quebradas por meses:

  `leafletPromise`  → o MAPA da Torre de Controle
  `DRECLI_LINHAS`   → a tabela da DRE por Cliente
  `MVB_COMP_LBL`    → a composição do Make vs Buy

O SINTOMA É MUDO. `ensureLeaflet` LÊ `leafletPromise` na primeira linha; ler
nome não declarado é `ReferenceError`, que estoura dentro do `try` do loader e
vira banner genérico ou — no caso do mapa — um retângulo cinza com o texto da
exceção em letra miúda. Passa por "hoje não carregou".

E note a assimetria que tornou isso difícil de rastrear: das TRÊS variáveis
perdidas na mesma linha, só uma deu erro. `torreMap` e `torreLayer` são apenas
ATRIBUÍDOS, e atribuir a nome não declarado cria global implícita — funciona.
Só a LEITURA estoura.

POR QUE ESTE TESTE É UMA LISTA, E NÃO UM ANALISADOR
===================================================
A primeira tentativa foi um varredor genérico: para todo identificador lido,
exigir que estivesse declarado. Ele devolveu **1.939 achados**; estreitado só
para constantes em CAIXA ALTA, ainda **102** — siglas de comentário (API, ERP,
CKM), hexadecimais de cor (F87171), palavras em português (POR, SEM, MAIOR).

Escopo de JavaScript com expressão regular não fecha: templates aninhados,
`//` dentro de URL em string, destruturação, parâmetros. Cada rodada de ajuste
trocava um falso positivo por outro, e **relatório com falso positivo é
relatório que alguém desliga na primeira semana** — aí não sobra guarda nenhuma.
Parei e fiquei com o que é confiável.

O QUE COBRE O QUE, HOJE
=======================
1. Esta lista: os nomes que JÁ se perderam uma vez não podem sumir de novo. É
   estreita e não erra.
2. `test_torre_mapa.py`: o mapa realmente carrega, num navegador, offline — e
   isso só ficou possível porque o Leaflet foi vendorizado junto.
3. A regra da casa em CLAUDE.md: depois de todo corte grande, comparar as
   declarações contra o HEAD do git e exigir `sumiram: nenhuma`. É ela que
   pega o caso GERAL; foi não tê-la seguido que criou este arquivo.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
HTML = (RAIZ / "api" / "static" / "index.html").read_text(encoding="utf-8")

# Nome → o que quebra sem ele. A segunda coluna é o que faz alguém entender a
# falha em vez de só reintroduzir a linha sem saber por quê.
JA_SE_PERDERAM = {
    "leafletPromise": "o mapa da Torre de Controle (ReferenceError engolido "
                      "pelo catch de torreMapa, que vira um retângulo cinza)",
    "torreMap": "a instância do mapa da Torre — sem ela cada recarga de 2 min "
                "tentaria criar um mapa novo",
    "torreLayer": "a camada de marcadores da Torre",
    "DRECLI_LINHAS": "as linhas da tabela da DRE por Cliente",
    "MVB_COMP_LBL": "os rótulos da composição de custo do Make vs Buy",
    # os nove da cauda de outro corte, que deixaram a ANTT com a tabela vazia
    "fmtKm": "a formatação de km na ANTT e na telemetria",
    "fmtRsKm": "a formatação de R$/km",
    "TELCON_SIT": "os rótulos de situação da Consumo e Estatísticas",
    "UT_LBL": "os rótulos de utilização de veículo",
    "MOD_COR": "as cores por modalidade",
    "fmtL": "a formatação de litros",
    "fmtKmL": "a formatação de km/l",
    "compLabel": "o rótulo de competência",
}


def _script() -> str:
    """O maior bloco <script> — o app. O outro é o carimbo do tema."""
    return max(re.findall(r"<script>(.*?)</script>", HTML, re.S), key=len)


def _declarado(js: str, nome: str) -> bool:
    """Aceita a forma MÚLTIPLA (`let a=1, b=2, c=3;`), que foi exatamente a que
    se perdeu — uma checagem que só olhasse `let <nome>` daria falso negativo
    nos dois últimos nomes da linha."""
    if re.search(r"^\s*(?:async\s+)?function\s+" + re.escape(nome) + r"\b", js, re.M):
        return True
    for m in re.finditer(r"\b(?:const|let|var)\s+([^;\n]+)", js):
        for parte in m.group(1).split(","):
            if parte.split("=")[0].strip() == nome:
                return True
    return False


def test_os_nomes_que_ja_se_perderam_CONTINUAM_declarados():
    js = _script()
    faltando = {n: p for n, p in JA_SE_PERDERAM.items() if not _declarado(js, n)}
    assert not faltando, (
        "declaração perdida de novo — cada uma quebra uma tela em silêncio, "
        "porque o ReferenceError é engolido pelo try/catch do loader:\n  "
        + "\n  ".join("%s → %s" % (n, p) for n, p in sorted(faltando.items())))


def test_a_checagem_ENXERGA_declaracao_multipla():
    """`let leafletPromise=null, torreMap=null, torreLayer=null;` era UMA linha
    com três nomes. Uma checagem ingênua acharia só o primeiro e daria os
    outros dois como perdidos — enchendo o relatório de falso positivo."""
    js = "let leafletPromise=null, torreMap=null, torreLayer=null;"
    for n in ("leafletPromise", "torreMap", "torreLayer"):
        assert _declarado(js, n), n


def test_a_checagem_ESTA_MEDINDO():
    """Verde que não mede é pior que vermelho — o defeito que esta casa já
    pegou três vezes."""
    assert not _declarado("function f(){ return NOME_FANTASMA; }", "NOME_FANTASMA")
