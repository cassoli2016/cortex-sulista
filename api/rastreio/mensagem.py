# -*- coding: utf-8 -*-
"""O TEXTO do aviso de WhatsApp — só a redação, separada do envio.

POR QUE UM MÓDULO SÓ PARA ISTO. O texto é a parte que muda toda semana (uma
palavra a mais, um emoji, um link novo) e é a única parte que o cliente vê.
Separá-la do `aviso.py` — que decide QUANDO mandar e o que fazer com a falha —
deixa a redação ser testada sozinha, com dicionários montados à mão, sem ERP
nem Z-API no caminho.

O QUE A MENSAGEM NÃO PODE TER, e esta é a regra que pesa mais aqui: nenhum
valor de frete, nome de motorista, placa, CNPJ ou coordenada. A página pública
já obedece isso, mas na mensagem a exigência é maior — o WhatsApp sai do nosso
controle no instante em que é entregue, e um encaminhamento não tem como ser
desfeito.

O LINK VAI NO FRAGMENTO (`#c=`), nunca na query. O que vem depois do `#` não
chega ao servidor nem ao log do proxy: é o mesmo caminho que o "esqueci minha
senha" desta casa usa, e aqui ele evita que o token de uma carga de cliente
fique gravado em log de acesso.

A BARRA É FEITA DE CARACTERES, não de imagem. No WhatsApp uma barra de blocos
é lida de relance, na notificação, sem abrir nada — e imagem remota é bloqueada
por padrão e entrega quem abriu e quando.
"""
from __future__ import annotations

from api import url_publica

#: Onde a página pública mora. Configurável de propósito: este domínio mudou de
#: `cortex.cassolitech.com.br` para `cortex.sulista.com.br` no meio da
#: construção, e um endereço cravado no código teria ido junto na mensagem de
#: todo cliente até alguém reparar.
PADRAO_BASE = url_publica.PADRAO


def base() -> str:
    """A MESMA fonte do resto da casa (`api/url_publica`). Antes esta função
    era a única que lia o endereço de uma variável — e o resultado foi a mesma
    pessoa recebendo dois links de domínios diferentes no mesmo WhatsApp."""
    return url_publica.base()


#: Como o texto se despede. Sair é responder uma palavra — quem precisa achar
#: um site para cancelar bloqueia o número em vez disso.
RODAPE = "\n\n_Para sair, responda SAIR._"


def rodape(quantas: int, exemplo: str = "") -> str:
    """Como a mensagem se despede — e com várias cargas isso muda.

    Com uma, sair é uma palavra. Com várias, a pessoa quase sempre quer parar
    UMA — a que já chegou — e continuar com as outras. Oferecer só o "tudo ou
    nada" faz quem queria sair de uma sair de todas, e essa pessoa não volta a
    se cadastrar.
    """
    if quantas <= 1:
        return RODAPE
    ex = " (ex.: SAIR %s)" % exemplo if exemplo else ""
    # CARGAS TAMBÉM VAI NO RODAPÉ, e não é excesso: quem quer sair de uma no
    # meio da noite precisa do NÚMERO dela, e rolar a conversa para trás até
    # achar a última mensagem horária é justamente o atrito que faz a pessoa
    # mandar o SAIR seco e sumir. Comando que ninguém sabe que existe não
    # existe.
    return ("\n\n_Responda CARGAS para ver todas. "
            "Para sair de UMA, SAIR e o número%s; para sair de todas, "
            "só SAIR._" % ex)

#: A ESTRADA. Blocos de cor, não traços: no WhatsApp o que se lê de relance é
#: a NOTIFICAÇÃO, e ali um `▰▰▱▱` some no meio do texto enquanto um bloco verde
#: aparece. O caminhão marca a posição — é ele que transforma "58%" em "estou
#: aqui", que é a pergunta que a pessoa realmente faz.
FEITO, CARRO, FALTA, CHEGADA = "🟩", "🚛", "⬜", "🏁"
CELULAS = 8


