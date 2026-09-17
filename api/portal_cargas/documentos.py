# -*- coding: utf-8 -*-
"""Documentos e peso das cargas do cliente (tela `pcdoc`).

O QUE O ERP TEM, MEDIDO EM 17/09/2026 (e por que a tela diz o que falta)
======================================================================
- **NF-e da carga**: o XML autorizado (`nfeProc`) esta em
  `xmldocumentoeletronico` para ~94,5% das notas das cargas de uma semana
  (`conhecimento_notafiscal.chaveacessonfe`, casada pela chave).
- **CT-e emitido**: so ~43% tem o XML guardado, EM QUALQUER IDADE (0-2 dias,
  3-7, 8-30, 31-90: a mesma fracao) — nao e atraso de copia. Os outros estao
  autorizados na SEFAZ (lote com status 100, chave e protocolo), mas o ERP nao
  guarda o XML assinado deles: nem no lote de envio
  (`xmldocumentoeletronicolote_documento.xmldocumento` vazio nos 861 da
  semana), nem na fila de exportacao ao cliente. Nao se "monta" um CT-e a
  partir do protocolo: sem o XML assinado nao ha documento, e um arquivo
  fabricado pareceria um. A tela mostra chave e protocolo e diz que o arquivo
  nao esta disponivel.
- **Canhoto**: anexo `tipoarquivo = 105` do CT-e em `arquivo.arquivobinario`,
  presente em ~68% dos CT-e de 15 a 30 dias. O ARQUIVO nao esta no banco: o
  armazenamento e externo (`tipoarmazenamento = 2`, conteudo nulo, so o
  caminho). A tela diz QUANDO o canhoto foi anexado; baixar depende de acesso
  a esse armazenamento, que e passo seguinte.
- **Peso**: `conhecimento.pesobruto` (a carga) e `conhecimento_notafiscal.
  pesobruto` (cada nota).

O CAMINHO coleta -> CT-e e `conhecimento_composicao` (o mesmo do rastreio e do
MDF-e da Minha Operacao; `conhecimento_composicao_notafiscal` esta vazia).

O ESCOPO E UM SO
================
Toda consulta daqui recebe a raiz e passa por `portal_cliente.FILTRO_CLIENTE`
sobre a COLETA — a mesma regra da Minha Operacao. O download nao confia na
lista que a tela montou: `autorizar()` refaz o caminho coleta -> CT-e -> nota a
partir da CHAVE pedida e so devolve o XML se ela pertencer a uma carga do
cliente. Sem isso, a rota de download seria um leitor de qualquer documento
fiscal da casa para quem soubesse (ou adivinhasse) uma chave de 44 digitos —
e chave de NF-e vem impressa no DANFE que circula por ai.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from api import db
from api.portal_cliente import FILTRO_CLIENTE
from api.queries import cached

log = logging.getLogger("cortex.portal_cargas.documentos")

#: Tipo de anexo do canhoto no cadastro do ERP (`arquivo.tipoarquivobinario`,
#: descricao "CANHOTO"). O anexo pende do CT-e: `tipodocumento = 6`.
TIPO_CANHOTO = 105
TIPODOC_CTE = 6

#: Janela maxima de uma consulta de documentos, em dias. Um trimestre cobre o
#: que o cliente procura ("a nota do mes passado"); mais que isso vira
#: exportacao em massa, que e outra pergunta e outro custo no ERP.
JANELA_MAX_D = 93
JANELA_PADRAO_D = 30

RE_CHAVE = re.compile(r"^[0-9]{44}$")

# As coletas do cliente no periodo, com o CT-e de cada uma. Uma coleta pode ter
# mais de um CT-e (e um CT-e cancelado e reemitido): a linha e o CT-e, e a tela
# agrupa pela coleta.
#
# `has_xml` e `canhoto_em` por EXISTS/max sobre indices que existem:
# `uk_chave` (xmldocumentoeletronico.chaveacesso) e
# `ix_ab_tpdoc_g_e_f_u_dif_ser_num` (arquivobinario pelos 7 campos do CT-e).
CARGAS_SQL = """
SELECT c.numero                                     AS coleta,
       concat_ws('|', c.grupo, c.empresa, c.filial, c.unidade,
                 c.diferenciadornumero, c.serie, c.numero) AS coleta_chave,
       to_char(c.dtemissao,'YYYY-MM-DD')             AS coleta_emissao,
       upper(trim(coalesce(c.origem,'')))            AS origem,
       coalesce(c.uforigem,'')                       AS uf_origem,
       upper(trim(coalesce(c.destino,'')))           AS destino,
       coalesce(c.ufdestino,'')                      AS uf_destino,
       coalesce(nullif(trim(cdd.nomefantasia),''),
                nullif(trim(cdd.razaosocial),''), '') AS destinatario,
       trim(coalesce(c.numerofatura,''))             AS ref_cliente,
       k.numero                                      AS cte_numero,
       k.serie                                       AS cte_serie,
       concat_ws('|', k.grupo, k.empresa, k.filial, k.unidade,
                 k.diferenciadornumero, k.serie, k.numero) AS cte_id,
       to_char(k.dtemissao,'YYYY-MM-DD HH24:MI')     AS cte_emissao,
       trim(coalesce(k.chaveacessocte,''))           AS cte_chave,
       k.numeroprotocolocte                          AS cte_protocolo,
       (k.dtcancelamento IS NOT NULL)                AS cte_cancelado,
       k.pesobruto::float8                           AS cte_peso,
       EXISTS (SELECT 1 FROM xmldocumentoeletronico x
               WHERE x.chaveacesso = trim(k.chaveacessocte))  AS cte_tem_xml,
       (SELECT to_char(max(a.dtinc),'YYYY-MM-DD HH24:MI')
          FROM arquivo.arquivobinario a
         WHERE a.tipodocumento = %(tipodoc_cte)s AND a.tipoarquivo = %(tipo_canhoto)s
           AND a.grupo = k.grupo AND a.empresa = k.empresa AND a.filial = k.filial
           AND a.unidade = k.unidade AND a.diferenciadornumero = k.diferenciadornumero
           AND a.serie = k.serie AND a.numerosequencia = k.numero) AS canhoto_em
