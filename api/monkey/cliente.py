"""Cliente HTTP da Monkey Exchange (portal de antecipação da Tupy).

Doc: https://developers.monkey.exchange/reference/receivableweblistreceivablecontractjson
Endpoint: GET /v2/sellers/{sellerId}/receivables

O QUE O FORNECEDOR RESPONDEU (01/09/2026) — e que este cliente segue:

  1. AUTENTICAÇÃO: o PRIMEIRO token sai com `grant_type=password`
     (client_id + client_secret + username + password do usuário da
     plataforma); a RENOVAÇÃO usa `grant_type=refresh_token` (client_id +
     client_secret + refresh_token da geração anterior). Se a renovação
     falhar (refresh vencido/rotacionado), volta ao password — nunca fica
     preso num refresh morto. `MONKEY_TOKEN` estático continua aceito.
  2. HOSTS: hmg-zuul.monkeyecx.com (homologação) e zuul.monkey.exchange
     (produção). `sandbox.monkeyecx.com` é o PORTAL WEB, não a API.
  3. `search`, `page` e `size` SE INVALIDAM em conjunto: a API devolve 200
     com lista vazia, sem erro. Busca é uma chamada SEM paginação; listagem
     completa pagina SEM search — os dois caminhos nunca se misturam.

AMBIENTE: `MONKEY_AMBIENTE` = 'hmg' (padrão) ou 'prod'. O padrão é homologação
DE PROPÓSITO — apontar para produção tem de ser um ato deliberado, e a primeira
coleta de uma integração nova é justamente quando o parser ainda pode estar
errado.
"""
from __future__ import annotations

import json
import ssl

from api import tls as _tls
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import credenciais

BASES = {
    "hmg": "https://hmg-zuul.monkeyecx.com",
    "prod": "https://zuul.monkey.exchange",
}
AMBIENTE_PADRAO = "hmg"

# folga na expiração do token: renovar em cima da hora produz o 401 que
# acontece uma vez por dia e ninguém consegue reproduzir
FOLGA_TOKEN_S = 60

# Contexto TLS DA CASA (api/tls.py) e nao o padrao do sistema: neste
# servidor Windows o padrao tem 45 raizes -- o que o armazem cacheou --
# e um fornecedor com CA fora dessa lista falha com "self-signed
# certificate in certificate chain", que manda procurar proxy onde nao
# ha nenhum. Medido: api.tomtom.com, certificado legitimo, recusado.
_CTX = _tls.contexto()


class MonkeyNaoConfigurado(Exception):
    """Faltam credenciais da Monkey — a integração fica desligada."""


class MonkeyIndisponivel(Exception):
    """A API não respondeu, ou respondeu o que não devia."""


def _cred(nome: str) -> str:
    return (credenciais.ler(nome) or "").strip()


def ambiente() -> str:
    amb = (_cred("MONKEY_AMBIENTE") or AMBIENTE_PADRAO).lower()
    return amb if amb in BASES else AMBIENTE_PADRAO


def base_url() -> str:
    return BASES[ambiente()]


def seller_id() -> str:
    return _cred("MONKEY_SELLER_ID")


def seller_ids() -> list[str]:
    """A Sulista tem UM sellerId por CNPJ (5 hoje) — o campo aceita todos,
    separados por vírgula. A coleta soma os sellers numa posição só."""
    return [s.strip() for s in seller_id().split(",") if s.strip()]


def modo_auth() -> str:
    """Qual credencial está configurada: 'token', 'oauth' ou '' (nenhuma).

    O modo oauth exige os QUATRO campos — o primeiro token é
    `grant_type=password` e sem username/password a Monkey recusa."""
    if _cred("MONKEY_TOKEN"):
        return "token"
    if (_cred("MONKEY_CLIENT_ID") and _cred("MONKEY_CLIENT_SECRET")
            and _cred("MONKEY_USERNAME") and _cred("MONKEY_PASSWORD")):
        return "oauth"
    return ""


def configurado() -> bool:
    """Precisa de credencial E do sellerId — um sem o outro não faz chamada."""
    return bool(modo_auth() and seller_id())


