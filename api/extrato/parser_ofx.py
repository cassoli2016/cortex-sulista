"""Parser de OFX (Open Financial Exchange) — formato padrão dos internet
bankings brasileiros.

Cobre as duas variantes com um único caminho: OFX 1.x é SGML (tags sem
fechamento: `<TRNAMT>10.50` até o fim da linha) e 2.x é XML bem-formado. Uma
regex por tag atende os dois, o que evita depender de parser XML (que quebraria
no SGML) ou de biblioteca externa.

Encoding: OFX de banco BR costuma vir em cp1252/latin-1, não utf-8.
"""
from __future__ import annotations

import re

_TAG = r"<{t}>\s*([^<\r\n]*)"


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _campo(bloco: str, tag: str) -> str:
    m = re.search(_TAG.format(t=tag), bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _data(cru: str) -> str | None:
    """OFX grava YYYYMMDD, opcionalmente com hora e fuso ('20260702120000[-03:EBT]')."""
    m = re.match(r"\s*(\d{4})(\d{2})(\d{2})", cru or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _valor(cru: str) -> float | None:
    """TRNAMT é ponto-decimal (padrão OFX). Alguns bancos mandam vírgula."""
    txt = (cru or "").strip().replace(" ", "")
    if not txt:
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def parse_ofx(bruto: bytes) -> dict:
    texto = _decodificar(bruto)
    if "<OFX" not in texto.upper():
        raise ValueError("Arquivo não parece ser um OFX (tag <OFX> não encontrada).")

    banco_cru = _campo(texto, "BANKID")
    agencia = _campo(texto, "BRANCHID")
    conta = _campo(texto, "ACCTID")
    try:
        banco = int(banco_cru) if banco_cru else None
    except ValueError:
        banco = None

    itens: list[dict] = []
    ignoradas = 0
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, re.IGNORECASE | re.DOTALL):
        dt = _data(_campo(bloco, "DTPOSTED"))
        valor = _valor(_campo(bloco, "TRNAMT"))
        if dt is None or valor is None:
            ignoradas += 1
            continue
        # o sinal do TRNAMT é a fonte da verdade; TRNTYPE só confirma
        tipo = "C" if valor >= 0 else "D"
        itens.append({
            "dt": dt, "valor": valor, "tipo": tipo,
            "historico": _campo(bloco, "MEMO") or _campo(bloco, "NAME"),
            "numerodoc": _campo(bloco, "CHECKNUM"),
            "fitid": _campo(bloco, "FITID") or None,
        })

    saldo = None
    m = re.search(r"<LEDGERBAL>(.*?)</LEDGERBAL>", texto, re.IGNORECASE | re.DOTALL)
    if m:
        s_valor = _valor(_campo(m.group(1), "BALAMT"))
        s_dt = _data(_campo(m.group(1), "DTASOF"))
        if s_valor is not None and s_dt:
            saldo = {"dt": s_dt, "saldo": s_valor}

    if not itens and saldo is None:
        raise ValueError("OFX sem lançamentos nem saldo legíveis.")

    ident = "/".join([banco_cru or "?", agencia or "?", conta or "?"])
    return {"ident": ident, "banco": banco, "agencia": agencia, "conta": conta,
            "itens": itens, "saldo": saldo, "ignoradas": ignoradas}
