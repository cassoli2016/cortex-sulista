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
from . import assinatura, consulta, detalhe

log = logging.getLogger("cortex.rastreio.aviso")

#: Como o texto se despede. Sair é responder uma palavra — quem precisa achar
#: um site para cancelar bloqueia o número em vez disso.
RODAPE = "\n\nPara parar de receber, responda SAIR."


def _texto(carga: dict) -> str | None:
    """A mensagem, ou None quando não há o que dizer.

    NENHUM VALOR, nenhum dado sensível: é a mesma regra da página, e aqui ela
    pesa mais — a mensagem sai do nosso controle no instante em que é entregue,
    e um encaminhamento não tem como ser desfeito.
    """
    a = carga.get("andamento") or {}
    doc = carga.get("documento") or "Sua carga"
    destino = carga.get("destino") or "o destino"

    if carga.get("estado") == "entregue":
        quando = (carga.get("entregue_em") or "")[:16].replace("T", " ")
        return ("%s: ENTREGUE em %s.%s"
                % (doc, quando or destino, "\n\nObrigado pela confiança."))
    if carga.get("estado") == "descarregando":
        return "%s: o veículo chegou em %s e está em descarga." % (doc, destino)

    if a.get("fora_da_rota"):
        # RECUSA DIZENDO O MOTIVO, não silêncio: quem contratou o aviso precisa
        # saber que ele não está enxergando, e não achar que nada mudou.
        return ("%s: não estamos conseguindo localizar o veículo nesta viagem "
                "no momento. Seguimos acompanhando." % doc)
    if a.get("posicao_velha_min"):
        h = max(1, int(a["posicao_velha_min"] / 60))
        return ("%s: sem atualização de posição há cerca de %dh. Assim que o "
                "veículo reportar, avisamos." % (doc, h))
    if not a.get("tem_posicao"):
        return None

    pct = a.get("progresso_pct")
    falta = a.get("falta_km")
    if pct is None or falta is None:
        return None
    como = "pela rota" if a.get("por_rota") else "em linha reta"
    linha = "%s: %d%% da viagem para %s, faltam cerca de %d km %s." % (
        doc, pct, destino, round(falta), como)
    t = a.get("transito")
    if t and t.get("estado") in ("lento", "parado", "bloqueado"):
        linha += " Trânsito %s no trecho." % (t.get("rotulo") or "carregado").lower()
    return linha


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
            "destino": consulta._lugar(linha.get("destinatario_cidade"),
                                       linha.get("destinatario_uf")),
            "estado": estado, "estado_rotulo": rotulo,
            "entregue_em": consulta._iso(linha.get("dtentrega")),
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
