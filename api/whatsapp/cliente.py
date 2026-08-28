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

4. **O `/status` USA O CAMPO `error` PARA DIZER QUE ESTÁ TUDO BEM.** Com a
   instância conectada ele responde 200 com
   `{"connected": true, "error": "You are already connected."}` — o campo é
   descritivo (explica por que não há QR Code para ler), não é falha. Custou
   caro descobrir: a regra "200 com `error` no corpo é erro", que está certa
   para o `/send-text`, fazia o CÓRTEX ler CONECTADO como desconectado. Como a
   sétima recusa do `envio.py` depende disso, o envio ficava barrado
   exatamente quando o WhatsApp estava no ar. Quem decide o estado é
   `connected`; `error` só é problema quando ele é falso.
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

# DUAS INSTÂNCIAS: o número do dia a dia e o reserva. São aparelhos diferentes,
# com números diferentes e — o que decide o desenho — REPUTAÇÕES diferentes no
# WhatsApp. Banir um não tem relação com o que o outro fez, então o freio conta
# destinatários separadamente para cada um (ver `registro.py`).
#
# A reserva é OPCIONAL: quem não tiver deixa os três campos em branco e nada
# muda. E não existe troca automática de uma para a outra, de propósito — se o
# sistema começasse a disparar pelo reserva sozinho quando o principal cai,
# queimaria o segundo número também, que é justamente o que não se pode perder.
# A escolha é de quem envia, e a tela diz o estado das duas.
INSTANCIAS: dict[str, tuple[str, str, str]] = {
    "principal": ("ZAPI_INSTANCIA", "ZAPI_TOKEN", "ZAPI_CLIENT_TOKEN"),
    "backup": ("ZAPI2_INSTANCIA", "ZAPI2_TOKEN", "ZAPI2_CLIENT_TOKEN"),
}
ROTULOS = {"principal": "Principal", "backup": "Reserva"}
PADRAO = "principal"


def qual_valida(qual: str | None) -> str:
    """Nome de instância desconhecido cai na principal em vez de estourar.

    Esta função é chamada com valor vindo de HTTP; recusar com exceção faria
    um parâmetro errado virar erro 500 no meio de um envio. Cair na principal é
    o comportamento que a pessoa espera de "não escolhi nada".
    """
    q = str(qual or "").strip().lower()
    return q if q in INSTANCIAS else PADRAO

# O status da instância é consultado no máximo uma vez por minuto. A tela de
# Saúde recarrega a cada 5 s: sem cache seriam ~17 mil chamadas por dia à
# Z-API só para desenhar um cartão. Um minuto de atraso na leitura de
# "conectado" não muda decisão nenhuma.
TTL_STATUS = 60

_CTX = ssl.create_default_context()
# UM CACHE POR INSTÂNCIA. Com um dicionário só, perguntar o estado do reserva
# devolveria o do principal (ou o contrário) durante os 60 s do TTL — e a tela
# mostraria um aparelho conectado no lugar do outro, que é o pior tipo de erro
# aqui: leva a mandar pelo número errado.
_STATUS: dict[str, dict] = {}


class ZapiNaoConfigurado(Exception):
    """Faltam credenciais — a integração fica desligada."""


class ZapiIndisponivel(Exception):
    """A API não respondeu, ou respondeu o que não devia."""


def _cred(nome: str) -> str:
    return (credenciais.ler(nome) or "").strip()


def instancia(qual: str | None = None) -> str:
    return _cred(INSTANCIAS[qual_valida(qual)][0])


def token(qual: str | None = None) -> str:
    return _cred(INSTANCIAS[qual_valida(qual)][1])


def client_token(qual: str | None = None) -> str:
    return _cred(INSTANCIAS[qual_valida(qual)][2])


def configurado(qual: str | None = None) -> bool:
    """Instância + token da instância. O `Client-Token` fica de fora de
    propósito: a conta pode não ter a validação ativada, e exigi-lo aqui
    bloquearia uma configuração legítima."""
    return bool(instancia(qual) and token(qual))


