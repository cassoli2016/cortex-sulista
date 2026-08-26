"""Cliente HTTP da Monkey Exchange (portal de antecipação da Tupy).

Doc: https://developers.monkey.exchange/reference/receivableweblistreceivablecontractjson
Endpoint: GET /v2/sellers/{sellerId}/receivables

AUTENTICAÇÃO PLUGÁVEL. A Monkey confirmou por e-mail que é OAuth2: credencial
trocada por `access_token`, `expires_in` na própria resposta, renovação por
`refresh_token` e o token em `Authorization: Bearer`. O que ela ainda NÃO disse
é qual o `grant_type` do fluxo máquina-a-máquina — a menção ao refresh sugere
que pode não ser `client_credentials`. Então o grant é configurável:

  1. TOKEN ESTÁTICO → `MONKEY_TOKEN` vai direto no `Authorization`.
  2. OAUTH2         → `MONKEY_GRANT_TYPE` = client_credentials (padrão),
     password ou refresh_token, trocado em `MONKEY_TOKEN_URL`, com cache.

RENOVAÇÃO. Quando a resposta de token traz `refresh_token`, ele é guardado e
usado na renovação seguinte — o fluxo que a Monkey descreveu. Se o refresh for
recusado (venceu, foi revogado), cai de volta no grant configurado em vez de
deixar a coleta morrer: refresh que expira é o defeito que só aparece depois de
horas no ar, quando ninguém está olhando.

VÁRIOS CNPJs, VÁRIOS SELLERS. A Sulista tem um perfil por CNPJ na Monkey e cada
um é um `sellerId` próprio, mas o caminho do endpoint carrega um só. Por isso
`MONKEY_SELLER_IDS` aceita a lista separada por vírgula e a coleta percorre
todos com o MESMO cliente — o token é obtido uma vez, não cinco.

AMBIENTE: `MONKEY_AMBIENTE` = 'hmg' (padrão) ou 'prod'. O padrão é homologação
DE PROPÓSITO — apontar para produção tem de ser um ato deliberado, e a primeira
coleta de uma integração nova é justamente quando o parser ainda pode estar
errado. `MONKEY_BASE_URL` sobrepõe o host: a Monkey indicou
`https://sandbox.monkeyecx.com` para homologação, o que NÃO bate com o
`hmg-zuul` que está aqui, e enquanto ela não confirma qual é o host de API o
valor certo entra por configuração, sem editar código.
"""
from __future__ import annotations

import json
import ssl
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

# Os grants que cobrem o fluxo máquina-a-máquina. `refresh_token` aparece aqui
# como grant INICIAL (quando a Monkey entrega um refresh já emitido); a
# renovação automática não depende dele estar configurado.
GRANTS = ("client_credentials", "password", "refresh_token")
GRANT_PADRAO = "client_credentials"

# folga na expiração do token: renovar em cima da hora produz o 401 que
# acontece uma vez por dia e ninguém consegue reproduzir
FOLGA_TOKEN_S = 60

_CTX = ssl.create_default_context()


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
    """Host da API. `MONKEY_BASE_URL` vence o ambiente — é o escape para o
    caso de o host de homologação não ser o que está no dicionário."""
    return (_cred("MONKEY_BASE_URL") or BASES[ambiente()]).rstrip("/")


def seller_ids() -> list[str]:
    """Os sellerIds configurados, na ordem, sem repetir.

    `MONKEY_SELLER_IDS` (vários, separados por vírgula ou ponto e vírgula) tem
    precedência; `MONKEY_SELLER_ID` continua valendo para quem já configurou um
    só. Ordem preservada de propósito: é ela que aparece nos relatórios de
    coleta, e alfabetizar embaralharia a leitura por filial.
    """
    bruto = _cred("MONKEY_SELLER_IDS") or _cred("MONKEY_SELLER_ID")
    vistos: set[str] = set()
    fora: list[str] = []
    for pedaco in bruto.replace(";", ",").split(","):
        item = pedaco.strip()
        if item and item not in vistos:
            vistos.add(item)
            fora.append(item)
    return fora


def seller_id() -> str:
    """O primeiro sellerId — para diagnóstico e compatibilidade."""
    ids = seller_ids()
    return ids[0] if ids else ""


def grant_type() -> str:
    return (_cred("MONKEY_GRANT_TYPE") or GRANT_PADRAO).strip() or GRANT_PADRAO


def modo_auth() -> str:
    """Qual credencial está configurada: 'token', 'oauth' ou '' (nenhuma)."""
    if _cred("MONKEY_TOKEN"):
        return "token"
    if (_cred("MONKEY_CLIENT_ID") and _cred("MONKEY_CLIENT_SECRET")) \
            or _cred("MONKEY_REFRESH_TOKEN"):
        return "oauth"
    return ""


