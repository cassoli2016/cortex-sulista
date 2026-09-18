# -*- coding: utf-8 -*-
"""Abrir o aplicativo de um motorista pelo PAINEL, para conferir.

═══════════════════════════════════════════════════════════════════════════
POR QUE ESTA PORTA EXISTE AO LADO DO CÓDIGO MESTRE
═══════════════════════════════════════════════════════════════════════════
O código mestre resolveu o problema certo (o app diz coisas sobre uma pessoa, e
o único leitor de cada tela é quem menos pode conferir se ela está certa) com o
instrumento que havia: um segredo da casa, digitado na própria página do app.

Ele tem um custo que não some com nenhuma contenção: **é um segredo
compartilhado, sem validade, que abre a conta de qualquer motorista** — e a
trilha que ele deixa diz "alguém que sabia o código", não quem.

Aqui o porteiro é outro: a SESSÃO DO PAINEL, que já tem nome, perfil e
auditoria. Três coisas mudam de verdade:

1. **A trilha ganha nome.** `audit_log` registra fulano@sulista abrindo a conta
   de quem, e quando.
2. **Revogar vira tirar o acesso de uma pessoa**, em vez de trocar o segredo e
   reavisar todos que o usavam.
3. **O poder nasce DESLIGADO** (`acessos.PODERES`), inclusive para quem tem a
   tela da premiação: ver a régua e abrir a conta de alguém são autorizações
   diferentes.

O código mestre CONTINUA existindo, por decisão de quem opera (18/09/2026):
ele é a retaguarda de quem precisa conferir pelo celular sem ter conta no
painel. Duas portas é mais superfície — e é por isso que as duas abrem a MESMA
coisa: uma sessão normal de motorista, curta, marcada como mestre e com tarja.

═══════════════════════════════════════════════════════════════════════════
O QUE ESTA PONTE NÃO É
═══════════════════════════════════════════════════════════════════════════
Ela vai do painel PARA o app, e só nesse sentido. Uma sessão de motorista
continua sem alcançar rota nenhuma do painel — o contrato de
`api/motorista/__init__.py` segue inteiro. E a sessão aberta aqui não é um
perfil de administração dentro do app: ela lê exatamente o que aquele
motorista leria.

A janela é CURTA de propósito. Quem administra abre a conta de outra pessoa no
mesmo navegador em que trabalha, e o cookie fica lá: `TTL_HORAS` baixo é o que
impede que a conferência de hoje vire a tela de amanhã.
"""
from __future__ import annotations

import logging

from api import acessos

log = logging.getLogger("cortex.conferencia")

#: O poder que abre esta porta.
PODER = "poder.conferir_app"

#: A sessão de conferência dura MENOS que a do código mestre (4 h): lá quem
#: abre está com o celular na mão, a fim de conferir; aqui está no meio do
#: expediente, com dez abas abertas, e vai esquecer.
TTL_HORAS = 1


class SemPoder(PermissionError):
    """Quem pediu não tem o poder. Recusa legível, não 500."""


def exigir(sessao: dict) -> None:
    """A porta. LEVANTA em vez de devolver `False` — uma função que
    respondesse "não pode" seria lida um dia num `if` distraído e a rota
    passaria a abrir a conta de qualquer um."""
    if not acessos.pode(PODER, [], bool(sessao.get("admin"))) and \
            PODER not in (sessao.get("poderes") or []):
        raise SemPoder(
            "Você não tem o acesso de conferência do aplicativo. Ele é "
            "concedido pessoa a pessoa, na ficha de acessos da Gestão.")


def motoristas(busca: str = "", esquema: str | None = None) -> dict:
    """Quem se pode abrir — a MESMA lista do código mestre.

    Ela devolve só id e nome (nunca o código do ERP, que é o CPF do agregado) e
    NÃO abre sessão nenhuma: listar e entrar são duas decisões, e juntá-las
    faria a busca virar um abridor de contas.
    """
    from api.motorista import mestre
    return mestre.motoristas(busca, esquema=esquema)


def por_codigo(codigo: str, esquema: str | None = None) -> int | None:
    """O vínculo do app a partir do código do cadastro.

    A TELA MANDA O CÓDIGO, e não o id do vínculo: ela já fala por código (é o
    que a premiação usa em tudo), e fazer o payload dela carregar mais um
    identificador só para este botão seria espalhar chave por uma tela que não
    precisa dela. Quem faz a ponte é o servidor.
    """
    from api import pglocal
    from api.motorista import mestre
    # O SCHEMA VEM DO MODULO DO APP (`mestre._esq`), nao de `None`. Ler com
    # `esquema=None` funcionaria em producao e leria a PRODUCAO durante o
    # teste — a mesma familia de defeito que ja custou cinco rodadas da suite
    # escrevendo em `cortex` (a Monkey, 01/09/2026). Aqui seria leitura, e o
    # sintoma foi mais barato: o vinculo do teste "nao existia".
    r = pglocal.um("SELECT id FROM mot_vinculos WHERE motorista_codigo = %s"
                   " AND ativo ORDER BY id LIMIT 1",
                   (str(codigo or "").strip(),), esquema=mestre._esq(esquema))
    return int(r["id"]) if r else None


def abrir(motorista_id: int, autor: str, *, aparelho: str = "", ip: str = "",
          agente: str = "", esquema: str | None = None) -> dict:
    """Abre a sessão de conferência na conta daquele motorista.

    Reusa `mestre.abrir()` de propósito: as duas portas têm de produzir a
    MESMA sessão, com a mesma marca e a mesma tarja. Se um dia uma delas
    passasse a abrir algo diferente, a tarja de uma protegeria e a da outra
    não — e ninguém descobriria pela tela.
    """
    from api.motorista import mestre
    if not autor:
        raise ValueError("Informe quem está abrindo (trilha de auditoria).")
    aberto = mestre.abrir(int(motorista_id), aparelho=aparelho, ip=ip,
                          agente=agente, esquema=esquema)
    return {**aberto, "ttl_horas": TTL_HORAS, "por": autor}
