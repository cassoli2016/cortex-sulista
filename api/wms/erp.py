# -*- coding: utf-8 -*-
"""A ÚNICA porta do WMS para o Avacorp — e ela só LÊ.

`tests/wms/test_independencia.py` cobra isto pelos dois lados: nenhum outro
arquivo do módulo importa `api.db`, e o recebimento manual funciona com o ERP
fora do ar. Armazém parado porque o ERP de terceiro teve uma manhã ruim é
caminhão parado na doca.

O QUE SE BUSCA, E ONDE ESTÁ (medido em 12/09/2026)
==================================================
- A NOTA do cliente: `public.coleta_notafiscal`, índice por `chaveacessonfe`
  (a busca por chave custa 0,03 s). **A mesma chave aparece em mais de uma
  coleta** — 50.937 linhas para 46.862 chaves em 90 dias (re-coleta,
  redespacho). Escolhe-se a coleta MAIS RECENTE, e o desempate é escrito por
  inteiro (a PK toda): empate em `ORDER BY` é sorteio, e sorteio estável por
  acidente passa em todo teste.
- Os ITENS: `public.coleta_notafiscal_item` (1,48 milhão), casados pela PK da
  nota na coleta — as 8 colunas, com `sequencianotafiscal`. Casar pelas 7 da
  coleta traria os itens de TODAS as notas daquela coleta; o total inflado
  sairia plausível. `produtocliente` é o código do produto DO CLIENTE, que é
  a chave do produto no WMS. Cobertura: ~95% das notas coletadas têm item.
- O CLIENTE: `public.cadastro` (8.373), chave `codigo` = CNPJ/CPF.

O módulo WMS do próprio Avacorp (`public.wms_*`) NÃO é lido: está vazio.
"""
from __future__ import annotations

import logging

from .. import db
from ..validacao import DadoInvalido

log = logging.getLogger("cortex.wms.erp")


class ErpIndisponivel(DadoInvalido):
    """O Avacorp não respondeu. É recusa legível (409), não falha nossa: a
    tela diz para seguir com o recebimento manual."""


NF_SQL = """
SELECT n.grupo, n.empresa, n.filial, n.unidade, n.diferenciadornumero,
       n.serie, n.numero, n.sequencianotafiscal,
       trim(n.chaveacessonfe)             AS chave,
       n.numeronotafiscal                 AS nf_numero,
       trim(n.serienotafiscal)            AS nf_serie,
       n.dtemissao                        AS nf_emissao,
       trim(n.remetente)                  AS remetente,
       trim(n.destinatario)               AS destinatario,
       n.valormercadoria                  AS valor_mercadoria,
       n.pesobruto                        AS peso_kg,
       n.quantidade                       AS volumes,
       trim(n.especiemercadoria)          AS especie,
       trim(n.naturezamercadoria)         AS natureza,
       count(*) OVER ()                   AS coletas
  FROM public.coleta_notafiscal n
 WHERE n.chaveacessonfe = %s
 ORDER BY n.dtinc DESC NULLS LAST, n.grupo DESC, n.empresa DESC, n.filial DESC,
          n.unidade DESC, n.diferenciadornumero DESC, n.serie DESC,
          n.numero DESC, n.sequencianotafiscal DESC
 LIMIT 1
"""

ITENS_SQL = """
SELECT i.sequencia,
       trim(i.produtocliente)    AS codigo,
       trim(i.produtodescricao)  AS descricao,
       trim(i.produtounidade)    AS unidade,
       trim(i.produtoespecie)    AS especie,
       i.quantidade              AS qtd,
       i.pesobruto               AS peso_kg,
       i.valormercadoria         AS valor
  FROM public.coleta_notafiscal_item i
 WHERE i.grupo = %s AND i.empresa = %s AND i.filial = %s AND i.unidade = %s
   AND i.diferenciadornumero = %s AND i.serie = %s AND i.numero = %s
   AND i.sequencianotafiscal = %s
 ORDER BY i.sequencia
"""

CADASTRO_POR_CODIGO_SQL = """
SELECT trim(codigo) AS cnpj, trim(razaosocial) AS razao_social,
       trim(coalesce(nomefantasia, '')) AS nome_fantasia,
       trim(coalesce(cidade, '')) AS cidade, trim(coalesce(uf, '')) AS uf
  FROM public.cadastro
 WHERE codigo = ANY(%s)
"""

