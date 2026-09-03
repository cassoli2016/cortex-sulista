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


# ---------------------------------------------------------------------------
# NENHUM TESTE ESCREVE NO SCHEMA DE PRODUÇÃO.
#
# Aconteceu em 01/09/2026: os testes da coleta da Monkey redirecionavam o
# `registro.ESQUEMA` (a posição) para o schema de teste e esqueciam o
# `espelho.ESQUEMA` — e `servico.coletar()` grava os dois. Cinco rodadas da
# suíte no mesmo dia puseram 3 recebíveis dos sellers de dublê (111/222/4242)
# e 65 "cargas" de um a quatro títulos dentro de `cortex.mky_recebiveis` e
# `cortex.mky_carga`, em produção. A tela do Portal Tupy passou a dizer
# "3 em aberto — DIVERGE do painel", e a divergência era o teste.
#
# O sintoma é mudo (nenhum teste falha — eles PASSAM gravando no lugar
# errado), então a regra precisa de um guard que fique vermelho: depois de
# cada teste, uma foto barata das tabelas que a coleta escreve. Se mudou, o
# teste que acabou de rodar escreveu em produção e é ELE que erra, com o
# nome na tela. Uma consulta por teste, numa conexão curta.
#
# Falso positivo possível: a coleta REAL (tarefa agendada, ou alguém na tela)
# gravando enquanto a suíte roda. Raro, e a mensagem diz como distinguir —
# a carga real tem dezenas de milhares de recebíveis, a de dublê tem um.
# ---------------------------------------------------------------------------
_FOTO_PRODUCAO: dict = {"ultima": None}


def _foto_producao():
    from api import pglocal
    return pglocal.um(
        "SELECT (SELECT coalesce(max(id), 0) FROM mky_carga) AS cargas,"
        " (SELECT count(*) FROM mky_recebiveis) AS recebiveis,"
        " (SELECT coalesce(max(id), 0) FROM ant_envios) AS envios,"
        " (SELECT coalesce(max(id), 0) FROM sup_chamados) AS chamados,"
        " (SELECT coalesce(max(id), 0) FROM sup_avisos) AS avisos_sup")


@pytest.fixture(autouse=True)
def producao_intocada(request, pg_disponivel):
    """Falha o teste que ESCREVEU em `cortex.mky_*`/`ant_envios` (produção)."""
    ok, _ = pg_disponivel
    if not ok:
        yield
        return
    if _FOTO_PRODUCAO["ultima"] is None:
        try:
            _FOTO_PRODUCAO["ultima"] = _foto_producao()
        except Exception:  # noqa: BLE001 — tabela ainda não migrada: nada a vigiar
            yield
            return
    yield
    try:
        agora = _foto_producao()
    except Exception:  # noqa: BLE001
        return
    antes, _FOTO_PRODUCAO["ultima"] = _FOTO_PRODUCAO["ultima"], agora
    if agora != antes:
        pytest.fail(
            f"{request.node.nodeid} ESCREVEU no schema de PRODUÇÃO (cortex): "
            f"{antes} -> {agora}. Todo módulo que grava expõe `ESQUEMA`; o teste "
            "tem de redirecioná-lo para o `esquema_pg` (a coleta da Monkey grava "
            "registro E espelho — os dois). Se foi a coleta real rodando junto, "
            "a carga tem dezenas de milhares de recebíveis, não um.")
