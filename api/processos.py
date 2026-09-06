# -*- coding: utf-8 -*-
"""Quantos processos servem esta aplicação — e o que isso muda.

MÓDULO SEM DEPENDÊNCIA DE PROPÓSITO (só `os`): quem precisa desta resposta é o
`api/pglocal.py` e o `api/db.py`, que são a base de tudo. Qualquer import a
mais aqui viraria ciclo.

`WEB_CONCURRENCY` é a variável que o próprio uvicorn lê para decidir o número
de workers, então usá-la evita ter DUAS fontes que podem divergir — o dia em
que alguém subir com `--workers 4` sem exportar a variável, os pools ainda
seriam dimensionados para 1 e o PostgreSQL local recusaria conexão.

POR QUE ISSO IMPORTA (medido em 06/09/2026): os pools são POR PROCESSO. Com o
`max_size=20` do banco da casa e 4 workers seriam 80 conexões, contra o
`max_connections=100` do PostgreSQL local que já tem 9 em uso. E num boot ruim
o uvicorn no Windows respawna worker (visto: 6 processos para `--workers 4`),
o que levaria a 120 — acima do teto, e a falha apareceria como "não consigo
entrar no sistema", não como "faltou conexão".
"""
from __future__ import annotations

import os


def workers() -> int:
    """Número de processos servindo a aplicação. 1 é o padrão e o estado atual."""
    try:
        return max(1, int(os.environ.get("WEB_CONCURRENCY", "1")))
    except (TypeError, ValueError):
        return 1


# O MAIOR LEQUE DE UMA REQUISIÇÃO SÓ. A Visão Geral abre
# `ThreadPoolExecutor(len(grupos) + 1)` = 5 conexões ao mesmo tempo, e todas
# saem do pool do MESMO processo. Um pool menor que isso faz uma única
# requisição esperar por si mesma até o `timeout` — foi o `PoolTimeout` de
# 04/09/2026, quando `max_size` era 6 e cinco vagas iam para a Visão Geral.
LEQUE_MAXIMO = 5


def fatia_do_pool(total: int, piso: int = LEQUE_MAXIMO + 1) -> int:
    """O tamanho de pool que cabe a CADA processo.

    O PISO NÃO É MARGEM DE CONFORTO, é o `LEQUE_MAXIMO` mais uma vaga: dividir
    o pool entre workers não pode deixá-lo menor que o que UMA requisição
    precisa de uma vez. Foi o guard `test_o_pool_cabe_o_maior_leque_da_casa`
    que pegou isto — o piso tinha nascido 4, e com 4 workers a Visão Geral
    pediria 5 vagas num pool de 4 e travaria em si mesma.
    """
    return max(piso, total // workers())