def instancias_configuradas() -> list[str]:
    """Quais existem de verdade, na ordem. A tela oferece só estas — apresentar
    um reserva que ninguém cadastrou seria oferecer um envio que vai falhar."""
    return [q for q in INSTANCIAS if configurado(q)]


def instancia_mascarada(qual: str | None = None) -> str:
    """A instância aparece na tela para conferência. Mesmo não sendo o segredo
    do par, ela compõe a URL — então vai mascarada como o resto."""
    return credenciais.mascarar(instancia(qual))


def _sanitizar(texto: str) -> str:
    """Tira instância e tokens de qualquer texto que vá para tela, log ou
    trilha. Chamada em TODA saída, sem exceção — inclusive nas que "não teriam
    como" conter a URL, porque é justamente a que ninguém revisou que vaza.

    VARRE AS DUAS INSTÂNCIAS, sempre, e não só a que está sendo usada: com dois
    pares de credenciais o mesmo texto pode passar por caminhos diferentes, e
    limpar "só a da vez" é a brecha que ninguém revisaria. São seis
    substituições de string — barato demais para valer a economia.
    """
    fora = str(texto or "")
    for qual in INSTANCIAS:
        for segredo in (token(qual), client_token(qual), instancia(qual)):
            if segredo and len(segredo) >= 6:
                fora = fora.replace(segredo, "***")
    return fora


def _base(qual: str | None = None) -> str:
    return f"{BASE}/instances/{instancia(qual)}/token/{token(qual)}"


