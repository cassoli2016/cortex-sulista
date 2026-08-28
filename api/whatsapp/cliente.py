"""Cliente HTTP da Z-API (WhatsApp).

Doc: https://developer.z-api.io  ·  fonte dos contratos usados aqui:
https://github.com/Z-API/z-api-docs — `docs/message/send-message-text.md`,
`docs/instance/status.md`, `docs/security/client-token.md`, `docs/queue/*`.

    POST {base}/send-text     {"phone": "5547999998888", "message": "..."}
      -> 200 {"zaapId": ..., "messageId": ..., "id": ...}
    GET  {base}/status        -> {"connected": bool, "smartphoneConnected": bool,
                                  "error": "..."}

    base = https://api.z-api.io/instances/{INSTANCIA}/token/{TOKEN_DA_INSTANCIA}

TRÊS COISAS DESTA API QUE NÃO SE PARECEM COM NENHUMA OUTRA INTEGRAÇÃO DAQUI:

1. **O TOKEN VAI DENTRO DA URL.** Na Gobrax, na Monkey e na Prolog o segredo
   viaja em cabeçalho, então o log podia registrar a URL à vontade. Aqui a URL
   É a credencial: qualquer `str(exc)` de `urllib`, qualquer log de "falhou ao
   chamar {url}", qualquer eco de erro para a tela publica o token da conta.
   Por isso NADA aqui devolve a exceção crua, e tudo que sai passa por
   `_sanitizar()`. É a regra mais importante deste arquivo.

2. **Existe um segundo token, de conta.** O `Client-Token` (aba Segurança do
   painel Z-API) é opcional até ser ativado e obrigatório depois. Quem ativa lá
   e não configura aqui recebe `{"error": "null not allowed"}` — que não diz
   nada. `_erro_legivel` traduz.

3. **Aceitar não é entregar.** Se o celular estiver desconectado, a Z-API
   responde 200 e ENFILEIRA — até 1.000 mensagens — e dispara tudo de uma vez
   quando o aparelho voltar. Uma cobrança de terça chegando no sábado à noite,
   em lote, é o pior resultado possível. Por isso `envio.py` consulta
   `conectado()` antes de mandar, e por isso este cliente guarda o estado da
   conexão em cache curto em vez de deixar cada chamador decidir.
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import credenciais

BASE = "https://api.z-api.io"
TIMEOUT = 20

# O status da instância é consultado no máximo uma vez por minuto. A tela de
# Saúde recarrega a cada 5 s: sem cache seriam ~17 mil chamadas por dia à
# Z-API só para desenhar um cartão. Um minuto de atraso na leitura de
# "conectado" não muda decisão nenhuma.
TTL_STATUS = 60

_CTX = ssl.create_default_context()
_STATUS: dict = {"em": 0.0, "dados": None}


class ZapiNaoConfigurado(Exception):
    """Faltam credenciais — a integração fica desligada."""


class ZapiIndisponivel(Exception):
    """A API não respondeu, ou respondeu o que não devia."""


def _cred(nome: str) -> str:
    return (credenciais.ler(nome) or "").strip()


def instancia() -> str:
    return _cred("ZAPI_INSTANCIA")


def token() -> str:
    return _cred("ZAPI_TOKEN")


def client_token() -> str:
    return _cred("ZAPI_CLIENT_TOKEN")


def configurado() -> bool:
    """Instância + token da instância. O `Client-Token` fica de fora de
    propósito: a conta pode não ter a validação ativada, e exigi-lo aqui
    bloquearia uma configuração legítima."""
    return bool(instancia() and token())


def instancia_mascarada() -> str:
    """A instância aparece na tela para conferência. Mesmo não sendo o segredo
    do par, ela compõe a URL — então vai mascarada como o resto."""
    return credenciais.mascarar(instancia())


def _sanitizar(texto: str) -> str:
    """Tira instância e tokens de qualquer texto que vá para tela, log ou
    trilha. Chamada em TODA saída, sem exceção — inclusive nas que "não teriam
    como" conter a URL, porque é justamente a que ninguém revisou que vaza."""
    fora = str(texto or "")
    for segredo in (token(), client_token(), instancia()):
        if segredo and len(segredo) >= 6:
            fora = fora.replace(segredo, "***")
    return fora


