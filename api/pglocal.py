"""Banco de ESCRITA do CÓRTEX — PostgreSQL local.

SEPARADO de `api/db.py` de propósito, e a separação não é estética:

- `api/db.py` é a réplica do ERP (AVA), de terceiro, **somente leitura**, num
  host remoto. Toda sessão dele nasce com `default_transaction_read_only=on`.
- este módulo é o banco da casa, onde o CÓRTEX ESCREVE — o que hoje mora nos
  dez SQLite de `data/`.

Um módulo só, com uma variável de ambiente trocada, mandaria query do ERP para
o banco local. O sintoma seria "os números sumiram", não "erro de conexão" — o
tipo de defeito que se procura no lugar errado por meio dia.

COM POOL DESDE 06/09/2026, E COM A MEDIÇÃO QUE ESTE ARQUIVO PEDIU. Aqui estava
escrito "conexão curta, sem pool… o pool entra quando o `auth` migrar — é ele
que faz muitas consultas pequenas por request — e aí com medição, não por
suposição". O `auth` migrou, e a medição chegou:

    caminho do `sessao_atual()`, que roda em TODA requisição autenticada
      conexão nova por requisição (como era)  31,4 ms   (p95 144,0 ms)
      pelo pool, com o `SET search_path`       0,4 ms   (p95   0,6 ms)

Abrir a conexão era **99% do custo**: a consulta em si mede 0,07 ms. E piorava
justamente sob carga — 60 conexões simultâneas levavam o mesmo `connect()` de
20 ms para 165 ms, porque no Windows cada conexão nova é um processo novo do
lado do servidor.

A RESSALVA DAQUELE COMENTÁRIO CONTINUA VALENDO, e é por isso que o
`SET search_path` ficou onde estava: ele é refeito A CADA RETIRADA do pool, não
uma vez na role. Schema de teste e schema de produção convivem no mesmo
servidor, e um `search_path` grudado de outra chamada gravaria dado de produção
dentro do schema de um teste — ou o contrário, que é pior. Custa 0,045 ms.

DUAS COISAS FORAM CONFERIDAS ANTES, e não presumidas:

1. **Nada de estado de sessão vaza entre conexões reusadas.** A varredura do
   código não achou `CREATE TEMP`, `pg_advisory_lock`, `LISTEN/NOTIFY` nem
   cursor nomeado; os únicos `SET` da casa são `SET LOCAL` (que morre no fim da
   transação) e moram no caminho do ERP, não neste.
2. **Prepared statement não fura o isolamento por schema.** A dúvida era real:
   a mesma SQL roda em centenas de schemas de teste na mesma conexão. Medido
   com um schema A e um B de mesma forma — o PostgreSQL replaneja quando o
   `search_path` muda, e a linha foi para o schema certo com
   `prepare_threshold` no padrão e desligado.

O ESQUEMA É PARÂMETRO porque é assim que o teste fica isolado: onde o SQLite
recebia um arquivo em `tmp_path`, aqui se recebe um schema próprio. Ver
`docs/MIGRACAO_POSTGRES.md`.
"""
from __future__ import annotations

import atexit
import os
from contextlib import contextmanager

import psycopg
from psycopg import sql as _sql
from psycopg.rows import dict_row

try:  # pool é opcional: sem a dependência sincronizada, conecta direto
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover
    ConnectionPool = None

from .db import _load_env  # o .env já é lido por api/db.py; não ler duas vezes

_load_env()

ESQUEMA_PADRAO = "cortex"


class NaoConfigurado(RuntimeError):
    """Faltam as variáveis do banco local — a instalação não tem esse recurso."""


def configurado() -> bool:
    """Sem senha não há banco local. Ausência NÃO é falha: é instalação que
    ainda não migrou nada, e nesse caso quem chama cai no SQLite."""
    return bool((os.environ.get("CORTEX_PG_PASSWORD") or "").strip())


