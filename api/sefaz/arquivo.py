# -*- coding: utf-8 -*-
"""O XML que chega POR FORA da caixa da SEFAZ — arquivo solto, .zip, anexo.

POR QUE ESTA PORTA EXISTE
=========================

A caixa da SEFAZ só entrega documento em que a Sulista é PARTE — destinatária,
transportadora, emitente ou tomadora. Isso não é configuração, é fronteira
legal: o serviço de Distribuição de DFe responde por CNPJ, e o que não diz
respeito àquele CNPJ não sai de lá para ninguém.

E a operação precisa de XML de nota em que a Sulista **não é parte nenhuma** —
a carga de um cliente que ela vai transportar num CT-e que ainda nem existe, a
nota que o embarcador manda antes de fechar o frete. Quando é assim, as pessoas
mandam o arquivo por e-mail, para `xml@sulista.com.br`. Esta é a segunda porta
da recolha, e ela não substitui a primeira: a da SEFAZ é automática e completa
para o que é nosso; esta é humana e cobre o que nunca vai chegar por lá.

O QUE ENTRA, E O QUE FICA DE FORA
---------------------------------

Entra o que se declara documento fiscal na PRÓPRIA RAIZ do XML (`nfeProc`,
`NFe`, `cteProc`, `mdfeProc`, `procEventoNFe`…). Não é rigor de arquiteto: o
endereço é público, qualquer um escreve para ele, e sem esse filtro a tabela
enche de assinatura de e-mail em HTML, boleto em XML e resposta automática de
férias. O root é a única coisa no arquivo que diz o que ele é sem depender de
adivinhação.

O que fica de fora **não some em silêncio**: cada mensagem lida guarda quantos
anexos vieram, quantos viraram documento e quantos foram ignorados. Mensagem
que chegou e não virou nada é uma linha que alguém precisa ver — senão quem
mandou acha que mandou e a operação acha que não veio.

A IDENTIDADE É O ARQUIVO
------------------------

`sha256` do XML (já decodificado para texto e sem espaço nas pontas). O mesmo
documento chega várias vezes por construção: o fornecedor manda, o cliente
reencaminha, alguém responde a todos. Byte igual, uma linha.

Dois arquivos DIFERENTES da mesma chave continuam dois, e isso é deliberado: a
nota sem protocolo e a autorizada são documentos diferentes, e o cancelamento é
outro documento ainda. Fundir pela chave apagaria um deles — e o que a lei
manda guardar por cinco anos é o arquivo, não a linha de tabela.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile

from .. import pglocal
from . import armazenamento as arm
from . import leitura

log = logging.getLogger("cortex.sefaz.arquivo")

#: Teto por arquivo. Uma NF-e tem 5 a 15 KB; um CT-e, menos. 4 MB dá folga de
#: duas ordens de grandeza para uma nota gigante e ainda barra o anexo que não
#: é nota nenhuma.
MAX_XML = 4 * 1024 * 1024

#: Teto de arquivos dentro de UM `.zip`. Lote mensal de fornecedor chega com
#: centenas; mil é generoso. O limite existe pelo zip que se expande sozinho
#: (um `.zip` de 40 KB pode declarar milhões de arquivos).
MAX_NO_ZIP = 1000

#: Teto do que sai de um `.zip` inteiro, DESCOMPRIMIDO. Sem ele, `MAX_NO_ZIP`
#: não protege: um único membro pode declarar gigabytes.
MAX_ZIP_ABERTO = 64 * 1024 * 1024

#: raiz do XML → o `esquema` equivalente ao que a SEFAZ carimbaria.
#:
#: A tradução existe para o resto do módulo não precisar saber de onde o
#: documento veio: `leitura.classificar()` continua sendo o único lugar que
#: decide tipo e completude, e ela fala a língua da SEFAZ.
#:
#: `NFe`/`CTe`/`MDFe` (sem `proc`) são o documento assinado SEM o protocolo de
#: autorização. Eles existem no mundo real — vários ERPs exportam assim — e não
#: são o que a guarda de cinco anos pede: falta a prova de que a SEFAZ aceitou.
#: Por isso entram como INCOMPLETOS, e a tela diz "sem protocolo" em vez de
#: "só resumo", que é outra coisa.
RAIZES: dict[str, str] = {
    "nfeProc": "procNFe_v4.00",
    "NFe": "NFe",
    "cteProc": "procCTe_v4.00",
    "CTe": "CTe",
    "mdfeProc": "procMDFe_v3.00",
    "MDFe": "MDFe",
    "procEventoNFe": "procEventoNFe_v1.00",
    "procEventoCTe": "procEventoCTe_v1.00",
    "procEventoMDFe": "procEventoMDFe_v1.00",
    "eventoNFe": "eventoNFe",
    "evento": "evento",
    "resNFe": "resNFe_v1.01",
    "resEvento": "resEvento_v1.01",
}


class NaoEDocumento(ValueError):
    """O arquivo não se declara documento fiscal na raiz."""


def texto(bruto: bytes) -> str:
    """Bytes → texto, na ordem que os arquivos reais pedem.

    XML de nota chega em UTF-8 e em ISO-8859-1, e a declaração no topo mente
    com frequência (arquivo salvo por editor que reconverteu e não reescreveu a
    linha). Tentar UTF-8 primeiro e cair em latin-1 acerta os dois casos, e
    latin-1 nunca levanta — o que garante que um arquivo torto vira texto
    estranho, e não uma exceção que derruba o lote inteiro.
    """
    for cod in ("utf-8-sig", "utf-8"):
        try:
            return bruto.decode(cod)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1")


def raiz(xml: str) -> str:
    """O nome da tag raiz, sem prefixo de namespace e sem atributos."""
    # Pula declaração, comentários e instruções de processamento até a primeira
    # tag de verdade.
    for m in re.finditer(r"<([A-Za-z_][\w.-]*(?::[\w.-]+)?)", xml):
        nome = m.group(1)
        if nome.lower().startswith("?xml") or nome.startswith("!"):
            continue
        return nome.split(":")[-1]
    return ""


def esquema_do_xml(xml: str) -> str:
    """O `esquema` no vocabulário da SEFAZ, a partir da raiz do arquivo.

    Levanta `NaoEDocumento` para o que não é documento fiscal — que é o caso
    comum numa caixa postal aberta.
    """
    r = raiz(xml)
    esquema = RAIZES.get(r)
    if not esquema:
        raise NaoEDocumento("raiz %r não é documento fiscal" % (r or "?"))
    return esquema


def _tem_protocolo(xml: str) -> bool:
    """Tem a prova de autorização dentro? (`protNFe`/`protCTe`/`protMDFe`)

    O `nfeProc` que um ERP exporta em geral tem; o `NFe` cru nunca tem. Vale
    conferir mesmo quando a raiz diz `proc`, porque arquivo montado à mão
    existe — e é o protocolo que separa "documento autorizado" de "arquivo com
    cara de documento".
    """
    return bool(re.search(r"<(?:prot(?:NFe|CTe|MDFe)|infProt)\b", xml))


def _sha(xml: str) -> str:
    return hashlib.sha256(xml.strip().encode("utf-8")).hexdigest()


def ler(xml: str) -> dict:
    """Um XML solto → a linha pronta para gravar. Levanta `NaoEDocumento`."""
    if not (xml or "").strip():
        raise NaoEDocumento("arquivo vazio")
    if len(xml.encode("utf-8", errors="ignore")) > MAX_XML:
        raise NaoEDocumento("arquivo acima de %d MB" % (MAX_XML // (1024 * 1024)))
    esquema = esquema_do_xml(xml)
    d = leitura.ler_documento(esquema, xml)
    # COMPLETO É "TEM O PROTOCOLO", e não "a raiz diz proc". A diferença
    # aparece na tela como "XML completo" × "sem protocolo", e ela é a diferença
    # entre a guarda cumprida e um arquivo que ainda não prova nada.
    if d["tipo"] != "evento":
        d["completo"] = _tem_protocolo(xml)
    d["sha256"] = _sha(xml)
    d["xml"] = xml.strip()
    return d


def do_arquivo(nome: str, bruto: bytes) -> tuple[list[dict], list[str]]:
    """`(documentos, ignorados)` de um anexo — `.xml` ou `.zip` de `.xml`.

    Um anexo ruim NÃO derruba os outros: numa mensagem com quinze notas e um
    PDF, o PDF sai na lista de ignorados e as quinze entram. É a mesma regra do
    lote da SEFAZ, pela mesma razão — o que se perde num `except` largo é
    exatamente o documento que ninguém vai notar faltando.
    """
    nome = nome or "(sem nome)"
    baixo = nome.lower()
    if baixo.endswith(".zip") or bruto[:2] == b"PK":
        return _do_zip(nome, bruto)
    try:
        return [ler(texto(bruto))], []
    except NaoEDocumento as exc:
        return [], ["%s: %s" % (nome, exc)]
    except Exception as exc:  # noqa: BLE001
        log.warning("arquivo: %s falhou (%s)", nome, type(exc).__name__)
        return [], ["%s: %s" % (nome, type(exc).__name__)]


def _do_zip(nome: str, bruto: bytes) -> tuple[list[dict], list[str]]:
    docs: list[dict] = []
    fora: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(bruto))
    except Exception as exc:  # noqa: BLE001
        return [], ["%s: não abriu como .zip (%s)" % (nome, type(exc).__name__)]
    with z:
        membros = [i for i in z.infolist() if not i.is_dir()]
        if len(membros) > MAX_NO_ZIP:
            return [], ["%s: %d arquivos dentro (teto de %d)"
                        % (nome, len(membros), MAX_NO_ZIP)]
        # O TAMANHO DECLARADO, ANTES DE ABRIR. Conferir depois de extrair é
        # conferir com o disco já cheio: um .zip de 40 KB pode declarar
        # gigabytes, e `read()` os entrega.
        if sum(i.file_size for i in membros) > MAX_ZIP_ABERTO:
            return [], ["%s: conteúdo descomprimido acima de %d MB"
                        % (nome, MAX_ZIP_ABERTO // (1024 * 1024))]
        for info in membros:
            interno = "%s › %s" % (nome, info.filename)
            if not info.filename.lower().endswith(".xml"):
                fora.append("%s: não é .xml" % interno)
                continue
            try:
                docs.append(ler(texto(z.read(info))))
            except NaoEDocumento as exc:
                fora.append("%s: %s" % (interno, exc))
            except Exception as exc:  # noqa: BLE001
                log.warning("arquivo: %s falhou (%s)", interno, type(exc).__name__)
                fora.append("%s: %s" % (interno, type(exc).__name__))
    return docs, fora


# ============================================================== a gravação

_INSERT = """
INSERT INTO dfe_arquivo (sha256, origem, esquema, tipo, chave, completo,
                         emitente, emitente_nome, destinatario, valor,
                         emitido_em, situacao, descricao, evento_tipo, xml,
                         arquivo_nome, remetente, mensagem_id, assunto)
