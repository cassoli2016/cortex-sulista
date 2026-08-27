"""Base local da situação do RNTRC — PostgreSQL (schema `cortex`).

PRIMEIRO STORE MIGRADO do SQLite. O plano, as decisões e a ordem das próximas
fases estão em `docs/MIGRACAO_POSTGRES.md`. O `data/antt.db` continua no disco
até a fase seguinte fechar: é o desfazer mais barato que existe.

Guarda SÓ os transportadores que a Sulista contrata (222 hoje), não a base
nacional: o casamento é por número de registro, então não há razão para trazer
1,16 milhão de linhas para dentro. Nenhum documento de pessoa é gravado aqui.

O que mudou no contrato: o parâmetro `path` (arquivo `.db`) virou `esquema`
(schema do Postgres). É o que mantém o teste isolado — onde antes cada teste
ganhava um arquivo em `tmp_path`, agora ganha um schema próprio.

O QUE NÃO MUDOU, e é de propósito: `situacao()` e `todas()` NÃO engolem falha
de conexão. Devolver dicionário vazio faria a tela dizer "sem base" — que ali
significa "nunca sincronizou" — quando o problema é o banco fora do ar. Num
módulo de compliance, esse silêncio é o pior desfecho possível.
"""
from __future__ import annotations

import re
from datetime import datetime

import psycopg

from .. import migracoes, pglocal

_SO_DIGITOS = re.compile(r"\D")


class BaseVazia(Exception):
    """Sync que não trouxe nenhuma linha. Nunca sobrescreve o que está gravado."""


def normalizar_rntrc(valor: str | None) -> str:
    """Chave de casamento: só dígitos, sem zeros à esquerda.

    O AVA guarda 8 dígitos ('07600540') e a ANTT publica 9 ('007600540'). Os
    dois lados passam por aqui — normalizar só um deles cria falso 'não
    encontrado', que num módulo de compliance acusa quem está em ordem.
    """
    if not valor:
        return ""
    return _SO_DIGITOS.sub("", str(valor)).lstrip("0")


def init_db(esquema: str | None = None) -> None:
    """Garante o schema aplicado. O DDL mora em `sql/cortex/`, não aqui: com o
    schema declarado em código E em migration, um dia os dois discordam."""
    migracoes.aplicar(esquema)


def gravar_lote(linhas: list[dict], competencia: str,
                esquema: str | None = None) -> int:
    """Substitui a base inteira, numa transação só.

    O DELETE + INSERT vive dentro de UMA transação — se o insert falhar no
    meio, não fica base pela metade. No SQLite isso dependia do
    `isolation_level`; aqui é o comportamento natural do `with conn`.
    """
    if not linhas:
        raise BaseVazia(f"sync de {competencia} não trouxe nenhuma linha")
    init_db(esquema)
    with pglocal.get_conn(esquema) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rntrc_transportador")
            cur.executemany(
                """INSERT INTO rntrc_transportador
                   (rntrc, nome, situacao, categoria, uf, municipio, data_situacao)
                   VALUES(%(rntrc)s, %(nome)s, %(situacao)s, %(categoria)s,
                          %(uf)s, %(municipio)s, %(data_situacao)s)
                   ON CONFLICT (rntrc) DO UPDATE SET
                     nome=EXCLUDED.nome, situacao=EXCLUDED.situacao,
                     categoria=EXCLUDED.categoria, uf=EXCLUDED.uf,
                     municipio=EXCLUDED.municipio,
                     data_situacao=EXCLUDED.data_situacao""",
                [{**l, "rntrc": normalizar_rntrc(l["rntrc"])} for l in linhas])
            cur.execute(
                "INSERT INTO rntrc_sync(competencia, quando, linhas)"
                " VALUES(%s,%s,%s)",
                (competencia, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 len(linhas)))
    return len(linhas)


def _sem_base(exc: Exception) -> bool:
    """Tabela que ainda não existe é BASE NUNCA SINCRONIZADA, não falha.

    É o mesmo caso que, no SQLite, era `if not Path(p).exists()`. A distinção
    importa: `UndefinedTable` vira base vazia (a tela mostra "sem base", que é
    verdade), enquanto erro de conexão SOBE — porque aí a tela não pode
    afirmar nada sobre a regularidade de ninguém.
    """
    return isinstance(exc, psycopg.errors.UndefinedTable)


def situacao(rntrc: str, esquema: str | None = None) -> dict | None:
    try:
        return pglocal.um("SELECT * FROM rntrc_transportador WHERE rntrc=%s",
                          (normalizar_rntrc(rntrc),), esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if _sem_base(exc):
            return None
        raise


def todas(esquema: str | None = None) -> dict[str, dict]:
    try:
        linhas = pglocal.query("SELECT * FROM rntrc_transportador",
                               esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if _sem_base(exc):
            return {}
        raise
    return {r["rntrc"]: dict(r) for r in linhas}


def ultima_sync(esquema: str | None = None) -> dict | None:
    try:
        return pglocal.um("SELECT competencia, quando, linhas FROM rntrc_sync"
                          " ORDER BY id DESC LIMIT 1", esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if _sem_base(exc):
            return None
        raise
