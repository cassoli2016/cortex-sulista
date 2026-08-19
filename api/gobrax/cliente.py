"""Cliente das APIs públicas da Gobrax — autenticação por token.

urllib puro de propósito: o venv não tem requests nem httpx, e um import de
requests já derrubou a aplicação inteira uma vez.

Isto NÃO é o mesmo caminho do api/premiacao/gobrax.py antigo, que fala com
gateway-v3-waf e faz login no Kratos com e-mail e senha. As APIs públicas são
outro host, outra porta e outra autenticação.

Comportamentos medidos contra a API em 19/08/2026, não supostos:
  - Authorization: Bearer <token>
  - driversOverview usa MM-YYYY e EXIGE endDate != startDate (400 code 67)
  - período de 12 meses estoura timeout; coletar mês a mês
  - vehicle-statistics da frota inteira leva ~73 s
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://gateway-v3.gobrax.com.br:8889"

_CTX = ssl.create_default_context()


class GobraxNaoConfigurado(Exception):
    """Falta GOBRAX_TOKEN no ambiente."""


class GobraxIndisponivel(Exception):
    """A API não respondeu, respondeu erro, ou respondeu coisa que não é JSON."""


def _token_efetivo() -> str:
    """Cofre da tela de Gestão primeiro, variável de ambiente depois."""
    from api import credenciais
    return credenciais.ler("GOBRAX_TOKEN") or ""


def configurado() -> bool:
    return bool(_token_efetivo())


def mes_api(mes: str) -> tuple[str, str]:
    """'2026-03' -> ('03-2026', '04-2026').

    O fim é o mês SEGUINTE porque a API recusa startDate igual a endDate com
    HTTP 400 'Datas fornecidas inválidas'.
    """
    if not isinstance(mes, str) or len(mes) != 7 or mes[4] != "-":
        raise ValueError(f"mês inválido: {mes!r} — use o formato AAAA-MM")
    ano, m = mes.split("-")
    if not (ano.isdigit() and m.isdigit() and 1 <= int(m) <= 12):
        raise ValueError(f"mês inválido: {mes!r} — use o formato AAAA-MM")
    ano_i, m_i = int(ano), int(m)
    prox = (ano_i + 1, 1) if m_i == 12 else (ano_i, m_i + 1)
    return f"{m_i:02d}-{ano_i}", f"{prox[1]:02d}-{prox[0]}"


def periodo_api(inicio: date, fim: date) -> tuple[str, str]:
    """Formato das APIs de veículo: 'AAAA-MM-DD HH:MM:SS'."""
    return (inicio.strftime("%Y-%m-%d 00:00:00"), fim.strftime("%Y-%m-%d 23:59:59"))


def _http(url: str, headers: dict, timeout: int):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Cliente:
    def __init__(self, token: str | None = None, http=None):
        self.token = (token if token is not None else _token_efetivo()).strip()
        if not self.token:
            raise GobraxNaoConfigurado(
                "GOBRAX_TOKEN não está no ambiente — a integração fica desligada")
        self._http = http or _http

    def get(self, caminho: str, params: dict | None = None,
            timeout: int = 120) -> dict:
        limpos = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{BASE}{caminho}"
        if limpos:
            url += "?" + urllib.parse.urlencode(limpos)
        try:
            status, corpo = self._http(
                url, {"Authorization": f"Bearer {self.token}",
                      "Accept": "application/json"}, timeout)
        except Exception as exc:  # noqa: BLE001 — timeout, DNS, socket
            # a mensagem vai para log e para a tela: nunca inclui o token
            raise GobraxIndisponivel(
                f"falha de rede ao chamar {caminho}: {type(exc).__name__}") from None
        if status != 200:
            trecho = (corpo or b"")[:200].decode("utf-8", "ignore")
            raise GobraxIndisponivel(f"{caminho} respondeu HTTP {status}: {trecho}")
        try:
            return json.loads(corpo)
        except json.JSONDecodeError:
            raise GobraxIndisponivel(
                f"{caminho} respondeu algo que não é JSON") from None
