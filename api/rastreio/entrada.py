# -*- coding: utf-8 -*-
"""O que chega DE VOLTA no WhatsApp: por enquanto, só a palavra SAIR.

POR QUE ISTO EXISTE. Toda mensagem do rastreio termina com "Para parar de
receber, responda SAIR". Prometer isso e não atender é pior que não prometer:
quem responde e continua recebendo não tenta de novo — bloqueia o número. E o
bloqueio não atinge esta mensagem, atinge o número que fala com todos os
outros clientes.

O RISCO DE UM WEBHOOK ABERTO, e o que o contém. A Z-API chama esta rota de
fora, então ela é pública, e qualquer um pode postar um corpo inventado. Três
coisas seguram isso:

1. **A única ação possível é DESCADASTRAR.** Não há caminho aqui que crie,
   cobre ou revele nada. O pior que um pedido forjado consegue é parar de
   avisar alguém — é a direção segura de errar.
2. **Só se responde a quem tinha inscrição.** Sem isso o webhook viraria um
   amplificador: qualquer POST com um telefone qualquer faria a casa mandar
   mensagem para ele.
3. **Segredo opcional** (`RASTREIO_ZAP_TOKEN`). Quando configurado, vira
   obrigatório. Não vem ligado por padrão porque uma integração que só funciona
   depois de um segredo que ninguém sabe que existe é uma integração que fica
   quebrada em silêncio — e o silêncio, aqui, é o defeito.

O FORMATO DA Z-API não é adivinhado: o corpo vem com o telefone em `phone` e o
texto em `text.message`, e os dois nomes variam entre versões da API deles.
Por isso a leitura procura em vários lugares e desiste declarando, em vez de
estourar num `KeyError` que a Z-API leria como falha de entrega.
"""
from __future__ import annotations

import logging
import os
import re

from ..whatsapp import envio as wa
from ..whatsapp import numeros
from ..whatsapp import resposta
from . import assinatura

log = logging.getLogger("cortex.rastreio.entrada")

#: O que conta como pedido de saída. Gente escreve "sair", "SAIR.", "parar",
#: "cancelar" — e quem pediu para sair e continua recebendo bloqueia o número.
#: Ser generoso aqui custa nada; ser restrito custa a reputação do número.
RE_SAIR = re.compile(r"^\s*(sair|parar|cancelar|remover|stop|descadastrar)\b",
                     re.IGNORECASE)

CONFIRMACAO = ("Pronto, você não receberá mais avisos de carga neste número. "
               "Se precisar acompanhar outra carga, é só cadastrar de novo na "
               "página de rastreio.")


def _token_ok(recebido: str | None) -> bool:
    esperado = (os.environ.get("RASTREIO_ZAP_TOKEN") or "").strip()
    if not esperado:
        return True
    return (recebido or "").strip() == esperado


def _extrair(corpo: dict) -> tuple[str, str]:
    """Telefone e texto do corpo da Z-API. Devolve ('', '') quando não achar."""
    fone = ""
    for chave in ("phone", "from", "sender", "participantPhone"):
        v = corpo.get(chave)
        if isinstance(v, str) and v.strip():
            fone = v.strip()
            break

    texto = ""
    t = corpo.get("text")
    if isinstance(t, dict):
        texto = str(t.get("message") or "")
    elif isinstance(t, str):
        texto = t
    if not texto:
        for chave in ("body", "message", "caption"):
            v = corpo.get(chave)
            if isinstance(v, str) and v.strip():
                texto = v
                break
    return fone, texto


