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

    UMA MENSAGEM POR TELEFONE, não por carga, e o número que decide isso: com o
    teto de 5 cargas por telefone e 14 ciclos por dia, uma mensagem por carga
    daria 70 diárias para a MESMA pessoa — acima do teto de 60 por número que a
    casa impõe. Quem acompanhasse cinco cargas parava de receber no meio da
    tarde, e sem aviso nenhum: as recusas ficam no nosso log, não no celular
    dela. E antes do teto vem o estrago maior — cinco notificações por hora do
    mesmo número é o que faz alguém bloquear o contato, e o bloqueio atinge o
    número que fala com todos os outros clientes.

    `ensaio` monta as mensagens sem enviar — é como se confere o texto antes de
    ele sair para um número de cliente.
    """
    inscricoes = assinatura.ativas()
    if limite:
        inscricoes = inscricoes[:limite]

    # AGRUPA POR TELEFONE. `ativas()` já vem ordenada pelo último envio, e o
    # `setdefault` preserva essa ordem dentro de cada grupo.
    por_fone: dict = {}
    for ins in inscricoes:
        por_fone.setdefault(ins["telefone"], []).append(ins)

    fora = {"inscricoes": len(inscricoes), "telefones": len(por_fone),
            "enviados": 0, "iguais": 0, "sem_texto": 0, "encerradas": 0,
            "falhas": 0, "ensaio": ensaio, "amostra": []}

    for fone, grupo in por_fone.items():
        pares = []
        for ins in grupo:
            carga = _carga_da_inscricao(ins)
            if carga:
                pares.append((ins, carga))
        if not pares:
            fora["sem_texto"] += len(grupo)
            continue

        cargas = [c for _, c in pares]
        texto = mensagem.montar_varias(cargas)
        if not texto:
            fora["sem_texto"] += len(pares)
            continue
        # O EXEMPLO DO RODAPÉ é o documento da PRIMEIRA carga: "SAIR 94537"
        # ensina a sintaxe com um número que a pessoa está vendo na tela.
        doc = (cargas[0].get("documento") or "").replace("CT-e ", "").strip()
        completo = texto + mensagem.rodape(len(cargas), doc)

        # MENSAGEM IGUAL NAO SE REPETE. E o que separa "aviso de hora em hora"
        # de "24 mensagens iguais por dia" — e a segunda faz a pessoa bloquear
        # o numero da empresa. Comparar pelo primeiro do grupo basta: todos
        # recebem o MESMO texto gravado.
        if texto == (pares[0][0].get("ultimo_texto") or ""):
            fora["iguais"] += len(pares)
            continue

        if len(fora["amostra"]) < 3:
            fora["amostra"].append({"telefone": fone[-4:], "cargas": len(cargas),
                                    "texto": completo})
        if ensaio:
            continue

        r = wa.enviar(fone, completo, usuario="rastreio",
                      origem="rastreio_carga")
        if not r.get("ok"):
            fora["falhas"] += 1
            log.info("aviso: envio recusado: %s", (r.get("erro") or "")[:120])
            continue

        fora["enviados"] += 1
        for ins, carga in pares:
            assinatura.marcar_envio(ins["id"], texto)
            if carga.get("estado") == "entregue":
                # A ENTREGA ENCERRA — só a dela. As outras cargas do mesmo
                # telefone seguem sendo avisadas, e é isso que a consolidação
                # tornou possível dizer: antes, encerrar era por mensagem.
                assinatura.encerrar(ins["id"], "entregue")
                fora["encerradas"] += 1
    return fora
