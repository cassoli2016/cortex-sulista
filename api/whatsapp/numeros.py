"""Telefone brasileiro: normalizar para o formato que a Z-API exige.

A Z-API pede `DDI DDD NÚMERO`, só dígitos, sem máscara — `5511999999999`.
Quem digita telefone não digita assim: digita `(47) 99999-8888`, `47 9 9999
8888`, `+55 47 99999-8888`. Traduzir isso é trabalho de uma função, não do
operador.

DUAS COISAS QUE PARECEM DETALHE E NÃO SÃO:

1. **A normalização é o que faz o freio funcionar.** O limite que protege o
   número conta DESTINATÁRIOS DISTINTOS na trilha. Se cada formato virasse uma
   linha diferente, o mesmo cliente contaria três vezes — e o contador que
   protege a conta nunca refletiria a realidade.
2. **DDD inválido é erro de digitação, não número que não existe.** `(04)` e
   `(20)` não são DDD no Brasil. Barrar aqui devolve "DDD 20 não existe" na
   hora, em vez de a mensagem sair e sumir.

O NONO DÍGITO NÃO É AJUSTADO AQUI, DE PROPÓSITO. Celular antigo pode estar
registrado no WhatsApp sem o 9 na frente, e existe a tentação de "consertar"
isso acrescentando ou removendo o dígito. Não fazemos: quem resolve essa
equivalência é o próprio WhatsApp, e a Z-API documenta que valida a existência
do número a cada mensagem enviada — pedindo explicitamente que NÃO se faça a
verificação antes do envio, porque duplica a checagem. O que se manda é o que o
cadastro tem, e a trilha guarda exatamente isso: se um número não recebe, dá
para ver o que saiu.

GRUPO ENTRA — COM NOME PRÓPRIO, como este arquivo prometeu quando ainda não
havia caso de uso. Ele apareceu: o resumo diário de faturamento vai para a
diretoria, e um grupo é o destino natural disso.

O que "nome próprio" quer dizer na prática: `normalizar()` continua sendo SÓ
telefone e continua recusando grupo. Quem aceita os dois é `destino()`, que
devolve o TIPO junto com o valor — porque quase toda decisão a jusante depende
de saber qual é qual:

* o freio conta grupo como UM destinatário, porque para o WhatsApp é uma
  conversa só (mandar para um grupo de 40 pessoas não é o mesmo risco que
  mandar para 40 números novos — é o oposto disso);
* a trilha guarda o id do grupo, que não é telefone de ninguém e não pode ser
  formatado como se fosse;
* a tela mostra o NOME do grupo, que só a Z-API sabe.

O ID DE GRUPO NÃO É VALIDÁVEL DE VERDADE AQUI, e o formato abaixo é só um
filtro de digitação. Quem sabe se um grupo existe é a Z-API (`GET /groups`), e
é de lá que a tela tira a lista — inventar validação mais esperta daria falso
negativo em grupo legítimo de formato novo.
"""
from __future__ import annotations

import re

# DDDs que existem no Brasil. A lista é literal por escolha: uma faixa 11..99
# aceitaria 20, 23, 30, 36, 40, 50, 60, 70, 80 e 90, que não são DDD de lugar
# nenhum — e o erro só apareceria como mensagem não entregue.
DDDS = frozenset({
    11, 12, 13, 14, 15, 16, 17, 18, 19,          # SP
    21, 22, 24,                                  # RJ
    27, 28,                                      # ES
    31, 32, 33, 34, 35, 37, 38,                  # MG
    41, 42, 43, 44, 45, 46,                      # PR
    47, 48, 49,                                  # SC
    51, 53, 54, 55,                              # RS
    61,                                          # DF
    62, 64,                                      # GO
    63,                                          # TO
    65, 66,                                      # MT
    67,                                          # MS
    68,                                          # AC
    69,                                          # RO
    71, 73, 74, 75, 77,                          # BA
    79,                                          # SE
    81, 87,                                      # PE
    82,                                          # AL
    83,                                          # PB
    84,                                          # RN
    85, 88,                                      # CE
    86, 89,                                      # PI
    91, 93, 94,                                  # PA
    92, 97,                                      # AM
    95,                                          # RR
    96,                                          # AP
    98, 99,                                      # MA
})

