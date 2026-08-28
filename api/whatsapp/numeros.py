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

GRUPO NÃO ENTRA. A Z-API aceita o id de um grupo no mesmo campo `phone`, mas
mandar para grupo é outra decisão (todo mundo lê, ninguém responde em
particular) e nenhum fluxo do CÓRTEX pede isso hoje. O validador recusa; quando
houver caso de uso, entra aqui com nome próprio.
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


def formatar(numero: str) -> str:
    """`5547999998888` -> `(47) 99999-8888`, para a tela e a trilha.

    O que vai para a Z-API é sempre o normalizado; isto existe só para o humano
    conferir que é o número que ele quis.
    """
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
            chave = normalizar(b)
        except TelefoneInvalido:
            chave = so_digitos(b) or b
        if chave in vistos:
            continue
        vistos.add(chave)
        fora.append(b)
    return fora
