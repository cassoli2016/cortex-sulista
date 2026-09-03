# -*- coding: utf-8 -*-
"""Lançamentos que a DRE Gerencial ignora, marcados à mão.

A DRE gerencial não é a contábil: há lançamento que o razão precisa ter e o
resultado gerencial não deve carregar — reclassificação que entra e sai,
provisão revertida, rateio já contado noutra linha. Até aqui isso só se
resolvia pedindo à Contabilidade que mexesse no razão.

ESTE MÓDULO CRIA UM JEITO DE MUDAR O RESULTADO PUBLICADO. Tudo aqui existe
para que isso nunca seja silencioso:

1. **MOTIVO OBRIGATÓRIO.** Exclusão sem motivo escrito é irrastreável em seis
   meses, e o que se perde primeiro é sempre a razão.

2. **A DRE MOSTRA O QUE FOI EXCLUÍDO** — `total()` alimenta o selo no topo da
   tela. Um número que pode ser mexido sem aparecer não é um número, é uma
   opinião.

3. **PERMISSÃO PRÓPRIA** (`dreexc`), separada de quem só LÊ a DRE. Quem tem
   `dre` vê a lista e os motivos; marcar exige a permissão.

4. **NÃO ALCANÇA AS OUTRAS TELAS.** Contabilidade, Orçamento e Fechamento
   continuam enxergando o lançamento. Silenciar todas de uma vez esconderia
   justamente de quem precisa achá-lo.

5. **A FOTO fica gravada.** O ERP é réplica de terceiro; o lançamento pode
   mudar ou sumir. A DRE filtra pela CHAVE, a tela mostra pela FOTO — sem
   isso, a lista viraria chaves órfãs que ninguém sabe mais o que eram.

DOIS BANCOS, e é isso que decide a implementação: as exclusões moram no banco
do CÓRTEX e os lançamentos no ERP. Não há join possível — as chaves viajam
para dentro da consulta do ERP como VALUES parametrizado (`filtro_sql`).
"""
from __future__ import annotations

import logging
from datetime import date

from . import pglocal

log = logging.getLogger("cortex.dre_exclusoes")

ESQUEMA: str | None = None

#: As cinco colunas que identificam um lançamento no ERP. Medido em 1.230.480
#: lançamentos de 12 meses: `sequencia` sozinha colide, `(sequencia, data)`
#: também. Só a chave completa não colide.
CHAVE = ("grupo", "empresa", "reduzido", "sequencia", "dtlancamento")

MOTIVO_MIN = 5


