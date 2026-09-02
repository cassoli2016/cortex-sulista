"""O mapa conta -> agrupador gerencial, em UMA definição para todas as telas.

`sulista.agrupadorgerencial` é uma tabela do ERP AVA (réplica, somente leitura)
que diz em que linha da DRE Gerencial cada conta do plano de contas entra. Ela
é mantida À MÃO pela Contabilidade, direto no banco primário — não tem chave
primária, não tem índice, não tem coluna de vigência e ninguém nos avisa quando
muda. Cinco telas dependem dela: DRE Gerencial (`dre`), Contabilidade (`cont`),
Orçamento (`orc`), Previsão e Custos (`custos`).

Em 02/09/2026 a tabela foi RECRIADA (574 das 585 linhas na mesma transação) e
duas coisas quebraram de uma vez — as duas caladas, as duas caras:

1. **`grupo` voltou como `character varying`**, era `integer`. Todo join da
   casa fazia `ag.grupo = l.grupo` contra o `int4` do razão, e o PostgreSQL
   não tem operador `varchar = integer`: as CINCO telas passaram a devolver
   erro na primeira consulta. Tipo de coluna de terceiro não é contrato — a
   comparação sai daqui já normalizada, e valor não-numérico vira NULL (a
   conta perde o agrupador e aparece em CLASSIFICAR) em vez de derrubar a
   tela.

2. **Uma conta ganhou DUAS linhas** (1|425406, "Multas Fiscais": a
   classificação nova entrou por INSERT em cima da antiga, sem apagar). Sem
   chave primária o banco aceita, e o LEFT JOIN então DUPLICA todo lançamento
   da conta — o valor entra duas vezes na DRE, em duas linhas diferentes, e o
   total continua plausível. É a mesma armadilha do join com tabela de
   vigência (`docs/LICOES.md`): a fonte entra AGREGADA por (grupo, reduzido),
   nunca crua. `min()` é desempate determinístico, não palpite — a duplicata
   real vai para a linha CLASSIFICAR da DRE, que é onde alguém a conserta, e
   `scripts/conferir_agrupador.py` a acusa pelo nome.

O que esta fonte NÃO resolve, porque é decisão da Contabilidade e não defeito
de código: conta de BALANÇO com agrupador. A elegibilidade das queries é
"tem agrupador OU estrutural de resultado", então classificar uma conta 1.x/2.x
a puxa para dentro da DRE como custo. Hoje são 6 contas, R$ +1,47 mi em 12
meses (o conferidor mede e nomeia).
"""
from __future__ import annotations

from datetime import date

# Uma linha por (grupo, reduzido), com `grupo` já em inteiro.
#
# O CASE é o para-choque do tipo: `grupo::text` funciona tanto com a coluna
# integer quanto com a varchar de hoje, e o que não for numérico sai NULL —
# não casa com ninguém e a conta cai em CLASSIFICAR, em vez de abortar a
# consulta inteira. A agregação é sobre 585 linhas: custo irrelevante, e o
# plano do razão não muda (o lado pesado do join continua sendo `lancamento`
# contra `planoconta`, intocado).
FONTE = """(SELECT CASE WHEN ag_.grupo::text ~ '^[0-9]+$'
                        THEN ag_.grupo::text::int END AS grupo,
                   ag_.reduzido, min(ag_.descricao) AS descricao
            FROM sulista.agrupadorgerencial ag_
            GROUP BY 1, 2)"""


def left_join(alias: str, origem: str, ident: str = "  ") -> str:
    """LEFT JOIN da fonte contra `origem` (o alias que tem grupo e reduzido)."""
    return (f"LEFT JOIN {FONTE} {alias}\n"
            f"{ident}ON {alias}.reduzido = {origem}.reduzido\n"
            f"{ident}AND {alias}.grupo = {origem}.grupo")


# Conferências de cadastro — usadas por scripts/conferir_agrupador.py e pela
# Saúde do Servidor. Ficam aqui junto da fonte: quem mexe numa lembra da outra.
DUPLICATAS_SQL = """
SELECT grupo::text AS grupo, reduzido, count(*)::int AS linhas,
       string_agg(descricao, ' || ') AS descricoes
FROM sulista.agrupadorgerencial GROUP BY 1, 2 HAVING count(*) > 1
ORDER BY 3 DESC, 2
"""

# Conta que NÃO é de resultado mas tem agrupador: entra na DRE pela
# elegibilidade "tem agrupador OU estrutural ~ '^[34]'".
BALANCO_CLASSIFICADO_SQL = """
SELECT ag.grupo, ag.reduzido, ag.descricao AS agrupador, p.estrutural,
       upper(regexp_replace(p.descricao, '[^\u0001-\u00ff]', '-', 'g')) AS conta,
       coalesce(sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0)), 0)::float8 AS valor
FROM %s ag
JOIN planoconta p ON p.reduzido = ag.reduzido AND p.grupo = ag.grupo
LEFT JOIN lancamento l ON l.reduzido = p.reduzido AND l.grupo = p.grupo
  AND l.dtlancamento >= %%(de)s::date AND l.dtlancamento < %%(ate)s::date
  AND coalesce(l.historico, 0) <> 18
WHERE p.estrutural !~ '^[34]'
GROUP BY 1, 2, 3, 4, 5 ORDER BY abs(coalesce(sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0)), 0)) DESC
""" % FONTE