FROM coleta c
LEFT JOIN cadastro cdd ON cdd.codigo = c.destinatario
LEFT JOIN conhecimento_composicao cc
  ON cc.grupo = c.grupo AND cc.empresa = c.empresa
 AND cc.filialdocumento = c.filial AND cc.unidadedocumento = c.unidade
 AND cc.diferenciadornumerodocumento = c.diferenciadornumero
 AND cc.seriedocumento = c.serie AND cc.numerodocumento = c.numero
LEFT JOIN conhecimento k
  ON k.grupo = cc.grupo AND k.empresa = cc.empresa AND k.filial = cc.filial
 AND k.unidade = cc.unidade AND k.diferenciadornumero = cc.diferenciadornumero
 AND k.serie = cc.serie AND k.numero = cc.numero
WHERE c.dtcancelamento IS NULL
  AND c.dtemissao >= %(de)s::date
  AND c.dtemissao <  %(ate)s::date + 1
  AND """ + FILTRO_CLIENTE + """
ORDER BY c.dtemissao DESC, c.numero DESC, k.dtemissao DESC NULLS LAST
"""

# As NOTAS dos CT-e das mesmas coletas. Mesma raiz, mesmo periodo, mesmo filtro
# — repetido e nao passado como lista de chaves, porque uma lista montada em
# Python e UMA segunda porta para o escopo: o dia em que alguem a montar de
# outro jeito, ela deixa de ser a lista do cliente.
NOTAS_SQL = """
SELECT concat_ws('|', k.grupo, k.empresa, k.filial, k.unidade,
                 k.diferenciadornumero, k.serie, k.numero) AS cte_id,
       n.numeronotafiscal                            AS numero,
       trim(coalesce(n.chaveacessonfe,''))           AS chave,
       n.pesobruto::float8                           AS peso,
       EXISTS (SELECT 1 FROM xmldocumentoeletronico x
               WHERE x.chaveacesso = trim(n.chaveacessonfe)) AS tem_xml
