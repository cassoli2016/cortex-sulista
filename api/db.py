"""Acesso ao banco legado AVA (PostgreSQL 9.3) — SOMENTE LEITURA.

Conecta em 127.0.0.1:15432 (porta local do túnel SSH). As credenciais vêm do
.env na raiz. Toda sessão é read-only e com statement_timeout para não travar.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

try:  # pool é opcional: se a dependência ainda não foi sincronizada, conecta direto
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover
    ConnectionPool = None

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for raw in env.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_env()


def _conninfo() -> str:
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "15432"),
        dbname=os.environ.get("POSTGRES_DB", "sulista"),
        user=os.environ.get("POSTGRES_USER", "consulta_sulista"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        connect_timeout=8,
        # O servidor é UTF8, mas o libpq no Windows deriva o client_encoding da
        # codepage do sistema e escolhe LATIN1. Aí o SERVIDOR passa a converter
        # UTF8 -> LATIN1 na saída, e um caractere fora do Latin-1 derruba a
        # CONSULTA INTEIRA com UntranslatableCharacter -- não a linha, a
        # consulta. São poucas linhas (4 praças de pedágio, 20 CT-e, 12 coletas
        # com o travessão "–"), e é justamente isso que torna a armadilha ruim:
        # a tela funciona por meses e quebra no dia em que alguém cadastra um
        # nome com travessão. Pedindo UTF8 não há conversão nenhuma.
        client_encoding="UTF8",
        # read-only + timeout de segurança (o banco é de produção de terceiros)
        options="-c statement_timeout=60000 -c default_transaction_read_only=on",
    )


# Pool de conexões: o handshake de uma conexão nova custa vários round-trips —
# reusar conexões corta esse custo em todas as rotas.
_pool: "ConnectionPool | None" = None

# ---------------------------------------------------------------------------
# O QUE O POOL COBRA POR CONSULTA, E O QUE DELE DÁ PARA TIRAR (06/09/2026)
#
# `SELECT 1` numa conexão presa custa ~15 ms — é o ida-e-volta até o ERP, e é
# o piso. O mesmo `SELECT 1` pelo pool custava ~60 ms. Os ~45 ms de diferença
# NÃO eram a consulta: eram duas idas e voltas extras, uma na retirada e outra
# na devolução.
#
#   autocommit=não  check=sim  (como estava)   59,5 ms
#   autocommit=não  check=não                  50,1 ms
#   autocommit=SIM  check=sim                  33,0 ms
#   autocommit=SIM  check=não                  15,9 ms   <- o piso
#
# A tabela diz que a metade MAIOR está na devolução: o psycopg3 nasce com
# `autocommit=False`, um `SELECT` deixa a conexão dentro de uma transação, e
# devolvê-la ao pool exige um `rollback`. Sob READ COMMITTED essa transação não
# comprava consistência nenhuma (cada comando já tira o próprio snapshot), e
# ninguém escreve por aqui — a sessão nasce `default_transaction_read_only=on`.
# Parecia dinheiro no chão.
#
# **`autocommit=True` FOI MEDIDO E RECUSADO, e a causa É CONHECIDA.** Com ele
# a Visão Geral saiu de ~1,9 s para o `statement_timeout` de 60 s, em 5
# execuções de 5. O motivo não tem nada a ver com o pool:
#
#   **`SET LOCAL` fora de uma transação é NO-OP.** Provado no ERP:
#     autocommit=False -> SET LOCAL enable_mergejoin=off  =>  fica `off`
#     autocommit=True  -> SET LOCAL enable_mergejoin=off  =>  segue `on`
#
# O `api/queries.py` abre o grupo de OC da Visão Geral com
# `SET LOCAL enable_mergejoin = off` e `SET LOCAL statement_timeout = 12000`,
# e o comentário ao lado diz por quê: sem a dica, o 9.3 escolhe um merge join
# degenerado no join OC × recebimentos. Com autocommit os dois evaporam antes
# da consulta — ela roda sem a dica E sem o teto de 12 s, e vai até o global de
# 60 s. Bate exatamente com o que foi observado.
#
# Ou seja: os 30 ms do rollback SÃO recuperáveis, mas não de graça. Antes de
# ligar autocommit é preciso converter cada `SET LOCAL` da casa em `SET` de
# sessão (e devolvê-lo no fim) ou abrir transação explícita nesses blocos.
# Enquanto isso não for feito, o rollback fica: 30 ms por consulta é barato
# perto da tela principal cair.
#
# O QUE FICA, ENTÃO: o `check` saiu do caminho quente, e só isso. Ele nasceu
# para o túnel SSH que podia cair no meio; hoje o `.env` aponta direto para o
# ERP, mas a rede pública tem os próprios motivos para derrubar conexão parada
# (NAT, firewall, o ERP reiniciando), então a garantia continua valendo a pena.
# O que não vale é conferir uma conexão que acabou de responder: é pagar uma
# ida e volta para saber o que já se sabe. Agora a conferência acontece no
# máximo UMA VEZ POR MINUTO por conexão — a que está trabalhando não paga nada,
# a que ficou parada é conferida antes de ser entregue. Medido alternando em 4
# voltas: 61,3 ms -> 46,7 ms, **14,6 ms a menos em cada consulta ao ERP**.
# ---------------------------------------------------------------------------

INTERVALO_CONFERIR = 60.0   # segundos


def _conferir_se_parada(conn) -> None:
    agora = time.monotonic()
    # o atributo mora na CONEXÃO porque é dela que a resposta depende; o pool
    # troca conexão por baixo e um contador global conferiria a errada.
    if agora - getattr(conn, "_cortex_conferida_em", 0.0) < INTERVALO_CONFERIR:
        return
    ConnectionPool.check_connection(conn)   # levanta se estiver morta
    conn._cortex_conferida_em = agora


def _get_pool() -> "ConnectionPool":
    global _pool
    if _pool is None:
        # MAX_SIZE TEM DE SER MAIOR QUE O MAIOR LEQUE DA CASA, e por muito.
        #
        # Era 6. A Visão Geral abre `ThreadPoolExecutor(len(grupos) + 1)` = 5
        # workers, e cada um segura UMA conexão enquanto roda o grupo dele —
        # cinco das seis vagas, sobrando UMA para o sistema inteiro. Com o ERP
        # num dia ruim, cada consulta ocupa a vaga por até os 60 s do
        # `statement_timeout`, e todo o resto do painel leva `PoolTimeout` em
        # 15 s. Medido em 04/09/2026: `/api/health` em 503 por ~50 minutos,
        # enquanto uma conexão NOVA ao mesmo banco respondia em 0,1 s. O banco
        # estava são o tempo todo; quem estava cheio era o pool.
        #
        # 16 cobre a Visão Geral (5) com folga para a navegação de várias
        # pessoas ao mesmo tempo e para o snapshot do Copiloto, que é
        # sequencial mas concorre pelas mesmas vagas. O servidor tem
        # max_connections=800 e o usuário usa ~18 no pico: a folga é nossa,
        # não dele.
        #
        # min_size=2 porque a primeira consulta depois de um período parado
        # pagava o handshake inteiro com o usuário esperando.
        _pool = ConnectionPool(
            _conninfo(), kwargs={"row_factory": dict_row},
            min_size=2, max_size=16, max_idle=300, timeout=15,
            # `max_lifetime`: conexão parada morre calada (NAT, firewall, ERP
            # reiniciando). Reciclar de hora em hora custa um handshake
            # amortizado e limita há quanto tempo uma conexão pode estar
            # apodrecendo sem ninguém ter olhado.
            max_lifetime=3600,
            check=_conferir_se_parada, name="ava", open=True)
    return _pool


def fechar_pool() -> None:
    """Encerra o pool de propósito — para SCRIPT, não para a API.

    A API vive com o pool aberto até o processo morrer. Já um script de linha
    de comando (conferir_numeros) que termina sem fechar deixa o worker do
    pool vivo e o psycopg imprime "couldn't stop thread 'ava-worker-0'" no
    stderr depois do veredito — aviso que se lê como problema onde não há.
    """
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn():
    if ConnectionPool is None:
        with psycopg.connect(_conninfo(), row_factory=dict_row) as conn:
            yield conn
        return
    with _get_pool().connection() as conn:
        yield conn


def query(sql: str, params: tuple | None = None) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()
