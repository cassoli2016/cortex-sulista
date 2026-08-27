"""Web Push — notificações no celular.

Inscrições (subscriptions do navegador) ficam no PostgreSQL local, schema
`cortex` (migrado do SQLite em 27/08/2026 — ver docs/MIGRACAO_POSTGRES.md); o envio usa
`pywebpush` com as chaves VAPID do `.env`. Um digest diário (07:00, thread
interna) manda o resumo dos alertas críticos/atenção via `build_alertas`.

Sem `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` no `.env` -> `habilitado()` é False e
tudo fica desligado (sem erro), igual OpenRouter/TomTom.

PII/segredo: a chave privada NUNCA sai da API; o payload do push traz só título
e resumo curto (sem CPF/placa). As subscriptions são endereços opacos do
navegador (não são dado pessoal do ERP).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime

from . import migracoes, pglocal

log = logging.getLogger("cortex.push")


def _pub() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY", "").strip()


def _priv() -> str:
    return os.environ.get("VAPID_PRIVATE_KEY", "").strip()


def _subject() -> str:
    return os.environ.get("VAPID_SUBJECT", "mailto:ti@sulista.com.br").strip()


def habilitado() -> bool:
    return bool(_pub() and _priv())


# ------------------------------------------------- PostgreSQL local (cortex)
#
# LEITURA NUNCA DERRUBA A TELA. Tabela ainda inexistente é "ninguém se
# inscreveu" — o mesmo que, no SQLite, era arquivo que não existia. Erro de
# CONEXÃO sobe (ver pglocal.sem_tabela): num contador de inscrições, zero por
# banco caído e zero por ninguém inscrito são a mesma tela e coisas opostas.


def init_db(esquema: str | None = None) -> None:
    """Garante o schema aplicado. NÃO é chamado no import: com o banco fora do
    ar, um DDL no import derrubaria a API inteira na subida — e push é acessório
    perto de qualquer outra tela."""
    migracoes.aplicar(esquema)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def salvar_sub(sub: dict, usuario: str | None, esquema: str | None = None) -> None:
    ep = (sub or {}).get("endpoint")
    keys = (sub or {}).get("keys") or {}
    if not ep or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("subscription invalida")
    init_db(esquema)   # primeira inscrição da instalação cria as tabelas
    pglocal.executar(
        "INSERT INTO push_subs(endpoint,p256dh,auth,usuario,criado_em)"
        " VALUES(%s,%s,%s,%s,%s)"
        " ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,"
        " auth=excluded.auth, usuario=excluded.usuario",
        (ep, keys["p256dh"], keys["auth"], usuario, _agora()), esquema=esquema)


def remover_sub(endpoint: str, esquema: str | None = None) -> None:
    try:
        pglocal.executar("DELETE FROM push_subs WHERE endpoint=%s", (endpoint,),
                         esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if not pglocal.sem_tabela(exc):
            raise


def _all_subs(esquema: str | None = None) -> list[dict]:
    try:
        return pglocal.query("SELECT * FROM push_subs", esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return []
        raise


def subs_do_usuario(usuario: str | None, esquema: str | None = None) -> list[dict]:
    try:
        return pglocal.query("SELECT * FROM push_subs WHERE usuario=%s", (usuario,),
                             esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return []
        raise


def contar_subs(usuario: str | None = None, esquema: str | None = None) -> int:
    sql = "SELECT count(*) AS n FROM push_subs"
    params = None
    if usuario:
        sql += " WHERE usuario=%s"
        params = (usuario,)
    try:
        r = pglocal.um(sql, params, esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return 0
        raise
    return int((r or {}).get("n") or 0)


# ---------------------------------------------------------------- envio

def send_push(title: str, body: str, url: str = "/", subs: list[dict] | None = None) -> int:
    """Envia o mesmo push a todas as subs (ou a uma lista dada). Remove as
    expiradas (404/410). Retorna quantas foram entregues ao serviço de push."""
    if not habilitado():
        return 0
    from pywebpush import webpush, WebPushException
    subs = subs if subs is not None else _all_subs()
    payload = json.dumps({"title": title, "body": body, "url": url})
    ok = 0
    for s in subs:
        info = {"endpoint": s["endpoint"],
                "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}
        try:
            webpush(info, payload, vapid_private_key=_priv(),
                    vapid_claims={"sub": _subject()}, ttl=86400)
            ok += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                remover_sub(s["endpoint"])  # inscrição morta (app removido/expirou)
            else:
                log.warning("push falhou (%s)", code)
        except Exception as exc:  # noqa: BLE001
            log.warning("push erro: %s", exc)
    return ok


def enviar_digest_push(subs: list[dict] | None = None) -> int:
    """Resumo dos alertas (crítico/atenção) como um push. Se não há nada
    crítico hoje, não incomoda ninguém."""
    from . import alertas
    itens = [i for i in alertas.build_alertas() if i["nivel"] in ("critico", "atencao")]
    if not itens:
        return 0
    crit = sum(1 for i in itens if i["nivel"] == "critico")
    title = f"Córtex Sulista · {len(itens)} alerta(s)" + (f" · {crit} crítico(s)" if crit else "")
    body = " · ".join(i["titulo"] for i in itens[:4])
    if len(itens) > 4:
        body += f"  +{len(itens) - 4}"
    return send_push(title, body, "/#home", subs)


# ---------------------------------------------------------------- scheduler diário

def _hora() -> int:
    try:
        return max(0, min(23, int(os.environ.get("PUSH_HORA", "7"))))
    except ValueError:
        return 7


_started = False


def _ja_enviou_hoje(esquema: str | None = None) -> bool:
    hoje = datetime.now().strftime("%Y-%m-%d")
    try:
        r = pglocal.um("SELECT valor FROM push_meta WHERE chave='ultimo_digest'",
                       esquema=esquema)
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return False
        raise
    return bool(r) and r["valor"] == hoje


def _marca_hoje(esquema: str | None = None) -> None:
    # instalação onde ninguém se inscreveu ainda não tem as tabelas, e o
    # marcador é escrito MESMO com zero envios (para o digest não repetir no
    # dia). Sem isto, o laço tentaria e falharia de 5 em 5 minutos durante a
    # hora inteira, enchendo o log de aviso que não é problema nenhum.
    init_db(esquema)
    hoje = datetime.now().strftime("%Y-%m-%d")
    pglocal.executar(
        "INSERT INTO push_meta(chave,valor) VALUES('ultimo_digest',%s)"
        " ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (hoje,), esquema=esquema)


def _loop() -> None:
    hora = _hora()
    while True:
        try:
            if datetime.now().hour == hora and not _ja_enviou_hoje():
                n = enviar_digest_push()
                _marca_hoje()  # marca mesmo com 0 (não repete no dia)
                log.info("digest push do dia: %s inscricao(oes)", n)
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler push: %s", exc)
        time.sleep(300)  # checa a cada 5 min (janela hora:00–hora:05)


def iniciar_scheduler() -> None:
    """Sobe a thread do digest diário (idempotente; só se VAPID configurado)."""
    global _started
    if _started or not habilitado():
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="push-digest").start()
    log.info("scheduler de push diario iniciado (%02d:00)", _hora())

# NÃO há `init_db()` no import. Enquanto era SQLite, criar o arquivo no import
# custava nada; com o Postgres, um DDL no import faz a API inteira falhar na
# subida se o banco estiver fora do ar. As tabelas nascem na primeira inscrição
# (`salvar_sub`), e toda leitura antes disso responde vazio.
