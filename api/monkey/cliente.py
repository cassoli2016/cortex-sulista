"""Cliente HTTP da Monkey Exchange (portal de antecipação da Tupy).

Doc: https://developers.monkey.exchange/reference/receivableweblistreceivablecontractjson
Endpoint: GET /v2/sellers/{sellerId}/receivables

POR QUE A AUTENTICAÇÃO É PLUGÁVEL. A documentação pública da Monkey NÃO cobre
autenticação máquina-a-máquina: o único material de auth é OIDC, e é login de
usuário no portal. O endpoint devolve 401/403, então exige credencial — só não
está escrito qual. Em vez de apostar num formato e reescrever quando a resposta
chegar, este cliente aceita os dois que cobrem quase todo o mercado:

  1. TOKEN ESTÁTICO   → `MONKEY_TOKEN` vai direto no `Authorization`.
  2. OAUTH2 CLIENT_CREDENTIALS → `MONKEY_CLIENT_ID` + `MONKEY_CLIENT_SECRET`
     trocados por access_token em `MONKEY_TOKEN_URL`, com cache até expirar.

Qual dos dois vale é decidido pelo que estiver configurado, sem mexer em código.

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


def modo_auth() -> str:
    """Qual credencial está configurada: 'token', 'oauth' ou '' (nenhuma)."""
    if _cred("MONKEY_TOKEN"):
        return "token"
    if _cred("MONKEY_CLIENT_ID") and _cred("MONKEY_CLIENT_SECRET"):
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

    # ------------------------------------------------------------------ auth
    def _token(self) -> str:
        if self.modo == "token":
            return _cred("MONKEY_TOKEN")

        agora = time.monotonic()
        if self._tok and agora < self._tok_expira:
            return self._tok

        url = _cred("MONKEY_TOKEN_URL") or f"{base_url()}/oauth/token"
        corpo = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": _cred("MONKEY_CLIENT_ID"),
            "client_secret": _cred("MONKEY_CLIENT_SECRET"),
        }).encode()
        try:
            status, resp = self._http(
                url, {"Content-Type": "application/x-www-form-urlencoded",
                      "Accept": "application/json"}, 60, corpo)
        except Exception as exc:  # noqa: BLE001
            raise MonkeyIndisponivel(
                f"falha de rede ao pedir token: {type(exc).__name__}") from None
        if status != 200:
            # NUNCA ecoa o corpo aqui: numa troca de credencial o retorno pode
            # devolver o que foi enviado, e isso iria para o log.
            raise MonkeyIndisponivel(
                f"pedido de token respondeu HTTP {status}")
        try:
            d = json.loads(resp)
        except json.JSONDecodeError:
            raise MonkeyIndisponivel("pedido de token não devolveu JSON") from None
        tok = d.get("access_token") or ""
        if not tok:
            raise MonkeyIndisponivel("resposta de token sem 'access_token'")
        self._tok = tok
        self._tok_expira = agora + max(30, int(d.get("expires_in") or 3600)) - FOLGA_TOKEN_S
        return tok

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
                   busca: dict | None = None) -> list[dict]:
        """Todos os recebíveis do seller, seguindo a paginação.

        `busca` é o parâmetro `search` da API — um `operationSpecificationInvoice`
        cuja estrutura a documentação pública NÃO detalha. Fica aberto de
        propósito: quando a Monkey mandar um exemplo, ele entra aqui sem tocar
        no resto.

        `maximo_paginas` é um freio contra laço infinito se a API devolver
        `totalPages` inconsistente — o que já vimos acontecer em API paginada.
        """
        fora: list[dict] = []
        pagina = 0
        while pagina < maximo_paginas:
            params = {"page": pagina, "size": tamanho}
            if busca:
                params.update(busca)
            d = self.get(f"/v2/sellers/{self.seller}/receivables", params)
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
