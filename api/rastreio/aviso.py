# -*- coding: utf-8 -*-
"""O aviso horário da carga por WhatsApp.

TRÊS RESPOSTAS, como todo aviso automático desta casa: manda, cala porque não
há o que dizer, ou recusa DIZENDO o motivo. O que não existe é a quarta —
parar em silêncio —, porque ela é indistinguível de "está tudo calmo" e some
justamente quando a integração quebra.

O QUE PROTEGE O NÚMERO DA EMPRESA, e isto vale mais que qualquer recurso aqui:

1. **Mensagem que não diz nada de novo não é reenviada.** Um caminhão parado
   geraria a mesma frase 24 vezes por dia; a pessoa bloqueia o número, e o
   estrago não é a mensagem — é a reputação do número que atende todos os
   outros clientes. Quem decide é a ASSINATURA do que mudou
   (`mensagem.assinatura`), nunca o texto: o texto carrega o frescor da posição
   e por isso muda a cada ciclo mesmo com a carga parada — foi assim que seis
   mensagens idênticas saíram em quatro horas, em 06/09/2026.
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
from . import assinatura, consulta, detalhe, macros, mensagem

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
    # A VIAGEM INTEIRA numa leitura só — a mesma que a página faz. A mensagem
    # mostra as últimas movimentações; a regra de chegada precisa enxergar até
    # o `INICIO DE VIAGEM`, que numa viagem com paradas fica bem atrás.
    movs = detalhe._movimentacao(linha, limite=macros.LIMITE_CRU)
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
            # A ULTIMA MOVIMENTACAO REAL. Vem pelo MESMO caminho do detalhe
            # (`detalhe._movimentacao`) de proposito: assim o WhatsApp nao pode
            # dizer uma coisa e a pagina outra sobre o mesmo instante — e o
            # recorte da viagem, que e o que impede a narrativa de outro
            # cliente de vazar, e escrito num lugar so.
            "movimentacao": movs[:detalhe.MOV_NA_TELA],
            # A CHEGADA QUE ENCERRA. Não é `movs[0]["rotulo"] == "Chegou no
            # cliente"`: o mesmo evento é mandado quando o caminhão encosta
            # para CARREGAR, e a regra que separa os dois mora num lugar só
            # (`macros.chegada_no_destino`), com a viagem do CT-e 94540 escrita
            # no docstring como caso de prova.
            "chegada_no_cliente": detalhe._chegada_no_cliente(linha, movs),
            "andamento": detalhe._andamento(linha)}


def _fim_da_carga(carga: dict) -> str | None:
    """O motivo pelo qual esta carga não se acompanha mais, ou None.

    TRÊS JEITOS DE A CARGA TER CHEGADO, e eles não concorrem — se completam.
    A entrega e a descarga vêm das DATAS do CT-e, que a operação preenche com
    atraso (às vezes no dia seguinte); a chegada vem da MACRO do rastreador, no
    minuto em que o motorista a manda. Enquanto só a entrega encerrava, quem
    esperava a carga continuava recebendo "faltam 0 km" de hora em hora com o
    caminhão parado na doca dele — e essa é a mensagem que faz alguém bloquear
    o número.

    A ORDEM é do mais definitivo para o mais recente, e o rótulo gravado é o
    que a tela `mon` lê para contar como os monitoramentos terminam.
    """
    if carga.get("estado") == "entregue":
        return "entregue"
    if carga.get("estado") == "descarregando":
        # JÁ ESTÁ NA DOCA descarregando: é a mesma notícia da chegada, por
        # outra fonte. Cai no mesmo balde de propósito — quem lê o painel
        # quer saber quantas terminaram porque a carga chegou, não por qual
        # dos dois campos do ERP contou primeiro.
        return "chegou"
    if carga.get("chegada_no_cliente"):
        return "chegou"
    return None


def _encerrar_terminais(pares: list, fora: dict) -> None:
    """Fecha as inscrições cuja carga chegou. A ENTREGA ENCERRA — só a dela.

    As outras cargas do mesmo telefone seguem sendo avisadas; foi a
    consolidação por telefone que tornou isso possível dizer, porque antes
    encerrar era por mensagem.
    """
    for ins, carga in pares:
        motivo = _fim_da_carga(carga)
        if motivo:
            assinatura.encerrar(ins["id"], motivo)
            fora["encerradas"] += 1


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

    # SÓ QUEM ESTÁ VENCIDO. O relógio é o do TELEFONE, contado do pedido dele
    # (ou da última mensagem que recebeu), e não a hora cheia do servidor.
    #
    # O QUE ISTO MUDA ENQUANTO O GATILHO FOR DE HORA EM HORA: nada piora e uma
    # coisa melhora — some a mensagem repetida logo depois do cadastro. A
    # cadência vira "no máximo uma por hora, no primeiro ciclo em que já se
    # passaram 60 minutos". Para virar 13h38 em vez de 14h00, o gatilho tem de
    # rodar a cada 10 minutos; nenhuma linha daqui muda quando isso acontecer.
    #
    # `desde_min` nulo é inscrição sem âncora legível — trata-se como VENCIDA:
    # errar para o lado de avisar quem espera a carga é melhor que calar.
    #
    # O INTERVALO E O DE QUEM RECEBE, e nao uma constante da casa: quem
    # escolheu "menos mensagens" tem 180 minutos no lugar de 60. A escolha so
    # ESPACA — nao existe opcao que aperte abaixo do piso de uma por hora.
    vencidas, cedo, fora_janela = [], 0, 0
    for ins in inscricoes:
        desde = ins.get("desde_min")
        piso = assinatura.preferencia(ins)["intervalo_min"]
        if not (desde is None or desde >= piso):
            cedo += 1
            continue
        # A JANELA DE QUEM RECEBE, conferida AQUI e nao so no envio. O
        # `whatsapp.envio` continua barrando a janela GERAL — ele e o freio da
        # casa e nao se mexe —, mas ele nao sabe que este telefone pediu para
        # ser avisado so de manha. Sem esta linha, a escolha da pessoa nao
        # existiria: a mensagem sairia as 19h com a recusa dela em lugar nenhum.
        if not assinatura.dentro_da_janela(ins):
            fora_janela += 1
            continue
        vencidas.append(ins)
    inscricoes = vencidas

    # AGRUPA POR TELEFONE. `ativas()` já vem ordenada pelo último envio, e o
    # `setdefault` preserva essa ordem dentro de cada grupo.
    por_fone: dict = {}
    for ins in inscricoes:
        por_fone.setdefault(ins["telefone"], []).append(ins)

    fora = {"inscricoes": len(inscricoes), "telefones": len(por_fone),
            "enviados": 0, "iguais": 0, "sem_texto": 0, "encerradas": 0,
            # AINDA NO PRAZO não é falha e não é silêncio: é a terceira
            # resposta do aviso — "calei porque não era hora" — e ela precisa
            # sair no relatório, senão a tarefa parece ter feito nada.
            "cedo": cedo,
            # FORA DA JANELA DE QUEM RECEBE também é resposta, não silêncio: é
            # a pessoa sendo atendida na escolha dela, e precisa aparecer no
            # relatório para não virar "a tarefa não fez nada".
            "fora_janela": fora_janela,
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

        # NADA MUDOU NAO SE REPETE. E o que separa "aviso de hora em hora" de
        # "24 mensagens iguais por dia" — e a segunda faz a pessoa bloquear o
        # numero da empresa.
        #
        # QUEM DECIDE E A ASSINATURA, NUNCA O TEXTO (06/09/2026). Comparar o
        # texto renderizado parecia a coisa obvia e era o defeito: ele carrega
        # `Atualizado ha N min` e o atraso do transito em minutos, dois numeros
        # que mudam a cada ciclo por construcao. A comparacao quase nunca
        # casava, e o telefone do CT-e 94540 recebeu seis mensagens em quatro
        # horas dizendo `2%` e `faltam 648 km` — sempre.
        #
        # Comparar pelo primeiro do grupo continua bastando: todos recebem a
        # MESMA mensagem, logo a mesma assinatura.
        # A CADENCIA E DO TELEFONE, e todas as inscricoes dele a compartilham
        # por construcao (a escrita em `inscrever` alcanca todas): ler a do
        # primeiro do grupo e ler a do grupo.
        so_marcos = assinatura.preferencia(pares[0][0])["so_marcos"]
        assin = mensagem.assinatura(cargas, so_marcos=so_marcos)
        if assin and assin == (pares[0][0].get("ultima_assinatura") or ""):
            fora["iguais"] += len(pares)
            # E MESMO CALANDO, A CARGA QUE CHEGOU SAI DA LISTA. Sem esta linha
            # a inscrição de quem se cadastrou DEPOIS da chegada ficaria viva
            # até expirar sozinha aos 15 dias: a primeira mensagem já era a de
            # chegada, a assinatura nasceu igual, e o ciclo seguinte nunca mais
            # entraria no ramo que encerra. Silenciosa, mas contando como
            # monitoramento ativo no painel — um número errado sem sintoma.
            if not ensaio:
                _encerrar_terminais(pares, fora)
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
            assinatura.marcar_envio(ins["id"], texto, assin=assin)
        # O ENCERRAMENTO VEM DEPOIS DO ENVIO, sempre. É essa ordem que torna a
        # mensagem de chegada a ÚLTIMA e não a primeira que faltou: encerrar
        # antes tiraria a inscrição da lista com a novidade ainda por contar.
        _encerrar_terminais(pares, fora)
    return fora