def _base() -> str:
    return f"{BASE}/instances/{instancia()}/token/{token()}"


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

    def __init__(self, http=None):
        self._http = http or _http
        if not configurado():
            falta = ("o id da instância" if not instancia()
                     else "o token da instância")
            raise ZapiNaoConfigurado(
                f"Z-API não configurada: falta {falta}. Configure em "
                "Gestão › WhatsApp.")

    # ------------------------------------------------------------------ http
    def _chamar(self, caminho: str, corpo: dict | None = None,
                timeout: int = TIMEOUT) -> dict:
        cab = {"Accept": "application/json"}
        if client_token():
            cab["Client-Token"] = client_token()
        dados = None
        if corpo is not None:
            cab["Content-Type"] = "application/json"
            dados = json.dumps(corpo).encode()

        try:
            status, bruto = self._http(_base() + caminho, cab, timeout, dados)
        except Exception as exc:   # noqa: BLE001
            # SÓ o nome da classe: str(exc) de urllib carrega a URL, e a URL
            # carrega o token.
            raise ZapiIndisponivel(
                f"Não foi possível falar com a Z-API ({type(exc).__name__}). "
                "Confira a internet do servidor.") from None

        try:
            d = json.loads(bruto) if bruto else {}
        except json.JSONDecodeError:
            d = {}
        if not isinstance(d, dict):
            d = {}

        if status != 200:
            raise ZapiIndisponivel(_erro_legivel(status, d))
        # 200 com corpo de erro acontece em alguns caminhos da Z-API
        if d.get("error"):
            raise ZapiIndisponivel(_erro_legivel(200, d))
        return d

    # --------------------------------------------------------------- métodos
    def enviar_texto(self, telefone: str, mensagem: str,
                     intervalo_seg: int | None = None) -> dict:
        """`telefone` já vem normalizado por `numeros.normalizar`."""
        corpo: dict = {"phone": telefone, "message": mensagem}
        if intervalo_seg:
            corpo["delayMessage"] = int(intervalo_seg)
        return self._chamar("/send-text", corpo)

    def status(self) -> dict:
        return self._chamar("/status", timeout=10)


def _erro_legivel(http_status: int, corpo: dict) -> str:
    """Mensagem que ajuda a consertar, já sanitizada.

    A Z-API devolve o motivo em `error`, mas os dois casos que mais acontecem
    saem incompreensíveis: `null not allowed` (o Client-Token foi ativado no
    painel e não está aqui) e o 401/403 genérico (instância ou token errados,
    que na URL é o mesmo sintoma).
    """
    bruto = _sanitizar(str(corpo.get("error") or corpo.get("message") or ""))

    if "not allowed" in bruto.lower() and not client_token():
        return ("A Z-API exigiu o token de segurança da conta. Ele foi ativado "
                "na aba Segurança do painel Z-API e precisa ser preenchido "
                "aqui no campo \"Token de segurança da conta\".")
    if http_status in (401, 403):
        return ("A Z-API recusou as credenciais. Confira o id da instância e o "
                "token da instância — na Z-API os dois formam o endereço, "
                "então um errado dá o mesmo erro que o outro.")
    if http_status == 404:
        return ("A Z-API não encontrou esta instância. Confira o id da "
                "instância no painel Z-API.")
    if http_status == 415:
        return "A Z-API recusou o formato do envio (Content-Type)."
    if http_status == 429:
        return ("A Z-API está limitando as chamadas (429). Aguarde antes de "
                "tentar de novo.")
    if bruto:
        return f"A Z-API respondeu HTTP {http_status}: {bruto}"
    return f"A Z-API respondeu HTTP {http_status}."


# ------------------------------------------------------------------- status

def estado(force: bool = False, http=None) -> dict:
    """Estado da conexão, com cache de `TTL_STATUS`.

    Devolve sempre um dicionário — nunca levanta. Quem chama precisa saber se
    dá para mandar; um erro de rede aqui é "não sei", não é motivo para
    derrubar a tela de Saúde nem o formulário de envio.
    """
    agora = time.monotonic()
    if not force and _STATUS["dados"] and (agora - _STATUS["em"]) < TTL_STATUS:
        return _STATUS["dados"]

    if not configurado():
        d = {"ok": False, "conectado": False, "celular": False,
             "erro": "Z-API não configurada.", "configurado": False}
    else:
        try:
            r = Cliente(http=http).status()
            d = {"ok": True,
                 "conectado": bool(r.get("connected")),
                 "celular": bool(r.get("smartphoneConnected")),
                 "erro": _sanitizar(str(r.get("error") or "")),
                 "configurado": True}
        except (ZapiIndisponivel, ZapiNaoConfigurado) as exc:
            d = {"ok": False, "conectado": False, "celular": False,
                 "erro": _sanitizar(str(exc)), "configurado": configurado()}

    d["em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _STATUS.update(em=agora, dados=d)
    return d


def conectado(http=None) -> bool:
    return bool(estado(http=http).get("conectado"))


def limpar_cache() -> None:
    """Usado pelos testes e depois de salvar credencial nova — senão a tela
    continuaria mostrando o erro da configuração anterior por um minuto."""
    _STATUS.update(em=0.0, dados=None)
