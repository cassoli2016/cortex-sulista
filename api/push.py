"""Web Push — notificações no celular.

Inscrições (subscriptions do navegador) ficam em `data/push.db`; o envio usa
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
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

log = logging.getLogger("cortex.push")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "push.db"


def _pub() -> str:
    return os.environ.get("VAPID_PUBLIC_KEY", "").strip()


def _priv() -> str:
    return os.environ.get("VAPID_PRIVATE_KEY", "").strip()


def _subject() -> str:
    return os.environ.get("VAPID_SUBJECT", "mailto:ti@sulista.com.br").strip()


def habilitado() -> bool:
    return bool(_pub() and _priv())


# ---------------------------------------------------------------- SQLite

@contextmanager
def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS subs("
            "endpoint TEXT PRIMARY KEY, p256dh TEXT NOT NULL, auth TEXT NOT NULL,"
            "usuario TEXT, criado_em TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT)")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def salvar_sub(sub: dict, usuario: str | None) -> None:
    ep = (sub or {}).get("endpoint")
    keys = (sub or {}).get("keys") or {}
    if not ep or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("subscription invalida")
    with _conn() as c:
        c.execute(
            "INSERT INTO subs(endpoint,p256dh,auth,usuario,criado_em) VALUES(?,?,?,?,?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, "
            "auth=excluded.auth, usuario=excluded.usuario",
            (ep, keys["p256dh"], keys["auth"], usuario, _agora()))


def remover_sub(endpoint: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM subs WHERE endpoint=?", (endpoint,))


def _all_subs() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM subs").fetchall()]


def subs_do_usuario(usuario: str | None) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in
                c.execute("SELECT * FROM subs WHERE usuario=?", (usuario,)).fetchall()]


def contar_subs(usuario: str | None = None) -> int:
    with _conn() as c:
        if usuario:
            r = c.execute("SELECT count(*) AS n FROM subs WHERE usuario=?", (usuario,)).fetchone()
        else:
            r = c.execute("SELECT count(*) AS n FROM subs").fetchone()
    return r["n"]


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


def _ja_enviou_hoje() -> bool:
    hoje = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        r = c.execute("SELECT valor FROM meta WHERE chave='ultimo_digest'").fetchone()
    return bool(r) and r["valor"] == hoje


def _marca_hoje() -> None:
    hoje = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        c.execute("INSERT INTO meta(chave,valor) VALUES('ultimo_digest',?) "
                  "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (hoje,))


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
    init_db()
    _started = True
    threading.Thread(target=_loop, daemon=True, name="push-digest").start()
    log.info("scheduler de push diario iniciado (%02d:00)", _hora())


init_db()  # garante as tabelas no import (inscrição funciona mesmo antes do 1º envio)
