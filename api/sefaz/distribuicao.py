# -*- coding: utf-8 -*-
"""A recolha: o laço de NSU contra o serviço nacional de Distribuição de DFe.

É AQUI QUE SE FALA COM A SEFAZ, e é o único arquivo do módulo que faz isso —
`leitura.py` é puro sobre texto e `armazenamento.py` puro sobre banco. A
separação não é arrumação: é o que permite testar o laço inteiro com um dublê
que devolve o CORPO REAL do serviço, sem certificado e sem rede.

OS CÓDIGOS QUE DECIDEM O LAÇO
=============================

    137  nenhum documento localizado    -> acabou; NÃO é erro, e o mais comum
    138  documento localizado           -> veio lote; continua
    656  consumo indevido               -> FREIO da SEFAZ; para AGORA
    others                              -> para e registra, sem insistir

**O 137 é o fim normal da varredura, e chamá-lo de erro é o defeito clássico
deste serviço**: a recolha diária termina em 137 quase todo dia, porque quase
todo dia não há nota nova depois do último NSU. Um cartão vermelho ali
ensinaria a ignorar o cartão.

**O 656 é o único que exige memória.** A SEFAZ pune consulta repetida sem
resultado — o freio é por CNPJ e dura cerca de uma hora. Por isso a recolha
respeita `INTERVALO_MINIMO` entre varreduras do mesmo CNPJ mesmo quando alguém
manda rodar de novo: o freio dela é mais caro que a espera nossa.

POR QUE O NSU É GRAVADO A CADA LOTE
-----------------------------------
Uma primeira varredura pode ter milhares de documentos, dezenas de lotes. Se o
NSU só fosse gravado no fim, uma queda no meio faria tudo recomeçar do zero na
próxima — e recomeçar do zero é exatamente o padrão de consulta que o 656 pune.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from . import armazenamento as arm, leitura

log = logging.getLogger("cortex.sefaz.distribuicao")

#: Um lote traz até 50 documentos. Mais que isto de lotes numa varredura é
#: primeira carga, e a primeira carga tem de caber numa execução — mas com
#: teto, porque laço sem teto contra serviço de terceiro é como se descobre o
#: freio pelo bloqueio.
MAX_LOTES = 40

#: A SEFAZ freia consulta repetida por CNPJ (cStat 656, ~1 h). Este intervalo é
#: NOSSO e evita chegar lá. Vale quando a última varredura terminou em 137
#: (nada novo) — se ela parou AINDA com documento, continuar é o certo e a
#: SEFAZ não reclama.
INTERVALO_MINIMO = timedelta(minutes=60)

#: E quando o freio DELES já pegou (656), a espera é maior — insistir dentro do
#: bloqueio prolonga o bloqueio. Isto foi achado sabotando: a versão anterior
#: parava o laço no 656 mas NÃO travava a próxima varredura (o freio só olhava
#: o 137), então a execução seguinte batia de novo, dentro do castigo. O `break`
#: do 656 era, sozinho, decorativo: o `!= 138` logo abaixo já parava o laço.
#:
#: 65 MINUTOS, E NÃO UM NÚMERO "SEGURO" MAIOR. A própria SEFAZ escreve o prazo
#: na rejeição — "Tente apos 1 hora" — e cinco minutos cobrem a diferença de
#: relógio. Nasceu 90 por precaução, e a precaução cobrou na primeira
#: execução real: com 62 minutos decorridos e o bloqueio DELES já vencido, era
#: o nosso freio que estava segurando a recolha. Margem inventada em cima de um
#: prazo declarado não é cautela, é meia hora de atraso todo dia.
INTERVALO_APOS_FREIO = timedelta(minutes=65)

#: `2` = homologação. Produção NÃO tem atalho aqui, pela mesma razão do módulo
#: da contrapartida: trocar de ambiente é decisão de quem chama.
#:
#: E uma ressalva que vale escrever: a Distribuição de DFe **não tem
#: homologação com dado real** — o ambiente 2 responde e responde vazio.
#: Provar este caminho é em produção, e não há risco nisso porque a consulta é
#: LEITURA. O que exige cuidado é a manifestação, que é escrita.
HOMOLOGACAO = "2"
PRODUCAO = "1"

FIM_NORMAL = "137"
TEM_DOCUMENTO = "138"
CONSUMO_INDEVIDO = "656"

#: A versão do schema da DISTRIBUIÇÃO, que NÃO é a da NF-e. Ver `_cliente()`.
#: Medido contra o serviço real em 07/09/2026: com "4.00" a SEFAZ devolve
#: `239 · Rejeicao: Cabecalho - Versao do arquivo XML nao suportada`.
VERSAO_DISTRIBUICAO = "1.01"


class SemCertificado(RuntimeError):
    """O CNPJ não tem .pfx ou senha no cofre."""


def _certificado(cnpj: str):
    """(caminho, senha) do cofre — ou levanta dizendo o que fazer."""
    import json
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent.parent
    arq = raiz / "data" / "certificados" / ("%s.pfx" % cnpj)
    senhas = raiz / "data" / "certificados" / "senhas.json"
    senha = None
    if senhas.exists():
        try:
            senha = (json.loads(senhas.read_text(encoding="utf-8"))
                     .get(cnpj) or {}).get("valor")
        except Exception:  # noqa: BLE001
            senha = None
    if not arq.exists() or not senha:
        raise SemCertificado(
            "Sem certificado A1 para o CNPJ %s. Rode "
            "`uv run python scripts/cadastrar_certificado.py "
            "data/certificados/%s.pfx` — o arquivo e a senha ficam no cofre, "
            "fora do git." % (cnpj, cnpj))
    return str(arq), senha


def _cliente(cnpj: str, uf: str, ambiente: str):
    """O objeto NFe da biblioteca, já com os remendos da casa aplicados.

    REUSA `api/contrapartida/sefaz.compatibilizar()`: são quatro correções de
    INFRAESTRUTURA da `erpbrasil.edoc` (endereço de SEFAZ própria, serialização,
    confiança TLS sob ICP-Brasil, leitura da resposta) que custaram quatro
    rodadas para achar. Escrever de novo aqui seria pagar de novo — e a que
    importa em qualquer caminho é a TLS: sem ela, "self-signed certificate in
    chain" manda procurar proxy onde não há nenhum.

    E MAIS TRÊS, DESTA FRENTE — o caminho de distribuição da NF-e também não
    estava exercitado, apesar de a NF-e ser o percurso maduro da biblioteca:

      5. `six` AUSENTE APAGA O BINDING EM SILÊNCIO. O módulo importa os
         bindings legados dentro de `with suppress(ImportError)`; eles usam
         `six.moves`, e sem ele os nomes `distDFeInt`/`retDistDFeInt`
         simplesmente não existem. A falha aparece muito depois, como
         `NameError` no meio da consulta. Está no `pyproject`, com guard.

      6. A UF VAI EM CÓDIGO IBGE, e os dois mapas da própria biblioteca são
         incompatíveis entre si (`nfe.SIGLA_ESTADO` é código→sigla em texto;
         `cte.SIGLA_ESTADO` é sigla→código em inteiro). Ver `codigo_uf()`.

      7. A VERSÃO DA DISTRIBUIÇÃO É 1.01, não 4.00 — logo abaixo.
    """
    from erpbrasil.assinatura.certificado import Certificado
    from erpbrasil.edoc.nfe import NFe
    from erpbrasil.transmissao import TransmissaoSOAP

    from api.contrapartida import sefaz as compat
    compat.compatibilizar()

    caminho, senha = _certificado(cnpj)
    doc = NFe(TransmissaoSOAP(Certificado(caminho, senha)),
              codigo_uf(uf), ambiente=ambiente)
    # A DISTRIBUIÇÃO NÃO É VERSÃO 4.00 — É 1.01, e a biblioteca não sabe disso.
    #
    # `NFe.versao` nasce "4.00" (a da NF-e) e `consultar_distribuicao` a copia
    # para dentro do `distDFeInt`. A SEFAZ responde:
    #
    #     239 · Rejeicao: Cabecalho - Versao do arquivo XML nao suportada
    #
    # — mensagem que fala de "cabeçalho" e manda procurar no SOAP, onde não
    # está. Este objeto só consulta distribuição (nunca emite nota), então
    # carimbar a versão certa aqui é seguro e não vaza para outro caminho.
    doc.versao = VERSAO_DISTRIBUICAO
    return doc


def codigo_uf(uf: str) -> int:
    """Sigla -> codigo IBGE. `NFe(...)` quer o NUMERO, nao a sigla.

    E ELA FALHA TARDE E FEIO SEM ISSO: `int('PR')` estoura la dentro do
    construtor da biblioteca, com uma mensagem que fala de literal invalido e
    nao diz nada sobre UF. Os dois mapas da propria biblioteca sao
    INCOMPATIVEIS entre si — `nfe.SIGLA_ESTADO` e {'41': 'PR'} (codigo -> sigla,
    e o codigo em TEXTO) enquanto `cte.SIGLA_ESTADO` e {'PR': 41} (sigla ->
    codigo, em inteiro). Usar o do modulo errado devolve `None` em silencio.
    """
    from erpbrasil.edoc.cte import SIGLA_ESTADO
    codigo = SIGLA_ESTADO.get((uf or "").strip().upper())
    if codigo is None:
        raise ValueError(
            "UF desconhecida: %r. A caixa precisa da UF do interessado "
            "(ela vai no cUFAutor da consulta)." % uf)
    return int(codigo)


def _campo(obj, nome):
    v = getattr(obj, nome, None)
    return getattr(v, "value", v)


def _docs_da_resposta(ret) -> list[dict]:
    """`[{nsu, esquema, conteudo}]` do `loteDistDFeInt` da resposta."""
    lote = getattr(ret, "loteDistDFeInt", None) or getattr(ret, "lote_dist_dfe_int", None)
    docs = getattr(lote, "docZip", None) or getattr(lote, "doc_zip", None) or []
    saida = []
    for d in docs:
        saida.append({
            "nsu": _campo(d, "NSU") or _campo(d, "nsu"),
            "esquema": _campo(d, "schema") or _campo(d, "schema_"),
            # o conteúdo é o TEXTO do próprio elemento (gzip em base64)
            "conteudo": getattr(d, "value", None) or getattr(d, "content", None) or "",
        })
    return saida


def um_lote(cliente, cnpj: str, ultimo_nsu: str) -> dict:
    """UMA chamada ao serviço. Devolve o que a resposta disse, sem decidir nada.

    Separado do laço de propósito: é a fronteira com o fornecedor, e é ela que
    o dublê substitui.
    """
    ret = cliente.consultar_distribuicao(cnpj_cpf=cnpj, ultimo_nsu=ultimo_nsu)
    resposta = getattr(ret, "resposta", ret)
    return {
        "cstat": str(_campo(resposta, "cStat") or ""),
        "motivo": str(_campo(resposta, "xMotivo") or ""),
        "ultimo_nsu": arm.nsu(_campo(resposta, "ultNSU")),
        "max_nsu": arm.nsu(_campo(resposta, "maxNSU")),
        "docs": _docs_da_resposta(resposta),
    }


def recolher(cnpj: str, uf: str, *, ambiente: str = HOMOLOGACAO,
             cliente=None, forcar: bool = False) -> dict:
    """Varre a caixa de um CNPJ até acabar (137), até o teto, ou até o freio.

    `cliente` entra por parâmetro para o teste poder passar o dublê — e o dublê
    devolve o CORPO REAL do serviço, campos "inúteis" inclusive.
    """
    cx = arm.caixa(cnpj)
    if cx is None:
        raise ValueError("CNPJ %s nao esta na recolha. Abra a caixa antes." % cnpj)
    if not cx["ativo"] and not forcar:
        return {"cnpj": cnpj, "pulou": "caixa inativa", "lotes": 0, "novos": 0}

    # O FREIO É NOSSO E VEM ANTES DO DELES. Só vale quando a última varredura
    # terminou em 137 (nada novo): se veio documento, continuar é o certo.
    agora = datetime.now(timezone.utc)
    ultima = cx.get("ultima_consulta")
    ultimo = cx.get("ultimo_cstat")
    espera = (INTERVALO_APOS_FREIO if ultimo == CONSUMO_INDEVIDO
              else INTERVALO_MINIMO if ultimo == FIM_NORMAL else None)
    if not forcar and ultima and espera and (agora - ultima) < espera:
        faltam = espera - (agora - ultima)
        motivo = ("a SEFAZ freou esta caixa (656) — insistir dentro do "
                  "bloqueio prolonga o bloqueio"
                  if ultimo == CONSUMO_INDEVIDO else
                  "a SEFAZ freia consulta repetida sem resultado")
        return {"cnpj": cnpj,
                "pulou": "consultada ha %d min · %s"
                         % (int((agora - ultima).total_seconds() // 60), motivo),
                "esperar_min": int(faltam.total_seconds() // 60),
                "freado": ultimo == CONSUMO_INDEVIDO,
                "lotes": 0, "novos": 0}

    cliente = cliente or _cliente(cnpj, uf, ambiente)
    ponteiro = arm.nsu(cx["ultimo_nsu"])
    resumo = {"cnpj": cnpj, "lotes": 0, "novos": 0, "completados": 0,
              "repetidos": 0, "cstat": "", "motivo": "", "max_nsu": cx.get("max_nsu")}

    for _ in range(MAX_LOTES):
        r = um_lote(cliente, cnpj, ponteiro)
        resumo["lotes"] += 1
        resumo["cstat"], resumo["motivo"] = r["cstat"], r["motivo"]
        resumo["max_nsu"] = r["max_nsu"]

        for linha in leitura.ler_lote(r["docs"]):
            estado = arm.gravar(cnpj, linha)
            resumo["novos" if estado == "novo" else
                   "completados" if estado == "completado" else "repetidos"] += 1

        # A CADA LOTE, e não no fim: ver o docstring do módulo.
        #
        # MAS O PONTEIRO SÓ ANDA COM DOCUMENTO NA MÃO. Numa REJEIÇÃO a SEFAZ
        # também devolve um `ultNSU` — e ele não é o que consumimos, é onde a
        # sequência dela está. Gravá-lo faz o ponteiro PULAR tudo que veio
        # antes, em silêncio: aconteceu aqui em 07/09/2026, num 656, e o
        # ponteiro saltou de 0 para 1.144.010 sem ninguém decidir. Pular
        # histórico é decisão de quem opera (é obrigação fiscal de guarda), não
        # efeito colateral de uma rejeição.
        #
        # O valor não se perde: vai para `max_nsu`, que é o que ele de fato é —
        # o fim da sequência. É dele que a tela tira "quanto falta".
        avancou = r["cstat"] == TEM_DOCUMENTO
        arm.marcar_consulta(cnpj,
                            ultimo_nsu=r["ultimo_nsu"] if avancou else None,
                            max_nsu=(r["max_nsu"] if avancou
                                     else max(r["max_nsu"], r["ultimo_nsu"])),
                            cstat=r["cstat"], motivo=r["motivo"])

        if r["cstat"] == CONSUMO_INDEVIDO:
            # ESTE `break` E REDUNDANTE com o `!= TEM_DOCUMENTO` logo abaixo, e
            # esta escrito assim de proposito: o que ele acrescenta e o AVISO no
            # log. O freio de verdade contra o 656 nao esta aqui -- esta no
            # `INTERVALO_APOS_FREIO`, que trava a PROXIMA varredura. Confundir
            # os dois foi o defeito que a sabotagem achou: parar o laco de hoje
            # nao impede a execucao da hora seguinte de bater dentro do castigo.
            log.warning("sefaz: %s freado pela SEFAZ (656)", cnpj)
            break
        if r["cstat"] != TEM_DOCUMENTO:
            break
        # PONTEIRO QUE NÃO ANDA É LAÇO INFINITO. Acontece de verdade: a SEFAZ
        # devolve 138 com o mesmo ultNSU quando o lote traz só documento que
        # não descomprime. Sem esta guarda seriam 40 chamadas idênticas e um
        # 656 na cara.
        if arm.nsu(r["ultimo_nsu"]) <= ponteiro:
            log.warning("sefaz: %s o NSU nao avancou (%s); parando",
                        cnpj, ponteiro)
            break
        ponteiro = arm.nsu(r["ultimo_nsu"])
        # `maxNSU` é o maior que EXISTE: alcançá-lo é o fim, sem precisar de
        # mais uma chamada só para ouvir 137.
        if ponteiro >= arm.nsu(r["max_nsu"]):
            break

    resumo["ultimo_nsu"] = ponteiro
    resumo["fim_normal"] = resumo["cstat"] in (FIM_NORMAL, TEM_DOCUMENTO)
    return resumo
