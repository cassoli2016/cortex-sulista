"""Cliente HTTP da Prolog — gestão de pneus.

Spec: https://prologapp.com/prolog/openapi.json (OpenAPI 3.0.1, 107 rotas).
Base declarada no spec: `/prolog`, servida em https://prologapp.com.

AUTENTICACAO: `X-Prolog-Api-Token`. Descoberto por sondagem em 25/08/2026,
porque o spec tem `securitySchemes: null` e nao documenta isso em lugar nenhum.
As respostas da propria API confirmaram o formato: com `Authorization: Bearer`
ela devolve "Autenticacao invalida, usuario nao encontrado"; com cabecalho
proprio errado, "Authorization header must be provided"; com este, 200.

Continua PLUGAVEL (PROLOG_AUTH_HEADER / PROLOG_AUTH_PREFIXO) para o caso de a
Prolog mudar, mas o padrao agora e o que funciona de verdade.

CUIDADO — A API TEM COTA. Ao procurar o companyId varrendo valores, a cota se
esgotou na setima chamada e a API passou a responder 429 para tudo. Nada aqui
pode varrer identificador: o que falta se pergunta, nao se adivinha.

NEM TODA ROTA ACEITA TOKEN DE API. `/api/v3/retreaders` responde
"Authorization method not allowed for this resource: API" — existe, esta
documentada, e simplesmente nao e liberada para integracao.

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
# confirmado contra a API em 25/08/2026 (ver cabecalho do modulo)
AUTH_HEADER_PADRAO = "X-Prolog-Api-Token"
# teto da propria API — acima disso ela devolve 400, nao uma pagina menor
PAGINA_MAX = 100
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
    """Base sem barra no fim.

    Dois cuidados que vieram do mundo real:

    - O nome que a Prolog entrega ao cliente e `PROLOG_API_BASE_URL`; eu tinha
      registrado `PROLOG_BASE_URL`. Aceitar os dois evita o suporte de
      "configurei e nao funcionou" por causa de um nome.
    - O valor chega com barra no fim (`.../prolog/`) e os caminhos comecam com
      barra, entao concatenar produziria `//api/v3/tires`. Alguns servidores
      normalizam, outros devolvem 404 — e um 404 aqui pareceria credencial
      errada.
    """
    bruto = (_cred("PROLOG_API_BASE_URL") or _cred("PROLOG_BASE_URL")
             or BASE_PADRAO)
    return bruto.rstrip("/")


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
    def cabecalhos_auth(self) -> dict:
        """Cabecalho(s) de autenticacao.

        Token pode chegar de tres formas e nenhuma esta na documentacao:
        `Authorization: Bearer <t>`, `Authorization: <t>` puro, ou um
        cabecalho proprio (`X-API-Key`, `apikey`...). Em vez de descobrir na
        hora e mexer em codigo, `PROLOG_AUTH_HEADER` escolhe o cabecalho e
        `PROLOG_AUTH_PREFIXO` o prefixo — os padroes cobrem o caso comum.
        """
        # O cabecalho proprio e o padrao SO para token. Basic e OAuth sao
        # esquemas do HTTP e vivem no Authorization por definicao — mandar um
        # "Basic ..." dentro do X-Prolog-Api-Token nao faria sentido nenhum.
        padrao = AUTH_HEADER_PADRAO if self.modo == "token" else "Authorization"
        nome = _cred("PROLOG_AUTH_HEADER") or padrao
        if self.modo == "token":
            t = _cred("PROLOG_TOKEN")
            pref = _cred("PROLOG_AUTH_PREFIXO")
            if pref:
                return {nome: f"{pref} {t}".strip()}
            if nome.lower() == "authorization":
                # so o Authorization pede esquema; cabecalho proprio leva o
                # token puro, que e como a Prolog aceita
                ja = t.lower().startswith(("bearer ", "basic ", "token "))
                return {nome: t if ja else f"Bearer {t}"}
            return {nome: t}
        if self.modo == "basic":
            par = f"{_cred('PROLOG_USUARIO')}:{_cred('PROLOG_SENHA')}"
            return {nome: "Basic " + base64.b64encode(par.encode()).decode()}
        return {nome: f"Bearer {self._oauth()}"}

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
                url, {**self.cabecalhos_auth(),
                      "Accept": "application/json"}, timeout)
        except Exception as exc:  # noqa: BLE001
            raise PrologIndisponivel(
                f"falha de rede ao chamar {caminho}: {type(exc).__name__}") from None
        if status == 429:
            # a cota da Prolog e por periodo e se recupera sozinha; tratar
            # como "credencial errada" mandaria conferir a coisa errada
            raise PrologIndisponivel(
                "cota de requisicoes da Prolog esgotada (HTTP 429). Ela se "
                "recupera sozinha no proximo periodo — nao e credencial "
                "invalida. Evite recarregar a tela em sequencia ate la.")
        if status in (401, 403):
            corpo_txt = (corpo or b"")[:160].decode("utf-8", "ignore")
            if "not allowed for this resource" in corpo_txt:
                raise PrologIndisponivel(
                    f"{caminho} nao aceita token de API — a Prolog libera essa "
                    "rota so para sessao de usuario")
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
    def paginado(self, caminho: str, params: dict, *, tamanho: int = PAGINA_MAX,
                 maximo_paginas: int = 500) -> list[dict]:
        """Percorre a paginacao da Prolog (content + lastPage + totalElements).

        Para tanto por `lastPage` quanto por pagina VAZIA: API paginada que
        mente na bandeira de fim ja apareceu antes, e sem essa segunda saida o
        laco iria ate o teto fazendo centenas de chamadas a toa.
        """
        # TETO DE 100 e da propria API: pedir mais devolve 400 "Max page size
        # should be 100 registers", nao uma pagina menor. Como o default daqui
        # era 200, toda coleta teria falhado — e o 400 pareceria filtro errado.
        tamanho = max(1, min(int(tamanho or PAGINA_MAX), PAGINA_MAX))
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
