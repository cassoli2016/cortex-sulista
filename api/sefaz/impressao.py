# -*- coding: utf-8 -*-
"""A representação gráfica do documento: DANFE, DACTE, DAMDFE, DACCE.

O QUE É ISTO, E O QUE NÃO É
===========================

O documento fiscal É o XML. O PDF é a **representação gráfica** dele — e
qualquer um que tenha o XML autorizado pode gerá-la; ela não é um segundo
documento nem precisa vir do emitente. É por isso que isto pode existir aqui.

O QUE ELE RESOLVE: o XML não se lê. Quem precisa conferir uma nota, anexar num
processo ou mandar para alguém precisa da folha — e é exatamente o que o
NSDocs cobra para fazer.

BIBLIOTECA, E NÃO LAYOUT À MÃO
------------------------------

O DANFE tem layout NORMATIVO (Manual de Orientação do Contribuinte): posição de
cada bloco, código de barras da chave, canhoto, cálculo do imposto. Desenhar
isso à mão é semanas, e o resultado erra em detalhes que só aparecem numa
fiscalização. `brazilfiscalreport` faz os quatro e é mantida para acompanhar as
notas técnicas.

SÓ COM O DOCUMENTO COMPLETO
---------------------------

Um `resNFe` tem chave, emitente e valor — e mais nada. Não há como desenhar
DANFE de um resumo: sairia uma folha com o cabeçalho preenchido e o corpo
vazio, que é pior que não sair, porque PARECE uma nota. Documento incompleto
recusa aqui, com o motivo.
"""
from __future__ import annotations

import logging

log = logging.getLogger("cortex.sefaz.impressao")

#: `tipo` do documento → (classe da biblioteca, nome do arquivo)
#:
#: O CT-e e o MDF-e chegam pela MESMA porta da nota, e a Sulista é
#: transportadora: o DACTE e o DAMDFE são os que ela mais imprime. Cobrir só a
#: NF-e deixaria de fora justamente o documento da casa.
_POR_TIPO = {
    "nfe": ("danfe", "Danfe", "DANFE"),
    "cte": ("dacte", "Dacte", "DACTE"),
    "mdfe": ("damdfe", "Damdfe", "DAMDFE"),
}


class NaoImprimivel(ValueError):
    """O documento não tem como virar folha — e o motivo importa."""


def _classe(tipo: str):
    alvo = _POR_TIPO.get(tipo)
    if not alvo:
        raise NaoImprimivel(
            "Não há representação gráfica para documento do tipo %r. Evento "
            "(cancelamento, passagem, carta de correção) não vira folha "
            "própria: ele se lê NA nota que alterou." % tipo)
    modulo, classe, _rotulo = alvo
    import importlib
    return getattr(importlib.import_module("brazilfiscalreport." + modulo), classe)


def rotulo(tipo: str) -> str:
    return (_POR_TIPO.get(tipo) or ("", "", "documento"))[2]


def gerar(documento: dict, xml: str) -> bytes:
    """O PDF de um documento guardado. Levanta `NaoImprimivel` com o motivo.

    `documento` é a linha do banco (para saber o tipo e dizer um erro útil);
    `xml` é o conteúdo, que é o que a biblioteca lê.
    """
    if not (xml or "").strip():
        raise NaoImprimivel("O documento está guardado sem XML.")
    if not documento.get("completo"):
        # A RECUSA É O SERVIÇO AQUI. Uma folha com cabeçalho e corpo vazio
        # PARECE uma nota, e quem a recebe só descobre o problema depois.
        #
        # E O MOTIVO DEPENDE DA PORTA POR ONDE O DOCUMENTO ENTROU. Os dois
        # casos são "falta o XML completo" e são coisas diferentes: da SEFAZ,
        # falta a MANIFESTAÇÃO (e há o que fazer sobre isso); do e-mail, falta
        # o PROTOCOLO no arquivo que a pessoa mandou (e o que se faz é pedir o
        # arquivo certo a ela). Dar a explicação da caixa da SEFAZ para um
        # arquivo de e-mail manda alguém procurar uma manifestação que não
        # existe.
        if (documento.get("origem") or "sefaz") != "sefaz":
            raise NaoImprimivel(
                "Este arquivo é o documento SEM o protocolo de autorização — "
                "veio assim de quem mandou. A folha só se gera a partir do XML "
                "autorizado; peça a quem enviou o arquivo com o protocolo "
                "(o que começa com <nfeProc>, e não com <NFe>).")
        raise NaoImprimivel(
            "Este documento chegou só como RESUMO — a SEFAZ entrega a nota "
            "inteira apenas depois da manifestação de ciência. Sem o XML "
            "completo não há o que imprimir: sairia uma folha com o cabeçalho "
            "preenchido e o corpo vazio.")

    Classe = _classe(documento.get("tipo") or "")
    try:
        pdf = Classe(xml=xml)
        saida = pdf.output()
    except NaoImprimivel:
        raise
    except Exception as exc:  # noqa: BLE001
        # O TIPO, nunca o texto: o XML inteiro entra na mensagem de algumas
        # falhas da biblioteca, e ele carrega CNPJ, endereço e itens.
        log.warning("dfe: %s falhou (%s)", rotulo(documento.get("tipo") or ""),
                    type(exc).__name__)
        raise NaoImprimivel(
            "Não foi possível montar o %s deste documento (%s). O XML está "
            "guardado e pode ser baixado."
            % (rotulo(documento.get("tipo") or ""), type(exc).__name__))
    # `output()` devolve bytes ou bytearray dependendo da versão do fpdf.
    return bytes(saida)


def nome_do_arquivo(documento: dict) -> str:
    """`<chave>.pdf` — a chave é o nome que todo sistema fiscal espera."""
    base = documento.get("chave") or ("nsu-%s" % documento.get("nsu", ""))
    return "%s.pdf" % base
