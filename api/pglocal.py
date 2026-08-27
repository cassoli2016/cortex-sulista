"""Banco de ESCRITA do CÓRTEX — PostgreSQL local.

SEPARADO de `api/db.py` de propósito, e a separação não é estética:

- `api/db.py` é a réplica do ERP (AVA), de terceiro, **somente leitura**, num
  host remoto. Toda sessão dele nasce com `default_transaction_read_only=on`.
- este módulo é o banco da casa, onde o CÓRTEX ESCREVE — o que hoje mora nos
  dez SQLite de `data/`.

Um módulo só, com uma variável de ambiente trocada, mandaria query do ERP para
o banco local. O sintoma seria "os números sumiram", não "erro de conexão" — o
tipo de defeito que se procura no lugar errado por meio dia.

CONEXÃO CURTA, SEM POOL. É a mesma forma que o SQLite já usava (`_conn()` abre,
faz, fecha), e evita de uma vez a classe de problema de pool com `search_path`
grudado de outra chamada. O pool entra quando o `auth` migrar — é ele que faz
muitas consultas pequenas por request — e aí com medição, não por suposição.

O ESQUEMA É PARÂMETRO porque é assim que o teste fica isolado: onde o SQLite
recebia um arquivo em `tmp_path`, aqui se recebe um schema próprio. Ver
`docs/MIGRACAO_POSTGRES.md`.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
from psycopg import sql as _sql
from psycopg.rows import dict_row

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
    conn = psycopg.connect(dsn(), row_factory=dict_row)
    try:
        with conn:
            with conn.cursor() as cur:
                # identificador vem de código nosso e de teste, nunca de HTTP;
                # ainda assim vai por Identifier, que é o certo e custa nada
                cur.execute(_sql.SQL("SET search_path TO {}, public").format(
                    _sql.Identifier(esquema or ESQUEMA_PADRAO)))
            yield conn
    finally:
        conn.close()


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
        with get_conn() as conn:
            with conn.cursor() as cur:
                # CONECTAR e LER A VERSÃO são duas perguntas diferentes, e
                # juntá-las custou a primeira execução do runner: banco
                # recém-criado não tem `schema_versao`, o UndefinedTable subia
                # como falha de conexão e o script se recusava a aplicar
                # justamente a migration que criaria a tabela.
                cur.execute("SELECT 1")
                ms = round((time.perf_counter() - t0) * 1000)
                try:
                    cur.execute("SELECT max(versao) AS v FROM schema_versao")
                    v = (cur.fetchone() or {}).get("v")
                except psycopg.errors.UndefinedTable:
                    v = None   # banco de pé, schema ainda por aplicar
        return {"configurado": True, "conectado": True, "onde": onde(),
                "erro": None, "ms": ms, "versao_schema": v}
    except Exception as exc:  # noqa: BLE001
        # o TIPO do erro é o que ajuda (conexão recusada × senha × schema
        # ausente); o texto do psycopg pode trazer o conninfo inteiro
        return {"configurado": True, "conectado": False, "onde": onde(),
                "erro": type(exc).__name__, "ms": None, "versao_schema": None}