def barra(pct: int) -> str:
    """A estrada com o caminhão na posição, ou a bandeirada no fim.

    A REGRA DAS PONTAS CONTINUA VALENDO, e aqui ela é mais visível ainda: com o
    caminhão na última célula a pessoa lê CHEGOU e vai para a doca. Então 99%
    nunca põe o caminhão no fim — só 100% troca a estrada pela bandeira.
    """
    p = max(0, min(100, int(pct)))
    if p >= 100:
        return FEITO * (CELULAS - 1) + CHEGADA
    i = int(round(p / 100.0 * (CELULAS - 1)))
    # NUNCA na ultima celula abaixo de 100: ver o docstring.
    i = min(i, CELULAS - 2)
    return FEITO * i + CARRO + FALTA * (CELULAS - 1 - i)


#: Semáforo do trânsito. Os mesmos três estados da casa, e nada além deles.
PONTO_TRANSITO = {"livre": "\U0001f7e2", "lento": "\U0001f7e1",
                  "parado": "\U0001f534", "bloqueado": "\U0001f534"}


def link(carga: dict) -> str:
    """O endereço que abre a carga JÁ ABERTA, sem a pessoa digitar nada."""
    t = carga.get("link_token")
    return "%s/r#c=%s" % (base(), t) if t else "%s/rastreio" % base()


def _cabecalho(carga: dict, emoji: str, titulo: str) -> list[str]:
    doc = carga.get("documento") or "Sua carga"
    return ["%s *%s*" % (emoji, doc), titulo]


def _trecho(carga: dict) -> str:
    destino = carga.get("destino") or "o destino"
    origem = carga.get("origem")
    if origem:
        return "\U0001f4cd %s ➜ %s" % (origem, destino)
    return "\U0001f4cd Destino: %s" % destino