class MotivoObrigatorio(ValueError):
    """Sem motivo escrito não se exclui. Ver a nota 1 no cabeçalho."""


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def _chave_de(dados: dict) -> tuple:
    try:
        return (int(dados["grupo"]), int(dados["empresa"]), int(dados["reduzido"]),
                int(dados["sequencia"]),
                dados["dtlancamento"] if isinstance(dados["dtlancamento"], date)
                else date.fromisoformat(str(dados["dtlancamento"])[:10]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "lançamento sem chave completa (%s)" % ", ".join(CHAVE)) from exc


def marcar(dados: dict, motivo: str, quem: str,
           esquema: str | None = None) -> dict:
    """Tira um lançamento do resultado gerencial. Idempotente por chave."""
    motivo = " ".join(str(motivo or "").split())
    if len(motivo) < MOTIVO_MIN:
        raise MotivoObrigatorio(
            "Escreva o motivo da exclusão — daqui a seis meses ninguém vai "
            "lembrar por que este lançamento saiu do resultado.")
    if not quem:
        raise ValueError("exclusão sem autor não entra")
    chave = _chave_de(dados)
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO dre_excluido
                 (grupo, empresa, reduzido, sequencia, dtlancamento,
                  valor_debito, valor_credito, conta, agrupador, historico,
                  motivo, quem)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (grupo, empresa, reduzido, sequencia, dtlancamento)
               DO UPDATE SET motivo = EXCLUDED.motivo, quem = EXCLUDED.quem,
                             quando = now()
               RETURNING *""",
            (*chave, dados.get("valor_debito"), dados.get("valor_credito"),
             dados.get("conta"), dados.get("agrupador"), dados.get("historico"),
             motivo, quem))
        r = dict(cur.fetchone())
        conn.commit()
    return r


def desmarcar(dados: dict, esquema: str | None = None) -> bool:
    """Devolve o lançamento ao resultado."""
    chave = _chave_de(dados)
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """DELETE FROM dre_excluido
                WHERE grupo=%s AND empresa=%s AND reduzido=%s
                  AND sequencia=%s AND dtlancamento=%s""", chave)
        n = cur.rowcount
        conn.commit()
    return bool(n)


def listar(de: str | None = None, ate: str | None = None,
           esquema: str | None = None) -> list[dict]:
    """As exclusões, da mais recente para trás. Sem período, todas."""
    where, params = "", []
    if de:
        where += " AND dtlancamento >= %s"
        params.append(de)
    if ate:
        where += " AND dtlancamento < %s"
        params.append(ate)
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM dre_excluido WHERE 1=1" + where
            + " ORDER BY dtlancamento DESC, quando DESC", params)
        return [dict(r) for r in cur.fetchall()]


def chaves(de: str | None = None, ate: str | None = None,
           esquema: str | None = None) -> list[tuple]:
    """As chaves para o filtro da DRE. Lista vazia = nada a filtrar."""
    return [tuple(x[c] for c in CHAVE)
            for x in listar(de, ate, esquema=esquema)]


def total(de: str | None = None, ate: str | None = None,
          esquema: str | None = None) -> dict:
    """Quanto foi excluído — o número do selo na tela.

    O sinal segue a convenção da DRE (`crédito − débito`), para o selo poder
    dizer "o resultado seria X a mais/menos" sem que alguém tenha de inverter
    de cabeça.
    """
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        w, p = "", []
        if de:
            w += " AND dtlancamento >= %s"
            p.append(de)
        if ate:
            w += " AND dtlancamento < %s"
            p.append(ate)
        cur.execute(
            "SELECT count(*)::int AS n,"
            " coalesce(sum(coalesce(valor_credito,0)-coalesce(valor_debito,0)),0)"
            "   ::float8 AS efeito"
            " FROM dre_excluido WHERE 1=1" + w, p)
        return dict(cur.fetchone())


def chave_texto(c) -> str:
    """A chave de cinco colunas como UMA string. Ver `filtro_sql`."""
    g, e, r, sq, d = c
    return "%d|%d|%d|%d|%s" % (int(g), int(e), int(r), int(sq),
                               (d.isoformat() if hasattr(d, "isoformat")
                                else str(d)[:10]))


def filtro_sql(alias: str, quantas: int) -> str:
    """O trecho que tira as chaves excluídas de uma consulta ao ERP.

    Devolve "" quando não há exclusão — e isso importa: uma cláusula com lista
    vazia é erro de sintaxe, e a DRE de quem nunca excluiu nada é o caso mais
    comum de todos.

    DUAS RESTRIÇÕES DECIDIRAM ESTE FORMATO, e nenhuma é estética:

    1. **As consultas da DRE usam parâmetro NOMEADO** (`%(de)s`). O psycopg não
       deixa misturar nomeado com posicional na mesma consulta, então o filtro
       precisa entrar por UM nome só — daí o array único de texto, em vez de
       uma lista de tuplas.

    2. **O AVA é PostgreSQL 9.3.** O `unnest` de várias colunas ao mesmo tempo,
       que resolveria isto numa linha, só existe do 9.4 em diante. Comparar a
       chave CONCATENADA contra um array de texto funciona nos dois.

    A data entra por `to_char` com formato fixo: `dtlancamento::text` depende
    do `DateStyle` da sessão, e no dia em que ele mudasse o filtro pararia de
    casar sem erro nenhum — a exclusão simplesmente deixaria de valer, que é a
    pior forma de falhar que este código pode ter.
    """
    if quantas <= 0:
        return ""
    a = alias
    return ("\n  AND (" + a + ".grupo || '|' || " + a + ".empresa || '|' || "
            + a + ".reduzido"
            "\n       || '|' || " + a + ".sequencia || '|' || "
            "to_char(" + a + ".dtlancamento,'YYYY-MM-DD'))"
            "\n      <> ALL(%(dre_excluidos)s::text[])")


def filtro_params(chs: list) -> dict:
    """O parâmetro NOMEADO que `filtro_sql` espera."""
    return {"dre_excluidos": [chave_texto(c) for c in chs]}

#: O teto da busca. A tela é para achar UM lançamento e marcá-lo, não para
#: navegar o razão — a Contabilidade tem tela própria para isso. Sem teto, um
#: período largo sem filtro traria 1,2 milhão de linhas para o navegador.
BUSCA_LIMITE = 300


def buscar(de: str, ate: str, conta: str | None = None,
           texto: str | None = None, valor_min: float | None = None,
           esquema: str | None = None) -> dict:
    """Lançamentos do ERP no período, para escolher o que excluir.

    Só traz o que a DRE enxerga: conta de RESULTADO com classificação. Mostrar
    aqui um lançamento que a DRE já ignora seria oferecer a exclusão de algo
    que não muda nada — e quem clicasse ficaria procurando o efeito.
    """
    from . import agrupador_gerencial as _ag
    from . import db

    onde, params = [], {"de": de, "ate": ate}
    if conta:
        onde.append("l.reduzido = %(conta)s::int")
        params["conta"] = int(conta)
    if texto:
        onde.append("upper(l.historicodescricao) LIKE upper(%(texto)s)")
        params["texto"] = "%" + str(texto).strip() + "%"
    if valor_min:
        onde.append("(coalesce(l.valordebito,0) + coalesce(l.valorcredito,0))"
                    " >= %(vmin)s")
        params["vmin"] = float(valor_min)
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
  %s
ORDER BY (coalesce(l.valordebito,0) + coalesce(l.valorcredito,0)) DESC
LIMIT %d
""" % (_ag.left_join("ag", "l"),
       ("AND " + " AND ".join(onde)) if onde else "",
       BUSCA_LIMITE + 1)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        linhas = [dict(r) for r in cur.fetchall()]
    # TETO ATINGIDO SE DECLARA. Uma lista cortada em silêncio faz quem procura
    # concluir que o lançamento não existe.
    truncou = len(linhas) > BUSCA_LIMITE
    linhas = linhas[:BUSCA_LIMITE]
    ja = {(x["grupo"], x["empresa"], x["reduzido"], x["sequencia"],
           x["dtlancamento"]) for x in listar(de, ate, esquema=esquema)}
    for x in linhas:
        x["excluido"] = (x["grupo"], x["empresa"], x["reduzido"],
                         x["sequencia"], x["dtlancamento"]) in ja
    return {"linhas": linhas, "truncou": truncou, "limite": BUSCA_LIMITE}
