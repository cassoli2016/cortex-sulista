# -*- coding: utf-8 -*-
"""Ler o lote da SEFAZ: do XML cru para as linhas que a casa guarda.

FUNÇÃO PURA SOBRE TEXTO. Nada aqui abre conexão, nada aqui grava. É o que
permite testar contra o corpo REAL do serviço — e dublê de fornecedor copia o
corpo real, campos "inúteis" inclusive.

O QUE A SEFAZ DEVOLVE, E POR QUE ISSO NÃO É UM FORMATO SÓ
=========================================================

Cada `docZip` do lote traz um `schema` que diz o que tem dentro. Os quatro que
importam:

    resNFe_v1.01        RESUMO de NF-e — chave, emitente, valor, situação.
                        É o que chega ANTES da manifestação de ciência.
    procNFe_v4.00       a NF-e INTEIRA, autorizada. Só vem DEPOIS da ciência.
    resEvento_v1.01     resumo de um evento (cancelamento, carta de correção…)
    procEventoNFe_v1.00 o evento inteiro

Tratar tudo como "NF-e" faria o cancelamento virar uma nota nova; ignorar o que
não se conhece faria o CT-e sumir. Por isso o `esquema` é GUARDADO CRU: um
documento que o parser de hoje não entende continua no banco, com o XML
inteiro, e pode ser relido quando alguém ensinar o parser.

O CONTEÚDO VEM COMPRIMIDO (gzip, base64). Não é detalhe de transporte: é onde
mora o XML que a casa tem de guardar por cinco anos.
"""
from __future__ import annotations

import base64
import gzip
import logging
import re
from datetime import datetime

log = logging.getLogger("cortex.sefaz.leitura")

#: `schema` → (tipo, é o documento COMPLETO?)
#:
#: A comparação é por PREFIXO porque a SEFAZ versiona no próprio campo
#: (`procNFe_v4.00`); casar a string inteira quebraria na primeira versão nova,
#: e quebraria em silêncio — o documento viraria "desconhecido" e sumiria da
#: tela sem erro nenhum.
ESQUEMAS: tuple[tuple[str, str, bool], ...] = (
    ("procNFe", "nfe", True),
    ("resNFe", "nfe", False),
    ("procCTe", "cte", True),
    ("resCTe", "cte", False),
    ("procEventoNFe", "evento", True),
    ("resEvento", "evento", False),
    ("procEventoCTe", "evento", True),
)


def classificar(esquema: str) -> tuple[str, bool]:
    """(tipo, completo) a partir do `schema` que a SEFAZ carimbou."""
    e = (esquema or "").strip()
    for prefixo, tipo, completo in ESQUEMAS:
        if e.startswith(prefixo):
            return tipo, completo
    return "desconhecido", False


class DocumentoVazio(ValueError):
    """O `docZip` chegou (ou saiu) sem conteúdo."""


def descomprimir(conteudo: str) -> str:
    """O `docZip` é gzip em base64. Devolve o XML em texto.

    VAZIO É ERRO, E PRECISA SER DITO — porque o Python NÃO o diz.
    `gzip.decompress(b"")` devolve `b""` em vez de levantar, então um conteúdo
    ausente atravessa esta função inteira sem um arranhão e vira uma linha no
    banco com `xml = ''`.

    Foi exatamente o que aconteceu em 07/09/2026: o atributo do binding tinha
    outro nome (`valueOf_`), o conteúdo veio vazio, e a recolha gravou 510
    documentos com XML VAZIO. Contagem certa, tela cheia, guarda de cinco anos
    vazia — e nenhum erro em lugar nenhum. Um documento sem XML não é um
    documento: é a ausência dele com a aparência de presença.
    """
    if not (conteudo or "").strip():
        raise DocumentoVazio("docZip sem conteúdo")
    xml = gzip.decompress(base64.b64decode(conteudo)).decode("utf-8", errors="replace")
    if not xml.strip():
        raise DocumentoVazio("docZip descomprimiu para vazio")
    return xml


def _tag(xml: str, nome: str) -> str | None:
    """O conteúdo da PRIMEIRA ocorrência de uma tag simples.

    Regex e não parser de XML de propósito: aqui se lê meia dúzia de campos
    escalares de um documento cuja forma canônica já está GUARDADA INTEIRA no
    banco. Montar a árvore de uma NF-e de 300 linhas para ler o valor total
    seria pagar caro por precisão que não muda nada — e o XML fica lá para quem
    precisar do resto.
    """
    m = re.search(r"<%s>([^<]*)</%s>" % (nome, nome), xml)
    return m.group(1).strip() if m else None


