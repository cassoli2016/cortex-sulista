"""SQL do módulo orçamentário — histórico, realizado e mapa de agrupador.

A chave de conta é `grupo|reduzido`, a MESMA que a DRE Gerencial (DRE_AG_SQL) e a
tela de Contabilidade usam. Isso garante que reclassificar uma conta mova orçado e
realizado juntos, sem abrir divergência entre as telas.

PostgreSQL 9.3: nada de FILTER/LATERAL. `%` é reservado pelo psycopg, então os
prefixos de estrutural usam position(...)=1 em vez de LIKE.
"""
from __future__ import annotations

from datetime import date

from api import agrupador_gerencial as _ag

# Base compartilhada: mesmos filtros de DRE_AG_SQL (ver api/queries.py).
#
# A ELEGIBILIDADE ENTRA POR `existe()`, NÃO POR JOIN, e a diferença é de ordem
# de grandeza. Esta consulta nunca leu nada do agrupador — só perguntava se a
# conta tem um. Com `left_join()` a janela de 24 meses estourava o
# `statement_timeout` de 60 s (e a de 9 meses levava 7,5 s); com o EXISTS ela
# roda em ~20 s, devolvendo exatamente as mesmas linhas. O porquê, com o plano
# do PostgreSQL, está no docstring de `agrupador_gerencial.existe`.
#
# Quem precisar do NOME do agrupador aqui um dia volta ao `left_join()` — e aí
# paga o preço com conhecimento de causa, em vez de por inércia.
_BASE = f"""
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (position('3' in p.estrutural) = 1 OR position('4' in p.estrutural) = 1
       OR {_ag.existe('l', '        ')})
"""

_SELECT = """
SELECT l.grupo::text || '|' || l.reduzido::text AS conta,
       to_char(l.dtlancamento,'YYYY-MM') AS mes,
       sum(coalesce(l.valorcredito,0) - coalesce(l.valordebito,0))::float8 AS valor
"""

# Valor por conta x mês. Serve tanto para derivar o baseline (recorte = meses
# fechados) quanto para o realizado (recorte = ano orçado) — é a MESMA pergunta em
# janelas diferentes, então é um alias explícito e não duplicação de query.
HIST_CONTA_SQL = _SELECT + _BASE + " GROUP BY 1, 2"
REAL_CONTA_SQL = HIST_CONTA_SQL

# Conta -> agrupador gerencial, para o rollup até a linha da DRE.
AGRUP_CONTA_SQL = f"""
SELECT ag.grupo::text || '|' || ag.reduzido::text AS conta,
       ag.descricao AS agrupador
FROM {_ag.FONTE} ag
WHERE ag.descricao IS NOT NULL AND ag.grupo IS NOT NULL
"""

# Conta -> nome do plano de contas (planoconta.descricao, como na Contabilidade).
# min() + GROUP BY protege contra (grupo, reduzido) duplicado no cadastro.
# O regexp_replace é OBRIGATÓRIO: a conexão sai em client_encoding LATIN1 e uma
# única descrição com en-dash (U+2013) derruba a query inteira ("has no
# equivalent in encoding LATIN1"). Tudo fora do LATIN1 (acima de U+00FF) vira
# '-' ainda no servidor; os escapes \\uXXXX chegam como ASCII puro na conexão.
NOME_CONTA_SQL = (
    "SELECT p.grupo::text || '|' || p.reduzido::text AS conta,\n"
    "       min(upper(regexp_replace(p.descricao, '[^\\u0001-\\u00ff]', '-', 'g'))) AS nome\n"
    "FROM planoconta p\n"
    "WHERE p.ativoinativo = 1\n"
    "GROUP BY 1\n"
)


def meses_fechados(hoje: date, n: int = 12) -> list[str]:
    """Os n meses 'YYYY-MM' anteriores ao mês corrente, em ordem cronológica.

    O mês corrente NUNCA entra: em jul/26 o custo variável aparece pela metade
    (R$ 3,4 mi contra R$ 6,5 mi normais) e contaminaria todo o baseline.
    """
    ano, mes = hoje.year, hoje.month
    saida: list[str] = []
    for _ in range(n):
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
        saida.append(f"{ano:04d}-{mes:02d}")
    return list(reversed(saida))