FROM coleta c
JOIN conhecimento_composicao cc
  ON cc.grupo = c.grupo AND cc.empresa = c.empresa
 AND cc.filialdocumento = c.filial AND cc.unidadedocumento = c.unidade
 AND cc.diferenciadornumerodocumento = c.diferenciadornumero
 AND cc.seriedocumento = c.serie AND cc.numerodocumento = c.numero
JOIN conhecimento k
  ON k.grupo = cc.grupo AND k.empresa = cc.empresa AND k.filial = cc.filial
 AND k.unidade = cc.unidade AND k.diferenciadornumero = cc.diferenciadornumero
 AND k.serie = cc.serie AND k.numero = cc.numero
JOIN conhecimento_notafiscal n
  ON n.grupo = k.grupo AND n.empresa = k.empresa AND n.filial = k.filial
 AND n.unidade = k.unidade AND n.diferenciadornumero = k.diferenciadornumero
 AND n.serie = k.serie AND n.numero = k.numero
WHERE c.dtcancelamento IS NULL
  AND c.dtemissao >= %(de)s::date
  AND c.dtemissao <  %(ate)s::date + 1
  AND """ + FILTRO_CLIENTE + """
ORDER BY n.numeronotafiscal
"""

# A CHAVE PEDIDA pertence a uma carga do cliente? Dois caminhos, um por tipo, e
# nenhum confia no que a tela mandou alem da chave. Sem janela de data: o
# cliente pode baixar a nota de qualquer carga dele, inclusive a do ano passado.
AUTORIZA_CTE_SQL = """
SELECT 1
FROM conhecimento k
JOIN conhecimento_composicao cc
  ON cc.grupo = k.grupo AND cc.empresa = k.empresa AND cc.filial = k.filial
 AND cc.unidade = k.unidade AND cc.diferenciadornumero = k.diferenciadornumero
 AND cc.serie = k.serie AND cc.numero = k.numero
JOIN coleta c
  ON c.grupo = cc.grupo AND c.empresa = cc.empresa
 AND c.filial = cc.filialdocumento AND c.unidade = cc.unidadedocumento
 AND c.diferenciadornumero = cc.diferenciadornumerodocumento
 AND c.serie = cc.seriedocumento AND c.numero = cc.numerodocumento
WHERE trim(k.chaveacessocte) = %(chave)s
  AND """ + FILTRO_CLIENTE + """
LIMIT 1
"""

AUTORIZA_NFE_SQL = """
SELECT 1
FROM conhecimento_notafiscal n
JOIN conhecimento k
  ON k.grupo = n.grupo AND k.empresa = n.empresa AND k.filial = n.filial
 AND k.unidade = n.unidade AND k.diferenciadornumero = n.diferenciadornumero
 AND k.serie = n.serie AND k.numero = n.numero
JOIN conhecimento_composicao cc
  ON cc.grupo = k.grupo AND cc.empresa = k.empresa AND cc.filial = k.filial
 AND cc.unidade = k.unidade AND cc.diferenciadornumero = k.diferenciadornumero
 AND cc.serie = k.serie AND cc.numero = k.numero
JOIN coleta c
  ON c.grupo = cc.grupo AND c.empresa = cc.empresa
 AND c.filial = cc.filialdocumento AND c.unidade = cc.unidadedocumento
 AND c.diferenciadornumero = cc.diferenciadornumerodocumento
 AND c.serie = cc.seriedocumento AND c.numero = cc.numerodocumento
WHERE trim(n.chaveacessonfe) = %(chave)s
  AND """ + FILTRO_CLIENTE + """
