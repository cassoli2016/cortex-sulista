# -*- coding: utf-8 -*-
"""O fundo da DRE Gerencial: centro de custo e lançamento.

A tela ia até a CONTA. Daqui para baixo há dois níveis, e cada um responde uma
pergunta que a conta não responde: "de quem é esse custo" (centro de custo) e
"que lançamento é esse" (o razão, linha a linha).

O QUE QUASE ESTRAGOU ISTO, e é o motivo de o módulo existir em vez de um JOIN:

  **14% dos lançamentos não têm linha de rateio.** Medido em 03/09/2026: 6.391
  de 45.885 em agosto (R$ 557.298,76) e 68.451 em 12 meses (R$ 15,76 milhões).
  Um `JOIN lancamento_filial_unidade_centrocusto` ingênuo simplesmente PERDE
  esses lançamentos — a soma dos centros não fecha com o total da conta, e o
  buraco tem cara de "esse centro custa menos do que eu pensava".

  Por isso a quebra tem uma linha explícita de SEM CENTRO DE CUSTO. Ela não é
  um resto: é 14% dos lançamentos, e some se ninguém a nomear.

  Quando o rateio existe, ele FECHA: zero casos de divergência em 521.610
  lançamentos de 12 meses. E ele pode dividir o mesmo lançamento em até 21
  partes — por isso a soma é do RATEIO, nunca do lançamento repetido.

A EXCLUSÃO VALE AQUI TAMBÉM. O drill-down é a mesma DRE vista de perto: se um
lançamento foi tirado do resultado, ele não pode reaparecer três cliques
abaixo, ou o total de cima deixaria de bater com a soma de baixo.
"""
from __future__ import annotations

import datetime
import logging

from . import agrupador_gerencial as _ag
from . import db, dre_exclusoes

log = logging.getLogger("cortex.dre_drill")

#: Sem centro de custo não é "outros": é 14% dos lançamentos, e o rótulo diz
#: isso em vez de fingir que é uma sobra pequena.
SEM_CENTRO = "(sem centro de custo)"

#: Teto da lista de lançamentos. A tela é para CONFERIR um número, não para
#: navegar o razão — e uma conta com 12 mil lançamentos travaria o navegador.
LIMITE_LANC = 500


def _filtro_exc(alias: str, de: str, ate: str) -> tuple[str, dict]:
    chs = dre_exclusoes.chaves(de, ate)
    return dre_exclusoes.filtro_sql(alias, len(chs)), dre_exclusoes.filtro_params(chs)


def _meses_do_periodo(de: str, ate: str) -> list[str]:
    """Todos os meses de `de` (inclusive) até `ate` (EXCLUSIVE).

    Gerado, nunca colhido do `GROUP BY`: mês sem lançamento tem de aparecer
    zerado, senão a série emenda um mês no outro e esconde o vão.
    """
    a = datetime.date.fromisoformat(de).replace(day=1)
    fim = datetime.date.fromisoformat(ate).replace(day=1)
    fora = []
    while a < fim:
        fora.append(a.strftime("%Y-%m"))
        a = (a.replace(day=28) + datetime.timedelta(days=7)).replace(day=1)
    return fora