def dsn() -> str:
    """Nunca devolve a senha em mensagem de erro: quem loga isto loga o segredo
    junto. O `conninfo` só é montado para ser entregue ao psycopg."""
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("CORTEX_PG_HOST", "127.0.0.1"),
        port=os.environ.get("CORTEX_PG_PORT", "5432"),
        dbname=os.environ.get("CORTEX_PG_DB", "cortex"),
        user=os.environ.get("CORTEX_PG_USER", "cortex"),
        password=os.environ.get("CORTEX_PG_PASSWORD", ""),
        connect_timeout=5,
        # o banco é local e nosso: pode escrever. O timeout existe para que uma
        # consulta ruim não segure um worker do uvicorn para sempre.
        options="-c statement_timeout=30000",
    )


def onde() -> str:
    """Host:porta/banco — para a tela de Saúde dizer contra o que está falando,
    sem nunca incluir usuário nem senha."""
    return (f"{os.environ.get('CORTEX_PG_HOST', '127.0.0.1')}:"
            f"{os.environ.get('CORTEX_PG_PORT', '5432')}/"
            f"{os.environ.get('CORTEX_PG_DB', 'cortex')}")


# O pool vive por processo. `_pool_dsn` guarda de QUE configuração ele nasceu:
# `tests/test_pglocal.py` troca `CORTEX_PG_*` por `monkeypatch` no meio da
# suíte, e um pool preso ao DSN antigo responderia consultas apontando para o
# lugar errado — em silêncio, que é o pior jeito.
_pool: "ConnectionPool | None" = None
_pool_dsn: str | None = None


def _get_pool() -> "ConnectionPool":
    global _pool, _pool_dsn
    atual = dsn()
    if _pool is not None and _pool_dsn != atual:
        _pool.close()
        _pool = None
    if _pool is None:
        _pool = ConnectionPool(
            atual, kwargs={"row_factory": dict_row},
            # 20 cobre o threadpool do uvicorn com folga; o PostgreSQL local
            # aceita 100 e tem 9 em uso. min_size=2 para a primeira requisição
            # depois de um período parado não pagar o handshake.
            min_size=2, max_size=20, max_idle=300, timeout=10,
            # AQUI o check vale a pena, ao contrário do pool do ERP: é
            # loopback, custa 0,043 ms (lá custava 20 ms), e o serviço do
            # PostgreSQL reinicia sozinho em atualização do Windows.
            check=ConnectionPool.check_connection,
            name="cortex", open=True)
        _pool_dsn = atual
    return _pool


def fechar_pool() -> None:
    """Encerra o pool — para SCRIPT, não para a API.

    A API vive com ele aberto até o processo morrer. Script de linha de comando
    que termina sem fechar deixa o worker do pool vivo e o psycopg imprime
    "couldn't stop thread" no stderr depois do veredito — aviso que se lê como
    problema onde não há. Registrado no `atexit` para os ~15 scripts da casa
    não precisarem lembrar disso um a um.
    """
    global _pool, _pool_dsn
    if _pool is not None:
        _pool.close()
        _pool = None
        _pool_dsn = None


atexit.register(fechar_pool)


@contextmanager
def get_conn(esquema: str | None = None):
    """Conexão curta com transação automática (commit no fim, rollback no erro).

    O `search_path` é fixado A CADA conexão, e não uma vez na role: schema de
    teste e schema de produção convivem no mesmo servidor, e um `SET` que
    sobrasse de outra chamada gravaria dado de produção dentro do schema de um
    teste — ou o contrário, que é pior.
    """
    if not configurado():
        raise NaoConfigurado(
            "banco local não configurado — falta CORTEX_PG_PASSWORD no .env "
            "(ver docs/MIGRACAO_POSTGRES.md)")

    def _preparar(conn):
        with conn.cursor() as cur:
            # identificador vem de código nosso e de teste, nunca de HTTP;
            # ainda assim vai por Identifier, que é o certo e custa nada
            cur.execute(_sql.SQL("SET search_path TO {}, public").format(
                _sql.Identifier(esquema or ESQUEMA_PADRAO)))

    if ConnectionPool is None:   # sem a dependência: como era antes
        conn = psycopg.connect(dsn(), row_factory=dict_row)
        try:
            with conn:
                _preparar(conn)
                yield conn
        finally:
            conn.close()
        return

    # `connection()` do pool já faz o `with conn:` (commit no fim, rollback no
    # erro) e devolve a conexão ao pool no `finally` — a mesma transação de
    # antes, sem o `connect()` de 31 ms.
    with _get_pool().connection() as conn:
        _preparar(conn)
        yield conn


