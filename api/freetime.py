"""A REGRA DO FREETIME — uma só, em dois sotaques.

O contrato (`sulista.sac_freetimecliente`) tem UMA LINHA POR TIPO DE
MERCADORIA, e um cliente pode ter várias ativas ao mesmo tempo, TODAS com o
mesmo `dtinicio`. Medido em 10/09/2026:

    IOCHPE MAXION   4 linhas, mesma data: genérica 3h · CONJUNTOS/RODAS/
                    ESCADAS 6,5h
    LEAR            4 linhas, mesma data: PEÇAS e EMBALAGENS 3h · ESPUMA 5h
    VOLVO           2 linhas em duas FILIAIS: a viva dá 2h e a outra, de 1h,
                    está VENCIDA (`dtfim` 31/08/2024) e continua marcada como
                    ativa — ver `vigente()` logo abaixo

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


# A VIGÊNCIA, e por que ela não é o mesmo que `ativoinativo`.
#
# `ativoinativo` é um campo GRAVADO: alguém tem de entrar no ERP e desligar a
# cláusula. `dtinicio`/`dtfim` são a vigência COMBINADA, e ela vira sozinha.
# A regra da casa é que estado que envelhece sozinho não se grava, se calcula —
# e aqui a diferença tem nome e sobrenome: a VOLVO tem uma cláusula genérica de
# 1h com `dtfim = 31/08/2024` e `ativoinativo = 1` até hoje (medido em
# 11/09/2026). Ninguém a inativou; ela simplesmente acabou.
#
# Filtrar só por `ativoinativo` aplica contrato encerrado. Hoje isso não move
# um centavo (a VOLVO teve UMA coleta em 180 dias, e a cláusula vencida é de
# outra filial), e é exatamente por isso que precisa de guard: o defeito está
# armado e o dia em que ele disparar é o dia em que alguém encerrar a cláusula
# de um cliente com volume.
def sql_vigente(alias: str = "") -> str:
    """O filtro de vigência, com o prefixo da tabela quando houver alias.

    Função e não constante porque uma das consultas usa `ft.` e as outras não:
    encadear `.replace("dtinicio", "ft.dtinicio")` por fora funciona até o dia
    em que uma coluna nova contiver o nome de outra, e aí a substituição acerta
    no meio de uma palavra sem ninguém ver.
    """
    p = (alias + ".") if alias else ""
    return ("{p}ativoinativo = 1\n"
            "    AND ({p}dtinicio IS NULL OR {p}dtinicio::date <= current_date)\n"
            "    AND ({p}dtfim IS NULL OR {p}dtfim::date >= current_date)"
            ).format(p=p)


def vigente(linha: dict, hoje=None) -> bool:
    """A mesma vigência, em Python, para quem já tem a linha na mão."""
    import datetime
    hoje = hoje or datetime.date.today()

    def _d(v):
        if v is None:
            return None
        return v.date() if hasattr(v, "date") else v

    ini, fim = _d(linha.get("dtinicio")), _d(linha.get("dtfim"))
    if linha.get("ativoinativo") not in (None, 1):
        return False
    return not ((ini and ini > hoje) or (fim and fim < hoje))


# O `distingueoperacao` do ERP É UMA SEGUNDA FONTE para "esta cláusula é
# genérica?", e ela concorda com a `observacao` em 24 de 24 linhas ativas
# (medido em 11/09/2026): 1 ⇔ tem mercadoria, 2 ⇔ genérica. Não se usa como
# PRIMÁRIA — a observação é o texto que casa com a coleta —, mas divergência
# entre as duas é cadastro furado, e a tela diz em vez de escolher em silêncio.
DISTINGUE_MERCADORIA = 1
DISTINGUE_GENERICA = 2


def confere_distingue(linha: dict) -> bool:
    """As duas fontes concordam sobre esta linha ser genérica?"""
    d = linha.get("distingueoperacao")
    if d is None:
        return True                     # o ERP não disse nada: nada a conferir
    tem_merc = bool((linha.get("mercadoria") or "").strip())
    return (int(d) == DISTINGUE_MERCADORIA) == tem_merc


def canonizar(mercs) -> tuple:
    """A escolha de mercadorias numa forma ÚNICA: normalizada, sem repetida,
    em ordem.

    Ela existe por causa do CACHE. A chave do `cached` da casa é `repr(args)`,
    então ["RODAS","ESCADAS"] e ["ESCADAS","RODAS"] seriam DUAS entradas para
    a mesma pergunta — duas idas ao ERP e duas cópias do mesmo número
    envelhecendo em ritmos diferentes. Ordenar antes de entrar resolve os dois.

    Normaliza pela mesma régua do casamento com o contrato: quem escolhe
    "PEÇAS" na lista está escolhendo também as coletas escritas "PECAS", e o
    filtro tem de concordar com a lista que ele mesmo ofereceu.

    Aceita string solta (uma só) ou lista; devolve tupla, que é hashável e
    imutável — lista como argumento de função cacheada é a porta para alguém
    mutá-la depois da chamada e o cache passar a mentir.
    """
    if mercs is None:
        return ()
    if isinstance(mercs, str):
        mercs = [mercs]
    vistos = {normalizar(m) for m in mercs if (m or "").strip()}
    return tuple(sorted(v for v in vistos if v))


# ───────────────────────────── AS EQUIVALÊNCIAS DECLARADAS ────────────────
#
# Duas grafias que a normalização NÃO aproxima, e que quem negocia o contrato
# disse serem a mesma mercadoria. Cada linha aqui MOVE DINHEIRO, e é por isso
# que ela mora numa tabela com data e efeito medido, e não numa aproximação de
# texto escondida na consulta: a normalização continua fazendo só aritmética
# (maiúscula, acento, espaço, plural), e tudo que for julgamento comercial
# passa por aqui, onde se lê.
#
# Quem acrescentar uma linha: meça o efeito ANTES e escreva na linha. Sem o
# número, a próxima pessoa não tem como saber se a equivalência é detalhe de
# cadastro ou um item de R$ 200 mil por ano.
EQUIVALENCIAS = {
    # 11/09/2026, decisão de quem opera: "Phevus também é conjuntos".
    # 764 coletas/ano da IOCHPE MAXION saem da cláusula genérica (3h) para a
    # de CONJUNTOS (6,5h na descarga). Efeito medido: R$ 7.324,75 A MENOS de
    # estadia estimada em 60 dias, sobre 63 permanências.
    #
    # LONGARINA PHEVUS (998 coletas/ano) FICA DE FORA, e isso foi perguntado e
    # respondido no mesmo dia: ela continua na genérica, junto com a LONGARINA
    # comum. Incluí-la levaria o efeito a R$ 45.210,51 em 60 dias — a
    # diferença entre as duas leituras era de R$ 37,9 mil, e por isso não foi
    # deduzida daqui.
    "CONJUNTO PHEVU": "CONJUNTO",
}


def _lit(t: str) -> str:
    """Literal SQL, com a aspa escapada. As chaves saem de `normalizar`, que
    só produz letra e espaço — o escape é para o dia em que alguém acrescentar
    uma mercadoria com apóstrofo no nome."""
    return "'" + t.replace("'", "''") + "'"


def sql_equivalente(expr: str) -> str:
    """A expressão já normalizada, com as equivalências declaradas aplicadas.

    `CASE <expr> WHEN … THEN … ELSE <expr> END` — sem `LIKE`, sem prefixo, sem
    nada que aproxime por conta própria: só as trocas que estão escritas na
    tabela acima. Tabela vazia devolve a expressão intacta.
    """
    if not EQUIVALENCIAS:
        return expr
    casos = "".join(" WHEN %s THEN %s" % (_lit(k), _lit(v))
                    for k, v in sorted(EQUIVALENCIAS.items()))
    return "CASE %s%s ELSE %s END" % (expr, casos, expr)


def equivalente(merc: str | None) -> str:
    """O mesmo, em Python: o valor normalizado depois das equivalências."""
    n = normalizar(merc)
    return EQUIVALENCIAS.get(n, n)


EQUIVALENCIA = "equivalencia"

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
    crua = normalizar(mercadoria)
    alvo = EQUIVALENCIAS.get(crua, crua)
    if alvo:
        for ln in linhas:
            if ln.get("mercadoria") and normalizar(ln["mercadoria"]) == alvo:
                # DIZ QUANDO FOI POR EQUIVALÊNCIA. "6,5h porque o contrato tem
                # uma cláusula para CONJUNTOS" e "6,5h porque alguém declarou
                # que CONJUNTO PHEVUS é CONJUNTOS" são o mesmo número e
                # afirmações diferentes — a segunda é uma decisão de pessoa, e
                # quem confere a conta tem direito de ver que ela existe.
                return dict(ln, origem=(MERCADORIA if alvo == crua else EQUIVALENCIA))
    for ln in linhas:
        if not ln.get("mercadoria"):
            return dict(ln, origem=GENERICO)
    maior = max(linhas, key=lambda ln: (
        ln.get("ft_descarga_h") or 0, ln.get("ft_carga_h") or 0,
        normalizar(ln.get("mercadoria"))))
    return dict(maior, origem=SEM_CLAUSULA)