# Grupo NÃO numérico: a conta perde o agrupador em silêncio (vira CLASSIFICAR).
GRUPO_INVALIDO_SQL = """
SELECT grupo::text AS grupo, count(*)::int AS linhas
FROM sulista.agrupadorgerencial WHERE grupo::text !~ '^[0-9]+$'
GROUP BY 1 ORDER BY 2 DESC
"""

# Agrupador apontando para conta que não existe no plano de contas.
ORFAO_SQL = """
SELECT ag.grupo, ag.reduzido, ag.descricao AS agrupador
FROM %s ag
LEFT JOIN planoconta p ON p.reduzido = ag.reduzido AND p.grupo = ag.grupo
WHERE p.reduzido IS NULL ORDER BY 2
""" % FONTE

# Os dois caminhos do resultado: pelo MAPA (agrupador) e pelo ESTRUTURAL do
# plano de contas, que não depende da tabela. Divergir é o sintoma de mapa
# furado — foi assim que os R$ 1,47 mi de conta de balanço apareceram.
DOIS_CAMINHOS_SQL = """
WITH por_agrupador AS (
  SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
         sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS v
  FROM lancamento l
  JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
    AND p.ativoinativo = 1
  %s
  WHERE l.dtlancamento >= %%(de)s::date AND l.dtlancamento < %%(ate)s::date
    AND coalesce(l.historico, 0) <> 18
    AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
  GROUP BY 1
), por_estrutural AS (
  SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
         sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS v
  FROM lancamento l
  JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  WHERE l.dtlancamento >= %%(de)s::date AND l.dtlancamento < %%(ate)s::date
    AND p.estrutural ~ '^[34]' AND p.estrutural NOT LIKE '4.9%%%%'
    AND coalesce(l.historico, 0) <> 18
  GROUP BY 1
)
SELECT coalesce(a.mes, e.mes) AS mes,
       coalesce(a.v, 0)::float8 AS por_agrupador,
       coalesce(e.v, 0)::float8 AS por_estrutural,
       (coalesce(a.v, 0) - coalesce(e.v, 0))::float8 AS diferenca
FROM por_agrupador a FULL OUTER JOIN por_estrutural e ON e.mes = a.mes
ORDER BY 1
""" % left_join("ag", "l")


# ============================================================================
# Diagnóstico — o que a Saúde do Servidor mostra e o conferidor detalha.
# ----------------------------------------------------------------------------
# Custa ~3 s contra o AVA (medido em 02/09/2026: cadastro 0,06 s, contas de
# balanço com valor 0,7 s, os dois caminhos 2,4 s). Quem chama põe TTL — na
# Saúde é `_AGRUPADOR_TTL`, que repinta de 5 em 5 s.
# ============================================================================
def janela_12m(hoje: date | None = None, meses: int = 12) -> tuple[str, str]:
    """[de, ate) dos ultimos `meses` FECHADOS — o mes corrente fica fora.

    Uma definicao para o conferidor e para a Saude: regua que muda de janela
    entre as duas telas nao e regua. O mes em curso e parcial por construcao e
    entraria como queda em toda conferencia rodada dia 2.
    """
    hoje = hoje or date.today()
    fim = date(hoje.year, hoje.month, 1)
    ano, mes = fim.year, fim.month - meses
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1).isoformat(), fim.isoformat()


def diagnostico(meses: int = 12) -> dict:
    """Estado do mapa contabil contra o banco VIVO. Nunca levanta excecao.

    `legivel=False` e o caso de 02/09/2026: a tabela recriada com `grupo` em
    varchar tornou o mapa impossivel de ler, e com ele foram DRE Gerencial,
    Contabilidade, Orcamento, Previsao e Custos. E `erro`, nao `alerta`: nao e
    numero torto, e cinco telas sem dado.
    """
    from . import db

    de, ate = janela_12m(meses=meses)
    d: dict = {"legivel": False, "erro": None, "de": de, "ate": ate,
               "meses": meses, "linhas": 0, "contas": 0, "duplicadas": [],
               "grupo_invalido": [], "orfaos": [], "balanco": [],
               "balanco_valor": 0.0, "divergencia": 0.0, "meses_divergentes": 0}
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*)::int AS linhas, "
                        "count(DISTINCT (grupo, reduzido))::int AS contas "
                        "FROM sulista.agrupadorgerencial")
            r = cur.fetchone()
            d["linhas"], d["contas"] = r["linhas"], r["contas"]

            cur.execute(GRUPO_INVALIDO_SQL)
            d["grupo_invalido"] = [dict(x) for x in cur.fetchall()]
            cur.execute(DUPLICATAS_SQL)
            d["duplicadas"] = [dict(x) for x in cur.fetchall()]
            cur.execute(ORFAO_SQL)
            d["orfaos"] = [dict(x) for x in cur.fetchall()]

            cur.execute(BALANCO_CLASSIFICADO_SQL, {"de": de, "ate": ate})
            d["balanco"] = [dict(x) for x in cur.fetchall()]
            d["balanco_valor"] = sum(x["valor"] for x in d["balanco"])

            cur.execute(DOIS_CAMINHOS_SQL, {"de": de, "ate": ate})
            difs = [x["diferenca"] for x in cur.fetchall()]
            d["divergencia"] = sum(difs)
            d["meses_divergentes"] = sum(1 for x in difs if abs(x) > 0.01)
            d["legivel"] = True
    except Exception as exc:  # noqa: BLE001
        # O TIPO da excecao, nunca o texto cru: a conninfo do AVA passa por
        # aqui em algumas falhas de conexao (mesma regra das integracoes).
        d["erro"] = type(exc).__name__
    return d