def _http(url: str, headers: dict, timeout: int, dados: bytes | None = None):
    req = urllib.request.Request(url, headers=headers, data=dados,
                                 method="POST" if dados is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Cliente:
    """`http` é injetável para os testes rodarem sem rede."""

    def __init__(self, http=None, seller: str | None = None):
        self._http = http or _http
        self.seller = (seller if seller is not None else seller_id()).strip()
        self.modo = modo_auth()
        if not self.modo:
            raise MonkeyNaoConfigurado(
                "sem credencial da Monkey: configure MONKEY_TOKEN, ou "
                "MONKEY_CLIENT_ID + MONKEY_CLIENT_SECRET")
        if not self.seller:
            raise MonkeyNaoConfigurado(
                "MONKEY_SELLER_ID não configurado — é o {id} do caminho "
                "/v2/sellers/{id}/receivables e não há como descobri-lo daqui")
        self._tok: str = ""
        self._tok_expira: float = 0.0
        self._refresh: str = ""

    # ------------------------------------------------------------------ auth
    def _pedir_token(self, corpo: dict) -> dict | None:
        """Uma ida ao endpoint de token. Devolve o JSON, ou None se a Monkey
        recusou (quem decide o que fazer com a recusa é o chamador)."""
        url = _cred("MONKEY_TOKEN_URL") or f"{base_url()}/oauth/token"
        dados = urllib.parse.urlencode(corpo).encode()
        try:
            status, resp = self._http(
                url, {"Content-Type": "application/x-www-form-urlencoded",
                      "Accept": "application/json"}, 60, dados)
        except Exception as exc:  # noqa: BLE001
            raise MonkeyIndisponivel(
                f"falha de rede ao pedir token: {type(exc).__name__}") from None
        if status != 200:
            # NUNCA ecoa o corpo aqui: numa troca de credencial o retorno pode
            # devolver o que foi enviado, e isso iria para o log.
            return None
        try:
            return json.loads(resp)
        except json.JSONDecodeError:
            return None

    def _token(self) -> str:
        """password no primeiro token, refresh_token na renovação — resposta
        oficial da Monkey (01/09/2026). O refresh que falhar (vencido,
        rotacionado) cai de volta no password em vez de travar a coleta."""
        if self.modo == "token":
            return _cred("MONKEY_TOKEN")

        agora = time.monotonic()
        if self._tok and agora < self._tok_expira:
            return self._tok

        base = {"client_id": _cred("MONKEY_CLIENT_ID"),
                "client_secret": _cred("MONKEY_CLIENT_SECRET")}
        d = None
        if self._refresh:
            d = self._pedir_token({**base, "grant_type": "refresh_token",
                                   "refresh_token": self._refresh})
        if not d or not d.get("access_token"):
            d = self._pedir_token({**base, "grant_type": "password",
                                   "username": _cred("MONKEY_USERNAME"),
                                   "password": _cred("MONKEY_PASSWORD")})
        if not d or not d.get("access_token"):
            raise MonkeyIndisponivel(
                "a Monkey recusou o pedido de token (password) — conferir "
                "client_id/client_secret e o usuário/senha da plataforma")
        self._tok = d["access_token"]
        self._refresh = d.get("refresh_token") or self._refresh
        self._tok_expira = (agora + max(30, int(d.get("expires_in") or 3600))
                            - FOLGA_TOKEN_S)
        return self._tok

    # ------------------------------------------------------------------ http
    def get(self, caminho: str, params: dict | None = None,
            timeout: int = 120) -> dict:
        limpos = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{base_url()}{caminho}"
        if limpos:
            url += "?" + urllib.parse.urlencode(limpos, doseq=True)
        cab = {"Authorization": f"Bearer {self._token()}",
               "Accept": "application/json"}
        try:
            status, corpo = self._http(url, cab, timeout)
        except Exception as exc:  # noqa: BLE001
            raise MonkeyIndisponivel(
                f"falha de rede ao chamar {caminho}: {type(exc).__name__}") from None
        if status in (401, 403):
            raise MonkeyIndisponivel(
                f"{caminho} respondeu HTTP {status} — credencial recusada ou "
                "sem permissão para este sellerId")
        if status != 200:
            trecho = (corpo or b"")[:200].decode("utf-8", "ignore")
            raise MonkeyIndisponivel(f"{caminho} respondeu HTTP {status}: {trecho}")
        try:
            return json.loads(corpo)
        except json.JSONDecodeError:
            raise MonkeyIndisponivel(
                f"{caminho} respondeu algo que não é JSON") from None

    # ------------------------------------------------------------- recebíveis
    def recebiveis(self, *, tamanho: int = 200, maximo_paginas: int = 200,
                   busca: str | None = None) -> list[dict]:
        """Todos os recebíveis do seller, seguindo a paginação.

        `busca` é o `search` da API no formato `campo:valor` (por exemplo
        `externalId:3082912`), e é EXCLUSIVO: a Monkey confirmou que search
        com page/size na mesma requisição devolve 200 com lista VAZIA — os
        parâmetros se invalidam sem erro nenhum. Por isso a busca é UMA
        chamada sem paginação, e a listagem completa pagina sem search.

        `maximo_paginas` é um freio contra laço infinito se a API devolver
        `totalPages` inconsistente — o que já vimos acontecer em API paginada.
        """
        caminho = f"/v2/sellers/{self.seller}/receivables"
        if busca:
            d = self.get(caminho, {"search": busca})
            return ((d.get("_embedded") or {}).get("receivables") or [])
        fora: list[dict] = []
        pagina = 0
        while pagina < maximo_paginas:
            d = self.get(caminho, {"page": pagina, "size": tamanho})
            lote = ((d.get("_embedded") or {}).get("receivables") or [])
            fora.extend(lote)
            meta = d.get("page") or {}
            total = int(meta.get("totalPages") or 0)
            pagina += 1
            # para se acabou a paginação OU se a página veio vazia: API que
            # mente no totalPages ainda assim para de devolver linha
            if not lote or pagina >= total:
                break
        return fora
