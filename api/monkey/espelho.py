# -*- coding: utf-8 -*-
"""Espelho local dos recebíveis da Monkey (mky_recebiveis).

A posição de antecipação guarda só o que está EM ABERTO; o espelho guarda
TUDO — é dele que a tela de validação do portal responde "quanto foi
antecipado por mês, a que taxa, com que deságio" sem re-paginar 500
chamadas. Convertido no LIMITE do módulo (date/float aqui, nunca Decimal
ou string de data adiante), upsert idempotente pela chave natural medida:
(seller_id, external_id).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from .. import pglocal

log = logging.getLogger(__name__)

# O teste redireciona isto para um schema próprio (fixture `esquema_pg`).
ESQUEMA: str | None = None


def _esq(esquema: str | None = None) -> str | None:
    return esquema or ESQUEMA


def _txt(v) -> str | None:
    s = "" if v is None else str(v).strip()
    return s or None


def _digitos(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d or None


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _data(v):
    """'2026-10-15T23:30:00.000-03:00' → date, cortando no 'T' — converter
    para UTC voltaria um dia perto da meia-noite (a regra do _iso())."""
    s = str(v or "").strip()
    return s[:10] if len(s) >= 10 else None


def _dh(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).strip())
    except ValueError:
        return None


def _id_monkey(r: dict) -> str | None:
    href = str((((r.get("_links") or {}).get("self")) or {}).get("href") or "")
    return href.rstrip("/").rsplit("/", 1)[-1] or None if href else None


def linha(r: dict, seller_id: str) -> dict | None:
    """Um ReceivableDTO → linha do espelho. Sem externalId não há chave —
    devolve None e o gravador conta (campo ausente é ACHADO, não silêncio)."""
    ext = _txt(r.get("externalId"))
    if not ext or not seller_id:
        return None
    return {
        "seller_id": seller_id,
        "external_id": ext,
        "id_monkey": _id_monkey(r),
        "seller_cnpj": _digitos(r.get("_seller_cnpj")),
        "seller_nome": _txt(r.get("_seller_nome")),
        "invoice_number": _txt(r.get("invoiceNumber")),
        "invoice_key": _txt(r.get("invoiceKey")),
        "installment": _int(r.get("installment")),
        "total_installment": _int(r.get("totalInstallment")),
        "asset_type": _txt(r.get("assetType")),
        "status": (_txt(r.get("status")) or "(sem status)").upper(),
        "invoice_date": _data(r.get("invoiceDate")),
        "payment_date": _data(r.get("paymentDate")),
        "real_payment_date": _data(r.get("realPaymentDate")),
        "effective_payment_date": _data(r.get("effectivePaymentDate")),
        "payment_value": _num(r.get("paymentValue")),
        "receipt_value": _num(r.get("receiptValue")),
        "purchased_tax": _num(r.get("purchasedTax")),
        "fee_rate": _num(r.get("feeRate")),
        "fee_amount": _num(r.get("feeAmount")),
        "sponsor_cnpj": _digitos(r.get("sponsorGovernmentId")),
        "sponsor_nome": _txt(r.get("sponsorName")),
        "buyer_cnpj": _digitos(r.get("buyerGovernmentId")),
        "buyer_nome": _txt(r.get("buyerName")),
        "criado_fornecedor": _dh(r.get("createdAt")),
        "alterado_fornecedor": _dh(r.get("updatedAt")),
    }


_COLS = tuple(linha({"externalId": "x"}, "s").keys())

_UPSERT = (
    "INSERT INTO mky_recebiveis (" + ", ".join(_COLS) + ") VALUES ("
    + ", ".join(f"%({c})s" for c in _COLS) + ") "
    "ON CONFLICT (seller_id, external_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS
                if c not in ("seller_id", "external_id"))
    + ", atualizado_em = now()"
)


def upsert(brutos_por_seller: list[tuple[str, dict]],
           esquema: str | None = None) -> tuple[int, int]:
    """Grava (gravados, sem_chave). Recoletar é o caso normal."""
    linhas, sem_chave = [], 0
    for seller_id, r in brutos_por_seller:
        ln = linha(r, seller_id)
        if ln is None:
            sem_chave += 1
        else:
            linhas.append(ln)
    if linhas:
        with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
            cur.executemany(_UPSERT, linhas)
            conn.commit()
    return len(linhas), sem_chave


def registrar_carga(iniciado_em: datetime, recebidos: int, gravados: int,
                    sem_chave: int, erro: str | None = None,
                    esquema: str | None = None) -> None:
    with pglocal.get_conn(_esq(esquema)) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO mky_carga (iniciado_em, terminado_em, recebidos,
                                      gravados, sem_chave, erro)
               VALUES (%s, now(), %s, %s, %s, %s)""",
            (iniciado_em, recebidos, gravados, sem_chave, erro))
        conn.commit()
