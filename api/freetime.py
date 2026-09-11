"""A REGRA DO FREETIME — uma só, em dois sotaques.

O contrato (`sulista.sac_freetimecliente`) tem UMA LINHA POR TIPO DE
MERCADORIA, e um cliente pode ter várias ativas ao mesmo tempo, TODAS com o
mesmo `dtinicio`. Medido em 10/09/2026:

    IOCHPE MAXION   4 linhas, mesma data: genérica 3h · CONJUNTOS/RODAS/
                    ESCADAS 6,5h
    LEAR            4 linhas, mesma data: PEÇAS e EMBALAGENS 3h · ESPUMA 5h
    VOLVO           2 linhas, datas DIFERENTES (1h -> 2h) — isso é revisão de
                    contrato, e aí a mais nova manda mesmo

Duas telas leem esse contrato e cada uma tinha inventado a própria saída:

  · `sac` (`api/queries.py`) escolhia UMA linha com `DISTINCT ON … ORDER BY
    dtinicio DESC`. Com as datas empatadas o banco escolhe AO ACASO — e o
    `valor_est` multiplica a hora excedente pelo valor contratado, então o
    sorteio mexia em DINHEIRO.
  · `cliop` (`api/portal_cliente.py`) recusava escolher e publicava uma FAIXA:
    dentro do menor freetime é aderente sob qualquer cláusula, acima do maior
    é excedente sob qualquer cláusula, no meio "depende da mercadoria".
    Honesto, e caro: a zona cinzenta engolia a leitura inteira.

A saída não era escolher melhor entre as duas — era parar de precisar
escolher. `coleta.mercadorias` está preenchida em **100%** das 17.269 coletas
de 180 dias (80 valores distintos) e usa o MESMO vocabulário do contrato.
A permanência é medida NA COLETA, e a coleta sabe o que carregou.

ESTE MÓDULO É A REGRA, e existe para que ela seja UMA. `api/queries.py` a
executa em SQL (a estimativa do SAC roda inteira no ERP, sobre milhares de
linhas) e `api/portal_cliente.py` a executa em Python (ali as linhas já vêm
para casa de qualquer jeito). São duas execuções do MESMO texto: a tabela de
acentos é uma, a ordem de resolução é uma, e
`tests/test_freetime_regra.py` prova que os dois sotaques dizem a mesma coisa.
Duas cópias da regra é como as duas telas passaram a discordar em primeiro
lugar.
"""
from __future__ import annotations

# A TABELA DE ACENTOS, e por que não é `unaccent`: a extensão não está
# instalada no ERP (PostgreSQL 9.3, réplica somente leitura), e pedir
# instalação de extensão num banco de TERCEIRO para normalizar texto é caro
# demais para o tamanho do problema. `translate` é nativo e faz o suficiente.
DE = "ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ"
PARA = "AAAAAEEEEIIIIOOOOOUUUUC"
assert len(DE) == len(PARA), "a tabela de acentos ficou torta"


def sql_normalizar(coluna: str) -> str:
    """A normalização, em SQL, para casar contrato × coleta dentro do ERP.

    Maiúscula, sem acento, e o S final de cada palavra fora — o contrato
    escreve "ESPUMA PARA BANCOS" e a coleta "ESPUMAS PARA BANCO"; um lado tem
    "PEÇAS" com cedilha e o outro "PECAS" sem. É a mesma mercadoria, e um `=`
    cru diz que não.

    É POUCO DE PROPÓSITO. O que ela NÃO faz é aproximar "CONJUNTO PHEVUS" de
    "CONJUNTOS" — são 382 coletas da Maxion em 180 dias, e decidir que são a
    mesma mercadoria muda o freetime de 3h para 6,5h. Isso é decisão
    COMERCIAL, de quem negocia o contrato, não de uma heurística de texto
    escondida numa query. Elas caem na linha genérica, e a tela DIZ que foi a
    genérica que respondeu — que é como a pergunta chega a quem pode
    respondê-la.
    """
    # A ORDEM IMPORTA, e o espaço interno é o passo que quase ficou de fora:
    # `btrim` só tira das pontas, e "ESPUMA  PARA  BANCOS" com espaço dobrado
    # no cadastro não casaria com a mesma mercadoria escrita direito. O guard
    # que executa os dois sotaques lado a lado (`tests/test_freetime_regra.py`)
    # foi quem achou — o Python colapsava e o SQL não, e nenhuma leitura do
    # texto das duas implementações teria mostrado isso.
    return (r"regexp_replace(regexp_replace(translate(upper(btrim("
            r"coalesce(%s,''))), '%s', '%s'), '\s+', ' ', 'g'),"
            r" 'S(\s|$)', '\1', 'g')" % (coluna, DE, PARA))


def normalizar(texto: str | None) -> str:
    """A mesma normalização, em Python. Mesmo texto, mesmo resultado.

    O `regexp_replace` do Postgres com a flag `g` aplica a substituição a cada
    ocorrência de "S seguido de espaço ou fim"; aqui isso é o mesmo que tirar
    o S final de cada palavra. Não se usa `unicodedata` para o acento: a
    tabela tem de ser a MESMA que o SQL usa, senão os dois lados divergem
    justamente nas letras que a tabela não cobre.
    """
    t = " ".join((texto or "").upper().split())
    t = t.translate(str.maketrans(DE, PARA))
    return " ".join(p[:-1] if p.endswith("S") else p for p in t.split())


# A ORDEM DE RESOLUÇÃO, que é a regra propriamente dita.
MERCADORIA = "mercadoria"
GENERICO = "generico"
SEM_CLAUSULA = "sem_clausula"


def resolver(linhas: list[dict], mercadoria: str | None) -> dict | None:
    """A cláusula que vale para esta coleta: da mercadoria, senão a genérica.

    `linhas` são as linhas ATIVAS do contrato do cliente, cada uma com a chave
    `mercadoria` (vazia = cláusula genérica). Devolve a linha escolhida com
    `origem` acrescentada, ou `None` quando não há contrato nenhum.

    QUANDO NADA CASA E NÃO HÁ GENÉRICA, o último recurso é o MAIOR freetime, e
    a escolha não é neutra: com o maior, só vira excedente a hora que excede
    sob QUALQUER cláusula do contrato — a estimativa passa a ser um PISO do que
    se pode afirmar sem saber a mercadoria. O contrário (o menor) inflaria a
    cobrança com horas que talvez estivessem contratadas, e estimativa que erra
    para cima é a que ninguém confere até o cliente contestar.

    `origem` volta junto porque a tela precisa dizer QUAL das três respondeu:
    "3h porque o contrato diz 3h para RODAS" e "3h porque não há cláusula para
    esta mercadoria" são afirmações diferentes, e a segunda é a única que
    alguém precisa ir resolver.
    """
    if not linhas:
        return None
    alvo = normalizar(mercadoria)
    if alvo:
        for ln in linhas:
            if ln.get("mercadoria") and normalizar(ln["mercadoria"]) == alvo:
                return dict(ln, origem=MERCADORIA)
    for ln in linhas:
        if not ln.get("mercadoria"):
            return dict(ln, origem=GENERICO)
    maior = max(linhas, key=lambda ln: (
        ln.get("ft_descarga_h") or 0, ln.get("ft_carga_h") or 0,
        normalizar(ln.get("mercadoria"))))
    return dict(maior, origem=SEM_CLAUSULA)