def _http(url: str, headers: dict, timeout: int, dados: bytes | None = None):
    req = urllib.request.Request(url, headers=headers, data=dados,
                                 method="POST" if dados is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Cliente:
    """`http` é injetável para os testes rodarem sem rede.

    `qual` escolhe a instância — principal (padrão) ou backup.
    """

    def __init__(self, http=None, qual: str | None = None):
        self._http = http or _http
        self.qual = qual_valida(qual)
        if not configurado(self.qual):
            falta = ("o id da instância" if not instancia(self.qual)
                     else "o token da instância")
            onde = ("" if self.qual == PADRAO
                    else f" da instância {ROTULOS[self.qual].lower()}")
            raise ZapiNaoConfigurado(
                f"Z-API não configurada: falta {falta}{onde}. Configure em "
                "Gestão › WhatsApp.")

    # ------------------------------------------------------------------ http
    def _chamar(self, caminho: str, corpo: dict | None = None,
                timeout: int = TIMEOUT, erro_em_200: bool = True) -> dict:
        cab = {"Accept": "application/json"}
        if client_token(self.qual):
            cab["Client-Token"] = client_token(self.qual)
        dados = None
        if corpo is not None:
            cab["Content-Type"] = "application/json"
            dados = json.dumps(corpo).encode()

        try:
            status, bruto = self._http(_base(self.qual) + caminho, cab, timeout,
                                       dados)
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
            raise ZapiIndisponivel(_erro_legivel(status, d, self.qual))
        # 200 com corpo de erro acontece em alguns caminhos da Z-API — mas NÃO
        # em todos: o `/status` usa `error` como texto descritivo e responde
        # "You are already connected." justamente quando está tudo certo. Por
        # isso quem chama diz se o campo vale como falha ali.
        if erro_em_200 and d.get("error"):
            raise ZapiIndisponivel(_erro_legivel(200, d, self.qual))
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
        """O corpo cru do `/status`. A leitura de `connected`/`error` é de
        `estado()` — aqui só não se pode confundir descrição com falha."""
        return self._chamar("/status", timeout=10, erro_em_200=False)


def _erro_legivel(http_status: int, corpo: dict,
                  qual: str | None = None) -> str:
    """Mensagem que ajuda a consertar, já sanitizada.

    A Z-API devolve o motivo em `error`, mas os dois casos que mais acontecem
    saem incompreensíveis: `null not allowed` (o Client-Token foi ativado no
    painel e não está aqui) e o 401/403 genérico (instância ou token errados,
    que na URL é o mesmo sintoma).
    """
    bruto = _sanitizar(str(corpo.get("error") or corpo.get("message") or ""))
    # com duas instâncias, "a Z-API recusou as credenciais" sem dizer QUAL
    # manda conferir o par errado
    de = "" if qual_valida(qual) == PADRAO else f" ({ROTULOS[qual_valida(qual)].lower()})"

    if "not allowed" in bruto.lower() and not client_token(qual):
        return ("A Z-API exigiu o token de segurança da conta. Ele foi ativado "
                "na aba Segurança do painel Z-API e precisa ser preenchido "
                "aqui no campo \"Token de segurança da conta\".")
    if http_status in (401, 403):
        return (f"A Z-API recusou as credenciais{de}. Confira o id da instância "
                "e o token da instância — na Z-API os dois formam o endereço, "
                "então um errado dá o mesmo erro que o outro.")
    if http_status == 404:
        return (f"A Z-API não encontrou esta instância{de}. Confira o id da "
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

# O `/status` responde em inglês e com frases que não dizem o que fazer. Elas
# vão para a tela de Saúde e para o motivo da recusa de envio, então valem uma
# tradução que aponte o conserto. O que não estiver aqui passa sanitizado, em
# inglês mesmo — inventar tradução para mensagem desconhecida esconderia
# justamente o caso novo.
_STATUS_PT = {
    "you are not connected": (
        "A instância não está pareada a um WhatsApp. Leia o QR Code no painel "
        "da Z-API para conectar o número."),
    "you are disconnected": (
        "A instância foi desconectada. Releia o QR Code no painel da Z-API."),
    "you need to be connected": (
        "A instância não está conectada. Releia o QR Code no painel da Z-API."),
}


def _status_legivel(bruto: str) -> str:
    chave = bruto.strip().rstrip(".").lower()
    return _STATUS_PT.get(chave, bruto)


def estado(force: bool = False, http=None, qual: str | None = None) -> dict:
    """Estado da conexão de UMA instância, com cache de `TTL_STATUS`.

    Devolve sempre um dicionário — nunca levanta. Quem chama precisa saber se
    dá para mandar; um erro de rede aqui é "não sei", não é motivo para
    derrubar a tela de Saúde nem o formulário de envio.
    """
    qual = qual_valida(qual)
    agora = time.monotonic()
    guardado = _STATUS.get(qual)
    if not force and guardado and (agora - guardado["em"]) < TTL_STATUS:
        return guardado["dados"]

    if not configurado(qual):
        d = {"ok": False, "conectado": False, "celular": False,
             "erro": "Z-API não configurada.", "configurado": False}
    else:
        try:
            r = Cliente(http=http, qual=qual).status()
            conectado_ = bool(r.get("connected"))
            # `error` aqui é DESCRIÇÃO, não falha: com a instância no ar ele
            # vem "You are already connected.". Repassá-lo como erro fazia a
            # tela dizer "desconectado" com o WhatsApp funcionando — e o
            # envio recusar tudo. Só vale como motivo quando `connected` é
            # falso.
            motivo = _sanitizar(str(r.get("error") or ""))
            d = {"ok": True,
                 "conectado": conectado_,
                 "celular": bool(r.get("smartphoneConnected")),
                 "erro": "" if conectado_ else _status_legivel(motivo),
                 "configurado": True}
        except (ZapiIndisponivel, ZapiNaoConfigurado) as exc:
            d = {"ok": False, "conectado": False, "celular": False,
                 "erro": _sanitizar(str(exc)), "configurado": configurado(qual)}

    d["em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d["instancia"] = qual
    d["rotulo"] = ROTULOS[qual]
    _STATUS[qual] = {"em": agora, "dados": d}
    return d


def conectado(http=None, qual: str | None = None) -> bool:
    return bool(estado(http=http, qual=qual).get("conectado"))


def limpar_cache() -> None:
    """Usado pelos testes e depois de salvar credencial nova — senão a tela
    continuaria mostrando o erro da configuração anterior por um minuto.

    Limpa AS DUAS: salvar credencial não diz qual mudou, e deixar uma parada
    faria a tela contradizer a outra."""
    _STATUS.clear()