def receber(corpo: dict, token: str | None = None) -> dict:
    """Trata uma mensagem recebida. NUNCA levanta.

    Devolve sempre 200 para a Z-API: erro aqui faria ela reenfileirar a mesma
    mensagem, e a segunda tentativa encontraria a inscrição já cancelada.
    """
    # TODA CHAMADA DEIXA RASTRO, e isto veio de uma tarde perdida. Dois
    # caminhos daqui saiam CALADOS — a nossa propria mensagem voltando e o
    # texto que nao e SAIR. Com eles mudos, "a Z-API nunca chamou" e "a Z-API
    # chamou e nos ignoramos" ficam indistinguiveis do lado de ca, e foi
    # exatamente essa duvida que travou o diagnostico do SAIR que nao
    # funcionava.
    #
    # SO AS CHAVES DO CORPO, nunca o conteudo: telefone e texto de cliente nao
    # entram em log. As chaves bastam para saber se chegou e em que formato.
    log.info("rastreio: webhook recebido, campos=%s",
             sorted(corpo)[:14] if isinstance(corpo, dict) else type(corpo).__name__)

    if not _token_ok(token):
        log.warning("rastreio: webhook com token invalido")
        return {"ok": True, "acao": "ignorado"}

    # MENSAGEM QUE NOS MESMOS ENVIAMOS volta no webhook. Sem este corte, a
    # confirmacao de saida seria lida como uma nova mensagem de entrada.
    if corpo.get("fromMe") or corpo.get("isGroup"):
        log.info("rastreio: webhook ignorado (fromMe=%s isGroup=%s)",
                 bool(corpo.get("fromMe")), bool(corpo.get("isGroup")))
        return {"ok": True, "acao": "ignorado"}

    fone, texto = _extrair(corpo)
    if not fone or not texto:
        # DESISTE DECLARANDO. Um KeyError aqui viraria HTTP 500, e a Z-API
        # leria isso como falha de entrega e tentaria de novo.
        log.info("rastreio: webhook sem telefone ou texto reconhecivel")
        return {"ok": True, "acao": "sem_dados"}

    if not RE_SAIR.match(texto):
        # NAO RESPONDEMOS a qualquer mensagem. Um "obrigado" do cliente nao
        # pode virar conversa automatica — e responder a tudo transformaria o
        # numero da empresa num robo que ninguem pediu.
        #
        # O LOG NAO LEVA O TEXTO, so o tamanho: e o bastante para saber que
        # chegou mensagem e que ela nao era um pedido de saida.
        log.info("rastreio: webhook ignorado (nao e SAIR, %d caracteres)",
                 len(texto))
        return {"ok": True, "acao": "ignorado"}

    if not numeros.valido(fone):
        # SO O TAMANHO, nunca o numero: telefone de cliente nao entra em log.
        log.info("rastreio: SAIR de telefone invalido (%d digitos)",
                 len([c for c in fone if c.isdigit()]))
        return {"ok": True, "acao": "telefone_invalido"}

    quantas = assinatura.cancelar_por_telefone(fone)
    if not quantas:
        # SO SE RESPONDE A QUEM TINHA INSCRICAO. Sem isso o webhook viraria
        # amplificador: qualquer POST com um telefone faria a casa mandar
        # mensagem para ele.
        #
        # E ESTE CAMINHO PRECISA FALAR. Ele e o unico jeito de "o SAIR chegou
        # mas o telefone nao bate com o gravado" se distinguir de "o SAIR nunca
        # chegou" — e as duas coisas se parecem exatamente igual do lado de ca.
        # Os quatro ultimos digitos bastam para conferir e nao identificam
        # ninguem sozinhos.
        log.info("rastreio: SAIR sem inscricao ativa (final %s)",
                 "".join(c for c in fone if c.isdigit())[-4:])
        return {"ok": True, "acao": "sem_inscricao"}

    # JANELA ABERTA: esta e uma RESPOSTA, nao um disparo. Quem pede para sair
    # e nao recebe nada nao tenta de novo — bloqueia o numero, e o bloqueio
    # atinge o numero que fala com todos os outros clientes. Com a janela
    # normal (08:00-20:00), um SAIR as 22h cancelava em silencio: exatamente a
    # promessa que a mensagem faz e nao cumpria. Ver `whatsapp/resposta.py`.
    wa.enviar(numeros.normalizar(fone), CONFIRMACAO, usuario="rastreio",
              origem="rastreio_saida", regras=resposta.regras())
    log.info("rastreio: %d inscricao(oes) canceladas por SAIR", quantas)
    return {"ok": True, "acao": "cancelado", "inscricoes": quantas}
