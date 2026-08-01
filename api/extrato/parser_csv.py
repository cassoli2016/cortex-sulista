"""Parser de extrato em CSV, com mapa de colunas por conta.

Cada banco exporta um layout diferente, então não há detecção automática de
colunas: no primeiro upload de uma conta o usuário aponta na tela qual coluna é
data/valor/histórico e o mapa fica salvo (`ext_conta.mapa_csv`).

Valor em formato BR exige parse ESTRITO: `parseFloat`/`float()` aceitam prefixo
válido e ignoram o resto ('1.234.56' viraria 1.234), e `type=number` no front
descarta a vírgula. Aqui a regex valida ANTES de converter.
"""
from __future__ import annotations

import csv
import io
import re

_RE_MILHAR_VIRGULA = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d{1,2})?$")   # 1.234.567,89
_RE_SO_VIRGULA = re.compile(r"^-?\d+(,\d{1,2})?$")                     # 1234,89
_RE_PONTO_DEC = re.compile(r"^-?\d+(\.\d{1,2})?$")                     # 1234.89
_RE_MILHAR_PONTO = re.compile(r"^-?\d{1,3}(\.\d{3})+$")                # 1.234 (milhar)


def valor_br(txt: str) -> float | None:
    """Converte valor pt-BR (ou en-US simples) para float. None se inválido."""
    s = (txt or "").strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "").replace("\xa0", "")
    negativo = s.startswith("(") and s.endswith(")")   # (1.234,56) = negativo
    if negativo:
        s = s[1:-1]
    if not s:
        return None
    if _RE_MILHAR_PONTO.match(s):          # 1.234 -> milhar, não decimal
        val = float(s.replace(".", ""))
    elif _RE_MILHAR_VIRGULA.match(s):
        val = float(s.replace(".", "").replace(",", "."))
    elif _RE_SO_VIRGULA.match(s):
        val = float(s.replace(",", "."))
    elif _RE_PONTO_DEC.match(s):
        val = float(s)
    else:
        return None
    return -val if negativo else val


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _delimitador(texto: str) -> str:
    cabeca = "\n".join(texto.splitlines()[:5])
    return max((";", ",", "\t"), key=cabeca.count)


def _data_br(txt: str) -> str | None:
    """DD/MM/AAAA (ou com '-'), e AAAA-MM-DD para exports ISO."""
    s = (txt or "").strip()
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def _linhas(bruto: bytes) -> tuple[list[list[str]], str]:
    texto = _decodificar(bruto)
    delim = _delimitador(texto)
    return [r for r in csv.reader(io.StringIO(texto), delimiter=delim) if r], delim


def preview_csv(bruto: bytes, linhas: int = 8) -> dict:
    todas, delim = _linhas(bruto)
    return {"delim": delim, "amostra": todas[:linhas]}


def _col(linha: list[str], idx) -> str:
    if idx is None or idx < 0 or idx >= len(linha):
        return ""
    return (linha[idx] or "").strip()


def parse_csv(bruto: bytes, mapa: dict) -> dict:
    tem_valor = mapa.get("valor") is not None
    tem_cd = mapa.get("credito") is not None or mapa.get("debito") is not None
    if mapa.get("dt") is None or not (tem_valor or tem_cd):
        raise ValueError("Mapa de colunas incompleto: informe a coluna de data e "
                         "a de valor (ou as de crédito e débito).")

    todas, _ = _linhas(bruto)
    pular = int(mapa.get("cabecalho", 1) or 0)
    itens: list[dict] = []
    ignoradas = 0
    for linha in todas[pular:]:
        dt = _data_br(_col(linha, mapa.get("dt")))
        if dt is None:
            ignoradas += 1          # cabeçalho repetido, rodapé, linha de saldo
            continue
        if tem_valor:
            valor = valor_br(_col(linha, mapa.get("valor")))
        else:
            cred = valor_br(_col(linha, mapa.get("credito")))
            deb = valor_br(_col(linha, mapa.get("debito")))
            valor = cred if cred else (-abs(deb) if deb else None)
        if valor is None:
            ignoradas += 1
            continue
        itens.append({
            "dt": dt, "valor": valor, "tipo": "C" if valor >= 0 else "D",
            "historico": _col(linha, mapa.get("historico")),
            "numerodoc": _col(linha, mapa.get("numerodoc")),
            "fitid": None,
        })
    if not itens:
        raise ValueError("Nenhuma linha do CSV foi reconhecida com o mapa de colunas atual.")
    return {"itens": itens, "saldo": None, "ignoradas": ignoradas}