def query(sql: str, params: tuple | dict | None = None,
          esquema: str | None = None) -> list[dict]:
    with get_conn(esquema) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def um(sql: str, params: tuple | dict | None = None,
       esquema: str | None = None) -> dict | None:
    linhas = query(sql, params, esquema)
    return linhas[0] if linhas else None


def executar(sql: str, params: tuple | dict | None = None,
             esquema: str | None = None) -> int:
    with get_conn(esquema) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def criar_esquema(nome: str) -> None:
    """Cria um schema vazio. Usado pelo runner de migration e pelos testes."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                _sql.Identifier(nome)))


def apagar_esquema(nome: str) -> None:
    """DROP CASCADE — só para schema de teste. Recusa o schema de produção de
    propósito: um `apagar_esquema()` sem argumento por engano apagaria tudo."""
    if nome == ESQUEMA_PADRAO:
        raise ValueError(f"recusado: {nome!r} é o schema de produção")
    # o runner memoriza quais schemas já estão na última versão; apagar sem
    # esquecer faria o próximo schema de mesmo nome nascer sem tabela nenhuma
    from .migracoes import _EM_DIA
    _EM_DIA.discard(nome)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                _sql.Identifier(nome)))


def sem_tabela(exc: Exception) -> bool:
    """Tabela que ainda não existe é BASE VAZIA, não falha.

    É o que, no SQLite, era `if not Path(p).exists()`. A distinção vale para
    todo store migrado: `UndefinedTable` vira "nunca gravou nada" (e a tela diz
    isso, que é verdade), enquanto erro de CONEXÃO sobe — aí a tela não pode
    afirmar nada, e engolir a falha faria "banco fora do ar" parecer "não há
    dado", que é a mentira mais cara desta migração.
    """
    return isinstance(exc, psycopg.errors.UndefinedTable)


def diagnostico() -> dict:
    """Estado da conexão — alimenta a tela de Saúde. Não levanta: é a tela onde
    se olha justamente quando alguma coisa está errada."""
    if not configurado():
        return {"configurado": False, "conectado": False, "onde": onde(),
                "erro": None, "ms": None, "versao_schema": None}
    import time
    t0 = time.perf_counter()
    try:
        # DE PROPÓSITO FORA DO POOL. Esta é a tela de Saúde, e o que ela precisa
        # responder é "o banco aceita uma conexão AGORA?" — não "a conexão que
        # o pool abriu meia hora atrás ainda serve". As duas perguntas se
        # separam no dia ruim: com o `max_connections` esgotado (ou o serviço
        # recusando conexão nova), o pool segue atendendo com o que já tem e o
        # cartão diria "conectado" enquanto ninguém mais consegue entrar. O
        # `ms` daqui também passa a significar de novo o custo de CHEGAR ao
        # banco, que é o número que se olha quando alguma coisa está errada.
        conn = psycopg.connect(dsn(), row_factory=dict_row)
        try:
            with conn:
                # CONECTAR e LER A VERSÃO são duas perguntas diferentes, e
                # juntá-las custou a primeira execução do runner: banco
                # recém-criado não tem `schema_versao`, o UndefinedTable subia
                # como falha de conexão e o script se recusava a aplicar
                # justamente a migration que criaria a tabela.
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    ms = round((time.perf_counter() - t0) * 1000)
                    cur.execute(_sql.SQL("SET search_path TO {}, public").format(
                        _sql.Identifier(ESQUEMA_PADRAO)))
                    try:
                        cur.execute("SELECT max(versao) AS v FROM schema_versao")
                        v = (cur.fetchone() or {}).get("v")
                    except psycopg.errors.UndefinedTable:
                        v = None   # banco de pé, schema ainda por aplicar
        finally:
            conn.close()
        return {"configurado": True, "conectado": True, "onde": onde(),
                "erro": None, "ms": ms, "versao_schema": v}
    except Exception as exc:  # noqa: BLE001
        # o TIPO do erro é o que ajuda (conexão recusada × senha × schema
        # ausente); o texto do psycopg pode trazer o conninfo inteiro
        return {"configurado": True, "conectado": False, "onde": onde(),
                "erro": type(exc).__name__, "ms": None, "versao_schema": None}
