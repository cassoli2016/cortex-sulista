"""De onde vêm as cargas: o MONITORAMENTO SAC do ERP, lido por cliente.

A consulta de referência é a do próprio ERP (`Querys Sulista/AVACORP/
OPERACAO - Monitoramento SAC.sql`), que é de onde a planilha à mão era
montada. Daqui saem as MESMAS colunas, pelas MESMAS regras:

- o cliente é o `agrupamentocliente` do PAGADOR do frete;
- a janela de carregamento é `dtcoletar` quando o remetente está definido na
  coleta, e o agendamento da `coleta_cliente` quando não está — idem para a
  entrega, com `dtprevisaochegadaviagem` (a janela que a operação combina, e
  não `dtprevisaoentrega`, que está vazia nesta operação: ver
  `api/portal_cliente.JANELA_DE_ENTREGA`);
- chegada e saída são as ocorrências SAC 394/395 (carregamento) e 396/397
  (descarga), a PRIMEIRA de cada código na ordem de lançamento.

Conferido em 12/09/2026 contra a planilha de uma semana de uma cliente: todas
as cargas, horário a horário, bateram com o ERP em todas as linhas em que quem
montava a planilha não tinha corrigido o horário à mão.

O QUE ESTA LEITURA NÃO FAZ, e diz: coleta com mais de um apontamento do mesmo
código (paradas múltiplas, milk run) sai com o PRIMEIRO e um aviso na linha —
separar parada por parada é outra conta, e o relatório do ERP também só olha
a primeira quando a coleta não tem `coleta_cliente`.
"""
from __future__ import annotations

import logging

from .. import db
from .. import queries as _q

log = logging.getLogger("cortex.horas_paradas")

#: Quantos dias ANTES do período uma coleta pode ter sido emitida e ainda
#: concluir dentro dele. A estadia mais longa medida na primeira conferência
#: foi de 1,7 dia; a viagem mais longa desta operação, poucos dias. 45 dá
#: folga larga sem trazer o ano inteiro.
FOLGA_EMISSAO_DIAS = 45

#: As sete colunas que identificam uma coleta no ERP. Número sozinho repete
#: entre filiais.
CHAVE = ("grupo", "empresa", "filial", "unidade", "diferenciadornumero",
         "serie", "numero")


def chave(r: dict) -> str:
    return "|".join(str(r.get(c)) for c in CHAVE)


_K = ("{a}.grupo = {b}.grupo AND {a}.empresa = {b}.empresa"
      " AND {a}.filial = {b}.filial AND {a}.unidade = {b}.unidade"
      " AND {a}.diferenciadornumero = {b}.diferenciadornumero"
      " AND {a}.serie = {b}.serie AND {a}.numero = {b}.numero")


def _k(a: str, b: str) -> str:
    return _K.format(a=a, b=b)


