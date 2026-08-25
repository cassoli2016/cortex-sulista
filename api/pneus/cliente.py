"""Cliente HTTP da Prolog — gestão de pneus.

Spec: https://prologapp.com/prolog/openapi.json (OpenAPI 3.0.1, 107 rotas).
Base declarada no spec: `/prolog`, servida em https://prologapp.com.

AUTENTICACAO PLUGAVEL, pelo mesmo motivo da Monkey: o spec da Prolog tem
`securitySchemes: null` e nao existe rota de login/token nele. As chamadas
claramente exigem credencial (a API e de dado de cliente), so nao esta escrito
qual formato. Em vez de apostar e reescrever depois, aceita:

  1. TOKEN ESTATICO  -> `PROLOG_TOKEN` no Authorization.
  2. BASIC           -> `PROLOG_USUARIO` + `PROLOG_SENHA`.
  3. OAUTH2          -> `PROLOG_CLIENT_ID` + `PROLOG_CLIENT_SECRET` trocados em
                        `PROLOG_TOKEN_URL`.

FILIAL E OBRIGATORIA. `GET /api/v3/tires` exige `branchOfficesId`, e nao ha
como adivinhar o id da Sulista — vem de `/api/v3/branch-offices`, que este
cliente sabe listar assim que houver credencial.
"""
from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import credenciais

BASE_PADRAO = "https://prologapp.com/prolog"
FOLGA_TOKEN_S = 60
_CTX = ssl.create_default_context()

# Situacoes que a API reconhece. INSTALLED e o unico que significa "rodando" —
# distincao que decide quase todo denominador desta tela.
STATUS = ("INVENTORY", "ANALYSIS", "INSTALLED", "DISPOSAL")


class PrologNaoConfigurado(Exception):
    """Faltam credenciais da Prolog — a integração fica desligada."""


class PrologIndisponivel(Exception):
    """A API não respondeu, ou respondeu o que não devia."""


def _cred(nome: str) -> str:
    return (credenciais.ler(nome) or "").strip()


def base_url() -> str:
    return _cred("PROLOG_BASE_URL") or BASE_PADRAO


def filiais_configuradas() -> list[str]:
    """Ids de filial, separados por virgula em `PROLOG_FILIAIS`."""
    bruto = _cred("PROLOG_FILIAIS")
    return [x.strip() for x in bruto.replace(";", ",").split(",") if x.strip()]


def modo_auth() -> str:
    if _cred("PROLOG_TOKEN"):
        return "token"
    if _cred("PROLOG_USUARIO") and _cred("PROLOG_SENHA"):
        return "basic"
    if _cred("PROLOG_CLIENT_ID") and _cred("PROLOG_CLIENT_SECRET"):
        return "oauth"
    return ""


def configurado() -> bool:
    """Credencial basta para LISTAR FILIAIS; a lista de pneus tambem exige
    filial, e por isso `pronto()` e mais exigente que `configurado()`."""
    return bool(modo_auth())


def pronto() -> bool:
    return bool(modo_auth() and filiais_configuradas())