LIMIT 1
"""

XML_SQL = """
SELECT tipodocumento, conteudoxml
FROM xmldocumentoeletronico
WHERE chaveacesso = %(chave)s
"""


class ForaDoEscopo(Exception):
    """A chave nao pertence a nenhuma carga do cliente. Vira 404, e nao 403:
    responder "existe, mas nao e sua" confirmaria a um estranho que a chave
    e de um documento da casa."""


class SemArquivo(Exception):
    """A carga e do cliente, mas o ERP nao guarda o XML deste documento."""


def periodo(de: str | None, ate: str | None, hoje: date | None = None) -> tuple[str, str]:
    """(de, ate) em ISO, com a janela limitada a `JANELA_MAX_D` dias.

    Datas ilegiveis caem no padrao em vez de virar erro 500: e filtro de tela,
    e o que se quer e a tela mostrando o ultimo mes. Janela maior que o teto
    e CORTADA a partir do `ate`, e o corte vai na resposta para a tela dizer.
    """
    hoje = hoje or date.today()

    def _d(s):
        try:
            return date.fromisoformat((s or "")[:10])
        except ValueError:
            return None

    d_ate = _d(ate) or hoje
    d_de = _d(de) or (d_ate - timedelta(days=JANELA_PADRAO_D - 1))
    if d_de > d_ate:
        d_de, d_ate = d_ate, d_de
    if (d_ate - d_de).days + 1 > JANELA_MAX_D:
        d_de = d_ate - timedelta(days=JANELA_MAX_D - 1)
    return d_de.isoformat(), d_ate.isoformat()


def _param(raiz: str, de: str, ate: str) -> dict:
    return {"raiz": raiz, "de": de, "ate": ate,
            "tipodoc_cte": TIPODOC_CTE, "tipo_canhoto": TIPO_CANHOTO}


def montar(cargas_linhas: list[dict], notas_linhas: list[dict]) -> dict:
    """Agrupa as linhas do ERP em cargas -> CT-e -> notas, e soma os indicadores.

    Separado da consulta para ser testado sem banco. O payload e uma lista
    EXPLICITA de campos, nunca `dict(linha)`: coluna nova no ERP nao pode virar
    campo na tela de um cliente sem ninguem decidir.
    """
    notas_por_cte: dict[str, list[dict]] = {}
    for n in notas_linhas:
        notas_por_cte.setdefault(n["cte_id"], []).append({
            "numero": n["numero"], "chave": n["chave"] or None,
            "peso_kg": n["peso"], "tem_xml": bool(n["tem_xml"]),
        })

    cargas: dict[str, dict] = {}
    for r in cargas_linhas:
        c = cargas.setdefault(r["coleta_chave"], {
            "coleta": r["coleta"], "emissao": r["coleta_emissao"],
            "origem": r["origem"], "uf_origem": r["uf_origem"],
            "destino": r["destino"], "uf_destino": r["uf_destino"],
            "destinatario": r["destinatario"] or None,
            "ref_cliente": r["ref_cliente"] or None,
            "ctes": [],
        })
        if r["cte_numero"] is None:
            continue
        c["ctes"].append({
            "numero": r["cte_numero"], "serie": r["cte_serie"],
            "emissao": r["cte_emissao"], "chave": r["cte_chave"] or None,
            "protocolo": str(r["cte_protocolo"]) if r["cte_protocolo"] else None,
            "cancelado": bool(r["cte_cancelado"]),
            "peso_kg": r["cte_peso"],
            "tem_xml": bool(r["cte_tem_xml"]),
            "canhoto_em": r["canhoto_em"],
            "notas": notas_por_cte.get(r["cte_id"], []),
        })

    lista = list(cargas.values())
    validos = [t for c in lista for t in c["ctes"] if not t["cancelado"]]
    for c in lista:
        vivos = [t for t in c["ctes"] if not t["cancelado"]]
        # PESO DA CARGA = soma dos CT-e VALIDOS. O cancelado nao transportou
        # nada; somado, dobraria o peso da carga que foi reemitida.
        pesos = [t["peso_kg"] for t in vivos if t["peso_kg"]]
        c["peso_kg"] = round(sum(pesos), 1) if pesos else None
        c["notas"] = sum(len(t["notas"]) for t in vivos)
        c["canhoto"] = (all(t["canhoto_em"] for t in vivos) if vivos else None)
    notas = [n for t in validos for n in t["notas"]]
    peso_total = sum(t["peso_kg"] or 0 for t in validos)
    return {
        "cargas": lista,
        "kpis": {
            "cargas": len(lista),
            "sem_cte": sum(1 for c in lista if not any(not t["cancelado"] for t in c["ctes"])),
            "peso_kg": round(peso_total, 1),
            "ctes": len(validos),
            "ctes_com_xml": sum(1 for t in validos if t["tem_xml"]),
            "notas": len(notas),
            "notas_com_xml": sum(1 for n in notas if n["tem_xml"]),
            "canhotos": sum(1 for t in validos if t["canhoto_em"]),
        },
    }


@cached(ttl=300, velha_ate=7200)
def get_documentos(raiz: str, de: str, ate: str) -> dict:
    """Cargas do cliente no periodo, com CT-e, notas, peso e canhoto.

    Com rede de leitura velha: a menor faixa desta tela e o DIA (documento
    emitido, canhoto anexado), e uma leitura de duas horas atras nao muda o
    que ela afirma. Diferente da Minha Operacao, que diz onde a carga esta
    AGORA.
    """
    p = _param(raiz, de, ate)
    linhas = db.query(CARGAS_SQL, p)
    notas = db.query(NOTAS_SQL, p) if linhas else []
    return {**montar(linhas, notas), "periodo": {"de": de, "ate": ate}}


def autorizar(raiz: str, chave: str) -> str:
    """'cte' ou 'nfe' se a chave e de uma carga do cliente; senao levanta.

    A chave e so digitos e 44 deles, conferido ANTES de ir ao banco: e o
    parametro que o cliente controla, e nao ha motivo para o ERP ver outra
    coisa.
    """
    chave = (chave or "").strip()
    if not RE_CHAVE.match(chave):
        raise ForaDoEscopo("chave invalida")
    p = {"raiz": raiz, "chave": chave}
    if db.query(AUTORIZA_CTE_SQL, p):
        return "cte"
    if db.query(AUTORIZA_NFE_SQL, p):
        return "nfe"
    raise ForaDoEscopo("chave fora das cargas do cliente")


def xml_autorizado(raiz: str, chave: str) -> tuple[str, str]:
    """(tipo, xml) de um documento do cliente. Levanta ForaDoEscopo/SemArquivo.

    O TIPO vem da AUTORIZACAO (por qual caminho a chave casou), nao do XML:
    uma chave de NF-e nao pode ser servida como CT-e so porque alguem
    guardou o arquivo com o tipo trocado.
    """
    tipo = autorizar(raiz, chave)
    linhas = db.query(XML_SQL, {"chave": chave})
    xml = (linhas[0]["conteudoxml"] if linhas else "") or ""
    if not xml.strip():
        raise SemArquivo(
            "O CT-e está autorizado, mas o arquivo XML dele não está guardado "
            "no sistema. A consulta pela chave no portal da SEFAZ mostra o "
            "documento." if tipo == "cte" else
            "O XML desta nota não está guardado no sistema.")
    return tipo, xml


def nome_arquivo(tipo: str, chave: str, formato: str) -> str:
    prefixo = {"cte": "CTe", "nfe": "NFe"}.get(tipo, "doc")
    return f"{prefixo}-{chave}.{'pdf' if formato == 'pdf' else 'xml'}"


def pdf(tipo: str, xml: str) -> bytes:
    """DACTE/DANFE a partir do XML autorizado — o mesmo gerador da tela `dfe`.

    O `completo=True` e verdade aqui por construcao: o que o ERP guarda em
    `xmldocumentoeletronico` e o `cteProc`/`nfeProc`, com protocolo (conferido
    em 17/09/2026). Se um dia vier sem, a biblioteca recusa e a rota diz.
    """
    from api.sefaz import impressao
    return impressao.gerar({"tipo": tipo, "completo": True, "origem": "erp"}, xml)