# O curinga é montado no PYTHON: `%` escrito dentro da constante vira
# placeholder do psycopg.
CADASTRO_POR_NOME_SQL = """
SELECT trim(codigo) AS cnpj, trim(razaosocial) AS razao_social,
       trim(coalesce(nomefantasia, '')) AS nome_fantasia,
       trim(coalesce(cidade, '')) AS cidade, trim(coalesce(uf, '')) AS uf
  FROM public.cadastro
 WHERE (razaosocial ILIKE %s OR nomefantasia ILIKE %s)
   AND length(trim(codigo)) IN (11, 14)
 ORDER BY razaosocial, codigo
 LIMIT %s
"""

CADASTRO_POR_PREFIXO_SQL = """
SELECT trim(codigo) AS cnpj, trim(razaosocial) AS razao_social,
       trim(coalesce(nomefantasia, '')) AS nome_fantasia,
       trim(coalesce(cidade, '')) AS cidade, trim(coalesce(uf, '')) AS uf
  FROM public.cadastro
 WHERE codigo LIKE %s
   AND length(trim(codigo)) IN (11, 14)
 ORDER BY codigo
 LIMIT %s
"""


def _num(v):
    return None if v is None else float(v)


def _curinga(texto: str) -> str:
    esc = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + esc + "%"


def _consultar(sql: str, params) -> list[dict]:
    try:
        return db.query(sql, params)
    except Exception as exc:  # noqa: BLE001 — conexão, timeout, réplica parada
        log.warning("wms.erp: %s", type(exc).__name__)
        raise ErpIndisponivel(
            "O Avacorp não respondeu agora. Siga com o recebimento manual — "
            "a nota pode ser vinculada depois.") from None


def nomes(cnpjs) -> dict[str, dict]:
    """CNPJ → cadastro do ERP, para os que existirem lá."""
    alvo = sorted({c for c in cnpjs if c})
    if not alvo:
        return {}
    return {r["cnpj"]: r for r in _consultar(CADASTRO_POR_CODIGO_SQL, (alvo,))}


def buscar_nf(chave: str) -> dict | None:
    """A nota e os itens, prontos para virar recebimento ou pedido.

    Devolve None quando a chave não está em coleta nenhuma — o que NÃO quer
    dizer que a nota não existe: só que a Sulista não a coletou. A tela diz
    isso e oferece o caminho manual.
    """
    linhas = _consultar(NF_SQL, (chave,))
    if not linhas:
        return None
    n = linhas[0]
    pk = (n["grupo"], n["empresa"], n["filial"], n["unidade"],
          n["diferenciadornumero"], n["serie"], n["numero"],
          n["sequencianotafiscal"])
    itens = _consultar(ITENS_SQL, pk)
    partes = nomes([n["remetente"], n["destinatario"]])
    return {
        "chave": n["chave"],
        "nf_numero": n["nf_numero"],
        "nf_serie": n["nf_serie"] or "",
        "nf_emissao": n["nf_emissao"].isoformat() if n["nf_emissao"] else None,
        "remetente": partes.get(n["remetente"]) or {"cnpj": n["remetente"], "razao_social": ""},
        "destinatario": partes.get(n["destinatario"]) or {"cnpj": n["destinatario"], "razao_social": ""},
        "valor_mercadoria": _num(n["valor_mercadoria"]),
        "peso_kg": _num(n["peso_kg"]),
        "volumes": _num(n["volumes"]),
        "especie": n["especie"] or "",
        "natureza": n["natureza"] or "",
        # quantas coletas carregam esta chave — a tela diz qual foi usada
        "coletas": int(n["coletas"] or 1),
        "coleta": f"{n['filial']}/{n['serie']}/{n['numero']}",
        "itens": [{"seq": i["sequencia"], "codigo": i["codigo"] or "",
                   "descricao": i["descricao"] or "", "unidade": (i["unidade"] or "UN")[:6],
                   "especie": i["especie"] or "", "qtd": _num(i["qtd"]) or 0.0,
                   "peso_kg": _num(i["peso_kg"]), "valor": _num(i["valor"])}
                  for i in itens],
    }


def buscar_cadastro(texto: str, limite: int = 20) -> list[dict]:
    """Cliente do ERP por CNPJ (ou começo dele) ou por nome."""
    t = (texto or "").strip()
    if len(t) < 3:
        raise DadoInvalido("Digite ao menos 3 letras do nome ou o começo do CNPJ.")
    lim = max(1, min(int(limite), 50))
    sem_pontuacao = "".join(ch for ch in t if ch not in ".-/ ")
    if sem_pontuacao.isdigit():
        if len(sem_pontuacao) < 8:
            raise DadoInvalido("Para buscar por CNPJ, digite ao menos os 8 dígitos da raiz.")
        return _consultar(CADASTRO_POR_PREFIXO_SQL, (sem_pontuacao + "%", lim))
    cur = _curinga(t)
    return _consultar(CADASTRO_POR_NOME_SQL, (cur, cur, lim))
