# -*- coding: utf-8 -*-
"""O aviso horário da carga por WhatsApp.

TRÊS RESPOSTAS, como todo aviso automático desta casa: manda, cala porque não
há o que dizer, ou recusa DIZENDO o motivo. O que não existe é a quarta —
parar em silêncio —, porque ela é indistinguível de "está tudo calmo" e some
justamente quando a integração quebra.

O QUE PROTEGE O NÚMERO DA EMPRESA, e isto vale mais que qualquer recurso aqui:

1. **Mensagem idêntica à anterior não é reenviada.** Um caminhão parado geraria
   a mesma frase 24 vezes por dia; a pessoa bloqueia o número, e o estrago não
   é a mensagem — é a reputação do número que atende todos os outros clientes.
   Comparar com `ultimo_texto` custa uma coluna e evita isso.
2. **A entrega encerra a inscrição**, com uma última mensagem. Ninguém volta
   para cancelar depois que a carga chegou.
3. **Toda mensagem diz como sair**, e sair não exige nada além de responder.
4. **Frescor antes de conteúdo.** Se a posição do veículo está velha, o aviso
   diz isso em vez de repetir o número de três horas atrás como se fosse agora.

O ENVIO PASSA PELO CAMINHO NORMAL da casa (`whatsapp.envio.enviar`), e isso é
deliberado: ali moram o interruptor geral, a janela de horário, o teto por
número e a checagem de conexão. Um atalho aqui seria o lugar por onde o freio
deixaria de valer justamente para a mensagem que sai sozinha, de hora em hora,
sem ninguém olhando.
"""
from __future__ import annotations

import logging

from ..whatsapp import envio as wa
from . import assinatura, consulta, detalhe, mensagem

log = logging.getLogger("cortex.rastreio.aviso")

#: A REDAÇÃO MORA EM OUTRO MÓDULO (`mensagem.py`). Ela muda toda semana — uma
#: palavra, um emoji, um link — e é a única parte que o cliente vê; este
#: arquivo decide QUANDO mandar e o que fazer com a falha, que é outra
#: pergunta e muda por outros motivos.
RODAPE = mensagem.RODAPE
_texto = mensagem.montar


def _carga_da_inscricao(ins: dict) -> dict | None:
    """A carga de uma inscrição, pelo caminho normal do detalhe.

    Passa pela busca de propósito: assim o aviso enxerga exatamente o que a
    página enxerga, e não há um segundo caminho para o mesmo número divergir.
    """
    from .. import db
    try:
        linhas = db.query(detalhe.DETALHE_SQL, {
            "g": ins["grupo"], "e": ins["empresa"], "f": ins["filial"],
            "n": ins["numero"], "s": ins["serie"]})
    except Exception as exc:  # noqa: BLE001
        log.warning("aviso: leitura da carga falhou: %s", type(exc).__name__)
        return None
    if not linhas:
        return None
    linha = dict(linhas[0])
    detalhe._CHAVES_ATUAIS["chaves"] = {
        "g": ins["grupo"], "e": ins["empresa"], "f": ins["filial"],
        "n": ins["numero"], "s": ins["serie"]}
    estado, rotulo = consulta._estado(linha)
    return {"documento": "CT-e %s" % ins["numero"],
            "origem": consulta._lugar(linha.get("cidadecoleta"),
                                      linha.get("ufcoleta")),
            "destino": consulta._lugar(linha.get("destinatario_cidade"),
                                       linha.get("destinatario_uf")),
            "estado": estado, "estado_rotulo": rotulo,
            "entregue_em": consulta._iso(linha.get("dtentrega")),
            # O LINK QUE ABRE A CARGA JA ABERTA. Assinado e com prazo: sem
            # isso a pessoa teria de reabrir a pagina e redigitar o documento e
            # o CNPJ a cada aviso, e o aviso de hora em hora viraria trabalho.
            "link_token": consulta.link_token(
                ins["grupo"], ins["empresa"], ins["filial"],
                ins["numero"], ins["serie"]),
            "andamento": detalhe._andamento(linha)}


def rodar(*, ensaio: bool = False, limite: int | None = None) -> dict:
    """Avisa quem está inscrito. NUNCA levanta.

    `ensaio` monta as mensagens sem enviar — é como se confere o texto antes de
    ele sair para um número de cliente.
    """
    inscricoes = assinatura.ativas()
    if limite:
        inscricoes = inscricoes[:limite]
    fora = {"inscricoes": len(inscricoes), "enviados": 0, "iguais": 0,
            "sem_texto": 0, "encerradas": 0, "falhas": 0, "ensaio": ensaio,
            "amostra": []}

    for ins in inscricoes:
        carga = _carga_da_inscricao(ins)
        if not carga:
            fora["sem_texto"] += 1
            continue
        texto = _texto(carga)
        if not texto:
            fora["sem_texto"] += 1
            continue

        # MENSAGEM IGUAL NAO SE REPETE. E o que separa "aviso de hora em hora"
        # de "24 mensagens iguais por dia" — e a segunda faz a pessoa bloquear
        # o numero da empresa.
        if texto == (ins.get("ultimo_texto") or ""):
            fora["iguais"] += 1
            continue

        if len(fora["amostra"]) < 3:
            fora["amostra"].append({"telefone": ins["telefone"][-4:],
                                    "texto": texto})
        if ensaio:
            continue

        r = wa.enviar(ins["telefone"], texto + RODAPE,
                      usuario="rastreio", origem="rastreio_carga")
        if r.get("ok"):
            fora["enviados"] += 1
            assinatura.marcar_envio(ins["id"], texto)
            if carga.get("estado") == "entregue":
                # A ENTREGA ENCERRA. Ninguem volta para cancelar depois que a
                # carga chegou, e o aviso seguiria ate o prazo expirar.
                assinatura.encerrar(ins["id"], "entregue")
                fora["encerradas"] += 1
        else:
            fora["falhas"] += 1
            log.info("aviso: envio recusado: %s", (r.get("erro") or "")[:120])
    return fora