# SEM `FILTER`, SEM `json_build_object`: o ERP é PostgreSQL 9.3.
CARGAS_SQL = """
WITH col AS (
  SELECT c.grupo, c.empresa, c.filial, c.unidade, c.diferenciadornumero,
         c.serie, c.numero, c.dtemissao, c.numerofatura, c.mercadorias,
         c.veiculo, c.carreta1, c.remetente, c.destinatario,
         c.remetentedefinido, c.destinatariodefinido,
         c.dtcoletar, c.dtprevisaochegadaviagem,
         c.origem, c.uforigem, c.destino, c.ufdestino
  FROM coleta c
  JOIN agrupamentocliente_cnpjcpfcodigo acc
    ON acc.grupo = c.grupo AND acc.empresa = c.empresa
   AND acc.cnpjcpfcodigo = c.cnpjcpfcodigopagadorfrete AND acc.vinculo = 1
  WHERE acc.codigo = %(cliente)s
    AND c.dtcancelamento IS NULL
    AND c.dtemissao >= %(de)s::date - %(folga)s
    AND c.dtemissao <  %(ate)s::date + 1
),
ev AS (
  SELECT co.grupo, co.empresa, co.filial, co.unidade, co.diferenciadornumero,
         co.serie, co.numero, co.ocorrencia, co.dtocorrencia,
         row_number() OVER wo AS rn,
         count(*)     OVER w  AS n
  FROM coleta_ocorrencia co
  JOIN col ON """ + _k("col", "co") + """
  WHERE co.ocorrencia IN (394, 395, 396, 397)
  WINDOW w  AS (PARTITION BY co.grupo, co.empresa, co.filial, co.unidade,
                             co.diferenciadornumero, co.serie, co.numero,
                             co.ocorrencia),
         wo AS (w ORDER BY co.sequenciaocorrencia)
),
evc AS (
  SELECT grupo, empresa, filial, unidade, diferenciadornumero, serie, numero,
         max(CASE WHEN ocorrencia = 394 AND rn = 1 THEN dtocorrencia END) AS carga_chegada,
         max(CASE WHEN ocorrencia = 395 AND rn = 1 THEN dtocorrencia END) AS carga_saida,
         max(CASE WHEN ocorrencia = 396 AND rn = 1 THEN dtocorrencia END) AS descarga_chegada,
         max(CASE WHEN ocorrencia = 397 AND rn = 1 THEN dtocorrencia END) AS descarga_saida,
         max(n) AS repeticoes
  FROM ev
  GROUP BY 1, 2, 3, 4, 5, 6, 7
)
SELECT col.grupo, col.empresa, col.filial, col.unidade,
       col.diferenciadornumero, col.serie, col.numero,
       col.dtemissao AS emissao,
       btrim(coalesce(col.numerofatura, '')) AS pedido,
       btrim(coalesce(col.mercadorias, ''))  AS mercadoria,
       btrim(coalesce(col.veiculo, ''))      AS placa_cavalo,
       -- Frota igual à placa é a placa COPIADA no campo (943 cadastros, ver
       -- `api/frota_identidade.py`): sai vazia, e não como número de frota.
       nullif(nullif(btrim(vc.numerofrota), ''), btrim(col.veiculo)) AS frota_cavalo,
       btrim(coalesce(col.carreta1, ''))     AS placa_carreta,
       nullif(nullif(btrim(vr.numerofrota), ''), btrim(col.carreta1)) AS frota_carreta,
       coalesce(nullif(btrim(rem.nomefantasia), ''),
                nullif(btrim(rem.razaosocial), ''), '') AS origem,
       coalesce(nullif(btrim(dst.nomefantasia), ''),
                nullif(btrim(dst.razaosocial), ''), '') AS destino,
       btrim(coalesce(col.destinatario::text, '')) AS destinatario_codigo,
       btrim(coalesce(col.origem, '')) || coalesce('/' || col.uforigem, '') AS cidade_origem,
       btrim(coalesce(col.destino, '')) || coalesce('/' || col.ufdestino, '') AS cidade_destino,
       CASE WHEN col.remetentedefinido = 1 THEN col.dtcoletar
            ELSE coalesce((SELECT x.dtagendamentocoleta FROM coleta_cliente x
                            WHERE """ + _k("x", "col") + """
                            ORDER BY x.sequencia LIMIT 1), col.dtcoletar)
            END AS carga_janela,
       CASE WHEN col.destinatariodefinido = 1 THEN col.dtprevisaochegadaviagem
            ELSE coalesce((SELECT x.dtagendamentoentrega FROM coleta_cliente x
                            WHERE """ + _k("x", "col") + """
                            ORDER BY x.sequencia LIMIT 1), col.dtprevisaochegadaviagem)
            END AS descarga_janela,
       (SELECT count(*) FROM coleta_cliente x WHERE """ + _k("x", "col") + """) AS paradas,
       evc.carga_chegada, evc.carga_saida, evc.descarga_chegada, evc.descarga_saida,
       coalesce(evc.repeticoes, 0) AS repeticoes,
       (SELECT string_agg(DISTINCT k.numero::text, ' / ' ORDER BY k.numero::text)
          FROM conhecimento_composicao kc
          JOIN conhecimento k
            ON k.grupo = kc.grupo AND k.empresa = kc.empresa AND k.filial = kc.filial
           AND k.unidade = kc.unidade AND k.diferenciadornumero = kc.diferenciadornumero
           AND k.serie = kc.serie AND k.numero = kc.numero
         WHERE kc.tipodocumento = 27
           AND kc.grupo = col.grupo AND kc.empresa = col.empresa
           AND kc.filialdocumento = col.filial AND kc.unidadedocumento = col.unidade
           AND kc.diferenciadornumerodocumento = col.diferenciadornumero
           AND kc.seriedocumento = col.serie AND kc.numerodocumento = col.numero
           AND k.dtcancelamento IS NULL) AS ctes
FROM col
LEFT JOIN evc ON """ + _k("evc", "col") + """
LEFT JOIN veiculo vc ON vc.placa = col.veiculo
LEFT JOIN veiculo vr ON vr.placa = col.carreta1
LEFT JOIN cadastro rem ON rem.codigo = col.remetente
LEFT JOIN cadastro dst ON dst.codigo = col.destinatario
ORDER BY col.filial, col.numero
"""

# O CONTRATO INTEIRO do cliente, vigente ou não: a vigência se confere NA
# DATA DA CARGA (`servico.contrato_da_carga`), não hoje. Cobrar a semana
# passada com a cláusula que entrou ontem seria cobrar retroativo.
CONTRATO_SQL = """
SELECT filial,
       btrim(coalesce(observacao, '')) AS mercadoria,
       extract(epoch FROM freetimecarga) / 3600    AS ft_carga_h,
       extract(epoch FROM freetimedescarga) / 3600 AS ft_descarga_h,
       valor_coleta, valor_entrega, dtinicio, dtfim, ativoinativo
FROM sulista.sac_freetimecliente
WHERE agrupamentocliente = %(cliente)s
ORDER BY dtinicio DESC NULLS LAST, filial, observacao
"""

