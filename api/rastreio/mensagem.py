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
    return ("\n\n_Para sair de UMA, responda SAIR e o número%s. "
            "Para sair de todas, só SAIR._" % ex)

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