def configurado() -> bool:
    """Precisa de credencial E de pelo menos um sellerId — um sem o outro não
    faz chamada."""
    return bool(modo_auth() and seller_ids())


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

    def __init__(self, http=None, seller: str | None = None,
                 sellers: list[str] | None = None):
        self._http = http or _http
        if seller is not None:
            self.sellers = [seller.strip()] if seller.strip() else []
        elif sellers is not None:
            self.sellers = [s.strip() for s in sellers if s and s.strip()]
        else:
            self.sellers = seller_ids()
        self.modo = modo_auth()
        self.grant = grant_type()
        if not self.modo:
            raise MonkeyNaoConfigurado(
                "sem credencial da Monkey: configure MONKEY_TOKEN, ou "
                "MONKEY_CLIENT_ID + MONKEY_CLIENT_SECRET")
        if not self.sellers:
            raise MonkeyNaoConfigurado(
                "MONKEY_SELLER_IDS não configurado — é o {id} do caminho "
                "/v2/sellers/{id}/receivables e não há como descobri-lo daqui")
        if self.modo == "oauth" and self.grant not in GRANTS:
            # grant escrito errado falharia como "credencial recusada", e a
            # gente iria caçar a senha em vez do typo
            raise MonkeyNaoConfigurado(
                f"MONKEY_GRANT_TYPE inválido: {self.grant!r} — "
                f"use um de {', '.join(GRANTS)}")
        if self.modo == "oauth" and self.grant == "password" and not (
                _cred("MONKEY_USUARIO") and _cred("MONKEY_SENHA")):
            raise MonkeyNaoConfigurado(
                "MONKEY_GRANT_TYPE=password exige MONKEY_USUARIO e MONKEY_SENHA")
        if self.modo == "oauth" and self.grant == "refresh_token" \
                and not _cred("MONKEY_REFRESH_TOKEN"):
            raise MonkeyNaoConfigurado(
                "MONKEY_GRANT_TYPE=refresh_token exige MONKEY_REFRESH_TOKEN")
        self._tok: str = ""
        self._tok_expira: float = 0.0
        self._refresh: str = _cred("MONKEY_REFRESH_TOKEN")

    @property
    def seller(self) -> str:
        """O primeiro seller — o que `recebiveis()` usa quando não recebe outro."""
        return self.sellers[0] if self.sellers else ""

    # ------------------------------------------------------------------ auth
    def _campos_do_grant(self) -> dict:
        campos = {
            "grant_type": self.grant,
            "client_id": _cred("MONKEY_CLIENT_ID"),
            "client_secret": _cred("MONKEY_CLIENT_SECRET"),
        }
        if self.grant == "password":
            campos["username"] = _cred("MONKEY_USUARIO")
            campos["password"] = _cred("MONKEY_SENHA")
        elif self.grant == "refresh_token":
            campos["refresh_token"] = self._refresh or _cred("MONKEY_REFRESH_TOKEN")
        escopo = _cred("MONKEY_SCOPE")
        if escopo:
            campos["scope"] = escopo
        return {k: v for k, v in campos.items() if v}

    def _pedir_token(self, campos: dict) -> None:
        """POST no endpoint de token e guarda o resultado no cache."""
        url = _cred("MONKEY_TOKEN_URL") or f"{base_url()}/oauth/token"
        # marcado ANTES da chamada de propósito: `expires_in` conta a partir da
        # emissão no servidor, então medir depois faria o cache achar que o
        # token dura mais do que dura.
        t0 = time.monotonic()
        corpo = urllib.parse.urlencode(campos).encode()
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
                f"pedido de token ({campos.get('grant_type')}) "
                f"respondeu HTTP {status}")
        try:
            d = json.loads(resp)
        except json.JSONDecodeError:
            raise MonkeyIndisponivel("pedido de token não devolveu JSON") from None
        tok = d.get("access_token") or ""
        if not tok:
            raise MonkeyIndisponivel("resposta de token sem 'access_token'")
        try:
            vida = int(float(d.get("expires_in") or 3600))
        except (TypeError, ValueError):
            vida = 3600
        self._tok = tok
        # refresh novo substitui o antigo; ausente, o que já tínhamos continua
        self._refresh = (d.get("refresh_token") or "").strip() or self._refresh
        self._tok_expira = t0 + max(30, vida) - FOLGA_TOKEN_S

    def _token(self) -> str:
        if self.modo == "token":
            return _cred("MONKEY_TOKEN")

        if self._tok and time.monotonic() < self._tok_expira:
            return self._tok

        # renovação: com refresh na mão, tenta por ele antes de reapresentar a
        # credencial. Se falhar, ESQUECE o refresh e cai no grant configurado —
        # senão a coleta ficaria presa num refresh morto para sempre.
        if self._refresh and self.grant != "refresh_token":
            try:
                self._pedir_token({
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh,
                    "client_id": _cred("MONKEY_CLIENT_ID"),
                    "client_secret": _cred("MONKEY_CLIENT_SECRET"),
                })
                return self._tok
            except MonkeyIndisponivel:
                self._refresh = ""

        self._pedir_token(self._campos_do_grant())
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
    def recebiveis_de(self, seller: str, *, tamanho: int = 200,
                      maximo_paginas: int = 200,
                      busca: dict | None = None) -> list[dict]:
        """Todos os recebíveis de UM seller, seguindo a paginação.

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
            d = self.get(f"/v2/sellers/{seller}/receivables", params)
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

    def recebiveis_por_seller(self, **kw) -> dict[str, list[dict]]:
        """Um lote por sellerId configurado, no MESMO cliente.

        O token fica no cache da instância, então 5 CNPJs custam 1 autenticação
        e não 5. A quebra por seller volta separada porque é ela que diz, no
        relatório da coleta, qual CNPJ trouxe o quê — somando tudo antes, um
        CNPJ que parasse de responder sumiria sem deixar rastro.
        """
        return {s: self.recebiveis_de(s, **kw) for s in self.sellers}

    def recebiveis(self, **kw) -> list[dict]:
        """Todos os recebíveis de TODOS os sellers configurados."""
        return [r for lote in self.recebiveis_por_seller(**kw).values()
                for r in lote]