def centros(grupo: int, reduzido: int, de: str, ate: str) -> dict:
    """Os centros de custo de UMA conta no período, e o que sobra sem centro.

    A soma dos centros mais o "sem centro" é IGUAL ao total da conta na DRE —
    e é isso que faz o drill-down ser conferência, e não uma segunda opinião.
    """
    fexc, pexc = _filtro_exc("l", de, ate)
    params = {"de": de, "ate": ate, "grupo": int(grupo),
              "reduzido": int(reduzido), **pexc}
    sql = """
WITH lanc AS (
  SELECT l.grupo, l.empresa, l.reduzido, l.sequencia, l.dtlancamento,
         (coalesce(l.valorcredito,0) - coalesce(l.valordebito,0))::float8 AS valor
  FROM lancamento l
  JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
    AND p.ativoinativo = 1
  WHERE l.dtlancamento >= %%(de)s::date AND l.dtlancamento < %%(ate)s::date
    AND coalesce(l.historico, 0) <> 18
    AND p.estrutural ~ '^[34]'
    AND l.grupo = %%(grupo)s AND l.reduzido = %%(reduzido)s%s
),
rat AS (
  SELECT r.grupo, r.empresa, r.reduzido, r.sequencia, r.dtlancamento,
         r.centrocusto,
         (coalesce(r.valorcredito,0) - coalesce(r.valordebito,0))::float8 AS valor
  FROM lancamento_filial_unidade_centrocusto r
  JOIN lanc x ON x.grupo = r.grupo AND x.empresa = r.empresa
    AND x.reduzido = r.reduzido AND x.sequencia = r.sequencia
    AND x.dtlancamento = r.dtlancamento
)
SELECT cc.codigo AS centro, coalesce(cc.descricao, '?') AS descricao,
       to_char(rat.dtlancamento, 'YYYY-MM') AS mes,
       sum(rat.valor)::float8 AS valor, count(*)::int AS lancamentos
FROM rat
LEFT JOIN centrocusto cc ON cc.grupo = rat.grupo AND cc.codigo = rat.centrocusto
GROUP BY 1, 2, 3
UNION ALL
-- O QUE NAO TEM RATEIO. `NOT EXISTS` e nao `LEFT JOIN ... IS NULL`: o rateio
-- divide o mesmo lancamento em ate 21 partes, e o LEFT JOIN multiplicaria a
-- linha antes de filtrar.
SELECT NULL::int, %%(sem)s, to_char(x.dtlancamento, 'YYYY-MM'),
       sum(x.valor)::float8, count(*)::int
FROM lanc x
WHERE NOT EXISTS (
  SELECT 1 FROM lancamento_filial_unidade_centrocusto r
   WHERE r.grupo = x.grupo AND r.empresa = x.empresa AND r.reduzido = x.reduzido
     AND r.sequencia = x.sequencia AND r.dtlancamento = x.dtlancamento)
GROUP BY 3
HAVING count(*) > 0
""" % fexc
    params["sem"] = SEM_CENTRO
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cruas = [dict(r) for r in cur.fetchall()]

    # PIVÔ MÊS A MÊS. A quebra por centro nasceu com um número só do período
    # inteiro, e ficava sozinha entre níveis que a tela mostra mês a mês —
    # quem via "R$ 2,3 mi" no centro não sabia se era um mês fora da curva ou
    # doze meses iguais, que é a pergunta que traz alguém até aqui.
    #
    # O intervalo de meses é GERADO a partir do período pedido, e não colhido
    # do resultado: `GROUP BY` não devolve o mês sem lançamento, e a linha
    # emendaria abril em agosto sem dizer que houve um vão.
    meses = _meses_do_periodo(de, ate)
    por: dict = {}
    for r in cruas:
        chave = r["centro"]
        x = por.setdefault(chave, {
            "centro": r["centro"], "descricao": r["descricao"],
            "meses": {m: 0.0 for m in meses}, "valor": 0.0, "lancamentos": 0})
        if r["mes"] in x["meses"]:
            x["meses"][r["mes"]] += r["valor"] or 0.0
        x["valor"] += r["valor"] or 0.0
        x["lancamentos"] += r["lancamentos"] or 0

    linhas = sorted(por.values(), key=lambda x: abs(x["valor"] or 0),
                    reverse=True)
    return {"linhas": linhas, "meses": meses,
            "total": sum(x["valor"] or 0 for x in linhas),
            "sem_centro_rotulo": SEM_CENTRO}


def lancamentos(grupo: int, reduzido: int, de: str, ate: str,
                centro: int | None = None, sem_centro: bool = False) -> dict:
    """Os lançamentos de uma conta — opcionalmente de UM centro de custo.

    `sem_centro=True` traz justamente os que não têm rateio, que é o balde que
    a quebra por centro precisa nomear para fechar.
    """
    fexc, pexc = _filtro_exc("l", de, ate)
    params = {"de": de, "ate": ate, "grupo": int(grupo),
              "reduzido": int(reduzido), "lim": LIMITE_LANC + 1, **pexc}
    corte = ""
    if sem_centro:
        corte = """
  AND NOT EXISTS (SELECT 1 FROM lancamento_filial_unidade_centrocusto r
     WHERE r.grupo=l.grupo AND r.empresa=l.empresa AND r.reduzido=l.reduzido
       AND r.sequencia=l.sequencia AND r.dtlancamento=l.dtlancamento)"""
    elif centro is not None:
        corte = """
  AND EXISTS (SELECT 1 FROM lancamento_filial_unidade_centrocusto r
     WHERE r.grupo=l.grupo AND r.empresa=l.empresa AND r.reduzido=l.reduzido
       AND r.sequencia=l.sequencia AND r.dtlancamento=l.dtlancamento
       AND r.centrocusto = %(centro)s)"""
        params["centro"] = int(centro)
    sql = """
SELECT l.grupo, l.empresa, l.reduzido, l.sequencia, l.dtlancamento,
       l.valordebito, l.valorcredito, l.historicodescricao,
       p.descricao AS conta, ag.descricao AS agrupador
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
%s
WHERE l.dtlancamento >= %%(de)s::date AND l.dtlancamento < %%(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND p.estrutural ~ '^[34]'
  AND l.grupo = %%(grupo)s AND l.reduzido = %%(reduzido)s%s%s
ORDER BY l.dtlancamento, l.sequencia
LIMIT %%(lim)s
""" % (_ag.left_join("ag", "l"), fexc, corte)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        linhas = [dict(r) for r in cur.fetchall()]
    # TETO ATINGIDO SE DECLARA: lista cortada em silêncio faz a soma da tela
    # não bater com o total de cima, e quem confere culpa o número certo.
    truncou = len(linhas) > LIMITE_LANC
    return {"linhas": linhas[:LIMITE_LANC], "truncou": truncou,
            "limite": LIMITE_LANC}