def _http(url: str, headers: dict, timeout: int, dados: bytes | None = None):
    req = urllib.request.Request(url, headers=headers, data=dados,
                                 method="POST" if dados is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Cliente:
    """`http` e injetavel para os testes rodarem sem rede."""

    def __init__(self, http=None):
        self._http = http or _http
        self.modo = modo_auth()
        if not self.modo:
            raise PrologNaoConfigurado(
                "sem credencial da Prolog: configure PROLOG_TOKEN, ou "
                "PROLOG_USUARIO + PROLOG_SENHA, ou PROLOG_CLIENT_ID + "
                "PROLOG_CLIENT_SECRET")
        self._tok = ""
        self._tok_expira = 0.0

    # ------------------------------------------------------------------ auth
    def _cabecalho_auth(self) -> str:
        if self.modo == "token":
            t = _cred("PROLOG_TOKEN")
            # aceita o token com ou sem o prefixo, para nao virar "Bearer Bearer"
            return t if t.lower().startswith(("bearer ", "basic ")) else f"Bearer {t}"
        if self.modo == "basic":
            par = f"{_cred('PROLOG_USUARIO')}:{_cred('PROLOG_SENHA')}"
            return "Basic " + base64.b64encode(par.encode()).decode()
        return f"Bearer {self._oauth()}"

    def _oauth(self) -> str:
        agora = time.monotonic()
        if self._tok and agora < self._tok_expira:
            return self._tok
        url = _cred("PROLOG_TOKEN_URL") or f"{base_url()}/oauth/token"
        corpo = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": _cred("PROLOG_CLIENT_ID"),
            "client_secret": _cred("PROLOG_CLIENT_SECRET"),
        }).encode()
        try:
            status, resp = self._http(
                url, {"Content-Type": "application/x-www-form-urlencoded",
                      "Accept": "application/json"}, 60, corpo)
        except Exception as exc:  # noqa: BLE001
            raise PrologIndisponivel(
                f"falha de rede ao pedir token: {type(exc).__name__}") from None
        if status != 200:
            # nao ecoa o corpo: numa troca de credencial ele pode devolver o
            # que foi enviado, e isso iria para o log
            raise PrologIndisponivel(f"pedido de token respondeu HTTP {status}")
        try:
            d = json.loads(resp)
        except json.JSONDecodeError:
            raise PrologIndisponivel("pedido de token nao devolveu JSON") from None
        tok = d.get("access_token") or ""
        if not tok:
            raise PrologIndisponivel("resposta de token sem 'access_token'")
        self._tok = tok
        self._tok_expira = agora + max(30, int(d.get("expires_in") or 3600)) - FOLGA_TOKEN_S
        return tok

    # ------------------------------------------------------------------ http
    def get(self, caminho: str, params: dict | None = None,
            timeout: int = 120) -> dict:
        limpos = {k: v for k, v in (params or {}).items()
                  if v is not None and v != []}
        url = f"{base_url()}{caminho}"
        if limpos:
            url += "?" + urllib.parse.urlencode(limpos, doseq=True)
        try:
            status, corpo = self._http(
                url, {"Authorization": self._cabecalho_auth(),
                      "Accept": "application/json"}, timeout)
        except Exception as exc:  # noqa: BLE001
            raise PrologIndisponivel(
                f"falha de rede ao chamar {caminho}: {type(exc).__name__}") from None
        if status in (401, 403):
            raise PrologIndisponivel(
                f"{caminho} respondeu HTTP {status} — credencial recusada ou "
                "sem permissao para estas filiais")
        if status != 200:
            trecho = (corpo or b"")[:200].decode("utf-8", "ignore")
            raise PrologIndisponivel(f"{caminho} respondeu HTTP {status}: {trecho}")
        try:
            return json.loads(corpo)
        except json.JSONDecodeError:
            raise PrologIndisponivel(
                f"{caminho} respondeu algo que nao e JSON") from None

    # ------------------------------------------------------------- paginacao
    def paginado(self, caminho: str, params: dict, *, tamanho: int = 200,
                 maximo_paginas: int = 500) -> list[dict]:
        """Percorre a paginacao da Prolog (content + lastPage + totalElements).

        Para tanto por `lastPage` quanto por pagina VAZIA: API paginada que
        mente na bandeira de fim ja apareceu antes, e sem essa segunda saida o
        laco iria ate o teto fazendo centenas de chamadas a toa.
        """
        fora: list[dict] = []
        pagina = 0
        while pagina < maximo_paginas:
            d = self.get(caminho, {**params, "pageSize": tamanho,
                                   "pageNumber": pagina})
            lote = d.get("content") or []
            fora.extend(lote)
            pagina += 1
            if not lote or d.get("lastPage") is True:
                break
        return fora

    # ------------------------------------------------------------- recursos
    def filiais(self) -> list[dict]:
        """Sem isto nao ha como montar a consulta de pneus: `branchOfficesId`
        e obrigatorio e o id da Sulista so existe do lado da Prolog."""
        d = self.get("/api/v3/branch-offices")
        return d if isinstance(d, list) else (d.get("content") or [])

    def pneus(self, filiais: list[str] | None = None,
              status: list[str] | None = None) -> list[dict]:
        alvo = filiais or filiais_configuradas()
        if not alvo:
            raise PrologNaoConfigurado(
                "PROLOG_FILIAIS nao configurado — `branchOfficesId` e "
                "obrigatorio em /api/v3/tires")
        p: dict = {"branchOfficesId": alvo}
        if status:
            p["tireStatuses"] = status
        return self.paginado("/api/v3/tires", p)