def montar(carga: dict) -> str | None:
    """A mensagem, ou None quando não há o que dizer.

    None é a resposta "calo porque não há novidade" — uma das três do aviso
    automático desta casa. O que não existe é parar em silêncio por engano: as
    situações sem posição têm texto próprio, dizendo o motivo.
    """
    a = carga.get("andamento") or {}
    lig = link(carga)

    if carga.get("estado") == "entregue":
        quando = (carga.get("entregue_em") or "")[:16].replace("T", " às ")
        linhas = _cabecalho(carga, "✅", "*Entregue*"
                            + (" em %s" % quando if quando else ""))
        linhas += [_trecho(carga), "", barra(100) + "  *100%*", "",
                   "Obrigado pela confiança! \U0001f64f"]
        return "\n".join(linhas)

    if carga.get("estado") == "descarregando":
        linhas = _cabecalho(carga, "\U0001f4e6", "*Chegou e está em descarga*")
        linhas += [_trecho(carga), "", barra(100) + "  *100%*",
                   "", "\U0001f449 " + lig]
        return "\n".join(linhas)

    if a.get("fora_da_rota"):
        # RECUSA DIZENDO O MOTIVO, não silêncio. O veículo pode ter engatado
        # outra carreta e seguido viagem; inventar um progresso aqui seria pior
        # que admitir a lacuna.
        linhas = _cabecalho(carga, "⚠️", "Sem localização confiável")
        linhas += ["Não estamos conseguindo situar o veículo nesta viagem "
                   "agora. Seguimos acompanhando.", "", "\U0001f449 " + lig]
        return "\n".join(linhas)

    if a.get("posicao_velha_min"):
        m = int(a["posicao_velha_min"])
        ha = "%d min" % m if m < 120 else "%dh" % round(m / 60.0)
        linhas = _cabecalho(carga, "\U0001f550", "Posição desatualizada")
        linhas += ["O veículo não reporta há cerca de %s. Assim que voltar a "
                   "reportar, avisamos." % ha, "", "\U0001f449 " + lig]
        return "\n".join(linhas)

    pct, falta = a.get("progresso_pct"), a.get("falta_km")
    if not a.get("tem_posicao") or pct is None or falta is None:
        return None

    linhas = _cabecalho(carga, "\U0001f69a", "*Em viagem*")
    linhas += [_trecho(carga), "", "%s  *%d%%*" % (barra(int(pct)), int(pct))]

    km_rota = a.get("km_rota")
    if km_rota:
        linhas.append("\U0001f6e3️ Faltam *%d km* de %d km"
                      % (round(falta), round(km_rota)))
    else:
        linhas.append("\U0001f6e3️ Faltam *%d km*" % round(falta))

    # A RETA SE DECLARA. Ela subestima sempre — "faltam 56 km" quando faltam 80
    # de asfalto é uma promessa que a operação não cumpre, e quem espera na doca
    # organiza a equipe em cima dela.
    if not a.get("por_rota"):
        linhas.append("_(distância em linha reta)_")

    t = a.get("transito") or {}
    if t.get("estado") in PONTO_TRANSITO:
        txt = "%s %s" % (PONTO_TRANSITO[t["estado"]],
                         t.get("rotulo") or "Trânsito no trecho")
        if t.get("atraso_min"):
            txt += " (~%d min de atraso)" % t["atraso_min"]
        linhas.append(txt)

    idade = a.get("atualizado_ha_min")
    if idade is not None:
        linhas.append("\U0001f550 Atualizado %s"
                      % ("agora" if idade < 2 else "há %d min" % int(idade)))

    linhas += ["", "\U0001f449 Acompanhe ao vivo:", lig]
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# várias cargas no mesmo telefone
# --------------------------------------------------------------------------
def _resumo(carga: dict) -> list[str] | None:
    """Uma carga em três linhas, para entrar numa mensagem com outras."""
    a = carga.get("andamento") or {}
    doc = carga.get("documento") or "Sua carga"
    trecho = "%s ➜ %s" % (carga.get("origem") or "origem",
                          carga.get("destino") or "destino")

    if carga.get("estado") == "entregue":
        return ["✅ *%s* · ENTREGUE" % doc, "\U0001f4cd %s" % trecho]
    if carga.get("estado") == "descarregando":
        return ["\U0001f4e6 *%s* · em descarga" % doc, "\U0001f4cd %s" % trecho]
    if a.get("fora_da_rota"):
        return ["⚠️ *%s* · sem localização agora" % doc,
                "\U0001f4cd %s" % trecho]
    if a.get("posicao_velha_min"):
        m = int(a["posicao_velha_min"])
        return ["\U0001f550 *%s* · sem reportar há %s" % (
                    doc, "%d min" % m if m < 120 else "%dh" % round(m / 60.0)),
                "\U0001f4cd %s" % trecho]

    pct, falta = a.get("progresso_pct"), a.get("falta_km")
    if not a.get("tem_posicao") or pct is None or falta is None:
        return None

    linhas = ["\U0001f69a *%s*" % doc, "\U0001f4cd %s" % trecho,
              "%s *%d%%* · faltam %d km" % (barra(int(pct)), int(pct),
                                            round(falta))]
    t = a.get("transito") or {}
    if t.get("estado") in PONTO_TRANSITO:
        linhas[-1] += "  %s" % PONTO_TRANSITO[t["estado"]]
    linhas.append("\U0001f449 " + link(carga))
    return linhas


