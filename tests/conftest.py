"""Fixtures compartilhadas da suíte.

`esquema_pg` é o padrão de teste do banco local (ver
`docs/MIGRACAO_POSTGRES.md`, seção 5). Onde o SQLite dava um arquivo próprio em
`tmp_path`, aqui cada teste ganha um SCHEMA próprio no PostgreSQL, com as
migrations aplicadas e apagado no fim.

REGRA: sem banco, o teste é PULADO dizendo por quê — nunca falha por ausência
de infraestrutura, e nunca finge que passou. Uma suíte que fica vermelha na
máquina de quem não migrou nada treina todo mundo a ignorar vermelho; uma que
passa sem ter rodado é pior ainda.
"""
from __future__ import annotations

import uuid

import pytest


@pytest.fixture(scope="session")
def pg_disponivel():
    """Diagnóstico UMA vez por sessão: sem isto, cada teste pagaria uma
    tentativa de conexão com timeout só para descobrir o mesmo."""
    from api import pglocal
    if not pglocal.configurado():
        return (False, "banco local não configurado (CORTEX_PG_PASSWORD "
                       "ausente no .env) — ver docs/MIGRACAO_POSTGRES.md")
    d = pglocal.diagnostico()
    if not d["conectado"]:
        return (False, f"PostgreSQL local inacessível em {d['onde']} "
                       f"({d['erro']}) — o serviço está de pé?")
    return (True, "")


@pytest.fixture
def esquema_pg(pg_disponivel):
    """Um schema vazio e exclusivo deste teste, com as migrations aplicadas."""
    ok, motivo = pg_disponivel
    if not ok:
        pytest.skip(motivo)
    from api import migracoes, pglocal
    # nome curto e único: o limite de identificador do Postgres é 63 bytes e
    # nome de teste com acento/parâmetro não cabe nem sempre é identificador
    nome = f"teste_{uuid.uuid4().hex[:12]}"
    migracoes.aplicar(nome)
    try:
        yield nome
    finally:
        pglocal.apagar_esquema(nome)