VALUES (%(sha256)s, %(origem)s, %(esquema)s, %(tipo)s, %(chave)s, %(completo)s,
        %(emitente)s, %(emitente_nome)s, %(destinatario)s, %(valor)s,
        %(emitido_em)s, %(situacao)s, %(descricao)s, %(evento_tipo)s, %(xml)s,
        %(arquivo_nome)s, %(remetente)s, %(mensagem_id)s, %(assunto)s)
ON CONFLICT (sha256) DO NOTHING
RETURNING sha256
"""


def guardar(doc: dict, *, origem: str, arquivo_nome: str = "",
            remetente: str = "", mensagem_id: str = "",
            assunto: str = "") -> str:
    """Grava um documento vindo de fora. Devolve 'novo' ou 'repetido'.

    NUNCA SOBRESCREVE. Diferente da caixa da SEFAZ — onde o mesmo NSU volta com
    conteúdo melhor e o resumo dá lugar ao completo —, aqui a chave primária é o
    próprio arquivo: conteúdo diferente é outra linha, conteúdo igual é o mesmo
    arquivo. Não existe "melhorar" uma linha, então não existe UPDATE.
    """
    if not (doc.get("xml") or "").strip():
        # A LIÇÃO DOS 510 VAZIOS, do outro lado da casa: documento sem XML não
        # é documento, é a ausência dele com aparência de presença.
        raise ValueError("XML vazio não se guarda")
    dados = {
        "sha256": doc.get("sha256") or _sha(doc["xml"]),
        "origem": origem,
        "esquema": doc.get("esquema"),
        "tipo": doc.get("tipo") or "desconhecido",
        "chave": doc.get("chave"),
        "completo": bool(doc.get("completo")),
        "emitente": doc.get("emitente"),
        "emitente_nome": doc.get("emitente_nome"),
        "destinatario": doc.get("destinatario"),
        "valor": doc.get("valor"),
        "emitido_em": doc.get("emitido_em"),
        "situacao": doc.get("situacao"),
        "descricao": doc.get("descricao"),
        "evento_tipo": doc.get("evento_tipo"),
        "xml": doc["xml"],
        "arquivo_nome": arquivo_nome or None,
        "remetente": remetente or None,
        "mensagem_id": mensagem_id or None,
        "assunto": assunto or None,
    }
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute(_INSERT, dados)
        return "novo" if cur.fetchone() else "repetido"


def guardar_lote(docs: list[dict], **kw) -> dict:
    """Grava vários e devolve o placar. Um documento ruim não leva os outros."""
    novos = repetidos = falhas = 0
    for d in docs:
        try:
            if guardar(d, **kw) == "novo":
                novos += 1
            else:
                repetidos += 1
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            log.warning("arquivo: gravar falhou (%s)", type(exc).__name__)
    return {"novos": novos, "repetidos": repetidos, "falhas": falhas}


def xml_de(sha256: str) -> str | None:
    """O XML guardado, pelo sha."""
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("SELECT xml FROM dfe_arquivo WHERE sha256 = %s",
                    ((sha256 or "").strip().lower(),))
        linha = cur.fetchone()
    return linha["xml"] if linha else None


def linha_de(sha256: str) -> dict | None:
    """A linha (sem o XML) de um arquivo guardado — o que a folha precisa saber.

    Sem o XML de propósito: quem vai imprimir pede o XML pela `xml_de()`, e
    quem só quer saber o que é o documento não carrega 15 KB para isso.
    """
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT sha256, origem, esquema, tipo, chave, completo, emitente, "
            "       emitente_nome, destinatario, valor::float8 AS valor, "
            "       emitido_em, situacao, descricao, evento_tipo, "
            "       arquivo_nome, remetente, assunto, recebido_em "
            "FROM dfe_arquivo WHERE sha256 = %s",
            ((sha256 or "").strip().lower(),))
        linha = cur.fetchone()
    return dict(linha) if linha else None


def resumo() -> dict:
    """Quantos arquivos entraram por fora, e por qual porta."""
    with pglocal.get_conn(arm._esq()) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE origem = 'email')  AS email,
                   count(*) FILTER (WHERE origem = 'upload') AS upload,
                   count(*) FILTER (WHERE completo)          AS completos,
                   max(recebido_em)                          AS ultimo
              FROM dfe_arquivo""")
        d = dict(cur.fetchone() or {})
    ultimo = d.get("ultimo")
    return {"total": d.get("total") or 0, "email": d.get("email") or 0,
            "upload": d.get("upload") or 0, "completos": d.get("completos") or 0,
            "ultimo": ultimo.isoformat() if ultimo is not None else None}