def montar_varias(cargas: list[dict]) -> str | None:
    """UMA mensagem com todas as cargas do telefone, ou None.

    POR QUE CONSOLIDAR, e o número que decide isso: uma mensagem por carga por
    ciclo, com o teto de 5 cargas por telefone e 14 ciclos por dia, dá 70
    mensagens diárias para a MESMA pessoa — acima do teto de 60 por número que
    a casa impõe. Ou seja, quem acompanhasse cinco cargas parava de receber no
    meio da tarde, e sem nenhum aviso: as recusas ficam no nosso log, não no
    celular dela.

    E antes do teto vem o outro estrago, que é pior: cinco notificações por
    hora do mesmo número é o que faz uma pessoa bloquear o contato. O bloqueio
    não atinge estas mensagens — atinge o número que fala com todos os outros
    clientes.

    UMA CARGA CONTINUA COM A MENSAGEM INTEIRA. A consolidada é mais seca por
    construção (três linhas por carga), e degradar a experiência de quem
    acompanha uma só para acomodar quem acompanha cinco seria pagar o preço no
    caso comum.
    """
    if not cargas:
        return None
    if len(cargas) == 1:
        return montar(cargas[0])

    blocos = [b for b in (_resumo(c) for c in cargas) if b]
    if not blocos:
        # CALA porque não há o que dizer de NENHUMA delas — a terceira das três
        # respostas. Não é o mesmo que uma lista vazia por engano.
        return None

    linhas = ["\U0001f69a *Suas %d cargas*" % len(blocos), ""]
    for i, b in enumerate(blocos):
        linhas += b
        if i < len(blocos) - 1:
            linhas.append("")
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# a assinatura do que MUDOU
# --------------------------------------------------------------------------
#
# POR QUE ELA EXISTE, e o estrago que a ausência dela custou. Até 06/09/2026
# quem decidia reenviar era o TEXTO: `aviso.rodar()` comparava a mensagem
# pronta com a anterior. Só que a mensagem carrega o frescor da posição
# (`🕐 Atualizado há 3 min`) e o atraso do trânsito em minutos — dois números
# que mudam a cada ciclo POR CONSTRUÇÃO. A comparação quase nunca casava.
#
# Medido na trilha: o telefone inscrito no CT-e 94540 recebeu 14 mensagens, e
# as seis últimas, ao longo de quatro horas, diziam a mesma coisa — `2%`,
# `faltam 648 km de 662`. Para quem espera a carga, nada aconteceu quatro vezes
# seguidas; para o WhatsApp, foi uma empresa mandando quatro mensagens numa
# tarde. O estrago não é a mensagem: é a reputação do número que atende todos
# os outros clientes.
#
# A ASSINATURA É O CONTRÁRIO DO TEXTO. O texto quer ser fresco; a assinatura
# quer ser ESTÁVEL, e só muda quando muda algo que faria a pessoa agir de outro
# jeito — chegou, parou, saiu da rota, andou um pedaço de estrada que se nota.
# O texto continua trazendo o frescor: ele só perde o voto sobre o reenvio.

#: Degraus de materialidade. Andar 3 km numa viagem de 662 não é notícia; andar
#: 25 é. Os dois degraus convivem porque medem coisas diferentes: o percentual
#: pega a viagem curta (25 km nela é meia viagem), o km pega a longa (5 pontos
#: nela são 33 km). Quem chegar primeiro solta a mensagem.
#:
#: O TETO DE UMA POR HORA CONTINUA VALENDO por cima disto
#: (`assinatura.INTERVALO_MIN`), então o pior caso não piorou: o que muda é o
#: piso — antes não havia nenhum.
PASSO_PCT = 5
PASSO_KM = 25

#: Faixas do silêncio do rastreador, em minutos. Sem elas a mensagem "não
#: reporta há cerca de 3h" viraria "há 4h", "há 5h"… de hora em hora, que é o
#: mesmo defeito com outra roupa: o número cresce sozinho sem nada ter mudado.
#: Com as faixas, um silêncio longo rende no máximo quatro avisos, e cada um
#: diz uma coisa de fato diferente.
FAIXAS_SILENCIO = (120, 360, 720)


def _faixa(valor: float, cortes) -> int:
    """Em qual faixa `valor` cai. Fora de todas, a última."""
    for i, corte in enumerate(cortes):
        if valor < corte:
            return i
    return len(cortes)