DDI_BR = "55"

# Id de grupo da Z-API. TRÊS formatos convivem, e o primeiro só apareceu quando
# se olhou a resposta de verdade — as duas suposições anteriores estavam certas
# na documentação e erradas nesta conta:
#
#   120363421141267015-group      é o que o `GET /groups` devolve AQUI
#   120363421141267015@g.us       o formato clássico do WhatsApp
#   5547999998888-1616969528      o antigo, criador + timestamp
#
# Reconhecer só os dois últimos fazia o grupo real desta conta cair na porta do
# TELEFONE e sair recusado com "DDD 12 não existe" — mensagem que manda
# conferir DDD onde não há DDD nenhum. Foi o playground que mostrou.
_GRUPO_SUFIXOS = ("@g.us", "-group")
_GRUPO_ANTIGO = re.compile(r"^\d{10,15}-\d{6,}$")
_GRUPO_NOVO = re.compile(r"^\d{16,}$")


def _sem_sufixo(texto: str) -> str:
    t = str(texto or "").strip()
    for suf in _GRUPO_SUFIXOS:
        if t.lower().endswith(suf):
            return t[: -len(suf)]
    return t

TIPO_TELEFONE = "telefone"
TIPO_GRUPO = "grupo"


class TelefoneInvalido(ValueError):
    """A mensagem desta exceção vai direto para a tela — escrita para quem está
    com o cadastro aberto, não para quem lê log."""


def so_digitos(bruto: str) -> str:
    return re.sub(r"\D", "", str(bruto or ""))


def normalizar(bruto: str) -> str:
    """`(47) 99999-8888` -> `5547999998888`. Levanta `TelefoneInvalido`.

    Aceita com ou sem DDI. Sem DDI assume Brasil, que é a operação inteira da
    Sulista — e um número estrangeiro digitado sem DDI seria indistinguível de
    um brasileiro, então adivinhar outro país seria pior que assumir este.
    """
    d = so_digitos(bruto)
    if not d:
        raise TelefoneInvalido("Informe o telefone.")

    # 00 é o prefixo de discagem internacional a partir do Brasil (00 55 ...);
    # aparece quando alguém copia o número de uma agenda de telefonia fixa.
    if d.startswith("00"):
        d = d[2:]

    if len(d) in (10, 11):
        d = DDI_BR + d              # sem DDI: é do Brasil
    elif len(d) in (12, 13) and d.startswith(DDI_BR):
        pass                        # já veio 55 + DDD + número
    elif d.startswith(DDI_BR):
        raise TelefoneInvalido(
            f"Telefone com {len(d) - 2} dígitos depois do DDI 55 — no Brasil "
            "são 10 (fixo) ou 11 (celular).")
    else:
        raise TelefoneInvalido(
            "Telefone fora do formato brasileiro. Informe DDD + número "
            "(ex.: 47 99999-8888) ou o número completo com DDI.")

    ddd = int(d[2:4])
    if ddd not in DDDS:
        raise TelefoneInvalido(f"DDD {d[2:4]} não existe no Brasil.")

    assinante = d[4:]
    if len(assinante) == 9:
        if assinante[0] != "9":
            raise TelefoneInvalido(
                "Celular com 9 dígitos tem de começar com 9 "
                f"(recebido: {assinante[0]}).")
    elif len(assinante) == 8:
        # Fixo começa em 2..5; 9 com 8 dígitos é celular ANTIGO, sem o nono
        # dígito — aceito, porque quem resolve isso é o WhatsApp. Mas 0 e 1 não
        # iniciam número de assinante nenhum.
        if assinante[0] in "01":
            raise TelefoneInvalido(
                f"Número de assinante inválido: começa com {assinante[0]}.")
    else:   # pragma: no cover - as faixas acima já cobrem
        raise TelefoneInvalido("Telefone com quantidade de dígitos inválida.")

    return d


def valido(bruto: str) -> bool:
    try:
        normalizar(bruto)
        return True
    except TelefoneInvalido:
        return False