CLIENTES_SQL = """
SELECT DISTINCT ON (ac.codigo) ac.codigo, btrim(ac.descricao) AS nome,
       EXISTS (SELECT 1 FROM sulista.sac_freetimecliente ft
                WHERE ft.agrupamentocliente = ac.codigo) AS tem_contrato
FROM agrupamentocliente ac
WHERE coalesce(btrim(ac.descricao), '') <> ''
ORDER BY ac.codigo
"""

# O que o cliente carregou e para quem, em 180 dias: é o cardápio de onde a
# tela oferece mercadoria e destinatário para as regras. Oferecer da lista
# REAL, e não de campo livre, é o que impede a regra de nascer com uma grafia
# que nenhuma coleta tem — e ficar muda para sempre.
CATALOGO_SQL = """
SELECT 'mercadoria' AS tipo, btrim(c.mercadorias) AS codigo,
       btrim(c.mercadorias) AS nome, count(*) AS n
FROM coleta c
JOIN agrupamentocliente_cnpjcpfcodigo acc
  ON acc.grupo = c.grupo AND acc.empresa = c.empresa
 AND acc.cnpjcpfcodigo = c.cnpjcpfcodigopagadorfrete AND acc.vinculo = 1
WHERE acc.codigo = %(cliente)s AND c.dtcancelamento IS NULL
  AND c.dtemissao >= current_date - 180
  AND coalesce(btrim(c.mercadorias), '') <> ''
GROUP BY 2, 3
UNION ALL
SELECT 'destino', btrim(c.destinatario::text),
       max(coalesce(nullif(btrim(d.nomefantasia), ''), btrim(d.razaosocial), '')),
       count(*)
FROM coleta c
JOIN agrupamentocliente_cnpjcpfcodigo acc
  ON acc.grupo = c.grupo AND acc.empresa = c.empresa
 AND acc.cnpjcpfcodigo = c.cnpjcpfcodigopagadorfrete AND acc.vinculo = 1
LEFT JOIN cadastro d ON d.codigo = c.destinatario
WHERE acc.codigo = %(cliente)s AND c.dtcancelamento IS NULL
  AND c.dtemissao >= current_date - 180
  AND c.destinatario IS NOT NULL
GROUP BY 2
ORDER BY 1, 4 DESC, 2
"""


def _num(v):
    return float(v) if v is not None else None


@_q.cached(ttl=180, velha_ate=_q.VELHA_ATE)
def cargas(cliente: int, de: str, ate: str) -> dict:
    """As coletas do cliente que podem cair no período, e o contrato dele.

    Traz MAIS do que o período (emissão até `FOLGA_EMISSAO_DIAS` antes): quem
    decide se a carga entra é o marco escolhido no perfil, e ele só se
    confere depois dos ajustes, que moram no banco da casa.
    """
    params = {"cliente": int(cliente), "de": de, "ate": ate,
              "folga": FOLGA_EMISSAO_DIAS}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CARGAS_SQL, params)
        linhas = [dict(r) for r in cur.fetchall()]
        cur.execute(CONTRATO_SQL, params)
        contrato = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT current_timestamp AS ts")
        ts = cur.fetchone()["ts"]
    for r in linhas:
        r["paradas"] = int(r.get("paradas") or 0)
        r["repeticoes"] = int(r.get("repeticoes") or 0)
    for ln in contrato:
        for k in ("ft_carga_h", "ft_descarga_h", "valor_coleta", "valor_entrega"):
            ln[k] = _num(ln.get(k))
        ln["ativoinativo"] = (int(ln["ativoinativo"])
                              if ln.get("ativoinativo") is not None else None)
    return {"cargas": linhas, "contrato": contrato, "lido_em": ts.isoformat()}


@_q.cached(ttl=3600, velha_ate=_q.VELHA_ATE)
def clientes() -> list[dict]:
    """Os agrupamentos de cliente do ERP, os com contrato de freetime antes."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CLIENTES_SQL)
        rs = [dict(r) for r in cur.fetchall()]
    rs.sort(key=lambda r: (not r["tem_contrato"], r["nome"]))
    return rs


@_q.cached(ttl=3600, velha_ate=_q.VELHA_ATE)
def catalogo(cliente: int) -> dict:
    """Mercadorias e destinatários do cliente em 180 dias, com a contagem."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CATALOGO_SQL, {"cliente": int(cliente)})
        rs = [dict(r) for r in cur.fetchall()]
    out = {"mercadorias": [], "destinos": []}
    for r in rs:
        item = {"codigo": r["codigo"], "nome": r["nome"] or r["codigo"],
                "n": int(r["n"] or 0)}
        out["mercadorias" if r["tipo"] == "mercadoria" else "destinos"].append(item)
    return out