def _data(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _valor(v: str | None) -> float | None:
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _chave(xml: str) -> str | None:
    """A chave de acesso: 44 dígitos.

    Procura a TAG primeiro (`chNFe`/`chCTe`) e só depois cai no `Id` do
    documento assinado — que vem com o prefixo `NFe`/`CTe` colado. Inverter a
    ordem funcionaria hoje e passaria a pegar a chave do EVENTO em vez da nota
    no dia em que os dois viessem juntos.
    """
    for tag in ("chNFe", "chCTe"):
        v = _tag(xml, tag)
        if v and len(re.sub(r"[^0-9]", "", v)) == 44:
            return re.sub(r"[^0-9]", "", v)
    m = re.search(r'Id="(?:NFe|CTe)(\d{44})"', xml)
    return m.group(1) if m else None


def ler_documento(esquema: str, xml: str) -> dict:
    """Os escalares de um documento do lote. Nunca levanta."""
    tipo, completo = classificar(esquema)
    d: dict = {"esquema": esquema, "tipo": tipo, "completo": completo,
               "xml": xml, "chave": _chave(xml)}
    try:
        # CNPJ do emitente: no resumo vem em <CNPJ> dentro de <resNFe>; no
        # documento completo, dentro de <emit>. Os dois casam com a mesma tag,
        # e a PRIMEIRA ocorrência é a certa nos dois — o destinatário vem
        # depois no XML da NF-e.
        d["emitente"] = _tag(xml, "CNPJ")
        d["emitente_nome"] = _tag(xml, "xNome")
        d["valor"] = _valor(_tag(xml, "vNF") or _tag(xml, "vTPrest"))
        # A DATA DEPENDE DO QUE O DOCUMENTO E. Nota tem `dhEmi`; EVENTO tem
        # `dhEvento`, e so ele -- procurar `dhEmi` num `resEvento` devolve None
        # e a linha aparece sem data nenhuma na tela. Foi o que aconteceu na
        # primeira recolha com conteudo real: cinco eventos, cinco linhas
        # mudas.
        d["emitido_em"] = _data(_tag(xml, "dhEmi") or _tag(xml, "dEmi")
                                or _tag(xml, "dhEvento"))
        # `xEvento` e a frase que a PROPRIA SEFAZ escreve ("Cancelamento",
        # "Registro de Passagem Automatico Originado MDFe"). Guarda-la e melhor
        # que traduzir `tpEvento` numa tabela nossa: codigo sem tabela de
        # dominio nao vira rotulo inventado -- e aqui o rotulo veio junto.
        d["descricao"] = _tag(xml, "xEvento") or _tag(xml, "descEvento")
        d["evento_tipo"] = _tag(xml, "tpEvento")
        # SITUAÇÃO VEM DO CAMPO, nunca da ausência de outro. `cSitNFe` é
        # 1 autorizada / 2 denegada / 3 cancelada; num documento completo a
        # situação está no protocolo (`cStat` 100 = autorizada).
        d["situacao"] = _tag(xml, "cSitNFe") or _tag(xml, "cSitCTe")
        if d["situacao"] is None and completo:
            d["situacao"] = _tag(xml, "cStat")
    except Exception as exc:  # noqa: BLE001
        # Um documento que o parser não entende NÃO pode derrubar o lote: o XML
        # já está aqui e é ele que tem de ser guardado. O tipo da exceção, e
        # nunca o texto — a chave de acesso é dado de terceiro.
        log.warning("sefaz: leitura de %s falhou: %s", esquema, type(exc).__name__)
    return d


def ler_lote(docs: list[dict]) -> list[dict]:
    """`[{nsu, schema, conteudo_base64}]` → linhas prontas para gravar.

    Documento que falha ao descomprimir NÃO derruba os outros: numa varredura
    de 4.000, um byte torto no meio não pode custar a leva inteira — e o NSU
    dele fica de fora do avanço, para ser tentado de novo.
    """
    saida = []
    for doc in docs:
        try:
            xml = descomprimir(doc["conteudo"])
        except Exception as exc:  # noqa: BLE001
            log.warning("sefaz: NSU %s nao descomprimiu: %s",
                        doc.get("nsu"), type(exc).__name__)
            continue
        linha = ler_documento(doc.get("esquema") or "", xml)
        linha["nsu"] = doc.get("nsu")
        saida.append(linha)
    return saida