def e_grupo(bruto: str) -> bool:
    """Parece id de grupo? Filtro de digitação, não prova de existência."""
    t = _sem_sufixo(bruto)
    return bool(_GRUPO_ANTIGO.match(t) or _GRUPO_NOVO.match(t))


def normalizar_grupo(bruto: str) -> str:
    """Tudo vira a forma canônica `120363...-group`.

    DUAS RAZÕES, e a segunda foi MEDIDA contra a API de verdade:

    1. O mesmo grupo chega de jeitos diferentes — da lista do `GET /groups` vem
       com `-group`, de um link copiado vem com `@g.us`, e digitado à mão vem
       pelado. Guardar como veio faria o mesmo grupo contar como três
       destinatários distintos na trilha, e o freio mediria formato em vez de
       conversa.
    2. **O SUFIXO É OBRIGATÓRIO PARA A Z-API.** A escolha óbvia seria guardar
       só os dígitos, que é o mais limpo; testado contra a API real, o id sem
       sufixo devolve `HTTP 400: Phone is wrong`. Então o canônico é o que ela
       aceita, não o que é bonito.

    O formato antigo (`5547999998888-1616969528`) fica como está: já é um id
    completo, e acrescentar `-group` a ele seria inventar.
    """
    t = _sem_sufixo(bruto)
    if not e_grupo(t):
        raise TelefoneInvalido(f"“{bruto}” não parece um id de grupo.")
    return t if _GRUPO_ANTIGO.match(t) else f"{t}-group"


def destino(bruto: str) -> tuple[str, str]:
    """`(tipo, valor)` — o único lugar que aceita telefone E grupo.

    Grupo é testado ANTES do telefone: um id novo (`120363…`, 18 dígitos)
    passaria pela porta do telefone como "número com dígitos demais" e sairia
    com a mensagem errada, mandando conferir DDD onde não há DDD nenhum.
    """
    t = str(bruto or "").strip()
    if e_grupo(t):
        return TIPO_GRUPO, normalizar_grupo(t)
    return TIPO_TELEFONE, normalizar(t)


def destino_valido(bruto: str) -> bool:
    try:
        destino(bruto)
        return True
    except TelefoneInvalido:
        return False


def formatar(numero: str) -> str:
    """`5547999998888` -> `(47) 99999-8888`, para a tela e a trilha.

    O que vai para a Z-API é sempre o normalizado; isto existe só para o humano
    conferir que é o número que ele quis.

    ID DE GRUPO SAI COMO ESTÁ: aplicar máscara de telefone nele produziria
    `(12) 03630-19502650977`, que parece um número e não é o de ninguém.
    """
    if e_grupo(numero):
        return str(numero or "").strip()
    d = so_digitos(numero)
    if len(d) in (12, 13) and d.startswith(DDI_BR):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return numero


def separar(texto: str | list) -> list[str]:
    """Vários destinatários vindos de um campo de texto, como o correio faz.

    Devolve os BRUTOS, na ordem — normalizar a saída esconderia qual entrada
    estava errada quando uma delas não passa.

    A REPETIÇÃO É MEDIDA PELO NÚMERO NORMALIZADO, não pelo que foi digitado.
    Deduplicar por dígitos crus deixava `47999998888` e `5547999998888`
    passarem como duas pessoas — a mesma cliente recebendo a mensagem duas
    vezes e gastando duas fatias do limite diário. Foi um teste que pegou.

    Entrada inválida não tem número normalizado para servir de chave: ela cai
    nos dígitos crus e sobrevive à limpeza, de propósito, para a recusa
    aparecer com o que a pessoa digitou.
    """
    if isinstance(texto, list):
        brutos = [str(x) for x in texto]
    else:
        brutos = re.split(r"[,;\n]+", str(texto or ""))
    fora, vistos = [], set()
    for b in brutos:
        b = b.strip()
        if not b:
            continue
        try:
            chave = destino(b)[1]
        except TelefoneInvalido:
            chave = so_digitos(b) or b
        if chave in vistos:
            continue
        vistos.add(chave)
        fora.append(b)
    return fora