def _assinatura_de_uma(carga: dict, so_marcos: bool = False) -> str:
    """O estado de UMA carga, reduzido ao que importa para quem espera.

    A ORDEM DAS PERGUNTAS É A MESMA DE `montar()`, e isso não é elegância: se
    as duas divergirem, existe um caminho em que o texto muda e a assinatura
    não — e a pessoa deixa de receber a mensagem que a avisaria da entrega.

    `so_marcos` é a cadência mais seca que a página oferece: só mudança de
    ESTADO conta. O progresso, os quilômetros e o semáforo do trânsito somem da
    assinatura — a viagem inteira, do embarque à doca, vira UMA linha que só se
    mexe quando a carga chega, entra em descarga, é entregue, ou quando paramos
    de enxergar o veículo. As ressalvas continuam valendo em qualquer cadência:
    "não sei onde ele está" é notícia para todo mundo, sempre.
    """
    a = carga.get("andamento") or {}
    doc = carga.get("documento") or "?"
    estado = carga.get("estado") or ""

    if estado in ("entregue", "descarregando"):
        # A DATA DA ENTREGA FICA DE FORA: ela é imutável depois de gravada, e
        # o estado sozinho já separa "chegou" de "está vindo".
        return "%s|%s" % (doc, estado)
    if a.get("fora_da_rota"):
        return "%s|fora" % doc
    if a.get("posicao_velha_min"):
        return "%s|mudo:%d" % (doc, _faixa(float(a["posicao_velha_min"]),
                                           FAIXAS_SILENCIO))

    pct, falta = a.get("progresso_pct"), a.get("falta_km")
    if not a.get("tem_posicao") or pct is None or falta is None:
        # `montar()` devolve None aqui — não há mensagem, então não há
        # assinatura. Quem chama trata o vazio.
        return ""

    if so_marcos:
        # EM VIAGEM É UM ESTADO SÓ. Foi para isto que a pessoa escolheu esta
        # cadência: ela não quer saber de 42% nem de 380 km, quer saber quando
        # chegar. A mensagem que sair continua trazendo tudo — o que muda é
        # QUANDO ela sai, nunca o que ela diz.
        return "%s|viagem" % doc

    # O TRÂNSITO ENTRA PELO ESTADO, NUNCA PELO ATRASO EM MINUTOS. "Fluxo livre"
    # virando "Fluxo livre (~1 min de atraso)" é ruído do provedor: o semáforo
    # é o mesmo, a decisão de quem espera é a mesma. Foi por essa diferença de
    # um minuto que uma das mensagens repetidas saiu.
    t = (a.get("transito") or {}).get("estado") or "nd"
    return "%s|v:%d:%d:%s" % (doc, int(pct) // PASSO_PCT,
                              int(round(float(falta))) // PASSO_KM, t)


def assinatura(cargas: list[dict], *, so_marcos: bool = False) -> str:
    """A assinatura da MENSAGEM inteira — todas as cargas do telefone.

    `so_marcos` é NOMEADO porque é uma escolha de quem recebe, não um detalhe
    de quem chama: um posicional aqui seria preenchido com a lista errada no
    primeiro chamador distraído, e o sintoma — mensagem a menos — é mudo.

    ORDENADA de propósito: as cargas chegam na ordem do último envio, que muda
    sozinha entre ciclos. Sem ordenar, a mesma situação assinaria diferente e a
    mensagem repetida voltaria pela porta que este módulo existe para fechar.

    O DOCUMENTO ENTRA EM CADA PEDAÇO porque o CONJUNTO também é notícia: quem
    acompanhava uma carga e cadastrou a segunda precisa receber a mensagem nova
    mesmo que a primeira não tenha se mexido um metro.
    """
    partes = sorted(p for p in (_assinatura_de_uma(c, so_marcos)
                                for c in cargas) if p)
    return "\n".join(partes)
