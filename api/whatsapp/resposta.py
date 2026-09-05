# -*- coding: utf-8 -*-
"""As regras de envio de uma RESPOSTA — não de um disparo.

A DIFERENÇA QUE ESTE MÓDULO EXISTE PARA MARCAR. A janela de horário
(08:00–20:00) protege o cliente de receber mensagem da empresa de madrugada, e
vale para tudo que a casa manda por iniciativa própria: o aviso de hora em
hora, o resumo diário, a cobrança. Mas há mensagens que não são iniciativa
nossa — são resposta a uma coisa que a pessoa acabou de fazer, com o celular na
mão:

- a primeira mensagem de quem apertou "Avisar-me" há dois segundos;
- a confirmação de quem respondeu SAIR.

Barrar essas duas pela janela não protege ninguém: a pessoa está acordada, ela
provocou a mensagem, e o silêncio faz o recurso parecer quebrado. Pior no caso
do SAIR — quem pede para sair e não recebe nada não tenta de novo, bloqueia o
número. E o bloqueio não atinge aquela mensagem: atinge o número que fala com
todos os outros clientes.

MEDIDO DUAS VEZES, e a segunda por não ter generalizado a primeira. Às 23h08 a
inscrição gravou e a primeira mensagem foi recusada com "fora da janela"; o
conserto foi feito só ali, em `assinatura._primeira_mensagem`. A confirmação do
SAIR ficou com o mesmo defeito, esperando alguém responder SAIR à noite — e
esse alguém teria sido um cliente.

`regras` SUBSTITUI a configuração inteira, não remenda: passar só a janela
derruba o envio num `KeyError` em `c["ativo"]`. Por isso aqui se parte da
configuração geral e se troca UM campo — assim o interruptor geral, o limite do
dia e o teto por número continuam valendo, que é o ponto.
"""
from __future__ import annotations

from . import config as cfg


def regras() -> dict:
    """A configuração da casa com a janela aberta, e só ela.

    O que NÃO muda: `ativo` (o interruptor geral continua desligando tudo),
    `limite_dia` e o teto por número. Uma resposta imediata pode sair às 3 da
    manhã; o que ela não pode é furar o freio.
    """
    geral = cfg.ler()
    return {**geral,
            "limite_numero": geral["limite_dia"],
            "limite_modelo": None,
            "janela_inicio": "00:00",
            "janela_fim": "23:59"}
