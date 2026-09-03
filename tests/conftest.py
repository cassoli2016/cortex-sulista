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
        " (SELECT coalesce(max(id), 0) FROM sup_avisos) AS avisos_sup,"
        # A auditoria de USO entrou aqui depois de vazar: 238 sessões de teste
        # (`ana@sulista.local` e companhia) apareceram na tela de Auditoria de
        # PRODUÇÃO em 03/09/2026, gravadas ao longo de uma suíte inteira. O
        # guard existia e não pegou porque a lista era fixa e o módulo era
        # novo — a mesma classe de defeito que já custou caro nesta casa.
        # Lista fixa envelhece: módulo que GRAVA entra aqui no mesmo commit.
        " (SELECT coalesce(max(id), 0) FROM aud_sessoes) AS aud_sess,"
        # `aud_telas` NÃO tem `id` — a chave dela é (sessao_id, tela). O
        # `max(id)` que eu escrevi aqui primeiro levantava UndefinedColumn, e
        # como o `producao_intocada` engole exceção para tolerar tabela ainda
        # não migrada, o efeito não era um guard incompleto: era o guard
        # INTEIRO desligado em silêncio, inclusive para as tabelas antigas.
        # Pego sabotando a lixeira e vendo que ninguém reclamou.
        " (SELECT count(*) FROM aud_telas) AS aud_telas")


@pytest.fixture(scope="session")
def _lixeira_auditoria(request):
    """Um schema descartável para onde vai a auditoria de uso INCIDENTAL.

    Quase todo teste que faz login pela API grava uma sessão de uso sem que o
    uso seja o assunto dele — e, com `ESQUEMA` em branco, "sem assunto" queria
    dizer "produção". Em vez de pedir a duzentos testes que redirecionem, o
    padrão passa a ser seguro: um schema por SESSÃO de teste (barato, criado
    uma vez), apagado no fim. Quem testa a auditoria de propósito continua
    redirecionando para o seu `esquema_pg` e sobrescreve isto.
    """
    from api import migracoes, pglocal
    nome = f"teste_aud_{uuid.uuid4().hex[:10]}"
    try:
        migracoes.aplicar(nome)
    except Exception:  # noqa: BLE001 — sem Postgres não há o que proteger
        yield None
        return
    try:
        yield nome
    finally:
        try:
            pglocal.apagar_esquema(nome)
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def auditoria_fora_de_producao(_lixeira_auditoria, monkeypatch):
    """A auditoria de uso nunca escreve em produção durante a suíte."""
    if _lixeira_auditoria:
        from api import auditoria
        monkeypatch.setattr(auditoria, "ESQUEMA", _lixeira_auditoria)


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
