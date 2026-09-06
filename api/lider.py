# -*- coding: utf-8 -*-
"""Qual processo roda os agendadores — quando há mais de um.

A PERGUNTA VALE UMA MENSAGEM NO CELULAR DE ALGUÉM, exatamente como a de
`api/sob_teste.py`, e pelo mesmo caminho: o `@app.on_event("startup")` roda em
CADA worker do uvicorn. Medido nesta bancada em 06/09/2026, com um app isolado
e `--workers 4`:

    volta 1: startup rodou 4 vezes
    volta 2: startup rodou 6 vezes   (dois workers morreram com WinError 10022
                                      e foram respawnados)
    volta 3: startup rodou 4 vezes

Ou seja: com quatro workers, o relógio do aviso de carga subiria quatro a seis
vezes, e o cliente receberia a mesma mensagem uma vez por worker. O gate de
credencial não segura nada — nesta máquina o WhatsApp está configurado de
verdade.

A ELEIÇÃO É POR `pg_try_advisory_lock`, e a escolha tem três razões:

1. **Não precisa de infraestrutura nova.** O banco da casa já está lá; o Redis
   do `pyproject` nunca foi ligado e ligá-lo para isto seria uma peça a mais
   para falhar.
2. **A trava é de SESSÃO, não de transação**: ela morre junto com a conexão.
   Se o worker líder cair, a liderança é liberada pelo próprio PostgreSQL, sem
   temporizador e sem ninguém precisar limpar nada. Medido: matando o líder, o
   processo seguinte assume.
3. **A conexão fica FORA do pool**, segurada num global deste módulo. Conexão
   de pool volta para a fila e seria reusada por outro trecho do código — e a
   trava iria junto, entregando a liderança a quem só queria consultar.

Com UM processo (o padrão de hoje, `WEB_CONCURRENCY` ausente) a eleição
continua acontecendo e o único candidato ganha: o comportamento não muda.
"""
from __future__ import annotations

import logging

import psycopg

from . import pglocal, processos
from .sob_teste import sob_teste

log = logging.getLogger("cortex.lider")

# Um número fixo e nosso. O `pg_advisory_lock` é um espaço global por banco:
# escolher um valor "redondo" convida colisão com outra aplicação no mesmo
# servidor. Este é a porta da API (8010) com um sufixo.
CHAVE_AGENDADOR = 80100001

_CONEXAO: "psycopg.Connection | None" = None


def sou_o_agendador() -> bool:
    """Este processo deve subir os relógios (aviso de carga, digest do push)?

    Idempotente: uma vez líder, sempre líder enquanto o processo viver — e a
    segunda chamada não vai ao banco.
    """
    global _CONEXAO
    if _CONEXAO is not None:
        return True
    if sob_teste():
        return False

    try:
        conn = psycopg.connect(pglocal.dsn())
        conn.autocommit = True
        venceu = conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok", (CHAVE_AGENDADOR,)
        ).fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        # SEM BANCO NÃO HÁ ELEIÇÃO, e a resposta certa depende de quantos
        # processos existem. Com UM, negar desligaria os agendadores numa
        # instalação que hoje os liga — regressão silenciosa. Com VÁRIOS,
        # deixar todos passarem é o defeito que este módulo existe para
        # impedir, e aí o certo é negar.
        log.warning("eleicao do agendador indisponivel (%s); workers=%d",
                    type(exc).__name__, processos.workers())
        return processos.workers() <= 1

    if not venceu:
        conn.close()
        return False
    # a conexão FICA ABERTA: é ela que segura a liderança
    _CONEXAO = conn
    return True


def largar() -> None:
    """Devolve a liderança — para TESTE, não para a aplicação.

    A API segura a trava até o processo morrer, que é o desenho. Um teste que
    não largasse deixaria a chave presa para a próxima rodada no mesmo banco.
    """
    global _CONEXAO
    if _CONEXAO is not None:
        try:
            _CONEXAO.close()
        finally:
            _CONEXAO = None
