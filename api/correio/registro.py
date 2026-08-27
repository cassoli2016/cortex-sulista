"""Trilha dos e-mails enviados — PostgreSQL local, schema `cortex`.

Terceiro store migrado do SQLite (27/08/2026 — ver `docs/MIGRACAO_POSTGRES.md`).
O `data/email.db` continua no disco até a fase seguinte fechar.

Existe separado do `audit_log` do auth de propósito: o audit responde
"quem mexeu no sistema", e aqui é "o que saiu para fora da empresa", com o
corpo da mensagem. São perguntas diferentes, retenções diferentes, e o
volume de um não pode empurrar o outro para fora da tela.

Toda tentativa é gravada — inclusive a que FALHOU. Registro só de sucesso
esconde justamente o caso que se precisa investigar ("o cliente diz que não
recebeu").

A tabela é `correio_envios`, com o prefixo do módulo: `antecipacoes.db`
também tem uma `envios`, e no schema único as duas disputariam o nome.
"""
from __future__ import annotations

from datetime import datetime

from .. import migracoes, pglocal

# corpo é guardado truncado: a trilha serve para conferir O QUE foi dito, não
# para virar arquivo de anexos — relatório grande encheria a tabela à toa.
MAX_CORPO = 4000

# Manopla de redirecionamento, no lugar do antigo `DB_PATH`: o teste faz
# `monkeypatch.setattr(registro, "ESQUEMA", <schema do teste>)` e a trilha
# inteira passa a escrever lá, sem que cada chamada precise carregar o
# parâmetro. O argumento `esquema=` continua valendo e vence — é o caminho
# explícito, para quem precisa de dois schemas na mesma linha de código.
ESQUEMA: str | None = None


def _esq(esquema: str | None) -> str | None:
    return esquema or ESQUEMA


def init_db(esquema: str | None = None) -> None:
    migracoes.aplicar(_esq(esquema))


def gravar(destinatarios: list[str], assunto: str, corpo: str, *,
           usuario: str = "", origem: str = "", ok: bool = False,
           erro: str = "", esquema: str | None = None) -> int:
    """Grava a tentativa e devolve o id.

    `RETURNING id` no lugar do `lastrowid` do SQLite — é a tradução direta, e
    dentro da mesma ida ao banco.
    """
    init_db(esquema)
    r = pglocal.um(
        "INSERT INTO correio_envios"
        " (ts, usuario, destinatarios, assunto, corpo, origem, ok, erro)"
        " VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), usuario or "",
         ", ".join(destinatarios), assunto or "", (corpo or "")[:MAX_CORPO],
         origem or "", 1 if ok else 0, erro or ""), esquema=_esq(esquema))
    return int(r["id"])


def listar(limite: int = 100, esquema: str | None = None) -> list[dict]:
    init_db(esquema)
    return pglocal.query(
        "SELECT id, ts, usuario, destinatarios, assunto, origem, ok, erro"
        " FROM correio_envios ORDER BY id DESC LIMIT %s",
        (int(limite),), esquema=_esq(esquema))


def resumo(esquema: str | None = None) -> dict:
    """Total, sucessos, falhas e o último envio.

    `count(*) FILTER (WHERE ...)` no lugar do `sum(CASE WHEN ...)`: é o mesmo
    número, escrito do jeito que o Postgres tem para isso. E vem tudo `or 0`
    porque tabela vazia devolve NULL nos agregados nos dois bancos.
    """
    init_db(esquema)
    r = pglocal.um(
        "SELECT count(*) AS total,"
        " count(*) FILTER (WHERE ok=1) AS ok,"
        " count(*) FILTER (WHERE ok=0) AS falha,"
        " max(ts) AS ultimo FROM correio_envios", esquema=_esq(esquema))
    return {"total": r["total"] or 0, "ok": r["ok"] or 0,
            "falha": r["falha"] or 0, "ultimo": r["ultimo"]}
