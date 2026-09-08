"""CÓRTEX — API do MVP do painel Financeiro.

Backend leve (roda neste Mac por enquanto). Lê o ERP AVA pelo túnel SSH e serve
o painel financeiro. Requer o túnel ativo (127.0.0.1:15432).

Rodar:  uv run uvicorn api.main:app --reload --port 8000
Abrir:  http://127.0.0.1:8000
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import threading
import tomllib
from datetime import date, datetime
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path

from api import (manutencao_compras, segredo_arquivo, suprimentos_oc,
                 suprimentos_pecas)

import psycopg
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.responses import JSONResponse as _JSONResponseBase
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import (alertas, auth, copiloto, db, documentacao, dre_cliente, lider,
               push, queries, queries_folha, servidor)


class JSONResponse(_JSONResponseBase):
    """O JSONResponse da casa, que não estoura por causa de um tipo do banco.

    POR QUE ISTO EXISTE (30/08/2026, tela de Premiação em 500 por um dia)
    ====================================================================
    `prem_ocorrencia_classe.peso` é `numeric`, o psycopg devolve `Decimal` e o
    `json` padrão não serializa `Decimal`. Até aí seria um erro comum. O que o
    tornou caro foi ONDE ele estoura:

        try:
            d = ler()                 # passa
        except Exception: ...
        d["x"] = do_banco()           # passa, o Decimal entra aqui
        return JSONResponse(d)        # ESTOURA no render(), já fora do try

    O `render()` só roda quando o Starlette vai escrever a resposta, DEPOIS do
    `try/except` da rota. A exceção escapa de todo o tratamento e o navegador
    recebe `HTTP 500 · text/plain`, sem uma pista apontando para o campo, para
    a tela ou para o banco — e a tela ainda mostra os números da carga
    anterior ao lado do aviso, o que faz parecer problema de conexão.

    São ~200 rotas montando dicionário de linha de banco. Consertar uma a uma
    deixaria a próxima passar, e a próxima é a que ninguém vai conseguir
    diagnosticar. **Converter aqui mata a família inteira**, e só age em caso
    que hoje QUEBRA — não muda nada que já funciona.

    Isso NÃO dispensa converter no limite do módulo (`float(...)`,
    `.isoformat()`), que continua sendo a forma certa: ali o tipo do banco
    para de importar e o resto do código não precisa saber que ele existiu.
    Isto aqui é a rede embaixo, para o erro degradar em vez de derrubar.
    """

    @staticmethod
    def _converter(o):
        # imports locais: este módulo só traz `date` no topo, e acrescentar
        # quatro nomes lá em cima por causa de uma função de borda poluiria o
        # espaço de nomes de um arquivo de 5 mil linhas
        import datetime as _dt
        from decimal import Decimal
        datetime, date, time, timedelta = (_dt.datetime, _dt.date, _dt.time,
                                           _dt.timedelta)
        if isinstance(o, Decimal):
            # float e não str: a tela faz conta com esse número
            return float(o)
        if isinstance(o, (datetime, date, time)):
            return o.isoformat()
        if isinstance(o, timedelta):
            return o.total_seconds()
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        if isinstance(o, (bytes, bytearray)):
            return o.decode("utf-8", "replace")
        raise TypeError(
            f"{type(o).__name__} não vai para JSON — converta no módulo que "
            "leu o dado, onde dá para saber o que ele significa")

    # ------------------------------------------------------------------
    # O CARIMBO DA LEITURA VELHA VIRA CABEÇALHO, e por isso vale para TODAS
    # as rotas de uma vez.
    #
    # `queries.cached(velha_ate=)` carimba o PAYLOAD (`leitura_velha`), e a
    # regra da casa é que a tela mostre. Enquanto duas telas tinham a rede,
    # duas telas desenhavam a tarja à mão — e uma das duas lia o campo com o
    # nome errado (`leitura_idade_s` em vez de `leitura_idade_seg`), então
    # dizia "0 min atrás" para sempre. Ninguém percebeu porque a tarja só
    # aparece no dia ruim, que é justamente o dia em que ninguém está
    # conferindo o texto dela.
    #
    # Com trinta telas ganhando a rede, trinta desenhos à mão seriam trinta
    # chances de esquecer — e esquecer aqui não deixa rastro: a tela mostra
    # número velho CALADO, que é o pior dos três estados possíveis (pior que
    # tela vazia, porque ninguém desconfia dele).
    #
    # O cabeçalho resolve no lugar por onde todo payload já passa. O
    # navegador o lê sem reabrir o corpo (o gancho do `fetch` custa uma
    # leitura de header, não um segundo parse de uma tabela de mil linhas), e
    # ele também aparece no `curl` e no DevTools — o que faz o estado ficar
    # visível justamente durante o incidente, que foi o que faltou hoje.
    # ------------------------------------------------------------------
    def __init__(self, content=None, status_code: int = 200,
                 headers: dict | None = None, *args, **kwargs):
        if isinstance(content, dict) and content.get("leitura_velha"):
            headers = dict(headers or {})
            # ASCII no valor: header com acento é campo minado entre proxies,
            # e o Cloudflare está no caminho. A tela formata o texto.
            headers["X-Leitura-Velha"] = "1"
            headers["X-Leitura-Em"] = str(content.get("leitura_em") or "")
            headers["X-Leitura-Idade"] = str(
                int(content.get("leitura_idade_seg") or 0))
            # Sem isto o navegador ENXERGA a resposta e NÃO enxerga os
            # cabeçalhos: numa resposta same-origin comum não haveria
            # problema, mas o portal passa por proxy e a regra de exposição
            # é barata o bastante para não depender disso.
            headers["Access-Control-Expose-Headers"] = (
                "X-Leitura-Velha, X-Leitura-Em, X-Leitura-Idade")
        super().__init__(content, status_code, headers, *args, **kwargs)

    def render(self, content) -> bytes:
        # mesmas opções do Starlette; só entra o `default`
        return json.dumps(content, ensure_ascii=False, allow_nan=False,
                          indent=None, separators=(",", ":"),
                          default=self._converter).encode("utf-8")


log = logging.getLogger("cortex.financeiro")

# LOG EM ARQUIVO, e nao so no stdout do uvicorn. A API roda por TAREFA
# AGENDADA do Windows: o stdout dela nao vai para lugar nenhum, entao todo
# `log.warning` que este arquivo escreve ha meses estava sendo escrito no
# vazio. Foi por isso que a Premiacao ficou dois dias em 500 sem que houvesse
# onde olhar -- e por isso o diagnostico virou tentativa e erro.
#
# Rotaciona em 5 MB e guarda 3: log que enche disco derruba o servidor
# inteiro, e ai o remedio virou a doenca (mesma regra da retencao do backup).
def _ligar_log_em_arquivo() -> None:
    from logging.handlers import RotatingFileHandler

    class _Rotativo(RotatingFileHandler):
        """Cala no ENCERRAMENTO do interpretador.

        O `__del__` do pool do psycopg registra um aviso quando o processo
        morre, e nesse ponto o modulo `logging.handlers` ja foi desmontado --
        o `emit` estoura com `AttributeError: 'NoneType' object has no
        attribute 'FileHandler'` e imprime um traceback assustador que nao e
        defeito nenhum. Ruido no encerramento treina a ignorar a saida, que e
        o oposto do que este log existe para fazer.
        """

        def handleError(self, record):
            """O `emit` do logging JA engole a excecao -- e imprime o traceback
            por conta propria, aqui. Sobrescrever o `emit` nao adianta: e este
            metodo que faz o barulho."""
            pass

    raiz = logging.getLogger()
    alvo = Path(__file__).resolve().parent.parent / "logs" / "api.log"
    if any(getattr(h, "baseFilename", "") == str(alvo)
           for h in raiz.handlers):
        return                      # ja ligado (recarga de modulo em teste)
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        h = _Rotativo(alvo, maxBytes=5 * 1024 * 1024,
                      backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        raiz.addHandler(h)
        if raiz.level > logging.INFO or raiz.level == logging.NOTSET:
            raiz.setLevel(logging.INFO)
    except Exception:  # noqa: BLE001 - log e apoio: nao pode impedir a API de subir
        pass


_ligar_log_em_arquivo()


# Recusa NÃO é erro de servidor — e a diferença é visível para o usuário.
#
# "O envio está desligado", "o limite do dia acabou", "a Gobrax não respondeu":
# em todos, o CÓRTEX funcionou perfeitamente e está dizendo NÃO, com um motivo
# que a pessoa precisa ler. Isso é 4xx. 502 significa "meu gateway está ruim",
# que é outra coisa.
#
# E não é preciosismo de vocabulário HTTP: **o Cloudflare substitui o corpo das
# respostas 5xx da origem pela página de erro dele**. Medido nesta bancada — um
# 401 atravessa o túnel intacto (`content-type: application/json`, mesmo
# tamanho), e o 502 chegava à tela sem JSON nenhum. O usuário via "erro interno
# da API" durante horas enquanto o servidor respondia, corretamente, "o envio
# está DESLIGADO em Gestão › WhatsApp" — mensagem que nunca cruzou o túnel.
#
# Regra: 5xx só para falha NOSSA de verdade (exceção não tratada). Tudo que o
# usuário precisa LER usa 4xx.
HTTP_RECUSA = 409

async def sem_travar(fn, *args, **kwargs):
    """Roda trabalho BLOQUEANTE fora do event loop.

    POR QUE ISTO EXISTE — e por que é obrigatório em toda rota `async def` que
    fale com o mundo lá fora:

    O FastAPI roda rota `def` num threadpool e rota `async def` NO PRÓPRIO
    EVENT LOOP. Como as rotas que recebem corpo precisam de `await req.json()`,
    elas nascem `async def` — e aí qualquer `urllib`, `psycopg` ou `smtplib`
    dentro delas trava o loop, ou seja, o SERVIDOR INTEIRO, pelo tempo da
    chamada. Ninguém mais é atendido: nem outra tela, nem a recarga automática
    da Torre, nem o `/api/health`.

    Não é teoria. Foi MEDIDO nesta bancada com o envio de WhatsApp: com a
    Z-API demorando 3 s, o `/api/health` — rota trivial e pública — levou
    5,7 s. Em produção o envio chega a 30 s por destinatário (10 s de
    `/status` + 20 s de `/send-text`), e `enviar_varios` repete isso em série,
    um número por vez. O Cloudflare Tunnel, sem resposta da origem, devolve
    **502 Bad Gateway em HTML** — que a tela não consegue nem ler como JSON.
    Foi exatamente esse o defeito relatado, e o teste
    `tests/test_rotas_nao_travam.py` existe para ele não voltar.

    A regra, então: em rota `async def`, tudo que faz I/O passa por aqui.
    """
    return await run_in_threadpool(fn, *args, **kwargs)


def _versao() -> str:
    """Fonte única: o pyproject.toml. Ler dele evita o número duplicado em dois
    lugares, que a primeira pressa faria divergir."""
    try:
        alvo = Path(__file__).resolve().parent.parent / "pyproject.toml"
        return tomllib.loads(alvo.read_text(encoding="utf-8"))["project"]["version"]
    except Exception:  # noqa: BLE001
        return "dev"


VERSAO = _versao()


def _rotulo() -> str:
    """Mesma guarda do _versao(): um docs/versoes.yaml ausente ou com data
    malformada NAO pode impedir a API de subir — e um problema de documentacao,
    nao de servico."""
    try:
        return documentacao.rotulo(VERSAO)
    except Exception:  # noqa: BLE001
        log.warning("versoes.yaml ilegivel; rotulo degradado")
        return f"CX-v{VERSAO}"


ROTULO = _rotulo()
# docs/openapi desligados: o painel é exposto na internet via Cloudflare Tunnel
app = FastAPI(title="Cortex Sulista — Financeiro (MVP)",
              docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(Exception)
async def _erro_nao_tratado(request: Request, exc: Exception) -> JSONResponse:
    """Exceção que escapou de tudo: REGISTRA o traceback e devolve JSON.

    POR QUE ISTO EXISTE (30/08/2026, Premiação em 500 por quase dois dias)
    =====================================================================
    Sem este handler, exceção não tratada vira o `Internal Server Error` do
    Starlette: **500 em `text/plain`**, sem corpo útil, e o traceback fica só
    na saída do uvicorn — que aqui roda por tarefa agendada, sem log em
    arquivo. Ou seja: o usuário vê "resposta em formato inesperado", e não há
    onde olhar.

    Foi exatamente o que aconteceu. Passei três rodadas testando rota por rota
    para descobrir QUAL falhava, porque a tela não dizia e o servidor não
    registrava. O `Decimal` que eu achei era real, mas o erro continuou depois
    de corrigido — e eu não tinha como saber por quê.

    O que muda:
    - o traceback COMPLETO vai para o log, com o caminho pedido;
    - a tela recebe JSON, então `respostaJSON()` consegue ler e mostrar algo
      melhor que "formato inesperado";
    - o `tipo` da exceção vai na resposta, e ele basta para saber onde olhar.
      **`str(exc)` NÃO vai** — a lição da Z-API: mensagem de exceção carrega
      credencial (lá era a URL inteira), e esta resposta vai para o navegador.
    """
    import traceback
    log.error("erro nao tratado em %s %s" + chr(10) + "%s",
              request.method, request.url.path,
              traceback.format_exc())
    return JSONResponse(status_code=500, content={
        "erro": "erro_interno",
        "tipo": type(exc).__name__,
        "caminho": request.url.path,
        "mensagem": ("Erro interno ao montar esta resposta. O detalhe foi "
                     "registrado no log do servidor.")})
class SecurityHeadersMiddleware:
    """ASGI puro — MESMO motivo do AuthMiddleware: @app.middleware("http")
    (Starlette BaseHTTPMiddleware) bufferiza a resposta e quebraria o SSE
    do copiloto. HSTS de propósito FORA daqui: a app roda tanto local
    (http://127.0.0.1, dev) quanto atrás do Cloudflare Tunnel (https,
    produção) — forçar HSTS quebraria o acesso local."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_com_headers(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"x-frame-options", b"DENY"),
                    (b"x-content-type-options", b"nosniff"),
                ])
            await send(message)

        await self.app(scope, receive, send_com_headers)


app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(auth.AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(auth.router_auth)
app.include_router(auth.router_gestao)
# CRM comercial. Router próprio pelo mesmo motivo do `router_gestao`: são ~30
# rotas, e enfiá-las aqui engordaria o arquivo que duas frentes mexem ao mesmo
# tempo. O acesso é o da tela `crm`, pelo prefixo já presente em `ROTA_TELAS`.
# A rota `GET /api/comercial/crm` (a base do Avacorp, só leitura) continua
# abaixo, no lugar dela — o router só serve os caminhos ABAIXO desse prefixo.
from api.crm.rotas import router as router_crm  # noqa: E402
app.include_router(router_crm)
from api.suporte.rotas import router as router_suporte  # noqa: E402
app.include_router(router_suporte)
from api.equipamentos.rotas import router as router_equipamentos  # noqa: E402
app.include_router(router_equipamentos)
# a raiz do repositorio -- usada por rota que grava arquivo temporario
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"


# ===========================================================================
# PAGINAS DO PAINEL — comprimidas UMA vez, e com 304 de verdade
#
# O `index.html` tem 2,5 MB, e ate 06/09/2026 cada carregamento pagava DUAS
# contas que ninguem enxergava com um usuario so:
#
# 1. O `GZipMiddleware` recomprimia o arquivo INTEIRO, no nivel 9, A CADA
#    REQUISICAO: 206 ms medidos, contra 19,5 ms sem compressao. Como isso
#    acontece no processo unico do uvicorn, 20 pessoas abrindo o painel juntas
#    levaram 3,46 s e saturaram 95% de UM nucleo (a maquina tem 28) — e toda
#    chamada de API no intervalo ficou 2,8x mais lenta (`/api/health` de
#    60,5 ms para 169,9 ms, medido nesta bancada em 06/09/2026).
#
# 2. O navegador NUNCA conseguia revalidar. O `FileResponse` EMITE o `ETag`,
#    mas quem implementa requisicao condicional no Starlette e o `StaticFiles`
#    — por isso `/static/vendor/echarts.min.js` devolvia 304 e a pagina, com o
#    MESMO ETag de volta em `If-None-Match`, devolvia 200 com 712 KB. Todo F5
#    de todo mundo rebaixava a pagina inteira.
#
# A correcao e uma so para as duas: comprimir UMA vez, guardar os bytes e
# responder 304 quando o navegador ja tem a versao. Custa 89 ms uma unica vez
# (a primeira requisicao depois de cada deploy) e ~0 ms depois.
#
# A CHAVE E (mtime, tamanho) DO ARQUIVO, e nao o boot do processo. O AutoDeploy
# reinicia a API a cada deploy, entao guardar "por processo" quase sempre
# bastaria — ate o dia em que alguem editasse o `index.html` na arvore sem
# reiniciar, que e coisa que ACONTECE aqui (o frontend e servido do disco, de
# proposito). Com a chave no arquivo, a requisicao seguinte ja ve o novo. O
# `stat()` custa microssegundos.
#
# O `Content-Encoding: gzip` sai daqui, e e ele que faz o `GZipMiddleware`
# deixar a resposta passar intacta em vez de comprimir tudo de novo.
# ===========================================================================

_PAGINAS: dict[Path, dict] = {}
_TRAVA_PAGINAS = threading.Lock()
_HTML = "text/html; charset=utf-8"


def _pagina(caminho: Path) -> dict:
    """Os bytes prontos desta pagina: crus, comprimidos, com ETag e data.

    A TRAVA NAO E ZELO. Sem ela, o primeiro pico depois de um deploy comprime
    2,5 MB uma vez POR REQUISICAO simultanea — exatamente a tempestade que esta
    funcao existe para acabar. Mesma forma do voo unico do `queries.cached`:
    confere, tranca, CONFERE DE NOVO (quem esperou na fila costuma achar o
    trabalho ja feito).
    """
    st = caminho.stat()
    chave = (st.st_mtime_ns, st.st_size)
    pronta = _PAGINAS.get(caminho)
    if pronta is not None and pronta["chave"] == chave:
        return pronta
    with _TRAVA_PAGINAS:
        pronta = _PAGINAS.get(caminho)
        if pronta is not None and pronta["chave"] == chave:
            return pronta
        cru = caminho.read_bytes()
        pronta = {
            "chave": chave,
            "cru": cru,
            # NIVEL 9 porque o custo e pago UMA vez, e quem sente o tamanho e
            # quem abre o painel no 4G: 712 KB contra 723 KB no nivel 5.
            "gz": gzip.compress(cru, 9),
            # ETag DO CONTEUDO, nao do mtime: `git checkout` mexe no mtime sem
            # mudar um byte, e um ETag de mtime reenviaria a pagina inteira
            # para todo mundo a cada deploy que nem tocou nela.
            "etag": '"%s"' % hashlib.md5(cru, usedforsecurity=False).hexdigest(),
            "mtime": int(st.st_mtime),
            "modificado_em": formatdate(st.st_mtime, usegmt=True),
        }
        _PAGINAS[caminho] = pronta
        return pronta


def _ja_tem(req: Request, p: dict) -> bool:
    """O navegador ja tem esta versao?

    `If-None-Match` tem precedencia sobre `If-Modified-Since` (RFC 9110), e um
    ETag pode voltar marcado como fraco (`W/"..."`) — o Cloudflare faz isso
    quando mexe na compressao no caminho. Ignorar o `W/` compararia a marca
    junto com o ETag e nunca daria 304 em producao, que e onde ele importa.
    """
    inm = req.headers.get("if-none-match")
    if inm:
        if inm.strip() == "*":
            return True
        return any(t.strip().removeprefix("W/") == p["etag"]
                   for t in inm.split(","))
    ims = req.headers.get("if-modified-since")
    if ims:
        try:
            return int(parsedate_to_datetime(ims).timestamp()) >= p["mtime"]
        except (TypeError, ValueError):
            return False
    return False


def _servir(caminho: Path, req: Request, tipo: str) -> Response:
    p = _pagina(caminho)
    cab = {
        # O painel muda toda semana, entao o navegador REVALIDA sempre. O que
        # mudou nao foi isso: e que agora revalidar custa um cabecalho em vez
        # de 712 KB.
        "Cache-Control": "no-cache, must-revalidate",
        "ETag": p["etag"],
        "Last-Modified": p["modificado_em"],
        "Vary": "Accept-Encoding",
    }
    if _ja_tem(req, p):
        # sem `media_type` de proposito: 304 nao leva corpo, e o Starlette ja
        # omite o `content-length` para este codigo.
        return Response(status_code=304, headers=cab)
    if "gzip" in req.headers.get("accept-encoding", ""):
        cab["Content-Encoding"] = "gzip"
        return Response(p["gz"], media_type=tipo, headers=cab)
    return Response(p["cru"], media_type=tipo, headers=cab)


@app.get("/")
def index(req: Request) -> Response:
    return _servir(STATIC / "index.html", req, _HTML)


# ===========================================================================
# RASTREIO PUBLICO DE CARGA — "Onde esta minha carga?"
#
# A UNICA parte do CORTEX que responde a quem nao tem conta. A excecao e
# deliberada: quem despachou e quem recebe a mercadoria nao sao usuarios do
# sistema, e obrigar cadastro para saber se a carga chegou empurraria todo
# mundo para o telefone do SAC.
#
# Estas rotas estao em `auth._PUBLICAS_RASTREIO`. Quem segura a porta e o
# modulo `api/rastreio`, nao o middleware — leia o docstring dele antes de
# acrescentar qualquer campo ao retorno.
# ===========================================================================
def _ip_do_cliente(req: Request) -> str:
    """O IP de quem chamou, para o freio.

    `Cf-Connecting-IP` PRIMEIRO: o trafego chega pelo tunnel e o socket sempre
    diz 127.0.0.1 — sem este header o freio seria UM balde para a internet
    inteira, e o primeiro visitante consumiria a cota de todos.
    """
    h = req.headers
    return (h.get("cf-connecting-ip")
            or (h.get("x-forwarded-for") or "").split(",")[0].strip()
            or (req.client.host if req.client else "?"))


@app.get("/r")
def rastreio_pagina_curta(req: Request) -> Response:
    """O mesmo `/rastreio`, com o caminho curto que vai no WhatsApp.

    NAO E VAIDADE: o endereco entra numa mensagem que a pessoa le no celular,
    e com o token o link tinha 96 caracteres — tres linhas, um paredao azul que
    ninguem clica. Com `/r` e o token binario ele fica em 59.

    `/rastreio` continua valendo: e o endereco que se digita e que ja foi
    divulgado; quem trocasse um pelo outro quebraria os dois.
    """
    return rastreio_pagina(req)


@app.get("/rastreio")
def rastreio_pagina(req: Request) -> Response:
    return _servir(STATIC / "rastreio.html", req, _HTML)


def _rastreio_freado(req: Request) -> JSONResponse | None:
    """A recusa do freio, ou None quando pode passar.

    RECUSA LEGIVEL E 4xx: 5xx o Cloudflare troca pela pagina dele, e a
    mensagem nunca chega em quem esta esperando a carga.
    """
    from api.rastreio import consulta
    if consulta.freio_livre(_ip_do_cliente(req)):
        return None
    return JSONResponse(status_code=HTTP_RECUSA, content={
        "ok": False,
        "motivo": "Muitas consultas seguidas. Aguarde alguns minutos."})


# ---------------------------------------------------------------------------
# MONITORAMENTOS DE CARGA — o painel de administracao do rastreio.
#
# O OUTRO LADO DO BALCAO PUBLICO. Quem se inscreve na pagina de rastreio nao
# tem conta, e por isso nada do que acontece ali aparecia aqui dentro: quantas
# pessoas acompanham uma carga agora, quantas foram avisadas, quem cancelou e
# por que. Estas rotas sao AUTENTICADAS e com RBAC por tela (`mon`) — e o
# prefixo e `/api/monitoramentos`, fora de `/api/rastreio/*`, de proposito:
# aquele prefixo tem excecoes publicas em `auth._PUBLICAS_RASTREIO`, e uma
# tela de administracao nao pode fazer vizinhanca com elas.
# ---------------------------------------------------------------------------
@app.get("/api/monitoramentos")
def monitoramentos(dias: int = 14) -> JSONResponse:
    from api.rastreio import painel
    return JSONResponse(painel.painel(dias))


@app.post("/api/monitoramentos/encerrar")
async def monitoramentos_encerrar(req: Request) -> JSONResponse:
    """Encerra uma inscricao pela tela. AUDITORIA ANTES DA ACAO."""
    from api.rastreio import painel
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict) or not body.get("id"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe a inscricao."})
    auth.audit(quem, "monitoramento_encerrar", str(body.get("id")))
    r = await sem_travar(painel.encerrar, body["id"], quem)
    if not r.get("ok"):
        # RECUSA LEGIVEL E 4xx: "ja encerrada" nao e falha nossa, e um 5xx
        # aqui viraria a pagina do Cloudflare no lugar da mensagem.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "recusado", "mensagem": r.get("motivo") or "nao foi possivel"})
    return JSONResponse(r)


@app.get("/api/rastreio/buscar")
def rastreio_buscar(req: Request, doc: str = "",
                    cnpj: str = "") -> JSONResponse:
    from api.rastreio import consulta
    return _rastreio_freado(req) or JSONResponse(consulta.buscar(doc, cnpj))


@app.get("/api/rastreio/carga")
def rastreio_carga(req: Request, doc: str = "", cnpj: str = "",
                   id: str = "") -> JSONResponse:
    from api.rastreio import detalhe
    return _rastreio_freado(req) or JSONResponse(detalhe.obter(doc, cnpj, id))


@app.get("/api/rastreio/link")
def rastreio_link(req: Request, t: str = "") -> JSONResponse:
    """Abre a carga direto pelo link assinado que foi no WhatsApp.

    O token chega aqui pelo JAVASCRIPT da pagina, lido do FRAGMENTO da URL
    (`#c=`), e nao pelo endereco que o navegador pede: o que vem depois do `#`
    nao sai do aparelho. Assim o token de uma carga de cliente nao fica gravado
    no log de acesso do Cloudflare nem no nosso.
    """
    from api.rastreio import detalhe
    return _rastreio_freado(req) or JSONResponse(detalhe.por_link(t))


@app.post("/api/rastreio/assinar")
def rastreio_assinar(req: Request, doc: str = "", cnpj: str = "",
                     id: str = "", fone: str = "", janela: str = "",
                     cadencia: str = "") -> JSONResponse:
    """Passa a avisar um telefone sobre uma carga.

    ESCRITA VINDA DA INTERNET, sem conta e sem login — o modulo
    `api/rastreio/assinatura.py` explica as quatro contencoes. O freio da busca
    vale aqui tambem: sem ele, o mesmo IP tentaria pares de quatro digitos ate
    achar uma carga para a qual inscrever um numero.

    `janela` e `cadencia` sao NOMES do catalogo do modulo, nunca horas: quem
    resolve o que "de manha" significa e o servidor, contra a configuracao da
    casa — a escolha do cliente so RESTRINGE a janela geral, nunca a amplia.
    E os dois vao DECLARADOS na assinatura porque o FastAPI descarta query
    param que a rota nao declara, calado.
    """
    from api.rastreio import assinatura
    freado = _rastreio_freado(req)
    if freado:
        return freado
    return JSONResponse(assinatura.inscrever(doc, cnpj, id, fone,
                                             _ip_do_cliente(req),
                                             janela=janela, cadencia=cadencia))


@app.post("/api/rastreio/cancelar")
def rastreio_cancelar(req: Request, doc: str = "", cnpj: str = "",
                      id: str = "", fone: str = "") -> JSONResponse:
    """Para de avisar. SAIR E MAIS FACIL QUE ENTRAR, de proposito: opt-out
    dificil nao reduz cancelamento — vira bloqueio do numero da empresa, e ai
    todos os outros clientes param de receber tambem."""
    from api.rastreio import assinatura
    freado = _rastreio_freado(req)
    if freado:
        return freado
    return JSONResponse(assinatura.cancelar(doc, cnpj, id, fone))


@app.post("/api/rastreio/zap")
async def rastreio_zap(req: Request) -> JSONResponse:
    """Webhook de entrada do WhatsApp — hoje so a palavra SAIR.

    SEMPRE 200, mesmo quando ignora: erro aqui faz a Z-API reenfileirar a mesma
    mensagem, e a segunda tentativa encontraria a inscricao ja cancelada.
    """
    from api.rastreio import entrada
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": True, "acao": "corpo_invalido"})
    if not isinstance(corpo, dict):
        return JSONResponse({"ok": True, "acao": "corpo_invalido"})
    # I/O BLOQUEANTE EM ROTA ASYNC PASSA POR `sem_travar`: sem isso o envio da
    # confirmacao seguraria o servidor INTEIRO pelo tempo da chamada a Z-API.
    return JSONResponse(await sem_travar(
        entrada.receber, corpo, req.headers.get("x-cortex-token")))


# ===========================================================================
# APP DO MOTORISTA — a operacao DELE, no celular dele.
#
# Escopo e fases: `docs/APP_MOTORISTA.md`. O contrato do modulo (o que sai, o
# que nao sai, e por que a identidade e separada) esta em
# `api/motorista/__init__.py` — LEIA antes de acrescentar rota aqui.
#
# ESTAS ROTAS SAO PUBLICAS PARA O MIDDLEWARE E GUARDADAS NO MODULO. O
# middleware do painel so sabe validar cookie de painel e responderia 401 a uma
# sessao de motorista valida; quem recusa e `sessao.exigir()`, que LEVANTA.
#
# **Rota nova aqui sem `_eu(req)` e rota aberta ao mundo.** A falha e MUDA — a
# rota funciona, devolve o dado certo, e nao pergunta quem esta lendo. Ha teste
# varrendo `/api/motorista/*` e cobrando o guard.
# ===========================================================================
def _mot_recusa(mensagem: str, *, status: int = HTTP_RECUSA) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"erro": "recusa", "mensagem": mensagem})


async def _corpo_json(req: Request) -> dict:
    """O corpo, ou `{}` — nunca uma excecao.

    Um `await req.json()` cru levanta em corpo vazio e em corpo que nao e
    objeto, e isso viraria 500 numa rota publica; a rota tem de RECUSAR pelo
    conteudo que faltou ("escolha um assunto"), nao explodir pela forma. As
    tres rotas de entrada ja faziam isto a mao, cada uma com o seu try — este
    e o mesmo codigo num lugar so.
    """
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    return corpo if isinstance(corpo, dict) else {}


def _eu(req: Request) -> dict:
    """A sessao do motorista desta requisicao. Levanta `SemSessao`."""
    from api.motorista import sessao as msessao
    return msessao.exigir(req)


@app.get("/api/aplicativos")
def aplicativos_lista(req: Request) -> JSONResponse:
    """Os aplicativos da casa, para a tela `apps`.

    A BASE VEM DE QUEM PEDIU, e nao de configuracao: o CORTEX responde por mais
    de um caminho ao mesmo tempo (o tunel Cloudflare, o ngrok ao lado dele e o
    `127.0.0.1` da bancada). Um endereco fixo aqui faria a pessoa copiar um
    link que nao e o dela -- e o link do rastreio existe para ser copiado.

    `X-Forwarded-Proto` primeiro porque atras do tunel o socket sempre diz
    `http`, e um QR com `http://` nao abre no celular de ninguem.
    """
    from api import aplicativos
    h = req.headers
    esquema = h.get("x-forwarded-proto") or req.url.scheme
    host = h.get("x-forwarded-host") or h.get("host") or req.url.netloc
    return JSONResponse({"aplicativos": aplicativos.listar(f"{esquema}://{host}")})


@app.get("/motorista")
def motorista_pagina() -> FileResponse:
    return FileResponse(STATIC / "motorista.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.post("/api/motorista/entrar")
async def motorista_entrar(req: Request) -> JSONResponse:
    """Pede o codigo. RESPONDE IGUAL para numero que existe e que nao existe.

    Inclusive quando o envio falha e quando o freio corta — a resposta unica e
    o que impede esta rota de virar uma maquina de descobrir quem dirige para
    esta empresa. `entrada.pedir` explica as cinco contencoes.

    `sem_travar` porque a ida a Z-API e I/O BLOQUEANTE numa rota `async`: sem
    ele, o servidor INTEIRO para pelo tempo da chamada ao fornecedor.
    """
    from api.motorista import entrada as ment
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    if not isinstance(corpo, dict):
        corpo = {}
    return JSONResponse(await sem_travar(
        ment.pedir, str(corpo.get("telefone") or ""),
        ip=_ip_do_cliente(req)))


@app.post("/api/motorista/confirmar")
async def motorista_confirmar(req: Request) -> JSONResponse:
    """Confere o codigo e abre a sessao.

    Devolve `{"escolher": [...]}` — 200, nao recusa — quando o telefone serve a
    mais de um motorista. Sao 5 casos em 585 medidos, e nesse caminho o codigo
    NAO e consumido: a pessoa acabou de prova-lo.
    """
    from api.motorista import entrada as ment
    from api.motorista import sessao as msessao
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    if not isinstance(corpo, dict):
        corpo = {}
    try:
        r = await sem_travar(
            ment.confirmar, str(corpo.get("telefone") or ""),
            str(corpo.get("codigo") or ""),
            aparelho=str(corpo.get("aparelho") or ""),
            motorista=str(corpo.get("motorista") or ""),
            ip=_ip_do_cliente(req),
            agente=req.headers.get("user-agent", ""))
    except ment.Recusa as exc:
        return _mot_recusa(str(exc))
    if r.get("escolher"):
        return JSONResponse(r)

    # A TRILHA GRAVA O ID OPACO, nunca o codigo do ERP — que para pessoa fisica
    # e o CPF. `audit_log` e append-only e imutavel: documento que entra ali nao
    # sai mais.
    quem = "motorista:%d" % r["motorista_id"]
    auth.audit(quem, "motorista_entrou", alvo=str(r["motorista_id"]),
               detalhe=f"sessao {r['sessao_id']}", ip=_ip_do_cliente(req))
    # O TOKEN NAO VAI NO CORPO: ele e o cookie, e cookie HttpOnly e o que
    # impede um script na pagina de ler a sessao. Devolver os dois seria
    # oferecer a copia legivel do que se acabou de proteger.
    resp = JSONResponse({"ok": True, "nome": r["nome"]})
    msessao.gravar_cookie(resp, r["token"], req)
    return resp


@app.get("/api/motorista/eu")
def motorista_eu(req: Request) -> JSONResponse:
    """Quem esta logado, se e sessao mestre, e o que ele TEM para ver.

    `secoes` existe por causa de uma regra do escopo: **item que nao existe
    para o agregado nao aparece vazio, some.** Dois tercos dos motoristas sao
    agregados e nunca terao jornada apurada (a RasterJOR cobre o empregado);
    uma aba que abre e diz "sem dados" para quem nunca vai ter dado ensina a
    pessoa a nao confiar no resto da tela.

    A conferencia e uma consulta local de uma linha e nao pode derrubar o
    login: sem ela a aba fica de fora, que e a degradacao certa.
    """
    from api.motorista import sessao as msessao
    try:
        sess = _eu(req)
    except msessao.SemSessao:
        return _mot_recusa("Faca login para continuar.", status=401)
    return JSONResponse({"nome": sess["nome"],
                         "telefone": sess["telefone"],
                         # A TARJA DEPENDE DISTO. Sem a marca chegando a
                         # pagina, quem administra esquece em que conta esta.
                         "mestre": bool(sess.get("mestre")),
                         "secoes": _mot_secoes(sess),
                         # A MARCA DE RECADO NOVO. Vem no boot porque e ela que
                         # faz o motorista ABRIR a aba do RH — sem isso, a
                         # resposta fica esperando ate ele passar por ali por
                         # acaso, e o canal vira o que o escopo temia.
                         "avisos": _mot_avisos(sess)})


def _mot_secoes(sess: dict) -> dict:
    """Que abas o app desenha para ESTE motorista."""
    from api.motorista import jornada as mjor
    tem_jornada = False
    try:
        tem_jornada = mjor.tem_apuracao(sess)
    except Exception as exc:  # noqa: BLE001
        log.info("secoes do motorista: jornada indisponivel (%s)",
                 type(exc).__name__)
    # As outras valem para TODO motorista: "nenhuma multa sua" e "nenhuma
    # ocorrencia" sao boa noticia, nao tela vazia — ao contrario da jornada,
    # que para o agregado e ausencia permanente. O canal do RH vale para todos
    # pelo mesmo motivo: falar com o RH nao depende de ja ter falado.
    return {"viagem": True, "produtividade": True, "desempenho": True,
            "multas": True, "ocorrencias": True, "jornada": tem_jornada,
            "conversas": True}


def _mot_avisos(sess: dict) -> dict:
    """Quantos recados esperam por ele. Uma consulta local, e ela NAO derruba
    o login: sem o numero a bolinha nao aparece, que e a degradacao certa."""
    from api.motorista import conversas as mconv
    from api.motorista import mural as mmural
    try:
        d = mconv.minhas(sess)
        n = int(d["nao_lidas"]) + int(d["pendencias"])
    except Exception as exc:  # noqa: BLE001
        log.info("avisos do motorista indisponiveis (%s)", type(exc).__name__)
        return {}
    try:
        # O COMUNICADO CONTA NA MESMA BOLINHA: para quem le, "tem coisa do RH
        # esperando" e uma so — dois avisos separados na mesma aba obrigariam
        # o motorista a aprender a diferenca entre mural e fila antes de
        # entender o que fazer.
        n += int(mmural.meus(sess)["pendentes"])
    except Exception as exc:  # noqa: BLE001
        log.info("mural indisponivel para o aviso (%s)", type(exc).__name__)
    return {"conversas": n}


@app.post("/api/motorista/sair")
def motorista_sair(req: Request) -> JSONResponse:
    """Sair NUNCA falha por falta de sessao: quem clicou ja quer estar fora, e
    um 401 aqui deixaria o cookie no aparelho de quem pediu para sair."""
    from api.motorista import sessao as msessao
    try:
        sess = _eu(req)
    except msessao.SemSessao:
        sess = None
    if sess:
        msessao.encerrar(sess["sessao_id"])
        auth.audit("motorista:%d" % sess["motorista_id"], "motorista_saiu",
                   alvo=str(sess["motorista_id"]), ip=_ip_do_cliente(req))
    resp = JSONResponse({"ok": True})
    msessao.apagar_cookie(resp, req)
    return resp


@app.get("/api/motorista/viagem")
def motorista_viagem(req: Request) -> JSONResponse:
    from api.motorista import sessao as msessao
    from api.motorista import viagem as mviagem
    try:
        sess = _eu(req)
    except msessao.SemSessao:
        return _mot_recusa("Faca login para continuar.", status=401)
    try:
        return JSONResponse(mviagem.minha(sess))
    except Exception as exc:  # noqa: BLE001
        # O ERP e replica de producao de TERCEIRO e ja teve manha ruim. O
        # cache com ultima leitura boa cobre a maior parte; passado o prazo
        # dele, a recusa aqui e LEGIVEL e 4xx — 5xx o Cloudflare troca pela
        # pagina dele e o motorista ve um erro que nao diz nada.
        log.warning("viagem do motorista falhou: %s", type(exc).__name__)
        return _mot_recusa("Nao consegui falar com o sistema agora. "
                           "Tente de novo em alguns minutos.")


def _mot_ler(req: Request, carregar, assunto: str) -> JSONResponse:
    """A forma de TODA rota de leitura do app, em um lugar só.

    As cinco telas novas (multas, desempenho, ocorrencias, produtividade,
    jornada) fazem exatamente a mesma coisa: exigem a sessao, chamam uma
    funcao que recebe a sessao, e degradam em RECUSA LEGIVEL quando a fonte
    cai. Escrever isso cinco vezes seria cinco chances de uma delas esquecer o
    `_eu(req)` — que e a falha MUDA deste modulo (a rota funciona, devolve o
    dado certo, e nao pergunta quem esta lendo).

    O 4xx aqui nao e preciosismo: 5xx o Cloudflare troca pela pagina dele e o
    motorista ve um erro que nao diz nada. E o `except` e largo de proposito —
    o ERP e replica de producao de TERCEIRO e ja teve manha ruim; quem cobre a
    maior parte disso e o cache com ultima leitura boa, e esta e a rede de
    baixo.
    """
    from api.motorista import sessao as msessao
    try:
        sess = _eu(req)
    except msessao.SemSessao:
        return _mot_recusa("Faca login para continuar.", status=401)
    try:
        return JSONResponse(carregar(sess))
    except Exception as exc:  # noqa: BLE001
        log.warning("%s do motorista falhou: %s", assunto, type(exc).__name__)
        return _mot_recusa("Nao consegui carregar isto agora. "
                           "Tente de novo em alguns minutos.")


@app.get("/api/motorista/multas")
def motorista_multas(req: Request) -> JSONResponse:
    from api.motorista import multas as mmultas
    return _mot_ler(req, mmultas.minhas, "multas")


@app.get("/api/motorista/desempenho")
def motorista_desempenho(req: Request) -> JSONResponse:
    from api.motorista import desempenho as mdesemp
    return _mot_ler(req, mdesemp.meu, "desempenho")


@app.get("/api/motorista/ocorrencias")
def motorista_ocorrencias(req: Request) -> JSONResponse:
    from api.motorista import ocorrencias as mocor
    return _mot_ler(req, mocor.minhas, "ocorrencias")


@app.get("/api/motorista/produtividade")
def motorista_produtividade(req: Request) -> JSONResponse:
    from api.motorista import produtividade as mprod
    return _mot_ler(req, mprod.minha, "produtividade")


@app.get("/api/motorista/jornada")
def motorista_jornada(req: Request) -> JSONResponse:
    from api.motorista import jornada as mjor
    return _mot_ler(req, mjor.minha, "jornada")


# ------------------------------------------------------- o canal com o RH
#
# A PRIMEIRA COISA DESTE APP EM QUE O NAVEGADOR MANDA UM ID DE LINHA. Ate aqui
# todo escopo saia da sessao e nao havia o que forjar; agora ha. A defesa nao
# esta nestas rotas e sim em `conversas._minha()`, que poe o
# `motorista_codigo` da SESSAO na clausula WHERE junto do id — nunca uma busca
# por id seguida de um `if` conferindo o dono. As duas formas parecem iguais e
# nao sao: o `if` e a linha que alguem apaga numa refatoracao, e o sintoma e
# ler a conversa de outra pessoa.

def _mot_escrever(req: Request, acao, assunto: str, corpo: dict) -> JSONResponse:
    """Rota de ESCRITA do app: sessao, recusa legivel, e trilha SEMPRE.

    A auditoria vem ANTES de qualquer coisa externa (regra da casa) e depois da
    gravacao — o que se registra e o que aconteceu, nao o que se pretendia.
    """
    from api.motorista import conversas as mconv
    from api.motorista import mural as mmural
    from api.motorista import sessao as msessao
    try:
        sess = _eu(req)
    except msessao.SemSessao:
        return _mot_recusa("Faca login para continuar.", status=401)
    try:
        r = acao(sess, corpo)
    # AS DUAS: `mural.Recusa` e outra classe, e com so a do canal aqui uma
    # recusa LEGIVEL viraria "nao consegui salvar" generico.
    except (mconv.Recusa, mmural.Recusa) as exc:
        return _mot_recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("%s do motorista falhou: %s", assunto, type(exc).__name__)
        return _mot_recusa("Nao consegui salvar agora. Tente de novo.")
    auth.audit("motorista:%d" % sess["motorista_id"], "motorista_" + assunto,
               alvo=str(r.get("id") or r.get("conversa_id") or ""),
               ip=_ip_do_cliente(req))
    return JSONResponse(r)


@app.get("/api/motorista/conversas")
def motorista_conversas(req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    return _mot_ler(req, mconv.minhas, "conversas")


@app.get("/api/motorista/conversas/{cid}")
def motorista_conversa(cid: int, req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    from api.motorista import sessao as msessao
    try:
        sess = _eu(req)
    except msessao.SemSessao:
        return _mot_recusa("Faca login para continuar.", status=401)
    try:
        return JSONResponse(mconv.ler(sess, cid))
    except mconv.Recusa as exc:
        return _mot_recusa(str(exc), status=404)
    except Exception as exc:  # noqa: BLE001
        log.warning("conversa do motorista falhou: %s", type(exc).__name__)
        return _mot_recusa("Nao consegui carregar isto agora.")


@app.post("/api/motorista/conversas")
async def motorista_conversa_abrir(req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    corpo = await _corpo_json(req)
    return _mot_escrever(
        req, lambda s, c: mconv.abrir(s, str(c.get("assunto") or ""),
                                      str(c.get("texto") or "")),
        "conversa_abriu", corpo)


@app.post("/api/motorista/conversas/{cid}/mensagem")
async def motorista_conversa_mensagem(cid: int, req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    corpo = await _corpo_json(req)
    return _mot_escrever(
        req, lambda s, c: mconv.responder(s, cid, str(c.get("texto") or "")),
        "conversa_respondeu", corpo)


@app.get("/api/motorista/mural")
def motorista_mural(req: Request) -> JSONResponse:
    """Os comunicados DELE. Separado das conversas de proposito: o mural nao
    tem fila, nao tem dono e nao se responde — ver `api/motorista/mural.py`."""
    from api.motorista import mural as mmural
    return _mot_ler(req, mmural.meus, "mural")


@app.post("/api/motorista/mural/{cid}/visto")
async def motorista_mural_visto(cid: int, req: Request) -> JSONResponse:
    """Ele ABRIU. Nao e ciencia — e por isso que sao dois campos: "viu e nao
    confirmou" e "nunca abriu" sao duas conversas diferentes com a pessoa."""
    from api.motorista import mural as mmural
    return _mot_escrever(req, lambda s, c: mmural.marcar_visto(s, cid),
                         "mural_viu", await _corpo_json(req))


@app.post("/api/motorista/mural/{cid}/ciencia")
async def motorista_mural_ciencia(cid: int, req: Request) -> JSONResponse:
    from api.motorista import mural as mmural
    return _mot_escrever(req, lambda s, c: mmural.dar_ciencia(s, cid),
                         "mural_ciencia", await _corpo_json(req))


@app.post("/api/motorista/conversas/{cid}/ciencia")
async def motorista_conversa_ciencia(cid: int, req: Request) -> JSONResponse:
    """"Li e entendi" num comunicado. E o unico botao do app que registra uma
    AFIRMACAO do motorista sobre um documento da empresa — por isso ele tem
    trilha propria e vira mensagem de sistema, com data, na conversa."""
    from api.motorista import conversas as mconv
    corpo = await _corpo_json(req)
    return _mot_escrever(req, lambda s, c: mconv.dar_ciencia(s, cid),
                         "conversa_ciencia", corpo)


# --------------------------------------------------------- o acesso mestre
#
# AS DUAS ROTAS ABAIXO SAO A SEGUNDA EXCECAO DESTE MODULO (a primeira sao as
# de entrada): elas respondem SEM sessao, porque sao o caminho de abrir uma.
# Quem recusa nelas e `mestre.conferir()`, que LEVANTA — e o teste
# `test_toda_rota_do_app_exige_sessao` cobra a lista, entao acrescentar uma
# rota aqui exige escrever a razao la tambem.
#
# O contrato inteiro (as seis contencoes, e por que "nao configurado" nao e
# falha) esta em `api/motorista/mestre.py`.

@app.post("/api/motorista/mestre/motoristas")
async def motorista_mestre_lista(req: Request) -> JSONResponse:
    """Quem se pode abrir. NAO ABRE SESSAO NENHUMA, e devolve so id e nome.

    O `motorista_codigo` e o CPF para pessoa fisica e esta lista vai para um
    navegador — a mesma disciplina da lista de escolha da entrada.
    """
    from api.motorista import mestre as mm
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    if not isinstance(corpo, dict):
        corpo = {}
    try:
        await sem_travar(mm.conferir, str(corpo.get("codigo") or ""),
                         ip=_ip_do_cliente(req))
        return JSONResponse(await sem_travar(
            mm.motoristas, str(corpo.get("busca") or "")))
    except mm.Recusa as exc:
        return _mot_recusa(str(exc))


@app.post("/api/motorista/mestre/entrar")
async def motorista_mestre_entrar(req: Request) -> JSONResponse:
    """Abre a sessao MESTRE na conta do motorista escolhido.

    O codigo e conferido DE NOVO aqui, e nao so na listagem: sao duas rotas
    independentes, e uma que confiasse na anterior seria uma rota que abre
    sessao sem segredo nenhum para quem chamar direto.
    """
    from api.motorista import mestre as mm
    from api.motorista import sessao as msessao
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    if not isinstance(corpo, dict):
        corpo = {}
    try:
        await sem_travar(mm.conferir, str(corpo.get("codigo") or ""),
                         ip=_ip_do_cliente(req))
        r = await sem_travar(
            mm.abrir, int(corpo.get("motorista") or 0),
            aparelho=str(corpo.get("aparelho") or ""),
            ip=_ip_do_cliente(req), agente=req.headers.get("user-agent", ""))
    except mm.Recusa as exc:
        return _mot_recusa(str(exc))
    except (TypeError, ValueError):
        return _mot_recusa("Escolha um motorista.")

    # A TRILHA DISTINGUE AS DUAS ENTRADAS. Se a mestre gravasse
    # `motorista_entrou` como a outra, a auditoria de uso do app viraria
    # ficcao — "300 acessos" com metade sendo a mesma pessoa conferindo.
    auth.audit("motorista:mestre", "motorista_mestre_entrou",
               alvo=str(r["motorista_id"]),
               detalhe=f"sessao {r['sessao_id']} · {mm.TTL_HORAS}h",
               ip=_ip_do_cliente(req))
    resp = JSONResponse({"ok": True, "nome": r["nome"], "mestre": True})
    msessao.gravar_cookie(resp, r["token"], req, horas=mm.TTL_HORAS)
    return resp


# ===========================================================================
# O CANAL DO RH — o lado de DENTRO (painel), tela `rhmot`.
#
# Estas rotas sao do PAINEL e passam pelo middleware normal: `/api/rh/motorista`
# esta em `ROTA_TELAS` apontando para a tela `rhmot`, entao quem nao tem a tela
# leva 403 antes de chegar aqui. Nada do app do motorista alcanca isto — o
# cookie dele nem e enviado para fora de `/api/motorista`.
#
# A CAIXA ORDENA PELO MAIS PARADO, nao pelo mais recente. E a diferenca entre
# uma fila e uma caixa de e-mail: numa caixa por data, quem escreveu ha tres
# semanas nunca mais e visto — e e exatamente essa pessoa que liga para a torre,
# que e o telefonema que este canal existe para tirar.
# ===========================================================================

def _rh_recusa(mensagem: str, *, status: int = HTTP_RECUSA) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"erro": "recusa", "mensagem": mensagem})


@app.get("/api/rh/motorista/conversas")
def rh_motorista_caixa(req: Request, status: str = "",
                       busca: str = "") -> JSONResponse:
    from api.motorista import conversas as mconv
    try:
        return JSONResponse(mconv.caixa(status, busca))
    except mconv.Recusa as exc:
        return _rh_recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("caixa do RH falhou: %s", type(exc).__name__)
        return _rh_recusa("Nao consegui carregar a caixa agora.")


@app.get("/api/rh/motorista/conversas/{cid}")
def rh_motorista_conversa(cid: int, req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    try:
        return JSONResponse(mconv.ler_rh(cid))
    except mconv.Recusa as exc:
        return _rh_recusa(str(exc), status=404)
    except Exception as exc:  # noqa: BLE001
        log.warning("conversa do RH falhou: %s", type(exc).__name__)
        return _rh_recusa("Nao consegui carregar a conversa agora.")


@app.get("/api/rh/motorista/motoristas")
def rh_motorista_lista(req: Request, busca: str = "") -> JSONResponse:
    """Para quem o RH pode abrir conversa. **So id opaco e nome.**

    A mesma disciplina da lista do acesso mestre e da escolha da entrada: o
    `motorista_codigo` e o CPF para pessoa fisica, e esta lista vai para um
    navegador.
    """
    from api.motorista import mestre as mm
    try:
        return JSONResponse(mm.motoristas(busca))
    except Exception as exc:  # noqa: BLE001
        log.warning("lista de motoristas do RH falhou: %s", type(exc).__name__)
        return _rh_recusa("Nao consegui carregar a lista agora.")


async def _rh_conversa_escrever(req: Request, acao, evento: str,
                                alvo=None) -> JSONResponse:
    """Escrita do lado do RH: sessao do painel, trilha, e o aviso DEPOIS.

    A ORDEM E A REGRA DA CASA: grava, audita, e so entao sai para o mundo. Se o
    WhatsApp falhar, a resposta continua existindo no app e o motorista a le
    quando abrir; o contrario deixaria um aviso apontando para uma resposta que
    nao existe.
    """
    from api.motorista import conversas as mconv
    from api.motorista import mural as mmural
    sess = req.scope.get("state", {}).get("sessao") or {}
    autor = sess.get("nome") or sess.get("email") or ""
    try:
        r = await sem_travar(acao, sess.get("id"), autor)
    # AS DUAS RECUSAS, e nao so a do canal. `mural.Recusa` e outra classe: com
    # so a de `conversas` aqui, "Escreva um titulo." cairia no `except
    # Exception` de baixo e chegaria ao RH como "Nao consegui salvar agora" —
    # uma recusa LEGIVEL virando erro generico, que e o oposto do que o
    # HTTP_RECUSA da casa existe para fazer.
    except (mconv.Recusa, mmural.Recusa) as exc:
        return _rh_recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        log.warning("%s do RH falhou: %s", evento, type(exc).__name__)
        return _rh_recusa("Nao consegui salvar agora. Tente de novo.")
    auth.audit(autor or "rh", evento,
               alvo=str(alvo if alvo is not None else r.get("id") or ""),
               ip=_ip_do_cliente(req))
    return JSONResponse(r)


async def _avisar_motorista(conversa_id: int) -> dict:
    """Manda o aviso de que ha resposta. NUNCA levanta, NUNCA abre a janela.

    `entrada.py` abre a janela de horario de proposito — codigo de entrada e
    resposta a alguem com o celular na mao as 03:40. **Aqui e o contrario e a
    janela FICA**: resposta do RH e mensagem de empresa, que e exatamente o que
    a janela existe para conter. Aviso de ferias as 3 da manha e a denuncia que
    faz o numero da casa ser banido — e o motorista perderia junto o canal que a
    torre usa.

    O texto NAO leva o conteudo nem o assunto: o que o RH escreveu pode ser
    sobre salario, saude ou desligamento, e WhatsApp e lido em tela de bloqueio,
    muitas vezes num aparelho compartilhado (medido: 5 dos 585 motoristas
    dividem o numero). O canal tem o conteudo; o aviso so diz que ele existe.
    """
    from api.motorista import conversas as mconv
    from api.whatsapp import envio as wa
    try:
        fone, _nome = mconv.telefone_de(conversa_id)
        if not fone:
            return {"ok": False, "erro": "sem telefone"}
        return await sem_travar(wa.enviar, fone, mconv.AVISO,
                                usuario="rh-canal-motorista",
                                origem="motorista_conversa")
    except Exception as exc:  # noqa: BLE001
        # O aviso e ENFEITE do canal: a resposta ja esta gravada e o motorista
        # a ve ao abrir o app. Derrubar a resposta do RH por causa do WhatsApp
        # seria trocar o essencial pelo acessorio.
        log.warning("aviso do canal do RH nao saiu: %s", type(exc).__name__)
        return {"ok": False, "erro": type(exc).__name__}


@app.post("/api/rh/motorista/conversas")
async def rh_motorista_abrir(req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    corpo = await _corpo_json(req)
    resp = await _rh_conversa_escrever(
        req,
        lambda uid, autor: mconv.abrir_rh(
            corpo.get("motorista"), str(corpo.get("assunto") or ""),
            str(corpo.get("titulo") or ""), str(corpo.get("texto") or ""),
            autor_id=uid, autor_nome=autor),
        "rh_conversa_abriu")
    if resp.status_code == 200:
        import json as _json
        await _avisar_motorista(_json.loads(bytes(resp.body))["id"])
    return resp


@app.post("/api/rh/motorista/conversas/{cid}/mensagem")
async def rh_motorista_responder(cid: int, req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    corpo = await _corpo_json(req)
    resp = await _rh_conversa_escrever(
        req,
        lambda uid, autor: mconv.responder_rh(
            cid, str(corpo.get("texto") or ""), autor_id=uid, autor_nome=autor),
        "rh_conversa_respondeu", alvo=cid)
    if resp.status_code == 200:
        await _avisar_motorista(cid)
    return resp


# --------------------------------------------------------------- o mural
#
# UM COMUNICADO PARA TODOS, e nao 300 conversas: `mot_conversas` recusa
# comunicado em massa por escrito porque trezentas linhas de uma vez destroem
# os dois numeros que fazem a caixa ser uma FILA (a ordem por mais parado e o
# "paradas ha 3+ dias"). O mural e o outro objeto — sem fila, sem dono e sem
# resposta —, e na tela ele e UM cartao com uma fracao.

@app.get("/api/rh/motorista/mural")
def rh_mural(req: Request) -> JSONResponse:
    from api.motorista import mural as mmural
    try:
        return JSONResponse(mmural.listar())
    except Exception as exc:  # noqa: BLE001
        log.warning("mural do RH falhou: %s", type(exc).__name__)
        return _rh_recusa("Nao consegui carregar os comunicados agora.")


@app.get("/api/rh/motorista/mural/{cid}/faltam")
def rh_mural_faltam(cid: int, req: Request) -> JSONResponse:
    """Quem ainda nao confirmou. "45 de 80" sem os nomes nao vira acao."""
    from api.motorista import mural as mmural
    try:
        return JSONResponse(mmural.faltam(cid))
    except mmural.Recusa as exc:
        return _rh_recusa(str(exc), status=404)
    except Exception as exc:  # noqa: BLE001
        log.warning("faltam do mural falhou: %s", type(exc).__name__)
        return _rh_recusa("Nao consegui carregar a lista agora.")


@app.post("/api/rh/motorista/mural")
async def rh_mural_publicar(req: Request) -> JSONResponse:
    """Publica para TODOS os motoristas ativos, num so ato.

    NAO HA AVISO EM MASSA POR WHATSAPP, e e decisao de quem opera com o numero
    na mesa: o teto da casa e 60 destinatarios DISTINTOS por dia, e ele protege
    o numero que fala com clientes. Trezentos motoristas seriam cinco dias de
    ondas — e no quinto dia o comunicado ja nao e noticia. Quem avisa e a marca
    no app.
    """
    from api.motorista import mural as mmural
    corpo = await _corpo_json(req)
    return await _rh_conversa_escrever(
        req,
        lambda uid, autor: mmural.publicar(
            str(corpo.get("titulo") or ""), str(corpo.get("texto") or ""),
            autor_id=uid, autor_nome=autor),
        "rh_mural_publicou")


@app.post("/api/rh/motorista/mural/{cid}/encerrar")
async def rh_mural_encerrar(cid: int, req: Request) -> JSONResponse:
    """Para de cobrar ciencia, sem apagar. Um comunicado de marco que segue
    pedindo "li e entendi" ensina a pessoa a ignorar o pedido — inclusive no
    de hoje."""
    from api.motorista import mural as mmural
    return await _rh_conversa_escrever(
        req, lambda uid, autor: mmural.encerrar(cid, autor_nome=autor),
        "rh_mural_encerrou", alvo=cid)


@app.post("/api/rh/motorista/conversas/{cid}/status")
async def rh_motorista_status(cid: int, req: Request) -> JSONResponse:
    from api.motorista import conversas as mconv
    corpo = await _corpo_json(req)
    return await _rh_conversa_escrever(
        req,
        lambda uid, autor: mconv.mudar_status(
            cid, str(corpo.get("status") or ""), autor_nome=autor),
        "rh_conversa_status", alvo=cid)


@app.get("/sw.js")
def service_worker(req: Request) -> Response:
    # servido da RAIZ (não de /static) para o escopo do SW ser "/" — senão
    # navigator.serviceWorker.ready nunca resolve (escopo /static/ não controla /)
    return _servir(STATIC / "sw.js", req, "application/javascript")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/versao")
def versao() -> JSONResponse:
    # exige sessão (não está em auth._PUBLICAS): serve para confirmar, dentro do
    # painel, qual build o AutoDeploy colocou no ar
    try:
        vs = documentacao.versoes()
        data = vs[0]["data"] if vs else ""
    except Exception:  # noqa: BLE001
        data = ""
    return JSONResponse({"versao": VERSAO, "rotulo": ROTULO, "data": data})


@app.get("/api/documentacao")
def doc(request: Request) -> JSONResponse:
    # um erro de digitação no manual.yaml não pode virar 500 sem corpo: o front
    # faz r.json() antes de olhar r.ok, e o usuário veria "não foi possível falar
    # com a API" em vez do motivo real
    sess = request.state.sessao or {}
    # admin enxerga tudo; os demais, só as telas do próprio perfil
    permitidas = None if sess.get("admin") else set(sess.get("telas") or [])
    try:
        return JSONResponse(documentacao.montar(permitidas))
    except Exception as exc:  # noqa: BLE001
        log.exception("documentacao: falha ao montar")
        return JSONResponse(status_code=500, content={
            "mensagem": "Não foi possível montar a documentação.",
            "detalhe": f"{type(exc).__name__}: {exc}"})


@app.get("/api/health")
def health() -> JSONResponse:
    # rota pública (monitoramento pelo túnel): não expor detalhe da exceção,
    # que revela host/porta internos do túnel do ERP a qualquer anônimo.
    try:
        db.query("SELECT 1 AS ok")
        return JSONResponse({"status": "ok", "db": "conectado"})
    except Exception as exc:  # noqa: BLE001
        log.warning("health: banco inacessível: %s", exc)
        return JSONResponse(status_code=503, content={"status": "erro", "db": "sem_conexao"})


@app.get("/api/dre/alavancas")
def dre_alavancas_rota(comp_de: str, comp_ate: str) -> JSONResponse:
    """Onde atacar para virar o resultado — alavancas medidas do periodo."""
    from api import dre_alavancas
    try:
        return JSONResponse(dre_alavancas.calcular(comp_de, comp_ate))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre alavancas falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel calcular as alavancas."})


@app.get("/api/dre/panorama")
def dre_panorama(comp_de: str, comp_ate: str,
                 nivel: str = "conta") -> JSONResponse:
    """Conta a conta: o que melhorou, o que piorou e o que so oscila."""
    from api import dre_alavancas
    try:
        return JSONResponse(dre_alavancas.panorama(comp_de, comp_ate, nivel))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre panorama falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel montar o panorama."})


@app.get("/api/dre/parecer/narrativa")
def dre_parecer_narrativa(comp_de: str, comp_ate: str) -> JSONResponse:
    """A REDACAO do parecer, pelo modelo que roda NESTA maquina.

    Nunca cai para modelo externo, e a diferenca nao e de gosto: o payload tem
    nome de conta, de centro de custo e de fornecedor. O que permite o fallback
    externo do Copiloto e o snapshot dele ser escalar e anonimo; este nao e.
    Sem o modelo, devolve a leitura MEDIDA dizendo que nao houve redacao — a
    tela nunca fica sem parecer por causa do Ollama.
    """
    from api import dre_parecer
    try:
        p = dre_parecer.parecer(comp_de, comp_ate)
        if p.get("erro"):
            return JSONResponse(status_code=HTTP_RECUSA, content={
                "erro": "periodo_curto", "mensagem": p["erro"]})
        return JSONResponse(dre_parecer.narrar(p))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre parecer narrativa falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel redigir o parecer."})


@app.get("/api/dre/parecer")
def dre_parecer_rota(comp_de: str, comp_ate: str) -> JSONResponse:
    """A CAUSA do movimento: recorrente x nao, par espelhado, provisao aberta.

    O ranking ja esta no /panorama; o que esta rota acrescenta e por que cada
    conta se moveu — e se o movimento e gestao ou aritmetica.
    """
    from api import dre_parecer
    try:
        return JSONResponse(dre_parecer.parecer(comp_de, comp_ate))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre parecer falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel montar o parecer."})


# ===========================================================================
# Avaliacao de Desempenho — nine box
#
# QUEM VE TUDO tem `desrh` (tela sem menu). Quem tem so `des` ve a propria
# equipe, e a equipe vem do MAPA do RH — mapa vazio e ver NINGUEM, nunca ver
# todos: abrir a folha inteira por esquecimento de cadastro e defeito que
# continua funcionando, e por isso ninguem descobre.
# ===========================================================================
def _des_quem(req: Request) -> tuple[str, bool]:
    """O e-mail de quem pede e se ele enxerga a casa inteira."""
    sess = getattr(req.state, "sessao", None) or {}
    telas = set(sess.get("telas") or ())
    return (sess.get("email") or "",
            bool(sess.get("admin")) or "desrh" in telas)


@app.get("/api/desempenho/ciclos")
def desempenho_ciclos() -> JSONResponse:
    from api import desempenho
    try:
        return JSONResponse({"linhas": desempenho.ciclos(),
                             "aberto": desempenho.ciclo_aberto()})
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho ciclos falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler os ciclos."})


@app.get("/api/desempenho/matriz")
def desempenho_matriz(ciclo_id: int | None = None,
                      request: Request = None) -> JSONResponse:
    from api import desempenho
    email, tudo = _des_quem(request)
    try:
        c = (desempenho.ciclo_aberto() if not ciclo_id
             else {"id": ciclo_id})
        if not c:
            return JSONResponse({"sem_ciclo": True, "caixas": [],
                                 "pendentes": [], "kpis": {}})
        d = desempenho.matriz(int(c["id"]), email, tudo)
        d["ver_tudo"] = tudo
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho matriz falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel montar a matriz."})


@app.get("/api/desempenho/equipe")
def desempenho_equipe(request: Request = None) -> JSONResponse:
    """Quem este usuario avalia, com a avaliacao ja dada (se houver)."""
    from api import desempenho
    email, tudo = _des_quem(request)
    try:
        c = desempenho.ciclo_aberto()
        time = desempenho.equipe(email, tudo)
        feitas = {int(a["codintfunc"]): a
                  for a in (desempenho.avaliacoes(int(c["id"])) if c else [])}
        linhas = []
        for p in time["linhas"]:
            a = feitas.get(int(p["codintfunc"])) or {}
            linhas.append({**p, "desempenho": a.get("desempenho"),
                           "potencial": a.get("potencial"),
                           "justificativa": a.get("justificativa"),
                           "avaliador": a.get("avaliador")})
        return JSONResponse({"linhas": linhas, "ciclo": c,
                             "alcance": time["alcance"],
                             "sem_escopo": time.get("sem_escopo", False),
                             "ver_tudo": tudo})
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho equipe falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler a equipe."})


@app.post("/api/desempenho/avaliar")
async def desempenho_avaliar(req: Request) -> JSONResponse:
    """Grava a avaliacao de UMA pessoa.

    A AUDITORIA VEM ANTES da resposta e leva as duas notas: a pergunta que
    alguem faz depois e "quem deu essa nota, e quando".
    """
    from api import desempenho
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    if not quem:
        return JSONResponse(status_code=401, content={
            "erro": "sem_sessao",
            "mensagem": "Sessao sem e-mail: nao da para registrar o avaliador."})
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo invalido."})
    try:
        c = desempenho.ciclo_aberto()
        if not c:
            return JSONResponse(status_code=HTTP_RECUSA, content={
                "erro": "sem_ciclo",
                "mensagem": "Nao ha ciclo aberto para avaliacao."})
        pessoa = body.get("pessoa") or {}
        auth.audit(quem, "desempenho_avaliar",
                   str(pessoa.get("nome") or pessoa.get("codintfunc") or "?"),
                   "ciclo %s · desempenho %s · potencial %s" % (
                       c["nome"], body.get("desempenho"), body.get("potencial")))
        r = desempenho.avaliar(
            int(c["id"]), pessoa, int(body.get("desempenho") or 0),
            int(body.get("potencial") or 0), body.get("justificativa") or "",
            quem)
        return JSONResponse({"ok": True, "avaliacao": r})
    except ValueError as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "recusado", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho avaliar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel gravar a avaliacao."})


@app.get("/api/desempenho/gestores")
def desempenho_gestores() -> JSONResponse:
    from api import desempenho
    try:
        return JSONResponse({"linhas": desempenho.mapa_gestores()})
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho gestores falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler o mapa de gestores."})


@app.post("/api/desempenho/gestores/mapear")
async def desempenho_mapear(req: Request) -> JSONResponse:
    from api import desempenho
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo invalido."})
    try:
        if body.get("remover"):
            auth.audit(quem, "desempenho_desmapear", str(body.get("remover")))
            desempenho.desmapear(int(body["remover"]))
            return JSONResponse({"ok": True})
        auth.audit(quem, "desempenho_mapear", str(body.get("email") or ""),
                   "%s %s" % (body.get("escopo_tipo"), body.get("escopo_valor")))
        return JSONResponse({"ok": True, "gestor": desempenho.mapear(
            body.get("email") or "", body.get("escopo_tipo") or "area",
            body.get("escopo_valor") or "", quem)})
    except ValueError as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "recusado", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho mapear falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel gravar o mapa."})


@app.post("/api/desempenho/ciclos/gravar")
async def desempenho_ciclo_gravar(req: Request) -> JSONResponse:
    from api import desempenho
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo invalido."})
    try:
        if body.get("id") and body.get("estado"):
            auth.audit(quem, "desempenho_ciclo_estado", str(body["id"]),
                       str(body["estado"]))
            return JSONResponse({"ok": True, "ciclo": desempenho.mudar_estado(
                int(body["id"]), body["estado"], quem)})
        auth.audit(quem, "desempenho_ciclo_criar", str(body.get("nome") or ""))
        return JSONResponse({"ok": True, "ciclo": desempenho.criar_ciclo(
            body.get("nome") or "", body.get("inicio") or "",
            body.get("fim") or "", quem)})
    except ValueError as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "recusado", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("desempenho ciclo falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel gravar o ciclo."})


@app.get("/api/dre/centros")
def dre_centros(grupo: int, reduzido: int, de: str, ate: str) -> JSONResponse:
    """Os centros de custo de UMA conta — o nivel abaixo da conta na DRE."""
    from api import dre_drill
    try:
        return JSONResponse(dre_drill.centros(grupo, reduzido, de, ate))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre centros falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel abrir os centros de custo."})


@app.get("/api/dre/conta-lancamentos")
def dre_conta_lancamentos(grupo: int, reduzido: int, de: str, ate: str,
                          centro: int | None = None,
                          sem_centro: bool = False) -> JSONResponse:
    """Os lancamentos de uma conta, opcionalmente de UM centro de custo."""
    from api import dre_drill
    try:
        return JSONResponse(dre_drill.lancamentos(
            grupo, reduzido, de, ate, centro=centro, sem_centro=sem_centro))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre lancamentos da conta falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel abrir os lancamentos."})


@app.get("/api/dre/exclusoes")
def dre_exclusoes_listar(de: str | None = None, ate: str | None = None) -> JSONResponse:
    """Os lancamentos tirados do resultado, com motivo e autor.

    LEITURA e de quem abre a DRE, nao so de quem pode excluir: o numero da
    tela depende disto, e esconder o porque de quem le seria pior do que nao
    ter a funcionalidade.
    """
    from api import dre_exclusoes
    try:
        return JSONResponse({"linhas": dre_exclusoes.listar(de, ate),
                             "total": dre_exclusoes.total(de, ate)})
    except Exception as exc:  # noqa: BLE001
        log.warning("dre exclusoes falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler as exclusoes."})


@app.get("/api/dre/lancamentos")
def dre_lancamentos(de: str, ate: str, conta: str | None = None,
                    busca: str | None = None,
                    valor_min: float | None = None) -> JSONResponse:
    """Lancamentos do periodo, para escolher o que excluir."""
    from api import dre_exclusoes
    try:
        return JSONResponse(dre_exclusoes.buscar(de, ate, conta, busca, valor_min))
    except Exception as exc:  # noqa: BLE001
        log.warning("dre lancamentos falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler os lancamentos."})


@app.post("/api/dre/exclusoes/marcar")
async def dre_exclusoes_marcar(req: Request) -> JSONResponse:
    """Tira UM lancamento do resultado gerencial.

    A AUDITORIA VEM ANTES da resposta e leva o MOTIVO: esta e a operacao mais
    sensivel da tela — ela muda o resultado publicado — e a pergunta que
    alguem vai fazer daqui a seis meses e "quem tirou isso, e por que".
    """
    from api import dre_exclusoes
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    if not quem:
        return JSONResponse(status_code=401, content={
            "erro": "sem_sessao",
            "mensagem": "Sessao sem e-mail: nao da para registrar o autor."})
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo invalido."})
    try:
        r = dre_exclusoes.marcar(body, body.get("motivo") or "", quem)
    except dre_exclusoes.MotivoObrigatorio as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "motivo_obrigatorio", "mensagem": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("dre excluir falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Nao foi possivel excluir o lancamento."})
    auth.audit(quem, "dre_excluir",
               alvo="%s/%s/%s/%s/%s" % (r["grupo"], r["empresa"], r["reduzido"],
                                        r["sequencia"], r["dtlancamento"]),
               detalhe=str(r.get("motivo") or "")[:180])
    return JSONResponse({"ok": True, "linha": r})


@app.post("/api/dre/exclusoes/remover")
async def dre_exclusoes_remover(req: Request) -> JSONResponse:
    """Devolve o lancamento ao resultado. Tambem auditado."""
    from api import dre_exclusoes
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    if not quem:
        return JSONResponse(status_code=401, content={
            "erro": "sem_sessao",
            "mensagem": "Sessao sem e-mail: nao da para registrar o autor."})
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo invalido."})
    try:
        achou = dre_exclusoes.desmarcar(body)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("dre desexcluir falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Nao foi possivel desfazer a exclusao."})
    auth.audit(quem, "dre_reincluir",
               alvo="%s/%s/%s/%s/%s" % (body.get("grupo"), body.get("empresa"),
                                        body.get("reduzido"),
                                        body.get("sequencia"),
                                        body.get("dtlancamento")))
    return JSONResponse({"ok": True, "removido": achou})


@app.get("/api/frota/comunicacao-tv")
def comunicacao_tv() -> JSONResponse:
    """Painel de TV da comunicacao com as rastreadoras."""
    try:
        return JSONResponse(queries.get_tv_comunicacao())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexao com o banco do ERP."})
    except Exception as exc:  # noqa: BLE001
        log.warning("comunicacao tv falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler a comunicacao da frota."})


@app.post("/api/gestao/dfe/certificado")
def dfe_certificado(payload: dict, req: Request) -> JSONResponse:
    """Cadastra o certificado A1 de uma filial na recolha. SO ADMINISTRADOR.

    ESTA ROTA E DE GESTAO e nao da tela `dfe`, de proposito. A tela e de RBAC
    normal -- quem opera precisa VER se a recolha esta viva --, mas trocar o
    certificado da empresa e ato de administrador: ele assina documento fiscal
    em nome dela. `/api/gestao` e admin pelo middleware, e essa e a fronteira.

    O .pfx vem em base64 NO CORPO, com a senha. No corpo e nao em query nem
    header: URL e cabecalho aparecem em log de servidor e de proxy, e senha de
    certificado em log e vazamento permanente. O corpo de um POST nao e
    registrado.

    O arquivo e ABERTO aqui com a senha. Se abre, titular, CNPJ e validade saem
    do PROPRIO certificado -- dado que nao precisa ser digitado e por isso nao
    pode ser digitado errado. Senha errada vira 422 agora, e nao uma recolha
    que falha calada daqui a semanas.
    """
    import base64
    from api.contrapartida import cadastro
    from api.contrapartida.certificado import (MAX_BYTES, CertificadoInvalido,
                                               conferir_titularidade, ler,
                                               senha_que_abre)
    from api.sefaz import armazenamento as arm

    _s = getattr(req.state, "sessao", None) or {}
    quem = _s.get("email") or _s.get("nome") or "?"
    cnpj = re.sub(r"[^0-9]", "", str(payload.get("cnpj") or ""))

    # SO CNPJ QUE JA ESTA NA RECOLHA. Sem isto a rota aceitaria guardar
    # certificado de qualquer CNPJ do mundo numa pasta que a casa protege e
    # usa para assinar -- e a lista de caixas vem do ERP, nao da tela.
    if not arm.caixa(cnpj):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "CNPJ nao esta na recolha. As caixas saem das filiais "
                        "ativas do ERP (scripts/abrir_caixas_dfe.py)."})

    senha = str(payload.get("senha") or "")
    b64 = str(payload.get("arquivo_b64") or "")
    if not (senha and b64):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Envie o arquivo .pfx e a senha."})
    try:
        bruto = base64.b64decode(b64, validate=True)
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Arquivo invalido."})
    if len(bruto) > MAX_BYTES:
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": "Arquivo acima de %d MB." % (MAX_BYTES // (1024 * 1024))})
    try:
        lido = ler(bruto, senha)
    except CertificadoInvalido as exc:
        return JSONResponse(status_code=422, content={
            "erro": "certificado_invalido", "mensagem": str(exc)})

    avisos = []
    if lido.get("aviso_senha"):
        avisos.append(lido["aviso_senha"])
    conf = conferir_titularidade(lido, cnpj)
    if conf:
        avisos.append(conf)
    if lido["vencido"]:
        avisos.append("O certificado venceu em %s: ele fica cadastrado, mas a "
                      "recolha desta filial nao vai funcionar." % lido["valida_ate"])
    elif isinstance(lido.get("dias"), int) and lido["dias"] <= 30:
        avisos.append("Vence em %d dia(s) (%s). Peca a renovacao agora: quando "
                      "ele vencer, a recolha para e nao ha erro que aponte para "
                      "o certificado." % (lido["dias"], lido["valida_ate"]))
    try:
        # AUDITORIA ANTES da acao externa, como toda escrita da casa.
        auth.audit(quem, "dfe_certificado", alvo=cnpj,
                   detalhe="titular=%s valida_ate=%s"
                           % (lido["titular"], lido["valida_ate"]))
    except Exception:  # noqa: BLE001
        pass
    try:
        cadastro.DIR_CERT.mkdir(parents=True, exist_ok=True)
        alvo = cadastro.DIR_CERT / ("%s.pfx" % cnpj)
        alvo.write_bytes(bruto)
        segredo_arquivo.proteger(alvo)   # ACL de verdade, nao so chmod
        # A senha que ABRIU, que pode ser a variante sem o espaco colado do
        # copiar-e-colar. Gravar a digitada faria a recolha falhar meses
        # depois, longe da causa.
        cadastro.gravar_senha(cnpj, senha_que_abre(bruto, senha) or senha)
        segredo_arquivo.proteger(cadastro.SENHAS_PATH)
    except Exception as exc:  # noqa: BLE001
        log.warning("dfe: gravar certificado falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao gravar o certificado."})
    log.info("dfe: certificado de %s cadastrado por %s", cnpj, quem)
    # a senha NAO volta, nem mascarada
    return JSONResponse({"ok": True, "cnpj": cnpj, "titular": lido["titular"],
                         "valida_ate": lido["valida_ate"], "dias": lido["dias"],
                         "avisos": avisos})


@app.get("/api/dfe")
def dfe_panorama(limite: int = 200, cnpj: str = "", tipo: str = "",
                 de: str = "", ate: str = "", busca: str = "",
                 origem: str = "") -> JSONResponse:
    """As notas recolhidas da SEFAZ: as caixas, o que chegou e o que falta.

    Rota `def` (nao `async`): le o banco e abre os .pfx para conferir validade,
    e trabalho bloqueante em rota `async` trava o servidor inteiro.

    NAO DISPARA COLETA. A pergunta e sobre o que JA chegou -- e bater na SEFAZ
    a cada pintura de tela cairia no freio de consumo indevido, que custa uma
    hora de recolha parada.
    """
    from api.sefaz import armazenamento, painel
    for nome, valor in (("de", de), ("ate", ate)):
        if valor and _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": "Parametro %s invalido: use AAAA-MM-DD." % nome})
    try:
        d = painel.panorama()
        d["documentos"] = armazenamento.documentos(
            re.sub(r"[^0-9]", "", cnpj or "") or None, limite=limite,
            tipo=(tipo or "").strip().lower(), de=de, ate=ate,
            busca=(busca or "").strip(),
            origem=(origem or "").strip().lower())
        # A SEGUNDA PORTA, do lado do estado. A tela precisa dizer se a caixa
        # de XML esta sendo lida -- e, quando nao esta, POR QUE. Falta de
        # credencial aqui nao e falha: e instalacao incompleta, e some da tela
        # no dia em que alguem configurar.
        try:
            from api.sefaz import caixa_email
            d["email"] = caixa_email.estado()
        except Exception as exc:  # noqa: BLE001
            log.warning("dfe: estado da caixa de xml (%s)", type(exc).__name__)
            d["email"] = None
        # A CONCILIACAO E OPCIONAL E NAO PODE DERRUBAR A TELA. Ela le o ERP,
        # que e replica de producao de TERCEIRO e tem dia ruim -- e a recolha
        # vale sozinha. Falhou, some, e a tela diz que sumiu.
        try:
            from api.sefaz import conciliacao
            d["conciliacao"] = conciliacao.marcar(d["documentos"])
        except Exception as exc:  # noqa: BLE001
            log.warning("dfe: conciliacao indisponivel (%s)", type(exc).__name__)
            d["conciliacao"] = None
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        log.exception("dfe: panorama falhou")
        return JSONResponse({"erro": "nao foi possivel ler a recolha",
                             "tipo": type(exc).__name__}, status_code=500)


@app.get("/api/dfe/pdf")
def dfe_pdf(cnpj: str = "", nsu: str = "", sha: str = "") -> Response:
    """A representacao grafica do documento: DANFE, DACTE ou DAMDFE.

    O documento fiscal E o XML; o PDF e a representacao grafica dele, e quem
    tem o XML autorizado pode gera-la. O que ele resolve e concreto: XML nao se
    le, e quem precisa conferir, anexar num processo ou mandar para alguem
    precisa da folha.
    """
    from api.sefaz import armazenamento, arquivo, impressao
    if sha:
        doc = arquivo.linha_de(sha)
        if not doc:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Documento nao encontrado."})
        xml = arquivo.xml_de(sha) or ""
    else:
        cnpj = re.sub(r"[^0-9]", "", cnpj or "")
        linhas = [d for d in armazenamento.documentos(cnpj or None, limite=2000)
                  if d.get("nsu") == armazenamento.nsu(nsu)]
        if not linhas:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Documento nao encontrado."})
        doc = linhas[0]
        xml = armazenamento.xml_de(doc["cnpj"], doc["nsu"]) or ""
    try:
        pdf = impressao.gerar(doc, xml)
    except impressao.NaoImprimivel as exc:
        # 409 e nao 500: e RECUSA LEGIVEL, e o Cloudflare troca o corpo de 5xx
        # pela pagina dele -- a mensagem nunca chegaria na tela.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "nao_imprimivel", "mensagem": str(exc)})
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="%s"'
                                        % impressao.nome_do_arquivo(doc)})


@app.get("/api/dfe/buscar")
def dfe_buscar(chave: str = "", cnpj: str = "", fora: int = 1) -> JSONResponse:
    """Procura UM documento pela chave: no que ja temos, e so depois na SEFAZ.

    A ORDEM NAO E ECONOMIA DE REDE. A SEFAZ CONTA consulta e freia quem
    pergunta demais (656, ~1 h de castigo por CNPJ) -- e tela de busca e
    exatamente o lugar onde alguem digita a mesma chave tres vezes porque nao
    viu o resultado. Ir ao banco primeiro faz a terceira digitacao custar zero.

    `fora=0` procura SO no que ja esta guardado, para quem quer conferir sem
    gastar cota nenhuma.
    """
    from api.sefaz import busca
    try:
        r = busca.por_chave(chave, cnpj=re.sub(r"[^0-9]", "", cnpj or ""),
                            buscar_fora=bool(fora))
    except Exception as exc:  # noqa: BLE001
        log.exception("dfe: busca por chave falhou")
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "tipo": type(exc).__name__})
    # 200 mesmo quando nao acha: "nao achei" e resposta, nao falha -- e o
    # corpo carrega o MOTIVO, que e o que a tela precisa dizer.
    return JSONResponse(r)


@app.get("/api/gestao/dfe/filiais")
def dfe_filiais() -> JSONResponse:
    """As filiais da recolha e o estado do certificado de cada uma. SO ADMIN.

    ELA EXISTE PARA OS DOIS CAMPOS DE ADMINISTRACAO da SEFAZ, que moram no
    modal do cartao dela na tela Integracoes. Poderia sair do proprio cartao,
    e nao sai de proposito: o cartao e de RBAC normal (quem opera precisa
    saber que a recolha parou sem depender de administrador), e CNPJ de filial
    nao precisa viajar para todo mundo por causa de um `select` que so
    administrador ve.

    A LISTA SAI DAS CAIXAS ABERTAS, que e a mesma fonte que `dfe_certificado`
    confere antes de gravar. Filial nova entra sozinha; filial que nao esta na
    recolha nao aparece para ser escolhida -- e essas duas frases sao a mesma
    frase.

    O que volta e o que a tela precisa dizer: apelido, CNPJ e se ha
    certificado, com a validade. A SENHA NAO VOLTA, e o arquivo tambem nao.
    """
    from api.sefaz import painel as sefaz_painel
    return JSONResponse({"filiais": sefaz_painel.certificados()})


@app.post("/api/gestao/dfe/recuperar")
def dfe_recuperar(payload: dict, req: Request) -> JSONResponse:
    """Puxa UM documento por NSU avulso. SO ADMINISTRADOR.

    E O UNICO CAMINHO DE VOLTA para um documento que passou na varredura e nao
    foi guardado. O `distNSU` nao rele faixa -- para a SEFAZ, consumidor que
    nao avanca e consumidor com defeito, e a segunda leitura da mesma faixa
    volta 656. O NSU avulso responde, um por chamada.

    SO ADMINISTRADOR porque cada chamada gasta cota de um servico que freia:
    um laço de recuperacao mal dosado custa uma hora de recolha parada para a
    filial inteira. Quem faz isso precisa saber o que esta fazendo.
    """
    from api.sefaz import armazenamento as arm, distribuicao as dist
    _s = getattr(req.state, "sessao", None) or {}
    quem = _s.get("email") or _s.get("nome") or "?"
    cnpj = re.sub(r"[^0-9]", "", str(payload.get("cnpj") or ""))
    nsu = re.sub(r"[^0-9]", "", str(payload.get("nsu") or ""))
    caixa = arm.caixa(cnpj) if cnpj else None
    if not caixa:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "CNPJ nao esta na recolha."})
    if not nsu:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe o NSU."})
    try:
        auth.audit(quem, "dfe_recuperar", alvo=cnpj, detalhe="nsu=%s" % nsu)
    except Exception:  # noqa: BLE001
        pass
    try:
        r = dist.buscar_avulso(cnpj, caixa.get("uf") or "PR", nsu_avulso=nsu)
    except dist.SemCertificado as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "sem_certificado", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("dfe: recuperar NSU falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=502, content={
            "erro": "sefaz", "mensagem": "A SEFAZ nao respondeu (%s)."
                                         % type(exc).__name__})
    return JSONResponse(r)


@app.get("/api/dfe/pacote")
def dfe_pacote(cnpj: str = "", de: str = "", ate: str = "",
               tudo: int = 0) -> Response:
    """Os XML de um periodo, num .zip. E ISTO que a operacao chama de "baixar".

    A recolha ja puxa da SEFAZ sozinha; o que faltava era o caminho de SAIDA --
    sem ele o XML fica guardado num banco que so o servidor abre, e quem precisa
    mandar para a contabilidade ou anexar num processo nao alcanca.

    UM ARQUIVO POR DOCUMENTO, nomeado pela CHAVE de acesso (44 digitos), que e
    o nome que todo sistema fiscal do pais espera. Nomear por NSU -- que e o
    nosso numero interno -- daria um zip que so o CORTEX entende.

    SO DOCUMENTO COMPLETO, por padrao. Um pacote com resumo dentro seria um
    arquivo que PARECE a nota e nao e, e quem descobre e o contador na hora de
    escriturar. `tudo=1` inclui os resumos, para quem sabe o que esta pedindo.
    """
    import io
    import zipfile
    from api.sefaz import armazenamento

    for nome, valor in (("de", de), ("ate", ate)):
        if valor and _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": "Parametro %s invalido: use AAAA-MM-DD." % nome})
    cnpj = re.sub(r"[^0-9]", "", cnpj or "")
    try:
        docs = armazenamento.para_pacote(cnpj or None, de, ate,
                                         so_completos=not tudo)
    except Exception as exc:  # noqa: BLE001
        log.exception("dfe: pacote falhou")
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "tipo": type(exc).__name__})
    if not docs:
        return JSONResponse(status_code=404, content={
            "erro": "vazio",
            "mensagem": "Nenhum documento COMPLETO no periodo. Documento que "
                        "chegou so como resumo nao entra no pacote."})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            # A CHAVE E O NOME; sem ela, o NSU. Documento sem chave e evento
            # ou coisa que o parser nao entendeu -- ele vai junto, porque o
            # que se guarda e tudo, mas com nome que nao finge ser nota.
            nome = "%s.xml" % (d.get("chave") or ("nsu-%s" % d["nsu"]))
            z.writestr(nome, d["xml"])
    buf.seek(0)
    rotulo = "-".join(x for x in ("dfe", cnpj or "todas", de or "", ate or "") if x)
    return Response(
        content=buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="%s.zip"' % rotulo,
                 "X-Documentos": str(len(docs))})


@app.get("/api/dfe/xml")
def dfe_xml(cnpj: str = "", nsu: str = "", sha: str = "") -> Response:
    """O XML de UM documento. Fora da listagem de proposito: 200 notas com o
    XML dentro sao ~2 MB numa resposta que a tela usa so para desenhar linhas.

    DOIS ENDERECOS PARA A MESMA COISA, porque sao duas portas: o documento da
    SEFAZ se acha por `(cnpj, nsu)`, que e a posicao dele no cursor da caixa; o
    que chegou por e-mail nao tem cursor nenhum e se acha pelo `sha` do
    proprio arquivo. Inventar um NSU falso para o segundo unificaria a
    assinatura desta rota e corromperia a varredura da primeira.
    """
    from api.sefaz import armazenamento, arquivo
    if sha:
        xml = arquivo.xml_de(sha)
        if not xml:
            return JSONResponse({"erro": "documento nao encontrado"},
                                status_code=404)
        return Response(content=xml, media_type="application/xml")
    if not (cnpj and nsu):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Informe cnpj+nsu (documento da SEFAZ) ou sha "
                        "(arquivo recebido por fora)."})
    xml = armazenamento.xml_de(cnpj, nsu)
    if not xml:
        return JSONResponse({"erro": "documento nao encontrado"}, status_code=404)
    return Response(content=xml, media_type="application/xml")


@app.post("/api/dfe/arquivo")
def dfe_receber_arquivo(payload: dict, req: Request) -> JSONResponse:
    """Recebe um XML (ou um .zip de XML) e guarda na recolha.

    A TERCEIRA PORTA, e ela existe por dois motivos concretos.

    O primeiro e HOJE: a leitura automatica da caixa `xml@sulista.com.br`
    depende de um aplicativo registrado no Microsoft 365, que e ato de quem
    administra o tenant. Ate isso acontecer, quem recebeu a nota no proprio
    e-mail arrasta o arquivo aqui e ele entra na mesma lista, com a mesma
    busca, o mesmo pacote .zip e a mesma folha.

    O segundo e DEPOIS: sempre vai existir a nota que chegou por WhatsApp, pelo
    portal do cliente, num pendrive. Uma porta manual nao e remendo enquanto a
    automatica nao vem -- e o que faz o portal ser o lugar UNICO onde o XML
    mora, que e a razao de ele existir.

    RBAC DA TELA, e nao de administrador: quem opera e quem recebe nota. A
    escrita entra no `audit_log` como toda escrita da casa.
    """
    import base64
    from api.sefaz import arquivo as arqmod

    _s = getattr(req.state, "sessao", None) or {}
    quem = _s.get("email") or _s.get("nome") or "?"
    nome = str(payload.get("nome") or "arquivo.xml")[:200]
    b64 = str(payload.get("conteudo_b64") or "")
    if not b64:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie o arquivo."})
    try:
        bruto = base64.b64decode(b64, validate=True)
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Arquivo invalido."})
    if len(bruto) > arqmod.MAX_ZIP_ABERTO:
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": "Arquivo acima de %d MB."
                        % (arqmod.MAX_ZIP_ABERTO // (1024 * 1024))})

    docs, fora = arqmod.do_arquivo(nome, bruto)
    if not docs:
        # RECUSA LEGIVEL (4xx), com o motivo de CADA arquivo. "Nao deu certo"
        # sem dizer o que veio faz a pessoa tentar o mesmo arquivo de novo.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "sem_documento",
            "mensagem": "Nenhum documento fiscal neste arquivo.",
            "ignorados": fora[:20]})
    try:
        auth.audit(quem, "dfe_arquivo", alvo=nome,
                   detalhe="documentos=%d ignorados=%d" % (len(docs), len(fora)))
    except Exception:  # noqa: BLE001
        pass
    r = arqmod.guardar_lote(docs, origem="upload", arquivo_nome=nome,
                            remetente=quem)
    log.info("dfe: %s enviou %s (%d documento(s))", quem, nome, len(docs))
    return JSONResponse({"ok": True, "arquivo": nome, "documentos": len(docs),
                         "novos": r["novos"], "repetidos": r["repetidos"],
                         "falhas": r["falhas"], "ignorados": fora[:20]})


@app.post("/api/gestao/dfe/coletar-email")
def dfe_coletar_email(payload: dict, req: Request) -> JSONResponse:
    """Le a caixa de XML AGORA. SO ADMINISTRADOR.

    A coleta normal e a tarefa agendada; esta rota existe para o dia em que
    alguem precisa do documento na hora, e para PROVAR a configuracao logo
    depois de cadastrar o aplicativo -- sem ela, quem configura fica esperando
    a proxima janela para saber se acertou.

    E de administrador porque o que ela usa e a credencial do aplicativo, e
    porque a recusa do provedor precisa chegar em quem consegue resolve-la.
    """
    from api.sefaz import caixa_email

    _s = getattr(req.state, "sessao", None) or {}
    quem = _s.get("email") or _s.get("nome") or "?"
    try:
        dias = int(payload.get("dias") or caixa_email.DIAS_PADRAO)
    except (TypeError, ValueError):
        dias = caixa_email.DIAS_PADRAO
    try:
        auth.audit(quem, "dfe_coletar_email", alvo=caixa_email.caixa(),
                   detalhe="dias=%d" % dias)
    except Exception:  # noqa: BLE001
        pass
    try:
        placar = caixa_email.coletar(dias=max(1, min(dias, 365)))
    except caixa_email.NaoConfigurada as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "nao_configurada", "mensagem": str(exc)})
    except caixa_email.Indisponivel as exc:
        # 409 e nao 502: e RECUSA LEGIVEL, e o Cloudflare troca o corpo de 5xx
        # pela pagina dele -- a mensagem nunca chegaria na tela.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "indisponivel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.exception("dfe: coleta da caixa de xml falhou")
        return JSONResponse(status_code=500, content={
            "erro": "erro_interno", "tipo": type(exc).__name__})
    return JSONResponse({"ok": True, **placar})


@app.get("/api/gestao/dfe/email")
def dfe_email_mensagens(limite: int = 30) -> JSONResponse:
    """As ultimas mensagens lidas da caixa. SO ADMINISTRADOR.

    E de admin por causa do REMETENTE e do ASSUNTO: sao dado de pessoa, e a
    tela de operacao nao precisa deles para trabalhar -- ela precisa dos
    DOCUMENTOS, que aparecem na lista para todo mundo que ve a tela.

    O que se olha aqui e a pergunta que so esta lista responde: chegou alguma
    coisa que NAO virou documento?
    """
    from api.sefaz import caixa_email
    try:
        return JSONResponse({"mensagens": caixa_email.ultimas(limite),
                             "estado": caixa_email.estado()})
    except Exception as exc:  # noqa: BLE001
        log.warning("dfe: mensagens da caixa (%s)", type(exc).__name__)
        return JSONResponse({"mensagens": [], "estado": None,
                             "erro": type(exc).__name__})


@app.get("/api/integracoes")
def integracoes_panorama() -> JSONResponse:
    """As integracoes da casa, com CONFIGURACAO e CHEGADA DE DADO juntas.

    Rota `def` (nao `async`): ela le o ERP e roda PowerShell por dentro da
    Saude, e trabalho bloqueante em rota `async` trava o servidor inteiro. Rota
    sincrona o FastAPI ja poe no threadpool.

    Tela `integ`, de RBAC normal. Nao devolve valor de credencial nenhum -- so
    "falta o token", nunca qual e; e por isso que ela pode ser liberada por
    perfil em vez de viver atras de /api/gestao.
    """
    from api import integracoes
    try:
        return JSONResponse(integracoes.panorama())
    except Exception as exc:  # noqa: BLE001
        log.exception("integracoes: panorama falhou")
        return JSONResponse({"erro": "nao foi possivel montar o panorama",
                             "tipo": type(exc).__name__}, status_code=500)


@app.get("/api/auditoria")
def auditoria_uso(dias: int = 30) -> JSONResponse:
    """Indicadores de USO — acessos, tempo de sessao, telas e trilha de acoes.

    Tela `aud`, com RBAC proprio (ver ROTA_TELAS): quem audita nao precisa da
    Gestao inteira — usuarios, perfis e senhas — para ler a trilha.
    """
    from api import auditoria as aud
    dias = max(1, min(int(dias or 30), 365))
    try:
        d = aud.resumo(dias)
        d["telas_sem_uso"] = aud.telas_sem_uso(auth.TELAS, dias)
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        log.warning("auditoria de uso falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Nao foi possivel ler a trilha de auditoria."})


@app.get("/api/gestao/servidor")
def gestao_servidor() -> JSONResponse:
    # /api/gestao/* já é restrito a admin pelo AuthMiddleware
    try:
        return JSONResponse(servidor.coletar())
    except Exception as exc:  # noqa: BLE001
        log.warning("saude do servidor falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_coleta", "mensagem": "Erro ao coletar a saúde do servidor."})


@app.get("/api/financeiro/filtros")
def filtros() -> JSONResponse:
    try:
        return JSONResponse(queries.get_filtros())
    except Exception as exc:  # noqa: BLE001
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={"erro": "banco_inacessivel"})


@app.get("/api/financeiro/dre")
def dre(comp_de: str | None = None, comp_ate: str | None = None) -> JSONResponse:
    import re
    hoje = date.today()
    comp_ate = comp_ate or f"{hoje.year}-{hoje.month:02d}"
    comp_de = comp_de or f"{hoje.year}-01"
    for nome, valor in (("comp_de", comp_de), ("comp_ate", comp_ate)):
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM.",
            })
    if comp_de > comp_ate:
        comp_de, comp_ate = comp_ate, comp_de
    try:
        return JSONResponse(queries.get_dre(comp_de, comp_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("dre falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao executar a consulta da DRE.",
        })


@app.get("/api/financeiro/balanco")
def balanco(anomes: str | None = None) -> JSONResponse:
    import re
    if anomes and not re.match(r"^\d{6}$", anomes):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro anomes inválido: use o formato AAAAMM."})
    try:
        return JSONResponse(queries.get_balanco(anomes))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("balanco falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o balanço patrimonial."})


@app.get("/api/financeiro/dre-cliente")
def dre_por_cliente(comp_de: str | None = None, comp_ate: str | None = None,
                    filial: int | None = None) -> JSONResponse:
    import re
    hoje = date.today()
    comp_ate = comp_ate or f"{hoje.year}-{hoje.month:02d}"
    comp_de = comp_de or f"{hoje.year}-01"
    for nome, valor in (("comp_de", comp_de), ("comp_ate", comp_ate)):
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM.",
            })
    if comp_de > comp_ate:
        comp_de, comp_ate = comp_ate, comp_de
    try:
        return JSONResponse(dre_cliente.get_dre_cliente(comp_de, comp_ate, filial))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("dre-cliente falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao calcular a DRE por cliente.",
        })


_OC_STATUS_VALIDOS = frozenset(suprimentos_oc.STATUS_TODOS)


@app.get("/api/suprimentos/oc-pendentes")
def oc_pendentes(dias_min: int = suprimentos_oc.DIAS_PARADA) -> JSONResponse:
    """Em aberto, todo o histórico: a fila de aprovação de agora e as OCs
    aprovadas sem nota (por tempo desde a aprovação). Não segue o filtro de
    período da tela — OC velha é justamente o alvo."""
    if not (0 <= dias_min <= 3000):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "dias_min fora do intervalo (0 a 3000)."})
    try:
        return JSONResponse(queries.get_oc_pendentes(dias_min=dias_min))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("oc_pendentes falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar as ordens de compra em aberto."})


@app.get("/api/suprimentos/ordens-compra")
def ordens_compra(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    status: str | None = None,
    fornecedor: str | None = None,
    criador: int | None = None,
    aprovador: int | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if status and status not in _OC_STATUS_VALIDOS:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": f"status deve ser um de: {', '.join(sorted(_OC_STATUS_VALIDOS))}.",
        })
    fornecedor = (fornecedor or "").strip() or None
    try:
        return JSONResponse(queries.get_ordens_compra(
            filial, dt_de, dt_ate,
            status=status, fornecedor=fornecedor, criador=criador, aprovador=aprovador))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("ordens_compra falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar ordens de compra.",
        })


# ---------------------------------------------------------------- ANTT — piso mínimo

@app.get("/api/operacao/antt/piso")
def antt_piso(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    modalidade: str | None = None,
    transportador: str | None = None,
) -> JSONResponse:
    """Confere o frete pago a agregado/terceiro contra o piso mínimo da ANTT."""
    from datetime import timedelta

    from api.antt.servico import get_piso_minimo
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if modalidade and modalidade not in ("AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "modalidade deve ser AGR (agregado) ou TER (terceiro).",
        })
    transportador = (transportador or "").strip() or None
    try:
        return JSONResponse(get_piso_minimo(
            filial, dt_de, dt_ate, modalidade=modalidade,
            transportador=transportador))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("antt_piso falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao conferir o piso mínimo da ANTT.",
        })


# ---------------------------------------------------------------- Telemetria Gobrax

def _competencia_valida(c: str | None) -> str:
    hoje = date.today()
    c = (c or "").strip() or hoje.strftime("%Y-%m")
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", c):
        raise ValueError("Parâmetro competencia inválido: use AAAA-MM.")
    return c


@app.get("/api/telemetria/consumo")
def telemetria_consumo(competencia: str | None = None) -> JSONResponse:
    """Consumo da telemetria cruzado com o abastecimento do AVA.

    Lê o CACHE local: a coleta na Gobrax leva mais de um minuto e não pode
    acontecer no carregamento da tela.
    """
    from api.gobrax.consumo import get_consumo
    try:
        comp = _competencia_valida(competencia)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    try:
        return JSONResponse(get_consumo(comp))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_consumo falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar o consumo."})


@app.get("/api/telemetria/consumo/evolucao")
def telemetria_consumo_evolucao() -> JSONResponse:
    """A série mensal do km/l (telemetria × AVA), do cache local."""
    from api.gobrax.consumo import get_evolucao
    try:
        return JSONResponse(get_evolucao())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("evolucao do consumo falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar a evolução do consumo."})


@app.get("/api/telemetria/motoristas")
def telemetria_motoristas() -> JSONResponse:
    """Nota e km por motorista, mês a mês — dos snapshots da premiação."""
    from api.gobrax.motoristas import get_motoristas
    try:
        return JSONResponse(get_motoristas())
    except Exception as exc:  # noqa: BLE001
        log.warning("motoristas da telemetria falharam: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar a evolução dos motoristas."})


@app.post("/api/telemetria/consumo/atualizar")
async def telemetria_consumo_atualizar(req: Request) -> JSONResponse:
    """Coleta estatísticas e odômetro na Gobrax. Leva mais de dois minutos."""
    from api.gobrax import estatisticas, odometro
    from api.gobrax.armazenamento import ColetaVazia
    from api.gobrax.cliente import GobraxIndisponivel, GobraxNaoConfigurado
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    try:
        comp = _competencia_valida((body or {}).get("competencia")
                                   if isinstance(body, dict) else None)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    try:
        # dois minutos de coleta na Gobrax: no event loop, seriam dois minutos
        # com o CÓRTEX inteiro fora do ar para todo mundo
        e = await sem_travar(estatisticas.sincronizar, comp)
        o = await sem_travar(odometro.sincronizar, comp)
        return JSONResponse({"competencia": comp, "estatisticas": e["gravadas"],
                             "odometro": o["gravadas"]})
    except ColetaVazia as exc:
        log.warning("coleta de telemetria vazia: %s", exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "coleta_vazia",
            "mensagem": ("A Gobrax não devolveu nenhum veículo. "
                         "A coleta anterior foi mantida.")})
    except GobraxNaoConfigurado:
        return JSONResponse(status_code=422, content={
            "erro": "nao_configurado",
            "mensagem": ("Token da Gobrax não configurado. "
                         "Defina em Administração › Gestão › Integrações.")})
    except GobraxIndisponivel as exc:
        log.warning("gobrax indisponivel: %s", exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "gobrax_indisponivel",
            "mensagem": "A Gobrax não respondeu. Tente novamente em alguns minutos."})
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_consumo_atualizar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_sync", "mensagem": "Não foi possível atualizar a coleta."})


@app.get("/api/telemetria/conducao")
def telemetria_conducao(placa: str | None = None,
                        competencia: str | None = None) -> JSONResponse:
    """Indicadores de condução de UM veículo. Ao vivo (~2 s)."""
    from api.gobrax.cliente import GobraxIndisponivel, GobraxNaoConfigurado
    from api.gobrax.performance import coletar
    try:
        comp = _competencia_valida(competencia)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    if not (placa or "").strip():
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Escolha um veículo: a Gobrax exige a placa nesta consulta."})
    try:
        return JSONResponse(coletar(placa, comp))
    except GobraxNaoConfigurado:
        return JSONResponse(status_code=422, content={
            "erro": "nao_configurado",
            "mensagem": ("Token da Gobrax não configurado. "
                         "Defina em Administração › Gestão › Integrações.")})
    except GobraxIndisponivel as exc:
        log.warning("gobrax indisponivel: %s", exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "gobrax_indisponivel",
            "mensagem": "A Gobrax não respondeu para este veículo."})
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_conducao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a condução."})


@app.get("/api/telemetria/conducao/frota")
def telemetria_conducao_frota(competencia: str | None = None) -> JSONResponse:
    """Os 14 indicadores de condução, a frota inteira, LIDOS DO CACHE.

    Não chama a Gobrax: a varredura é uma requisição POR PLACA (108 na frota) e
    quem a faz é a tarefa agendada, uma vez ao dia. A tela que dispara coleta
    de fundo vira uma tela que trava quando o fornecedor demora.

    Vem com o `resumo`, que é o que dá sentido ao número individual: "motor
    ligado parado 18%" não decide nada sozinho — só ao lado da mediana da
    frota.
    """
    from api.gobrax import armazenamento, performance
    try:
        comp = _competencia_valida(competencia)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    try:
        linhas = performance.ler(comp)
        u = armazenamento.ultima(performance.COLECAO)
        return JSONResponse({
            "competencia": comp,
            "veiculos": linhas,
            "resumo": performance.resumo_frota(comp),
            "catalogo": [{"chave": c, "rotulo": r,
                          "menor_melhor": c in performance.MENOR_MELHOR}
                         for c, r in performance.INDICADORES.items()],
            "familias": [{"chave": c, "rotulo": r, "indicadores": ks}
                         for c, r, ks in performance.FAMILIAS],
            "coletado_em": (u or {}).get("quando"),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_conducao_frota falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler os indicadores da frota."})


@app.get("/api/telemetria/comunicacao")
def telemetria_comunicacao(limite: int | None = None,
                           competencia: str | None = None) -> JSONResponse:
    """Veículo que parou de mandar dado para a Gobrax.

    O denominador contém SÓ quem a Gobrax conhece na competência — veículo sem
    equipamento não pode cumprir a regra e não entra na conta. É a lição dos
    664 de 836 rastreadores "sem sinal", que eram 79% cadastro.
    """
    from api.gobrax import comunicacao
    try:
        comp = _competencia_valida(competencia)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    lim = comunicacao.LIMITE_H if limite is None else int(limite)
    if not (1 <= lim <= 720):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "O limite vai de 1 hora a 30 dias."})
    try:
        return JSONResponse(comunicacao.estado(comp, limite_h=lim))
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_comunicacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao apurar a comunicação dos veículos."})


@app.get("/api/telemetria/hodometro")
def telemetria_hodometro(competencia: str | None = None) -> JSONResponse:
    """Hodômetro por veículo, do cache, com a data da última leitura."""
    from api.gobrax import armazenamento, odometro
    try:
        comp = _competencia_valida(competencia)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    linhas = armazenamento.ler(odometro.COLECAO, comp)
    sem_leitura = sum(1 for l in linhas if not l.get("odometro"))
    # km do mês (estatísticas da MESMA competência, somado por placa — a
    # coleção pode trazer a placa repetida) e o delta contra a competência
    # ANTERIOR: |km − Δ| grande é sensor mentindo, e só o cruzamento vê
    from api.gobrax import estatisticas as _est
    km_mes: dict[str, float] = {}
    for r in armazenamento.ler(_est.COLECAO, comp):
        p0 = (r.get("placa") or "").upper()
        if p0:
            km_mes[p0] = km_mes.get(p0, 0.0) + float(r.get("km") or 0)
    comps = armazenamento.competencias(odometro.COLECAO)
    ant = comps[comps.index(comp) - 1] if comp in comps and comps.index(comp) > 0 else None
    odo_ant: dict[str, float] = {}
    if ant:
        for r in armazenamento.ler(odometro.COLECAO, ant):
            p0 = (r.get("placa") or "").upper()
            if p0 and r.get("odometro") is not None:
                odo_ant[p0] = float(r["odometro"])
    km_frota = 0.0
    ociosos = 0
    for l in linhas:
        p0 = (l.get("placa") or "").upper()
        l["km_mes"] = km_mes.get(p0)
        if l["km_mes"] is not None:
            km_frota += l["km_mes"]
            if l["km_mes"] < 500:
                ociosos += 1
        oa = odo_ant.get(p0)
        l["delta_odometro"] = (float(l["odometro"]) - oa) \
            if (l.get("odometro") is not None and oa is not None) else None
    return JSONResponse({
        "competencia": comp,
        "competencia_anterior": ant,
        "kpis": {"veiculos": len(linhas), "sem_leitura": sem_leitura,
                 "com_leitura": len(linhas) - sem_leitura,
                 "km_frota_mes": km_frota, "ociosos": ociosos},
        "linhas": sorted(linhas, key=lambda l: (l.get("odometro") is not None,
                                                l.get("odometro") or 0)),
        "sync": armazenamento.ultima(odometro.COLECAO),
        "fonte": "Gobrax vehicle-odometer (cache local) · leitura direta do veículo",
    })


@app.get("/api/telemetria/rastro")
def telemetria_rastro(placa: str | None = None,
                      dia: str | None = None) -> JSONResponse:
    """Trilha do veículo num dia. Ao vivo — a API de posições é rápida."""
    from api.gobrax.cliente import GobraxIndisponivel, GobraxNaoConfigurado
    from api.gobrax.rastro import coletar
    d = (dia or "").strip() or date.today().isoformat()
    if _bad_date(d):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro dia inválido: use AAAA-MM-DD."})
    try:
        linhas = coletar(date.fromisoformat(d), placa=placa)
        return JSONResponse({"dia": d, "placa": (placa or "").strip() or None,
                             "veiculos": linhas,
                             "pontos": sum(len(v["pontos"]) for v in linhas)})
    except GobraxNaoConfigurado:
        return JSONResponse(status_code=422, content={
            "erro": "nao_configurado",
            "mensagem": ("Token da Gobrax não configurado. "
                         "Defina em Administração › Gestão › Integrações.")})
    except GobraxIndisponivel as exc:
        log.warning("gobrax indisponivel: %s", exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "gobrax_indisponivel", "mensagem": "A Gobrax não respondeu."})
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_rastro falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o rastro."})


# ---------------------------------------------------------------- Integrações (credenciais)

@app.get("/api/gestao/credenciais")
def gestao_credenciais() -> JSONResponse:
    """Integrações por FORNECEDOR, com o estado de cada uma.

    NUNCA devolve o valor de um segredo — só o mascarado. Campo de
    configuração (ambiente, URL base, filiais) volta com o valor de propósito;
    a regra está em `api/credenciais.py`.

    `credenciais` continua indo na resposta: é a lista plana, sem agrupamento,
    de que outros consumidores dependem.
    """
    from api import credenciais
    # /api/gestao/* já é restrito a admin pelo AuthMiddleware (api/auth.py:654)
    return JSONResponse({"servicos": credenciais.panorama(),
                         "credenciais": credenciais.listar()})


@app.post("/api/gestao/credenciais/gerar-mestre")
def gestao_gerar_codigo_mestre(req: Request) -> JSONResponse:
    """Gera o código mestre do app do motorista, grava no cofre e MOSTRA UMA VEZ.

    ESTA É A ÚNICA ROTA DA CASA QUE DEVOLVE UM SEGREDO NO CORPO, e a exceção
    tem a mesma forma da senha provisória: o valor é gerado PELO SISTEMA (nunca
    escolhido), vai para o cofre no mesmo instante, e a resposta é a única
    chance de lê-lo — depois disso nem esta tela consegue.

    `/api/gestao/*` já é restrito a admin pelo próprio middleware, antes de
    chegar aqui. E o segredo NÃO ENTRA NA TRILHA: o `audit_log` é append-only e
    imutável, então um valor que entrasse ali não sairia mais. O que se registra
    é que alguém gerou, e quando — que é a pergunta que a auditoria responde.

    GERAR SUBSTITUI O ANTERIOR, e isso é a rotação: quem sabia o código velho
    perde o acesso na hora. As sessões mestres já abertas continuam valendo até
    vencerem (8 h) — encerrá-las junto seria derrubar a conferência que alguém
    pode estar fazendo no meio, e o prazo curto é justamente o que torna isso
    aceitável.
    """
    from api import credenciais
    from api.motorista import mestre as mm
    autor = (getattr(req.state, "sessao", None) or {}).get("email") or "?"
    # HAVIA UM ANTES? A resposta muda por causa disso, e o motivo e um erro
    # real de 07/09/2026: o botao foi usado as 10:08 e o cofre foi sobrescrito
    # as 11:52 por outro caminho, sem ninguem saber. Substituir e o
    # comportamento CERTO — e o que faz "gerar de novo" ser rotacao —, mas quem
    # clica precisa LER que o anterior morreu ali. Aviso igual nos dois casos e
    # o que faz alguem clicar "so para ver" e derrubar o acesso de quem estava
    # usando o outro. O valor anterior NAO e lido para nada alem deste booleano.
    ja_havia = bool(credenciais.ler(mm.CHAVE))
    novo = credenciais.gerar_codigo_mestre()
    try:
        credenciais.gravar(mm.CHAVE, novo)
    except Exception as exc:  # noqa: BLE001
        log.warning("falha ao gravar o codigo mestre: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Nao foi possivel gravar o codigo no cofre."})
    auth.audit(autor, "codigo_mestre_gerado", alvo=mm.CHAVE,
               detalhe="app do motorista", ip=_ip_do_cliente(req))
    return JSONResponse({
        "ok": True, "codigo": novo, "substituiu": ja_havia,
        "aviso": ("Copie agora: este código não é mostrado outra vez."
                  + (" Ele SUBSTITUIU o código anterior, que não abre mais — "
                     "quem estava usando aquele perdeu o acesso agora."
                     if ja_havia else
                     " Este é o primeiro código; guarde-o em lugar seguro."))})


@app.post("/api/gestao/credenciais")
async def gestao_credenciais_salvar(req: Request) -> JSONResponse:
    """Grava uma credencial. O valor não é logado em nenhuma hipótese."""
    from api import credenciais
    # /api/gestao/* já é restrito a admin pelo AuthMiddleware (api/auth.py:654)
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict) or not body.get("nome"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe nome e valor."})
    autor = (getattr(req.state, "sessao", None) or {}).get("email") or "?"
    try:
        # o valor sai daqui direto para o cofre: nada de log, nada de eco
        st = credenciais.gravar(str(body["nome"]), str(body.get("valor") or ""))
    except ValueError as exc:
        # A RECUSA TAMBEM SE REGISTRA. Este era o unico ramo mudo da rota, e o
        # silencio custou tres tentativas de cadastrar a senha da 3S: a tela
        # recusava por tamanho minimo, o servidor nao escrevia nada, e do lado
        # de quem digita aparecia como "salvei e nao salvou". So o NOME e o
        # motivo entram — o valor nunca.
        log.warning("credencial %s recusada: %s", body.get("nome"), exc)
        auth.audit(autor, "credencial_recusada", alvo=str(body["nome"]),
                   detalhe=str(exc)[:120])
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("falha ao gravar credencial %s: %s",
                    body.get("nome"), type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Não foi possível gravar a credencial."})
    # TROCA DE CREDENCIAL E ESCRITA, e toda escrita entra na trilha. Faltava:
    # nao havia como responder "essa senha foi trocada quando, e por quem" —
    # a unica pista era o carimbo dentro do proprio arquivo de segredo. Vai o
    # NOME e quem trocou; o valor nao entra na trilha em hipotese nenhuma.
    auth.audit(autor, "credencial_gravada", alvo=str(body["nome"]),
               detalhe="apagada" if not str(body.get("valor") or "") else "definida")
    return JSONResponse(st)


@app.post("/api/fiscal/contrapartida/envio")
async def contrapartida_envio(req: Request) -> JSONResponse:
    """Liga ou desliga a emissão para UM agregado.

    Serve para testar com um de cada vez e para tirar da fila quem rejeita
    sempre — sem apagar certificado nem autorização, que são registros de
    outra natureza. O autor sai da SESSÃO, nunca do corpo.
    """
    from api.contrapartida import emissao
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    if not quem:
        return JSONResponse(status_code=401, content={
            "erro": "sem_sessao",
            "mensagem": "Sessão sem e-mail: não dá para registrar o autor."})
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict) or not body.get("cnpj"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe o agregado."})
    try:
        r = emissao.definir_envio(str(body["cnpj"]), bool(body.get("ativo")),
                                  quem)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("contrapartida_envio falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Não foi possível gravar."})
    return JSONResponse(r)


@app.post("/api/fiscal/contrapartida/cancelar")
async def contrapartida_cancelar(req: Request) -> JSONResponse:
    """Cancela um CT-e já autorizado. Ato fiscal, com prazo e justificativa.

    Não exige a liberação de produção: liberar existe para impedir que se
    EMITA sem querer, e exigi-la para cancelar seria pedir para destravar a
    emissão a fim de corrigir uma emissão.
    """
    from api.contrapartida import emissao
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    if not quem:
        return JSONResponse(status_code=401, content={
            "erro": "sem_sessao",
            "mensagem": "Sessão sem e-mail: não dá para registrar o autor."})
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict) or not body.get("chave"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe a chave."})
    try:
        # ida à SEFAZ: lenta e imprevisível, e o event loop não pode esperar
        r = await sem_travar(emissao.cancelar, str(body["chave"]),
                             str(body.get("justificativa") or ""), quem=quem)
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("contrapartida_cancelar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_cancelamento",
            "mensagem": f"Falha ao cancelar: {str(exc)[:200]}"})
    return JSONResponse(r)


@app.get("/api/fiscal/contrapartida/validacao")
def contrapartida_validacao(dias: int = 90) -> JSONResponse:
    """Valida o cadastro de TODOS os agregados ativos, sem o filtro da tela.

    Rota própria porque o recorte é outro: a tela abre no dia de hoje e o
    validador dentro dela seguia esse recorte, então quem não rodou hoje não
    era validado. Defeito de cadastro não pertence a uma janela de datas.
    """
    from api.contrapartida import servico
    try:
        return JSONResponse(servico.validacao_completa(dias))
    except Exception as exc:  # noqa: BLE001
        log.warning("contrapartida_validacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao validar o cadastro dos agregados."})


@app.get("/api/fiscal/contrapartida/automacao")
def contrapartida_automacao() -> JSONResponse:
    """Estado da rotina automática — só o que o cronômetro da tela precisa.

    Rota SEPARADA da de gestão de propósito, e só de LEITURA: quem enxerga a
    tela precisa saber quando sai a próxima rodada, mas ligar a automação,
    mudar o intervalo e liberar produção continuam restritos a administrador
    em /api/gestao/*. Aqui não vai quem mexeu em quê.

    Lê só o SQLite local (não toca no ERP), porque a tela chama isto a cada
    30 segundos — uma consulta ao AVA nessa cadência seria carga constante
    para mostrar um relógio.
    """
    from api.contrapartida import lote
    try:
        e = lote.estado()
        a = e.get("automacao") or {}
        return JSONResponse({
            "ativa": bool(a.get("ativa")),
            "intervalo_min": a.get("intervalo_min"),
            "ultima_execucao": a.get("ultima_execucao"),
            "ambiente": (e.get("ambiente") or {}).get("nome"),
            "producao": bool((e.get("ambiente") or {}).get("producao")),
            # O agendador do Windows dispara de 5 em 5 minutos e o CORTEX
            # decide se e hora. A tela precisa dizer isso, senao o cronometro
            # chega a zero, nada acontece por ate 5 minutos e parece travado.
            "passo_agendador_min": 5,
            # Se a pilha que assina e transmite nao estiver instalada, a
            # rotina passa e nao emite nada. Sem isto na tela, o cronometro
            # contaria bonito enquanto nada sai.
            "pilha_ok": lote.pilha_fiscal()[0],
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("contrapartida_automacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler o estado da automação."})


@app.get("/api/fiscal/contrapartida/transmitidos")
def contrapartida_transmitidos(dias: int = 90, limite: int = 200) -> JSONResponse:
    """Acompanhamento dos CT-e de contrapartida JA transmitidos.

    Rota propria, e nao um pedaco da conciliacao: a tela `ctecp` responde
    "quanto falta fazer" e esta responde "o que ja saiu, esta valendo e chegou
    a contabilidade". Sao duas perguntas, dois publicos e dois recortes de
    RBAC — e juntar as duas num payload so faria a tela pesada carregar o que
    nao usa.

    Rota `def` (nao `async`): o FastAPI a roda num threadpool, entao a consulta
    ao Postgres nao trava o event loop.
    """
    from api.contrapartida import transmitidos
    try:
        return JSONResponse(transmitidos.painel(dias=dias, limite=limite))
    except Exception as exc:  # noqa: BLE001
        log.warning("contrapartida_transmitidos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar o acompanhamento dos transmitidos."})


@app.get("/api/fiscal/contrapartida/documento/{chave}")
def contrapartida_documento(chave: str) -> Response:
    """Baixa o `cteProc` de um documento transmitido — XML + protocolo.

    Fica sob /api/fiscal/contrapartida/* e não em /api/gestao/*: quem enxerga
    a tela pode baixar o documento dela. Ligar produção é outra conversa e
    continua restrito a administrador.
    """
    from api.contrapartida import emissao
    limpa = "".join(c for c in (chave or "") if c.isdigit())
    if len(limpa) != 44:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Chave de CT-e tem 44 dígitos."})
    try:
        proc = emissao.proc_de(limpa)
    except Exception as exc:  # noqa: BLE001
        log.warning("download de contrapartida %s: %s", limpa, exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao ler o documento."})
    if not proc:
        # 404 e não um XML vazio: documento recusado não tem processo, e um
        # arquivo com cara de válido é pior que a ausência dele.
        return JSONResponse(status_code=404, content={
            "erro": "sem_documento",
            "mensagem": "Sem arquivo para esta chave. Só documento AUTORIZADO "
                        "tem processo — e os autorizados antes de o sistema "
                        "passar a guardar o XML não têm arquivo."})
    return Response(
        content=proc, media_type="application/xml",
        headers={"Content-Disposition":
                 f'attachment; filename="{limpa}-procCTe.xml"'})


# ------------------------------------------------- CT-e de contrapartida (emissão)
#
# /api/gestao/* é restrito a administrador pelo AuthMiddleware. Aqui isso não é
# detalhe: estes dois interruptores decidem se o sistema emite documento fiscal
# real, em nome de outra empresa, e se faz isso sem ninguém olhando.

@app.get("/api/gestao/contrapartida")
def gestao_contrapartida() -> JSONResponse:
    """Ambiente ativo, automação e intervalo — com quem mudou cada coisa."""
    from api.contrapartida import lote
    try:
        return JSONResponse(lote.estado())
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_contrapartida falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler a configuração de emissão."})


@app.post("/api/gestao/contrapartida")
async def gestao_contrapartida_salvar(req: Request) -> JSONResponse:
    """Muda ambiente, automação ou intervalo. Tudo entra na trilha.

    O autor sai da SESSÃO, nunca do corpo do pedido: quem responde por ligar
    produção não pode ser um campo que o próprio cliente preenche.
    """
    from api.contrapartida import emissao, lote, xml_email
    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    if not quem:
        return JSONResponse(status_code=401, content={
            "erro": "sem_sessao",
            "mensagem": "Sessão sem e-mail: não dá para registrar o autor."})
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo inválido."})
    try:
        if "ambiente" in body:
            emissao.definir_ambiente(str(body["ambiente"]), quem,
                                     str(body.get("confirmacao") or ""))
        if "automacao" in body:
            lote.definir_automacao(bool(body["automacao"]), quem)
        if "intervalo_min" in body:
            lote.definir_intervalo(body["intervalo_min"], quem)
        # XML para a contabilidade. CHAVE AUSENTE = NAO MEXE: a tela salva o
        # formulario inteiro, e um `body.get(...)` comum leria o campo que o
        # usuario nao tocou como vazio e apagaria o destinatario — mesmo
        # sentinela do cadastro de usuario (`api/auth.py`).
        if "xml_email_ativo" in body or "xml_email_destino" in body:
            await sem_travar(
                xml_email.definir, quem,
                ligado=(bool(body["xml_email_ativo"])
                        if "xml_email_ativo" in body else None),
                para=(str(body["xml_email_destino"])
                      if "xml_email_destino" in body else None))
        if body.get("xml_email_reenfileirar"):
            await sem_travar(xml_email.reenfileirar, quem)
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={
            "erro": "confirmacao_necessaria", "mensagem": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_contrapartida_salvar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Não foi possível gravar."})
    # `estado()` vai ao banco e esta rota e `async def`: no event loop, o
    # psycopg travaria o CORTEX inteiro pelo tempo da consulta.
    return JSONResponse(await sem_travar(lote.estado))


# ---------------------------------------------------------------- E-mail (SMTP)
#
# Tudo aqui é /api/gestao/*, ou seja: só administrador (AuthMiddleware).
# Enviar e-mail é ação para FORA da empresa — não pode ficar a um clique de
# qualquer usuário logado, e todo envio entra na trilha com o autor.

@app.get("/api/gestao/email")
def gestao_email() -> JSONResponse:
    """Config do SMTP + trilha de envios. NUNCA devolve a senha."""
    from api.correio import config as ecfg
    from api.correio import registro
    try:
        return JSONResponse({"config": ecfg.status(), "resumo": registro.resumo(),
                             "envios": registro.listar(50)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_email falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao ler a configuração de e-mail."})


@app.post("/api/gestao/email")
async def gestao_email_salvar(req: Request) -> JSONResponse:
    from api.correio import config as ecfg
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie a configuração."})
    try:
        st = ecfg.gravar(body)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_email_salvar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Não foi possível gravar a configuração."})
    sess = getattr(req.state, "sessao", None) or {}
    auth.audit(sess.get("email", "?"), "email_config", detalhe=f"host={st.get('host')}")
    return JSONResponse(st)


@app.get("/api/gestao/correio/agenda")
def gestao_agenda() -> JSONResponse:
    """Agendamentos, catálogo de relatórios e estado do SMTP."""
    from api.correio import agenda
    try:
        return JSONResponse(agenda.estado())
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_agenda falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler os agendamentos de e-mail."})


@app.post("/api/gestao/correio/agenda")
async def gestao_agenda_gravar(req: Request) -> JSONResponse:
    """Cria ou altera um agendamento. O autor sai da SESSÃO, nunca do corpo:
    trilha em que o autor vem do cliente não serve de trilha."""
    from api.correio import agenda
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email") or sess.get("nome") or ""
    try:
        r = agenda.gravar(body, autor)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_agenda_gravar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Erro ao gravar o agendamento."})
    auth.audit(autor or "?", "correio_agenda",
               alvo=f"{r['relatorio']} -> {r['destinatarios']}"[:200],
               detalhe=("ativo" if r["ativo"] else "desligado")
               + f" · {r['frequencia']} {r['hora']}")
    return JSONResponse(r)


@app.delete("/api/gestao/correio/agenda/{ident}")
def gestao_agenda_remover(ident: int, req: Request) -> JSONResponse:
    from api.correio import agenda
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email") or sess.get("nome") or "?"
    try:
        agenda.remover(ident)
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_agenda_remover falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao remover."})
    auth.audit(autor, "correio_agenda_remover", alvo=str(ident))
    return JSONResponse({"ok": True})


@app.get("/api/gestao/correio/previa")
def gestao_correio_previa(relatorio: str = "") -> Response:
    """Devolve o HTML do relatório para conferir ANTES de agendar.

    Sem isto, o único jeito de ver o relatório é agendar e esperar — ou
    mandar para si mesmo, que polui a trilha de envios com testes.
    """
    from api.correio import relatorios
    try:
        r = relatorios.montar(relatorio)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("previa de relatorio falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar o relatório."})
    # `text/html` com CSP restritiva: o corpo e montado aqui dentro, mas esta
    # rota devolve documento inteiro e vai para um iframe - sem script, sem
    # frame de terceiro, sem nada externo.
    return Response(content=r["html"], media_type="text/html; charset=utf-8",
                    headers={"Content-Security-Policy":
                             "default-src 'none'; style-src 'unsafe-inline'",
                             "X-Frame-Options": "SAMEORIGIN"})


@app.post("/api/gestao/correio/agenda/testar")
async def gestao_agenda_testar(req: Request) -> JSONResponse:
    """Manda UM agendamento agora, para o próprio usuário logado.

    Para o usuário logado e não para os destinatários configurados: testar não
    pode virar atalho para disparar relatório à diretoria fora de hora.
    """
    from api.correio import relatorios
    from api.correio.envio import enviar
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email") or ""
    if not autor:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Sessão sem e-mail: não há para onde mandar o teste."})
    try:
        # montar o relatório consulta o AVA e enviar abre SMTP: os dois são
        # bloqueantes e não podem rodar no event loop
        r = await sem_travar(relatorios.montar, str(body.get("relatorio") or ""))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    res = await sem_travar(enviar, [autor], "[TESTE] " + r["assunto"], r["texto"],
                           corpo_html=r["html"], usuario=autor,
                           origem="agenda:teste")
    auth.audit(autor, "correio_agenda_teste", alvo=str(body.get("relatorio")),
               detalhe=("ok" if res["ok"] else f"falha: {res['erro']}")[:200])
    if not res["ok"]:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "falha_envio", "mensagem": res["erro"]})
    return JSONResponse({"ok": True, "destinatario": autor})


@app.post("/api/gestao/email/enviar")
async def gestao_email_enviar(req: Request) -> JSONResponse:
    """Envia um e-mail. `teste=true` manda para o próprio usuário logado.

    O teste não aceita destinatário: o objetivo é validar a configuração, e
    deixar escolher para quem mandar transformaria o botão de teste num
    atalho para disparar mensagem a terceiros sem passar pelo formulário.
    """
    from api.correio.envio import enviar
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")

    if body.get("teste"):
        if not autor:
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": "Sessão sem e-mail: não há para onde mandar o teste."})
        destinatarios, origem = [autor], "teste"
        assunto = "CÓRTEX — teste de envio de e-mail"
        corpo = ("Este é um teste de configuração do envio de e-mail do CÓRTEX.\n\n"
                 "Se você recebeu esta mensagem, o servidor SMTP está funcionando.")
    else:
        destinatarios = body.get("destinatarios") or ""
        origem = str(body.get("origem") or "manual")
        assunto = str(body.get("assunto") or "")
        corpo = str(body.get("mensagem") or body.get("corpo") or "")

    # SMTP é bloqueante como a Z-API: sem isto, um servidor de e-mail lento
    # trava o CÓRTEX inteiro pelo tempo do handshake
    r = await sem_travar(enviar, destinatarios, assunto, corpo,
                         usuario=autor, origem=origem)
    auth.audit(autor or "?", "email_enviar",
               alvo=", ".join(r["destinatarios"])[:200],
               detalhe=("ok" if r["ok"] else f"falha: {r['erro']}")[:200])
    if not r["ok"]:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "envio_falhou", "mensagem": r["erro"]})
    return JSONResponse({"ok": True, "destinatarios": r["destinatarios"]})


# ------------------------------------------------------------------ WhatsApp
#
# Tudo sob /api/gestao/*, que o middleware já restringe ao ADMINISTRADOR. Não é
# só simetria com o e-mail: disparar WhatsApp em nome da empresa é ação para
# fora, com um número que pode ser banido — a permissão certa é a mais estreita
# que existe hoje no sistema.

@app.get("/api/gestao/whatsapp")
def gestao_whatsapp() -> JSONResponse:
    """Configuração + estado da conexão + trilha. NUNCA devolve os tokens."""
    from api.whatsapp import cliente as zcli
    from api.whatsapp import config as zcfg
    from api.whatsapp import registro as zreg
    try:
        conta = {"total": 0, "ok": 0, "falha": 0, "numeros": 0,
                 "ultimo": None, "hoje": 0}
        envios: list = []
        try:
            conta, envios = zreg.resumo(), zreg.listar(50)
        except Exception as exc:   # noqa: BLE001
            # banco local fora não pode esconder a configuração: é justamente
            # onde se olha para entender por que nada está saindo
            log.warning("gestao_whatsapp: trilha indisponível: %s", exc)
        # UMA ENTRADA POR INSTÂNCIA. A tela precisa mostrar as duas lado a
        # lado: com dois números, "conectado" sem dizer QUAL é a informação
        # que leva a mandar pelo aparelho errado. `conexao` (singular) fica
        # como está, apontando para a principal, porque a Saúde e os testes
        # antigos já leem essa chave.
        instancias = [
            {"chave": q, "rotulo": zcli.ROTULOS[q],
             "configurado": zcli.configurado(q),
             "instancia": zcli.instancia_mascarada(q) if zcli.configurado(q) else "",
             "client_token_ok": bool(zcli.client_token(q)),
             "conexao": zcli.estado(qual=q) if zcli.configurado(q) else {
                 "ok": False, "conectado": False, "celular": False,
                 "configurado": False,
                 "erro": "Instância não configurada."},
             "hoje": (conta.get("hoje_por_instancia") or {}).get(q, 0)}
            for q in zcli.INSTANCIAS]
        return JSONResponse({"config": zcfg.status(), "resumo": conta,
                             "envios": envios, "conexao": zcli.estado(),
                             "instancias": instancias})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_whatsapp falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler a configuração do WhatsApp."})


@app.post("/api/gestao/whatsapp")
async def gestao_whatsapp_salvar(req: Request) -> JSONResponse:
    from api.whatsapp import cliente as zcli
    from api.whatsapp import config as zcfg
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie a configuração."})
    try:
        st = zcfg.gravar(body)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_whatsapp_salvar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Não foi possível gravar a configuração."})
    # credencial nova invalida o cache de 60 s — sem isto a tela continuaria
    # mostrando o erro da configuração anterior por um minuto inteiro
    zcli.limpar_cache()
    sess = getattr(req.state, "sessao", None) or {}
    # LIGAR/DESLIGAR é a informação que importa na auditoria: é o que autoriza
    # o sistema a falar com clientes em nome da empresa.
    auth.audit(sess.get("email", "?"), "whatsapp_config",
               detalhe=f"ativo={st['ativo']} limite={st['limite_dia']}")
    return JSONResponse(st)


@app.post("/api/gestao/whatsapp/conexao")
def gestao_whatsapp_conexao(instancia: str | None = None) -> JSONResponse:
    """Relê o status de UMA instância IGNORANDO o cache — é o botão 'testar
    conexão'. Não manda mensagem nenhuma: só pergunta à Z-API se o aparelho
    está pareado.

    Continua sendo rota `def` (não `async`): o FastAPI a roda em threadpool,
    então a ida à Z-API não trava o event loop — ver `sem_travar()`.
    """
    from api.whatsapp import cliente as zcli
    return JSONResponse(zcli.estado(force=True, qual=instancia))


@app.post("/api/gestao/whatsapp/enviar")
async def gestao_whatsapp_enviar(req: Request) -> JSONResponse:
    """Envia mensagem de WhatsApp.

    DIFERENÇA DELIBERADA PARA O TESTE DE E-MAIL: lá o teste vai para o e-mail
    do próprio usuário logado, e não aceita destinatário. Aqui não existe
    telefone na sessão, então o teste PRECISA de um número — e por isso não há
    "modo teste" separado: é o mesmo envio, com a mesma trilha, o mesmo limite
    diário e a mesma auditoria. Um caminho paralelo mais frouxo viraria o
    atalho para disparar sem passar pelas regras.
    """
    from api.whatsapp.envio import enviar_modelo, enviar_varios
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    telefones = body.get("telefones") or body.get("telefone") or ""
    chave = str(body.get("modelo") or "").strip()
    # instância desconhecida cai na principal (`qual_valida`), em vez de virar
    # erro: é o que a pessoa espera de "não escolhi nada"
    from api.whatsapp.cliente import qual_valida
    inst = qual_valida(body.get("instancia"))

    # COM MODELO, QUEM MONTA O TEXTO É O SERVIDOR — a tela manda a chave e os
    # valores, nunca a mensagem pronta. Aceitar o texto do cliente junto com a
    # chave deixaria gravar "veio do modelo de cobrança" numa trilha em que o
    # texto é outro qualquer, e a coluna `modelo` deixaria de ser prova.
    # REDE DE SEGURANÇA. `enviar`/`enviar_varios` têm contrato de nunca levantar,
    # mas o que roda antes deles (ler o modelo, tocar o banco local) não tem — e
    # exceção que escapa daqui vira "Internal Server Error" em TEXTO PURO, que o
    # `r.json()` da tela não consegue ler. O usuário então vê "não foi possível
    # falar com a API" para um servidor que respondeu, e o motivo real fica só
    # no log de um processo que roda sem janela. Toda saída desta rota é JSON.
    try:
        if chave:
            valores = body.get("valores")
            r = await sem_travar(
                enviar_modelo, telefones, chave,
                valores if isinstance(valores, dict) else {},
                usuario=autor, origem=str(body.get("origem") or "") or "",
                instancia=inst)
        else:
            r = await sem_travar(
                enviar_varios, telefones, str(body.get("mensagem") or ""),
                usuario=autor, origem=str(body.get("origem") or "manual"),
                instancia=inst)
    except Exception as exc:  # noqa: BLE001
        from api.whatsapp.cliente import _sanitizar
        log.exception("whatsapp_enviar falhou")
        auth.audit(autor or "?", "whatsapp_enviar", alvo=str(telefones)[:200],
                   detalhe=f"erro interno: {type(exc).__name__}")
        return JSONResponse(status_code=500, content={
            "erro": "erro_interno",
            # o tipo, não o texto: `str(exc)` de urllib carrega a URL da Z-API,
            # e a URL é a credencial. Sanitizado ainda assim, por via das dúvidas
            "mensagem": _sanitizar(
                f"Erro interno ao enviar ({type(exc).__name__}). A mensagem NÃO "
                "saiu. Confira a Saúde do Servidor e o banco local do CÓRTEX.")})
    alvos = ", ".join(x["telefone"] for x in r["resultados"])
    auth.audit(autor or "?", "whatsapp_enviar", alvo=alvos[:200],
               detalhe=(f"por={inst} · "
                        + (f"modelo={chave} · " if chave else "")
                        + f"{r['enviados']} enviada(s), {r['falhas']} falha(s)"
                        + (f": {r['erro']}" if r["erro"] else ""))[:200])
    if not r["ok"]:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "envio_falhou", "mensagem": r["erro"],
            "resultados": r["resultados"]})
    return JSONResponse(r)


@app.get("/api/gestao/whatsapp/modelos")
def gestao_whatsapp_modelos() -> JSONResponse:
    """Os modelos + o catálogo de contextos.

    O catálogo vai JUNTO, e não numa rota à parte, porque a tela não consegue
    desenhar um modelo sem ele: é dele que saem as variáveis permitidas, os
    exemplos da prévia e a informação de quais telas já disparam cada contexto.
    """
    from api.whatsapp import modelos as zmod
    try:
        from api.whatsapp import config as zcfg
        geral = zcfg.ler()
        return JSONResponse({"modelos": zmod.listar(),
                             "contextos": zmod.contextos(),
                             # a regra GERAL vai junto: o editor precisa dela
                             # para dizer "isto aperta" ou "isto amplia", e sem
                             # a comparação os dois campos perigosos (limite
                             # acima do teto, janela maior que a geral) parecem
                             # inofensivos ao digitar
                             "geral": {k: geral[k] for k in
                                       ("limite_dia", "janela_inicio",
                                        "janela_fim", "assinatura",
                                        "intervalo_seg")},
                             "limites": {"corpo": zmod.CORPO_MAX,
                                         "texto": zmod.TEXTO_MAX,
                                         "assinatura": zmod.ASSINATURA_MAX,
                                         "limite_dia": zmod.LIMITE_MAX}})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_whatsapp_modelos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler os modelos de mensagem."})


@app.get("/api/gestao/whatsapp/modelos/valores")
async def gestao_whatsapp_modelo_valores(contexto: str = "") -> JSONResponse:
    """Preenche as variáveis de um contexto com os números de agora.

    Existe para o modelo de faturamento diário não obrigar alguém a copiar nove
    valores da Visão Geral todo dia — que é o tipo de tarefa em que um dígito a
    menos passa despercebido e vira mensagem dizendo que a empresa faturou um
    décimo do que faturou.

    `sem_travar` porque a Visão Geral consulta o AVA e demora: no event loop,
    seriam segundos com o CÓRTEX inteiro parado para todo mundo.
    """
    from api.whatsapp import modelos as zmod
    from api.whatsapp import valores as zval
    provedor = zmod.provedor_do_contexto(contexto)
    if not provedor:
        # contexto sem provedor é resposta NORMAL, não erro: a tela pergunta
        # por todos e só mostra o botão onde há o que preencher
        return JSONResponse({"provedor": "", "valores": {}})
    try:
        return JSONResponse({"provedor": provedor,
                             "valores": await sem_travar(zval.obter, provedor)})
    except Exception as exc:  # noqa: BLE001
        log.warning("valores de %s falharam: %s", provedor, exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "valores_indisponiveis",
            "mensagem": ("Não foi possível ler os números agora (o banco do ERP "
                         "respondeu?). Preencha à mão ou tente de novo.")})


@app.post("/api/gestao/whatsapp/modelos/previa")
async def gestao_whatsapp_modelo_previa(req: Request) -> JSONResponse:
    """Valida e renderiza SEM gravar — é o que a tela mostra enquanto se digita.

    Fica no servidor, e não em JavaScript, porque a regra que decide se um
    modelo é válido tem de ser UMA: uma prévia que aceitasse o que a gravação
    recusa ensinaria a escrever errado.
    """
    from api.whatsapp import modelos as zmod
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    corpo = str(body.get("corpo") or "")
    contexto = str(body.get("contexto") or zmod.CONTEXTO_PADRAO)
    try:
        zmod.validar({**body, "nome": body.get("nome") or "previa",
                      "corpo": corpo or "."})
        erro = ""
    except zmod.ModeloInvalido as exc:
        erro = str(exc)
    # Com `valores`, a prévia é a do FORMULÁRIO DE ENVIO (o que vai sair de
    # verdade); sem eles, é a do editor, com os exemplos do catálogo. Os dois
    # passam pelo mesmo `renderizar()` de propósito: uma prévia escrita em
    # JavaScript acabaria discordando do que o servidor manda, e a hora de
    # descobrir isso seria depois de a mensagem chegar ao cliente.
    valores = body.get("valores")
    texto = (zmod.renderizar(corpo, valores, estrito=False)
             if isinstance(valores, dict) else zmod.previa(corpo, contexto))
    return JSONResponse({
        "erro": erro,
        "texto": texto,
        "variaveis": zmod.variaveis_usadas(corpo),
        "caracteres": len(corpo)})


@app.post("/api/gestao/whatsapp/modelos")
async def gestao_whatsapp_modelo_salvar(req: Request) -> JSONResponse:
    from api.whatsapp import modelos as zmod
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie o modelo."})
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    modelo_id = body.get("id")
    modelo_id = int(modelo_id) if isinstance(modelo_id, int) else None
    try:
        d = zmod.gravar(body, usuario=autor, modelo_id=modelo_id)
    except zmod.ModeloInvalido as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_whatsapp_modelo_salvar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Não foi possível gravar o modelo."})
    # O TEXTO ENTRA NA AUDITORIA porque ele sai em nome da empresa: saber quem
    # escreveu "pague hoje para evitar protesto" importa tanto quanto saber
    # quem ligou o envio. Cortado em 200 para não empurrar a trilha para fora
    # da tela — o texto inteiro está no próprio modelo.
    auth.audit(autor or "?", "whatsapp_modelo",
               alvo=d["chave"],
               detalhe=(f"{'editado' if modelo_id else 'criado'} · "
                        f"contexto={d['contexto']} · ativo={d['ativo']} · "
                        f"{d['corpo'][:200]}"))
    return JSONResponse(d)


@app.post("/api/gestao/whatsapp/modelos/{modelo_id}/excluir")
def gestao_whatsapp_modelo_excluir(modelo_id: int, req: Request) -> JSONResponse:
    from api.whatsapp import modelos as zmod
    apagado = zmod.excluir(modelo_id)
    if not apagado:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Este modelo não existe mais."})
    sess = getattr(req.state, "sessao", None) or {}
    auth.audit(sess.get("email", "?"), "whatsapp_modelo_excluir",
               alvo=apagado["chave"], detalhe=apagado["nome"])
    return JSONResponse({"ok": True})


@app.get("/api/gestao/whatsapp/grupos")
async def gestao_whatsapp_grupos(instancia: str | None = None) -> JSONResponse:
    """Os grupos de que o número participa — para o seletor de envio.

    Só a Z-API sabe quais são. É por isso que a tela LISTA em vez de pedir o id
    digitado: id de grupo é uma sequência de 18 dígitos que ninguém decora e
    que, digitada com um erro, manda a mensagem para outro grupo qualquer.
    """
    from api.whatsapp import cliente as zcli
    qual = zcli.qual_valida(instancia)
    if not zcli.configurado(qual):
        return JSONResponse({"grupos": [], "erro": "Instância não configurada."})
    try:
        crus = await sem_travar(lambda: zcli.Cliente(qual=qual).grupos())
    except (zcli.ZapiIndisponivel, zcli.ZapiNaoConfigurado) as exc:
        return JSONResponse({"grupos": [], "erro": zcli._sanitizar(str(exc))})
    except Exception as exc:  # noqa: BLE001
        log.warning("grupos da z-api falharam: %s", type(exc).__name__)
        return JSONResponse({"grupos": [],
                             "erro": "Não foi possível ler os grupos agora."})
    # só o que a tela usa: id e nome. O resto da resposta da Z-API traz
    # participantes e telefones, que não têm por que trafegar para desenhar
    # um <select>
    grupos = [{"id": str(g.get("phone") or g.get("id") or ""),
               "nome": str(g.get("name") or g.get("subject") or "(sem nome)")}
              for g in crus if isinstance(g, dict)]
    return JSONResponse({"grupos": [g for g in grupos if g["id"]], "erro": ""})


@app.get("/api/gestao/whatsapp/playground")
def gestao_whatsapp_playground() -> JSONResponse:
    """O catálogo do playground. É documentação: nada a esconder."""
    from api.whatsapp import playground as zpg
    return JSONResponse({"endpoints": zpg.catalogo()})


@app.post("/api/gestao/whatsapp/playground")
async def gestao_whatsapp_playground_executar(req: Request) -> JSONResponse:
    """Executa UM endpoint do catálogo. Nunca uma URL livre.

    O caminho é montado por `playground.preparar()` a partir de um id — a tela
    manda id e parâmetros, jamais um endereço. É essa diferença que impede o
    playground de virar um proxy para `/send-text` sem limite, sem janela e sem
    trilha.
    """
    from api.whatsapp import cliente as zcli
    from api.whatsapp import playground as zpg
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    ident = str(body.get("id") or "")
    qual = zcli.qual_valida(body.get("instancia"))

    try:
        metodo, caminho = zpg.preparar(ident, body.get("params"))
    except zpg.ChamadaRecusada as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "recusado", "mensagem": str(exc)})

    e = zpg.POR_ID[ident]
    # ESCRITA vai para a auditoria SEMPRE, e antes de acontecer: `/disconnect`
    # derruba o WhatsApp da empresa, e a pergunta seguinte é sempre "quem fez?"
    if e["risco"] == zpg.ESCRITA:
        auth.audit(autor or "?", "whatsapp_playground", alvo=ident,
                   detalhe=f"{metodo} {caminho} · instância={qual}")
    try:
        dados = await sem_travar(
            lambda: zcli.Cliente(qual=qual).explorar(metodo, caminho))
    except (zcli.ZapiIndisponivel, zcli.ZapiNaoConfigurado) as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "zapi", "mensagem": zcli._sanitizar(str(exc))})
    except Exception as exc:  # noqa: BLE001
        log.warning("playground %s falhou: %s", ident, type(exc).__name__)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "falhou",
            "mensagem": f"A chamada falhou ({type(exc).__name__})."})

    # a resposta passa por _sanitizar: o token viaja na URL desta API, e um eco
    # de erro do fornecedor pode trazê-la de volta
    bruto = json.dumps(dados, ensure_ascii=False, indent=2, default=str)
    return JSONResponse({"metodo": metodo, "caminho": caminho,
                         "instancia": qual,
                         "resposta": zcli._sanitizar(bruto)[:20000]})


@app.get("/api/gestao/whatsapp/agenda")
def gestao_whatsapp_agenda() -> JSONResponse:
    """As rotinas agendadas, com o motivo de cada uma não estar pronta.

    O motivo é a informação: "por que a mensagem não saiu hoje?" é a pergunta
    que sempre aparece, e sem ela sobra abrir o log da tarefa do Windows.
    """
    from api.whatsapp import agenda as zag
    try:
        return JSONResponse(zag.estado())
    except Exception as exc:  # noqa: BLE001
        log.warning("gestao_whatsapp_agenda falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler as rotinas agendadas."})


@app.post("/api/gestao/whatsapp/agenda")
async def gestao_whatsapp_agenda_salvar(req: Request) -> JSONResponse:
    from api.whatsapp import agenda as zag
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie a rotina."})
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    try:
        d = await sem_travar(zag.gravar, body, autor)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("agenda de whatsapp falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Não foi possível gravar."})
    # LIGAR uma rotina é autorizar o sistema a falar com gente sozinho, todo
    # dia, sem ninguém olhando — é o que a auditoria precisa registrar
    auth.audit(autor or "?", "whatsapp_agenda", alvo=d["modelo"],
               detalhe=(f"{'editada' if body.get('id') else 'criada'} · "
                        f"ativo={d['ativo']} · {d['frequencia']} {d['hora']} · "
                        f"{d['destinatarios'][:80]}"))
    return JSONResponse(d)


@app.post("/api/gestao/whatsapp/agenda/{ident}/excluir")
def gestao_whatsapp_agenda_excluir(ident: int, req: Request) -> JSONResponse:
    from api.whatsapp import agenda as zag
    zag.remover(ident)
    sess = getattr(req.state, "sessao", None) or {}
    auth.audit(sess.get("email", "?"), "whatsapp_agenda_excluir", alvo=str(ident))
    return JSONResponse({"ok": True})


@app.post("/api/gestao/whatsapp/agenda/{ident}/testar")
async def gestao_whatsapp_agenda_testar(ident: int, req: Request) -> JSONResponse:
    """Roda a rotina AGORA, fora do horário.

    É o mesmo caminho do disparo automático — mesmo freio, mesma janela, mesma
    trilha. Não existe um "modo teste" mais frouxo: ele viraria o atalho para
    disparar sem as regras, que é como se perde o número.
    """
    from api.whatsapp import agenda as zag
    alvo = [x for x in zag.listar() if int(x["id"]) == ident]
    if not alvo:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Esta rotina não existe."})
    sess = getattr(req.state, "sessao", None) or {}
    linha = await sem_travar(zag.executar, alvo[0], forcado=True)
    auth.audit(sess.get("email", "?"), "whatsapp_agenda_testar",
               alvo=str(ident), detalhe=linha[:200])
    return JSONResponse({"ok": linha.startswith("OK"), "resultado": linha})


@app.get("/api/operacao/antt/rntrc")
def antt_rntrc(dt_de: str | None = None, dt_ate: str | None = None) -> JSONResponse:
    """Situação do RNTRC dos transportadores contratados no período."""
    from datetime import timedelta

    from api.antt.rntrc_servico import get_rntrc
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=365)).isoformat()   # 12 meses
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    try:
        return JSONResponse(get_rntrc(dt_de, dt_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("antt_rntrc falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao conferir o RNTRC dos transportadores.",
        })


@app.post("/api/operacao/antt/rntrc/atualizar")
async def antt_rntrc_atualizar(req: Request) -> JSONResponse:
    """Baixa a competência mais recente da base aberta da ANTT (~158 MB)."""
    from datetime import timedelta

    from api.antt.armazenamento import BaseVazia
    from api.antt.rntrc import LayoutInesperado
    from api.antt.rntrc_servico import atualizar_base
    hoje = date.today()
    try:
        # 158 MB de download: o event loop não pode ficar esperando por isso
        return JSONResponse(await sem_travar(
            atualizar_base,
            (hoje - timedelta(days=365)).isoformat(), hoje.isoformat()))
    except BaseVazia as exc:
        log.warning("sync do rntrc veio vazia: %s", exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "sync_vazia",
            "mensagem": ("A base da ANTT não trouxe nenhum dos transportadores "
                         "procurados. A base anterior foi mantida."),
        })
    except LayoutInesperado as exc:
        log.warning("layout do csv do rntrc mudou: %s", exc)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "layout_inesperado",
            "mensagem": f"O arquivo da ANTT mudou de formato: {exc}",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("antt_rntrc_atualizar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_sync",
            "mensagem": "Não foi possível atualizar a base do RNTRC.",
        })


@app.get("/api/suprimentos/agregados")
def agregados(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    modalidade: str | None = None,
    transportador: str | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if modalidade and modalidade not in ("AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "modalidade deve ser AGR (agregado) ou TER (terceiro).",
        })
    transportador = (transportador or "").strip() or None
    try:
        return JSONResponse(queries.get_agregados(
            filial, dt_de, dt_ate, modalidade=modalidade, transportador=transportador))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("agregados falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar agregados e terceiros.",
        })


@app.get("/api/operacao/make-vs-buy")
def make_vs_buy(comp_de: str | None = None, comp_ate: str | None = None) -> JSONResponse:
    import re
    hoje = date.today()
    # padrão: últimos 12 meses fechados
    ano, mes = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    comp_ate = comp_ate or f"{ano}-{mes:02d}"
    ano_de, mes_de = (ano - 1, mes + 1) if mes < 12 else (ano, 1)
    comp_de = comp_de or f"{ano_de}-{mes_de:02d}"
    for nome, valor in (("comp_de", comp_de), ("comp_ate", comp_ate)):
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM.",
            })
    if comp_de > comp_ate:
        comp_de, comp_ate = comp_ate, comp_de
    try:
        return JSONResponse(queries.get_make_vs_buy(comp_de, comp_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("make_vs_buy falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao calcular o make-vs-buy.",
        })


@app.get("/api/frota/combustivel")
def combustivel(
    dt_de: str | None = None,
    dt_ate: str | None = None,
    modalidade: str | None = None,
    placa: str | None = None,
    posto: str | None = None,
    combustivel: str | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if modalidade and modalidade not in ("proprio", "terceiros"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "modalidade deve ser proprio ou terceiros."})
    if posto and posto not in ("comercial", "interno"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "posto deve ser comercial ou interno."})
    placa = (placa or "").strip() or None
    combustivel = (combustivel or "").strip() or None
    try:
        return JSONResponse(queries.get_combustivel(
            dt_de, dt_ate, modalidade=modalidade, placa=placa, posto=posto,
            combustivel=combustivel))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("combustivel falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar combustível."})


@app.get("/api/frota/manutencao")
def manutencao(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    placa: str | None = None,
    status: str = "todas",
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if status not in ("todas", "abertas", "fechadas"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "status deve ser todas, abertas ou fechadas."})
    placa = (placa or "").strip() or None
    try:
        return JSONResponse(queries.get_manutencao(filial, dt_de, dt_ate, placa=placa,
                                                   status=status))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("manutencao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar manutenção."})


@app.get("/api/comercial/clientes-lista")
def comercial_clientes_lista() -> JSONResponse:
    """Nomes dos agrupamentos para o autocomplete da Consulta de Cliente.
    Rota separada de propósito: /clientes devolve o painel comercial inteiro
    (8 consultas) e seria desperdício só para preencher um datalist."""
    try:
        return JSONResponse(queries.get_clientes_lista())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("lista de clientes falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao listar os clientes."})


@app.get("/api/comercial/clientes")
def comercial_clientes(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    cliente: str | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    cliente = (cliente or "").strip() or None
    try:
        return JSONResponse(queries.get_comercial(filial, dt_de, dt_ate, cliente=cliente))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("comercial falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o comercial."})


@app.get("/api/visao-geral")
def visao_geral() -> JSONResponse:
    try:
        return JSONResponse(queries.get_visao_geral())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("visao_geral falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a visão geral."})


@app.get("/api/financeiro/cobranca")
def cobranca(filial: int | None = None, cliente: str | None = None) -> JSONResponse:
    cliente = (cliente or "").strip() or None
    try:
        return JSONResponse(queries.get_cobranca(filial, cliente=cliente))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("cobranca falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a cobrança."})


@app.get("/api/financeiro/fluxo-consolidado")
def fluxo_consolidado(gran: str = "semana", dias: int = 180) -> JSONResponse:
    """Fluxo de caixa na granularidade pedida — o formato da planilha de
    tesouraria, de diário a semestral."""
    GRANS = ("dia", "semana", "mes", "trimestre", "semestre")
    if gran not in GRANS:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": f"Granularidade inválida: use {', '.join(GRANS)}."})
    if not (7 <= dias <= 900):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Horizonte inválido: use entre 7 e 900 dias."})
    try:
        return JSONResponse(queries.get_fluxo_consolidado(gran=gran, dias=dias))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("fluxo_consolidado falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar o fluxo consolidado."})


@app.get("/api/financeiro/recorrentes")
def recorrentes(meses: int = 6, min_meses: int = 5) -> JSONResponse:
    """Contas que entram todo mês e ainda não foram lançadas neste."""
    if not (3 <= meses <= 24):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Use entre 3 e 24 meses de base."})
    if not (2 <= min_meses <= meses):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "min_meses precisa ficar entre 2 e o total de meses da base."})
    try:
        return JSONResponse(queries.get_recorrentes(meses=meses, min_meses=min_meses))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("recorrentes falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar os lançamentos recorrentes."})


@app.get("/api/financeiro/fluxo-consolidado/detalhe")
def fluxo_consolidado_detalhe(de: str, ate: str) -> JSONResponse:
    """Títulos que compõem um período do fluxo. Sob demanda, ao expandir."""
    for nome, valor in (("de", de), ("ate", ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if de > ate:
        de, ate = ate, de
    try:
        return JSONResponse(queries.get_fluxo_detalhe(de, ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("fluxo_detalhe falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao detalhar o período."})


@app.get("/api/financeiro/antecipacao")
def antecipacao(dias: int = 90, reserva: float = 0.0, taxa_mes: float = 2.0,
                incluir_vencidos: int = 0, exigir_portal: int = 0,
                sacados: str = "") -> JSONResponse:
    if dias not in (30, 60, 90, 120, 180):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Horizonte inválido: use 30, 60, 90, 120 ou 180 dias."})
    try:
        reserva = float(reserva or 0)
        taxa_mes = float(taxa_mes if taxa_mes is not None else 2.0)
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Reserva e taxa precisam ser números."})
    if reserva < 0:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "A reserva mínima não pode ser negativa."})
    # teto de 20% a.m. é grosseiro de propósito: taxa digitada errada (200 em vez
    # de 2,00) produziria um custo de antecipação absurdo com cara de cálculo
    if not (0 <= taxa_mes <= 20):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Taxa fora do razoável: informe o percentual ao mês (ex.: 2 para 2%)."})
    # `sacados` restringe DE QUEM antecipar, por RAIZ de CNPJ (8 digitos). Nao
    # aceita nome: o ERP fatura por filial ("IOCHPE MAXION - CRUZEIRO/SP" e
    # "- RESENDE/RJ") e o convenio e da matriz, entao casar por nome deixaria
    # metade do recebivel do mesmo cliente de fora.
    escolhidos: tuple[str, ...] = ()
    if (sacados or "").strip():
        cruas = [x.strip() for x in sacados.split(",") if x.strip()]
        if any(not x.isdigit() or len(x) < 8 for x in cruas):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": ("Informe o cliente pela raiz do CNPJ (8 dígitos), "
                             "separando com vírgula.")})
        escolhidos = tuple(dict.fromkeys(x[:8] for x in cruas))
        # RAIZ QUE NAO TEM CONVENIO E RECUSA, nao filtro vazio: aceitar em
        # silencio devolveria a tela zerada, que se le como "nao ha o que
        # antecipar" em vez de "voce escolheu quem nao pode".
        try:
            from api.antecipacoes import registro as antec_reg
            elegiveis = antec_reg.raizes_elegiveis()
        except Exception:  # noqa: BLE001 - base local fora nao barra a tela
            elegiveis = set()
        desconhecidas = [x for x in escolhidos if elegiveis and x not in elegiveis]
        if desconhecidas:
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": ("Sem convênio de antecipação: "
                             + ", ".join(desconhecidas)
                             + ". Só entra na simulação quem tem convênio "
                               "assinado.")})
    try:
        return JSONResponse(queries.get_antecipacao(
            dias=dias, reserva=reserva, taxa_mes=taxa_mes,
            incluir_vencidos=bool(int(incluir_vencidos or 0)),
            exigir_portal=bool(int(exigir_portal or 0)),
            sacados=escolhidos))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("antecipacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao calcular a antecipação de recebíveis."})


@app.get("/api/financeiro/lancamentos")
def lancamentos_bancarios(
    dt_de: str | None = None,
    dt_ate: str | None = None,
    conta: str | None = None,
    busca: str | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=30)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    conta = (conta or "").strip() or None
    busca = (busca or "").strip() or None
    try:
        return JSONResponse(queries.get_lancamentos_bancarios(dt_de, dt_ate, conta=conta, busca=busca))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("lancamentos_bancarios falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar os lançamentos bancários."})


@app.get("/api/bi/produtividade-veiculos")
def bi_produtividade_veiculos(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    modalidade: str | None = None,
) -> JSONResponse:
    """Produtividade por veículo — quanto cada um produz e quem produz pouco."""
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if modalidade and modalidade not in ("TRA", "LOC", "AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "modalidade deve ser TRA (frota), LOC (locação), AGR (agregado) ou TER (terceiro)."})
    try:
        return JSONResponse(queries.get_produtividade_veiculos(
            filial, dt_de, dt_ate, modalidade=modalidade))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "O banco do ERP não respondeu."})
    except Exception as exc:  # noqa: BLE001
        log.warning("produtividade de veiculos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar a produtividade de veículos."})


@app.get("/api/operacao/analise-km")
def analise_km(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    modalidade: str | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=90)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    if modalidade and modalidade not in ("TRA", "LOC", "AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "modalidade deve ser TRA (frota), LOC (locação), AGR (agregado) ou TER (terceiro)."})
    try:
        return JSONResponse(queries.get_analise_km(filial, dt_de, dt_ate, modalidade=modalidade))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("analise_km falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a análise de km."})


@app.get("/api/jornada/diarias")
def jornada_diarias(de: str | None = None, ate: str | None = None) -> JSONResponse:
    """Diária paga (folha) × dias trabalhados (jornada).

    As duas fontes vivem em BANCOS diferentes — a folha no AVA, a jornada no
    Postgres local —, então o cruzamento é em Python e a chave é o nome
    normalizado. `def` e não `async def`: são duas consultas pesadas, e num
    `async def` elas travariam o event loop.
    """
    from datetime import date, timedelta
    from api.jornada import diarias as _di
    hoje = date.today()
    try:
        d_de = date.fromisoformat(de) if de else (hoje.replace(day=1)
                                                 - timedelta(days=365))
        d_ate = date.fromisoformat(ate) if ate else hoje
    except ValueError:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Data inválida (AAAA-MM-DD)."})
    try:
        dados = _di.levantar(d_de.replace(day=1), d_ate)
        # A competência ABERTA é a do mês corrente: a folha ainda não fechou, e
        # sem marcar isso ela aparece como despencando.
        mes = _di.mensal(dados, competencia_aberta=hoje.strftime("%Y-%m"))
        top, total_mot = _di.por_motorista(dados)
        return JSONResponse({
            "kpis": _di.resumo(dados, mes),
            "mensal": mes, "motoristas": top, "motoristas_total": total_mot,
            "sem_diaria": sorted(dados["sem_diaria"],
                                 key=lambda x: -x["dias"])[:30],
            "sem_diaria_total": len(dados["sem_diaria"]),
            "de": d_de.isoformat(), "ate": d_ate.isoformat(),
            "fonte": "folha GLOBUS (AVA) × jornada RasterJOR (CÓRTEX)",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_diarias: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao cruzar diárias com a jornada."})


@app.get("/api/operacao/torre/chegadas")
def torre_chegadas(forcar: int = 0) -> JSONResponse:
    """Chegada estimada com trânsito × prometida no ERP.

    Rota SEPARADA da condição da estrada, e com TTL próprio de 30 min: a
    previsão de uma viagem de horas não melhora sendo recalculada a cada dez
    minutos, e cada recálculo custa ~50 chamadas de ROTA — que é a família
    mais apertada da TomTom (429 a partir de ~6 req/s).
    """
    from api.tomtom import eta
    try:
        return JSONResponse(eta.previsoes(forcar=bool(forcar)))
    except Exception as exc:  # noqa: BLE001
        log.warning("torre_chegadas: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao estimar as chegadas."})


@app.get("/api/operacao/torre/estradas")
def torre_estradas(forcar: int = 0, tolerancia: int = 0) -> JSONResponse:
    """Condição da estrada onde cada caminhão EM VIAGEM está agora (TomTom).

    ROTA SEPARADA da Torre, de propósito: são ~70 chamadas a uma API de
    terceiro, com TTL de 10 min. Pendurá-la no payload da Torre — que recarrega
    a cada 2 min — faria a tela inteira esperar pelo trânsito, e faria o
    consumo da TomTom seguir a recarga do mapa em vez de seguir o uso.

    `def` e não `async def`: a varredura faz I/O de rede, e num `async def` ela
    travaria o event loop, isto e, o CÓRTEX inteiro pelo tempo da coleta.
    """
    from api.tomtom import coleta
    try:
        # `tolerancia` em segundos: o painel de TV manda 1200 porque roda
        # sozinho o dia inteiro e não pode ditar o consumo da TomTom.
        return JSONResponse(coleta.condicao_da_frota(
            forcar=bool(forcar),
            idade_maxima_s=int(tolerancia) if tolerancia else None))
    except Exception as exc:  # noqa: BLE001
        log.warning("torre_estradas: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar a condição das estradas."})


@app.get("/api/operacao/torre")
def torre(filial: int | None = None) -> JSONResponse:
    try:
        return JSONResponse(queries.get_torre(filial))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("torre falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a torre de controle."})


@app.get("/api/frota/veiculos")
def veiculos(modalidade: str | None = None, situacao: str = "ativos",
             grupo: str | None = None) -> JSONResponse:
    if modalidade and modalidade not in ("TRA", "LOC", "AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "modalidade deve ser TRA, LOC, AGR ou TER."})
    if situacao not in ("ativos", "todos"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "situacao deve ser ativos ou todos."})
    if grupo and grupo not in ("tracao", "impl", "apoio", "nd"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "grupo deve ser tracao, impl, apoio ou nd."})
    try:
        return JSONResponse(queries.get_veiculos(modalidade=modalidade, situacao=situacao,
                                                 grupo=grupo))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("veiculos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar os veículos."})


def _telas_do_usuario(req: Request) -> tuple[int, set[str]]:
    """Quem e a pessoa e o que ela pode ver. Base de tudo aqui.

    A sessao sai de `req.state.sessao`, que o AuthMiddleware ja preencheu --
    e nao de uma leitura propria do cookie: duas nocoes de "quem esta logado"
    divergem no dia em que a sessao expira no meio da requisicao.

    ADMIN VE TUDO. `sess["telas"]` do administrador nao lista as telas uma a
    uma (o middleware o libera por `sess["admin"]`), entao usar aquele
    conjunto como filtro esconderia todas as telas dele.
    """
    from api import auth
    sess = getattr(req.state, "sessao", None)
    if not sess or not sess.get("id"):
        raise PermissionError("sem sessão")
    return int(sess["id"]), auth.telas_favoritaveis(sess)


@app.get("/api/notificacoes")
def notificacoes_listar(req: Request) -> JSONResponse:
    """As notificações do usuário logado — o que alimenta o sino.

    Vale para TODO usuário autenticado, e por isso está em
    `auth._ROTAS_SEM_TELA`: sem essa entrada o `AuthMiddleware` devolveria 403
    para quem não é administrador, e o sino apareceria para todos funcionando
    só para um — o defeito que o botão de report já teve.
    """
    from api import notificacoes
    sess = getattr(req.state, "sessao", None)
    if not sess:
        return JSONResponse(status_code=401, content={
            "erro": "nao_autenticado", "mensagem": "Faça login para continuar."})
    try:
        return JSONResponse(notificacoes.listar(sess))
    except Exception as exc:  # noqa: BLE001
        log.warning("notificacoes_listar: %s: %s", type(exc).__name__, exc)
        # Sino é acessório: ele não pode derrubar a barra de topo, que segura o
        # menu inteiro. Devolve vazio com a marca de falha e a tela se cala.
        return JSONResponse({"itens": [], "nao_lidas": 0, "erro": True})


@app.post("/api/notificacoes/lida")
async def notificacoes_lida(req: Request) -> JSONResponse:
    """Dispensa uma notificação. Idempotente.

    Chave desconhecida é RECUSA (4xx), não erro do servidor: o CÓRTEX
    funcionou e está dizendo não. E 5xx aqui seria pior que impreciso — o
    Cloudflare troca o corpo das respostas 5xx da origem pela página de erro
    dele, e a mensagem nunca chegaria à tela.
    """
    from api import notificacoes
    sess = getattr(req.state, "sessao", None)
    if not sess:
        return JSONResponse(status_code=401, content={
            "erro": "nao_autenticado", "mensagem": "Faça login para continuar."})
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    chave = str((corpo or {}).get("chave") or "").strip()
    if not chave or not notificacoes.marcar_lida(sess["id"], chave):
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "chave_desconhecida",
            "mensagem": "Notificação desconhecida: %s." % (chave or "(vazia)")})
    # Devolve a lista JÁ ATUALIZADA: sem isso a tela teria de fazer uma segunda
    # chamada para saber o novo número do sino, e entre as duas ela mostraria
    # um contador que não corresponde ao que está na tela.
    return JSONResponse(notificacoes.listar(sess))


@app.get("/api/favoritos")
def favoritos_listar(req: Request) -> JSONResponse:
    """Os favoritos do usuário logado, já filtrados pelo que ele pode ver."""
    from api import favoritos
    try:
        uid, telas = _telas_do_usuario(req)
    except PermissionError:
        return JSONResponse(status_code=401, content={
            "erro": "nao_autenticado", "mensagem": "Faça login para continuar."})
    try:
        return JSONResponse({"favoritos": favoritos.listar(uid, telas),
                             "limite": favoritos.LIMITE})
    except Exception as exc:  # noqa: BLE001
        log.warning("favoritos_listar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler seus favoritos."})


@app.post("/api/favoritos")
async def favoritos_alternar(req: Request) -> JSONResponse:
    """Liga/desliga um favorito. Devolve a lista inteira, já filtrada.

    Devolve a LISTA e não só o estado do item: a tela precisa repintar o menu,
    e deixá-la remontar a lista por conta própria criaria uma segunda verdade
    sobre a ordem.
    """
    from api import favoritos
    try:
        uid, telas = _telas_do_usuario(req)
    except PermissionError:
        return JSONResponse(status_code=401, content={
            "erro": "nao_autenticado", "mensagem": "Faça login para continuar."})
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    tela = (corpo or {}).get("tela")
    ordem = (corpo or {}).get("ordem")
    try:
        if isinstance(ordem, list):
            lista = favoritos.reordenar(uid, [str(x) for x in ordem], telas)
            return JSONResponse({"favoritos": lista,
                                 "limite": favoritos.LIMITE})
        r = favoritos.alternar(uid, tela, telas)
        return JSONResponse({**r, "favoritos": favoritos.listar(uid, telas),
                             "limite": favoritos.LIMITE})
    except PermissionError as exc:
        # 4xx e nao 5xx: o CORTEX funcionou e esta dizendo NAO, com um motivo
        # que a pessoa precisa LER. E o Cloudflare troca o corpo dos 5xx.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "sem_acesso", "mensagem": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "recusado", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("favoritos_alternar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao gravar seu favorito."})


@app.get("/api/frota/veiculos/identidade")
def frota_veiculos_identidade() -> JSONResponse:
    """O De-Para placa -> identidade, e o que o cadastro tem de errado.

    UMA chamada serve TODAS as telas. A alternativa era acrescentar uma coluna
    `frota` a 132 consultas de `queries.py` — varredura enorme, arriscada, e
    que ainda deixaria de fora as telas alimentadas pela Gobrax, que só conhece
    placa. São ~1.900 linhas de dois campos curtos.
    """
    from api import frota_identidade as fi
    try:
        linhas = fi.linhas()
        return JSONResponse({
            "mapa": fi.mapa(linhas),
            "pendencias": fi.pendencias(linhas),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("frota_veiculos_identidade falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao ler a identidade dos veículos."})


@app.get("/api/frota/veiculo")
def veiculo_ficha(placa: str | None = None, dias: int = 30) -> JSONResponse:
    placa = (placa or "").strip()
    if not placa:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe a placa do veículo."})
    if dias not in (30, 60, 90, 180):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "dias deve ser 30, 60, 90 ou 180."})
    try:
        return JSONResponse(queries.get_veiculo_ficha(placa, dias=dias))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("veiculo_ficha falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o veículo."})


@app.get("/api/comercial/crm")
def crm() -> JSONResponse:
    try:
        return JSONResponse(queries.get_crm())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("crm falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o CRM."})


@app.get("/api/comercial/cliente")
def cliente_ficha(cliente: str | None = None, comp_de: str | None = None,
                  comp_ate: str | None = None) -> JSONResponse:
    import re
    if not (cliente or "").strip():
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe o cliente."})
    hoje = date.today()
    comp_ate = comp_ate or f"{hoje.year}-{hoje.month:02d}"
    comp_de = comp_de or f"{hoje.year}-01"
    for nome, valor in (("comp_de", comp_de), ("comp_ate", comp_ate)):
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM."})
    if comp_de > comp_ate:
        comp_de, comp_ate = comp_ate, comp_de
    try:
        return JSONResponse(queries.get_cliente_ficha(cliente, comp_de, comp_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("cliente_ficha falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o cliente."})


def _comp_defaults(comp_de: str | None, comp_ate: str | None):
    """Normaliza/valida competência AAAA-MM (default: ano corrente até o mês
    atual). Devolve (comp_de, comp_ate) ou uma JSONResponse 422 de erro."""
    import re
    hoje = date.today()
    comp_ate = comp_ate or f"{hoje.year}-{hoje.month:02d}"
    comp_de = comp_de or f"{hoje.year}-01"
    for nome, valor in (("comp_de", comp_de), ("comp_ate", comp_ate)):
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM."})
    if comp_de > comp_ate:
        comp_de, comp_ate = comp_ate, comp_de
    return comp_de, comp_ate


@app.post("/api/jornada/coletar")
async def jornada_coletar(req: Request) -> JSONResponse:
    """Dispara uma coleta agora. MESMO caminho da tarefa agendada.

    Não existe "modo teste" mais frouxo: a coleta da tela é a mesma chamada,
    com a mesma trilha em `jor_carga` e a mesma janela. Caminho paralelo vira
    o atalho para rodar sem registro.

    `sem_travar` porque a coleta faz I/O de rede: numa rota `async def` isso
    trava o event loop e o CÓRTEX inteiro para de responder pelo tempo da
    chamada — foi assim que o envio de WhatsApp derrubou o painel por minutos.
    """
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    from api.jornada import coleta as jcol
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    try:
        r = await sem_travar(lambda: jcol.coletar(
            de=body.get("de") or None, ate=body.get("ate") or None))
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_coletar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_coleta",
            "mensagem": "Não foi possível rodar a coleta da jornada."})
    auth.audit(autor or "?", "jornada_coletar",
               alvo=f"{r['de']}..{r['ate']}",
               detalhe=" · ".join(f"{k}:{v['gravados']}"
                                  for k, v in r["recursos"].items()) or r["erro"])
    # RECUSA NÃO É 5xx: sem credencial o CÓRTEX está dizendo NÃO com um motivo
    # que a pessoa precisa ler, e o Cloudflare troca o corpo dos 5xx pelo dele.
    if not r["ok"] and not r["recursos"]:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "nao_configurado", "mensagem": r["erro"]})
    return JSONResponse(r)


@app.get("/api/operacao/custos-extras")
def custos_extras(dt_de: str | None = None, dt_ate: str | None = None) -> JSONResponse:
    hoje = date.today()
    dt_de = dt_de or f"{hoje.year}-01-01"
    dt_ate = dt_ate or hoje.isoformat()
    try:
        return JSONResponse(queries.get_custos_extras(dt_de, dt_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("custos_extras falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar os custos extras."})


@app.get("/api/rh/vagas")
def rh_vagas() -> JSONResponse:
    try:
        return JSONResponse(queries.get_rh())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("rh_vagas falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar as vagas de RH."})


def _folha_erro(exc: Exception) -> JSONResponse:
    import oracledb
    if isinstance(exc, oracledb.Error) or isinstance(exc, RuntimeError):
        log.warning("folha indisponivel (Oracle): %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "folha_indisponivel",
            "mensagem": "Sem conexão com o banco da folha (GLOBUS/Oracle). "
                        "Rode a partir da máquina de produção (mesma rede) e confira o .env."})
    log.warning("folha falhou: %s", exc)
    return JSONResponse(status_code=500, content={
        "erro": "erro_consulta", "mensagem": "Erro ao consultar a folha."})


@app.get("/api/rh/headcount")
def rh_headcount() -> JSONResponse:
    try:
        return JSONResponse(queries_folha.get_headcount())
    except Exception as exc:  # noqa: BLE001
        return _folha_erro(exc)


@app.get("/api/frota/pneus/ficha")
def frota_pneus_ficha(serie: str = "") -> JSONResponse:
    """UM pneu pelo numero de serie, para a tela de registro.

    O ESTADO ATUAL VEM JUNTO e e o campo que mais importa aqui: e ele que
    decide o que a pessoa pode fazer, e ver "sucata" na tela antes de tentar
    montar poupa uma recusa que pareceria arbitraria.
    """
    from api import pglocal
    alvo = (serie or "").strip()
    if len(alvo) < 2:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "serie_curta", "mensagem": "Informe o numero de serie."})
    try:
        r = pglocal.query("""
            SELECT p.id, p.serie, p.status, p.vida_atual AS vida,
                   upper(trim(p.placa_atual)) AS placa, p.posicao_atual AS posicao,
                   m.marca, m.modelo, m.medida
            FROM pne_pneu p LEFT JOIN pne_modelo m ON m.id = p.modelo_id
            WHERE upper(trim(p.serie)) = upper(%s) LIMIT 1""", (alvo,))
    except Exception as exc:  # noqa: BLE001
        log.warning("pneus/ficha falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "ficha_indisponivel",
            "mensagem": "Nao foi possivel consultar agora."})
    if not r:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "nao_encontrado",
            "mensagem": "Nenhum pneu com essa serie."})
    return JSONResponse(dict(r[0]))


@app.get("/api/frota/pneus/recentes")
def frota_pneus_recentes(limite: int = 30) -> JSONResponse:
    """Os ultimos movimentos que ESTA CASA gravou.

    SO ORIGEM `cortex`, de proposito: a lista existe para mostrar o que ja
    migrou para ca, separado dos 6 mil eventos importados. Misturar os dois
    esconderia justamente o numero que interessa acompanhar.
    """
    from api import pglocal
    try:
        r = pglocal.query("""
            SELECT e.ocorrido_em AS quando, p.serie, e.tipo, e.placa, e.posicao,
                   e.km_veiculo AS km, e.usuario, e.motivo
            FROM pne_evento e JOIN pne_pneu p ON p.id = e.pneu_id
            WHERE e.origem = 'cortex'
            ORDER BY e.ocorrido_em DESC LIMIT %s""",
            (max(1, min(200, limite)),))
    except Exception as exc:  # noqa: BLE001
        log.warning("pneus/recentes falhou: %s", type(exc).__name__)
        return JSONResponse({"itens": []})
    return JSONResponse({"itens": [
        {**dict(x), "quando": x["quando"].isoformat() if x["quando"] else None,
         "km": float(x["km"]) if x["km"] is not None else None} for x in r]})


@app.get("/api/frota/pneus/posicoes")
def frota_pneus_posicoes(placa: str = "") -> JSONResponse:
    """As posicoes que um veiculo aceita, para a tela nao deixar digitar.

    Campo livre de posicao e o jeito de encher o banco de `3DE` em carreta de
    dois eixos. A lista sai do diagrama do veiculo cruzado com o que os
    veiculos IRMAOS realmente tem montado.
    """
    from api.pneus import movimento
    try:
        return JSONResponse(movimento.posicoes_do_veiculo(placa))
    except Exception as exc:  # noqa: BLE001
        log.warning("pneus/posicoes falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "posicoes_indisponiveis",
            "mensagem": "Nao foi possivel ler as posicoes do veiculo."})


@app.post("/api/frota/pneus/movimento")
async def frota_pneus_movimento(req: Request) -> JSONResponse:
    """Registra um movimento de pneu NO CORTEX.

    RECUSA E 4xx, NAO 5xx. `MovimentoInvalido` e uma recusa legivel — "a
    posicao ja esta com o pneu X" e informacao para quem digitou, e ela tem de
    CHEGAR: o Cloudflare troca o corpo de 5xx pela pagina dele e a mensagem
    morre no caminho.

    `sem_travar` porque a rota e `async` e tudo aqui e I/O de banco: sem ele o
    servidor INTEIRO para pelo tempo da escrita.
    """
    from api.pneus.movimento import MovimentoInvalido
    from api.pneus import movimento

    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        corpo = {}
    if not isinstance(corpo, dict):
        corpo = {}

    quem = (getattr(req.state, "sessao", None) or {}).get("email") or ""
    ip = _ip_do_cliente(req)
    acao = (corpo.get("acao") or "").strip().lower()
    try:
        pneu = int(corpo.get("pneu") or 0)
    except (TypeError, ValueError):
        pneu = 0
    # CRIAR NAO TEM PNEU AINDA — e a unica acao que nasce sem um. Exigir o
    # identificador aqui recusaria justamente o cadastro do pneu novo.
    if not pneu and acao != "criar":
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "sem_pneu", "mensagem": "Informe o pneu."})

    try:
        if acao == "instalar":
            r = await sem_travar(movimento.instalar, pneu,
                                 corpo.get("placa") or "",
                                 corpo.get("posicao") or "",
                                 corpo.get("km"), quem, ip)
        elif acao == "remover":
            r = await sem_travar(movimento.remover, pneu, corpo.get("km"),
                                 corpo.get("motivo") or "", quem, ip)
        elif acao == "sucatear":
            r = await sem_travar(movimento.sucatear, pneu,
                                 int(corpo.get("motivo_id") or 0), quem, ip)
        elif acao == "criar":
            r = await sem_travar(movimento.criar,
                                 corpo.get("numero_fogo") or "",
                                 corpo.get("marca") or "",
                                 corpo.get("modelo") or "",
                                 corpo.get("medida") or "",
                                 corpo.get("dot") or "",
                                 corpo.get("custo"),
                                 corpo.get("filial") or "", quem, ip)
        elif acao == "inspecionar":
            r = await sem_travar(movimento.inspecionar, pneu,
                                 corpo.get("sulcos") or [],
                                 corpo.get("pressao"), corpo.get("km"),
                                 quem, ip)
        else:
            return JSONResponse(status_code=HTTP_RECUSA, content={
                "erro": "acao_desconhecida",
                "mensagem": "Acao invalida. Use criar, instalar, remover, "
                            "sucatear ou inspecionar."})
    except MovimentoInvalido as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "movimento_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        # AQUI SIM e falha NOSSA, e o tipo vai para o log sem o `str(exc)`
        # cru: mensagem de excecao de banco carrega SQL e as vezes valor.
        log.warning("pneus/movimento (%s) falhou: %s", acao, type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_interno",
            "mensagem": "Nao foi possivel registrar o movimento."})
    return JSONResponse(r)


@app.get("/api/frota/pneus/motivos")
def frota_pneus_motivos() -> JSONResponse:
    """Os motivos de baixa, para a tela oferecer LISTA e nao campo livre."""
    from api import pglocal
    try:
        return JSONResponse({"motivos": [
            dict(r) for r in pglocal.query(
                "SELECT id, rotulo FROM pne_motivo "
                "WHERE especie = 'descarte' AND ativo ORDER BY rotulo")]})
    except Exception as exc:  # noqa: BLE001
        log.warning("pneus/motivos falhou: %s", type(exc).__name__)
        return JSONResponse({"motivos": []})


@app.get("/api/frota/pneus/troca")
def frota_pneus_troca(dias: int = 365) -> JSONResponse:
    """Previsao de troca por DESGASTE MEDIDO — nao por calendario.

    Rota separada da do instantaneo pela mesma razao do CPK: ela nao depende da
    Prolog e nao pode morrer quando a cota de la estoura.
    """
    from api.pneus import servico
    try:
        return JSONResponse(servico.troca(max(30, min(1095, dias))))
    except Exception as exc:  # noqa: BLE001
        log.warning("pneus/troca falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "troca_indisponivel",
            "mensagem": "Nao foi possivel calcular a previsao de troca agora."})


@app.get("/api/frota/pneus/rendimento")
def frota_pneus_rendimento(dias: int = 365) -> JSONResponse:
    """O CPK dos pneus instalados, por pneu e por modelo.

    NAO PASSA PELA PROLOG, e essa e a diferenca deste bloco para o resto da
    tela: o instantaneo da Prolog diz o que existe e onde esta; o CPK sai do
    banco da casa cruzado com o ERP (odometro do abastecimento e engate do
    manifesto). Quando a Prolog for desligada, este numero continua saindo.

    Rota SEPARADA da `/api/frota/pneus` de proposito: aquela morre quando a
    cota da Prolog estoura, e o CPK nao tem por que morrer junto.
    """
    from api.pneus import servico
    try:
        return JSONResponse(servico.rendimento(max(30, min(1095, dias))))
    except Exception as exc:  # noqa: BLE001
        log.warning("pneus/rendimento falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "rendimento_indisponivel",
            "mensagem": "Nao foi possivel calcular o CPK agora."})


@app.get("/api/frota/pneus")
def frota_pneus(status: str = "", filial: str = "") -> JSONResponse:
    """Gestao de pneus (Prolog). `status` filtra INVENTORY/ANALYSIS/INSTALLED/
    DISPOSAL; vazio traz todos."""
    from api.pneus import servico
    from api.pneus.cliente import PrologIndisponivel, PrologNaoConfigurado
    try:
        return JSONResponse(servico.obter(status=status, filial=filial))
    except PrologNaoConfigurado as exc:
        return JSONResponse(status_code=503, content={
            "erro": "prolog_nao_configurado", "mensagem": str(exc)})
    except PrologIndisponivel as exc:
        return JSONResponse(status_code=503, content={
            "erro": "prolog_indisponivel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("frota_pneus falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a tela de pneus."})


@app.post("/api/fiscal/contrapartida/autorizacao")
def fiscal_contrapartida_autorizacao(payload: dict, req: Request) -> JSONResponse:
    """Registra a AUTORIZACAO para emitir em nome do agregado.

    O instrumento (procuracao, clausula de contrato, termo) e decisao do
    juridico. O que o software exige e escopo, validade e autor - sem data de
    fim ele nao sabe parar quando o agregado sai da frota.
    """
    from api.contrapartida import cadastro
    # a sessao e quem responde pela autorizacao: trilha com "?" nao serve
    # para nada meses depois, que e exatamente quando ela e consultada
    _s = getattr(req.state, "sessao", None) or {}
    quem = _s.get("email") or _s.get("nome") or "?"
    try:
        return JSONResponse(cadastro.gravar_autorizacao(
            str(payload.get("cnpj") or "").strip(),
            str(payload.get("escopo") or "").strip(),
            str(payload.get("valida_de") or "").strip(),
            str(payload.get("valida_ate") or "").strip(),
            quem, str(payload.get("observacao") or "").strip()))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("gravar autorizacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao gravar a autorizacao."})


@app.post("/api/fiscal/contrapartida/certificado")
def fiscal_contrapartida_certificado(payload: dict, req: Request) -> JSONResponse:
    """Recebe o .pfx em base64 NO CORPO, com a senha.

    No corpo e nao em query nem header de proposito: URL e cabecalho aparecem
    em log de servidor e de proxy, e senha de certificado em log e vazamento
    permanente. O corpo de um POST nao e registrado.

    O arquivo e ABERTO aqui com a senha: se abre, titular e validade saem do
    proprio certificado - dado que nao precisa ser digitado e por isso nao
    pode ser digitado errado. Senha errada vira 422 agora, e nao rejeicao
    documento a documento na transmissao.
    """
    import base64
    from api.contrapartida import cadastro
    from api.contrapartida.certificado import (MAX_BYTES, CertificadoInvalido,
                                               conferir_titularidade, ler,
                                               senha_que_abre)
    # a sessao e quem responde pela autorizacao: trilha com "?" nao serve
    # para nada meses depois, que e exatamente quando ela e consultada
    _s = getattr(req.state, "sessao", None) or {}
    quem = _s.get("email") or _s.get("nome") or "?"
    cnpj = str(payload.get("cnpj") or "").strip()
    tipo = str(payload.get("tipo") or "A1").strip().upper()
    if not cnpj:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe o CNPJ do agregado."})
    if tipo == "A3":
        # A3 nao tem arquivo: registra o impedimento para a tela explicar por
        # que aquele agregado nunca fica pronto, em vez de ficar sem resposta.
        try:
            cadastro.gravar_certificado(cnpj, "A3", quem,
                                        titular=str(payload.get("titular") or ""))
            return JSONResponse({"ok": True, "tipo": "A3", "avisos": [
                "Certificado A3 registrado como impedimento: ele mora em token "
                "fisico e exige presenca a cada assinatura, entao nao automatiza."]})
        except ValueError as exc:
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": str(exc)})
    senha = str(payload.get("senha") or "")
    b64 = str(payload.get("arquivo_b64") or "")
    if not (senha and b64):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Envie o arquivo .pfx e a senha."})
    try:
        bruto = base64.b64decode(b64, validate=True)
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Arquivo invalido."})
    if len(bruto) > MAX_BYTES:
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima de {MAX_BYTES // (1024*1024)} MB."})
    try:
        lido = ler(bruto, senha)
    except CertificadoInvalido as exc:
        return JSONResponse(status_code=422, content={
            "erro": "certificado_invalido", "mensagem": str(exc)})
    avisos = []
    if lido.get("aviso_senha"):
        avisos.append(lido["aviso_senha"])
    conf = conferir_titularidade(lido, cnpj)
    if conf:
        avisos.append(conf)
    if lido["vencido"]:
        avisos.append(f"O certificado venceu em {lido['valida_ate']}: ele fica "
                      "cadastrado, mas o agregado nao aparece como autorizado.")
    try:
        cadastro.DIR_CERT.mkdir(parents=True, exist_ok=True)
        alvo = cadastro.DIR_CERT / f"{cnpj}.pfx"
        alvo.write_bytes(bruto)
        segredo_arquivo.proteger(alvo)   # ACL de verdade, nao so chmod
        cadastro.gravar_certificado(
            cnpj, "A1", quem, arquivo=alvo.name,
            valida_ate=lido["valida_ate"], titular=lido["titular"],
            # a senha que ABRIU (pode ser a variante sem o espaço colado do
            # copiar-e-colar) — gravar a digitada quebraria a transmissão
            senha=senha_que_abre(bruto, senha) or senha)
    except Exception as exc:  # noqa: BLE001
        log.warning("gravar certificado falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao gravar o certificado."})
    # a senha NAO volta, nem mascarada
    return JSONResponse({"ok": True, "titular": lido["titular"],
                         "valida_ate": lido["valida_ate"], "dias": lido["dias"],
                         "avisos": avisos})


@app.get("/api/fiscal/contrapartida")
def fiscal_contrapartida(de: str = "", ate: str = "",
                         busca: str = "") -> JSONResponse:
    """Conciliacao do CT-e de contrapartida do agregado.

    So LEITURA. Nao emite, nao assina, nao transmite: emissao em nome de
    terceiro depende de procuracao vigente, certificado A1 e enquadramento
    fiscal definido, e nenhuma das tres e decisao de software.
    """
    from api.contrapartida import servico
    for nome, valor in (("de", de), ("ate", ate)):
        if valor and _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parametro {nome} invalido: use AAAA-MM-DD."})
    try:
        return JSONResponse(servico.get_contrapartida(de or None, ate or None,
                                                      busca or None))
    except Exception as exc:  # noqa: BLE001
        log.warning("fiscal_contrapartida falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar a conciliacao de contrapartida."})


@app.get("/api/operacional/poligonos")
def operacional_poligonos(de: str = "", ate: str = "",
                          uso: str = "") -> JSONResponse:
    """Permanencia nos poligonos mapeados dentro da planta do cliente.

    `uso` filtra a modalidade da placa (TRA/AGR/LOC/TER, separadas por
    virgula): 48 das 70 placas que entram na planta sao de AGREGADO, e sem a
    quebra o tempo perdido aparece como se fosse todo da frota propria.
    """
    from api.poligonos import servico
    try:
        return JSONResponse(servico.get_poligonos(de=de or None,
                                                  ate=ate or None,
                                                  uso=uso or None))
    except ValueError as exc:               # data mal formada no filtro
        return JSONResponse(status_code=400, content={
            "erro": "periodo_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("operacional_poligonos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar a tela de permanencia na planta."})


@app.get("/api/rh/ferias")
def rh_ferias(dias: int = 90, filial: str = "", chapa: str = "",
              dt_de: str = "", dt_ate: str = "") -> JSONResponse:
    """Vencimento de ferias pela regra da CLT (aquisitivo + 12 meses = dobra).

    Devolve NOME e CHAPA pela mesma razao da tela de CNH: ninguem agenda as
    ferias de "um funcionario". Salario, CPF e dado bancario ficam fora.

    `chapa` recorta um colaborador. E a chapa, e nao o nome: nome se repete,
    muda com casamento e chega com o espacamento que o ERP gravou.
    """
    from api.queries_folha import get_ferias
    try:
        return JSONResponse(get_ferias(dias=dias, filial=filial, chapa=chapa,
                                       dt_de=dt_de, dt_ate=dt_ate))
    except Exception as exc:  # noqa: BLE001
        log.warning("rh_ferias falhou: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "globus_indisponivel",
            "mensagem": "Sem conexao com o banco da folha (GLOBUS)."})


@app.get("/api/rh/ferias/custo")
def rh_ferias_custo(dt_de: str = "", dt_ate: str = "", filial: str = "",
                    chapa: str = "") -> JSONResponse:
    """Custo de ferias: o realizado na ficha e o passivo ainda nao gozado.

    Rota MAIS ESPECIFICA que /api/rh/ferias, e o `ROTA_TELAS` casa por
    PREFIXO — as duas caem na mesma tela `ferias`, que e o que se quer: quem
    ve o vencimento ve o custo dele. Nao ha entrada nova de RBAC a criar.

    Nao devolve nome, chapa nem salario individual: aqui tudo e agregado por
    unidade e por natureza de evento.
    """
    from api.rh.ferias_custo import get_ferias_custo
    try:
        return JSONResponse(get_ferias_custo(
            dt_de=dt_de, dt_ate=dt_ate, filial=filial, chapa=chapa))
    except Exception as exc:  # noqa: BLE001
        log.warning("rh_ferias_custo falhou: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "globus_indisponivel",
            "mensagem": "Sem conexao com o banco da folha (GLOBUS)."})


@app.get("/api/rh/people")
def rh_people(escopo: str = "todos") -> JSONResponse:
    """People Analytics: afastados, sucessao, dispersao salarial e custo por
    area. Devolve nome so na lista de afastados, que e onde o RH precisa agir.

    `escopo` recorta a tela INTEIRA em todos | lideranca | demais. Valor
    desconhecido cai em "todos" dentro de get_people, e nao em recusa: um
    recorte digitado errado na URL nao pode deixar a tela em branco."""
    from api.people import get_people
    try:
        return JSONResponse(get_people(escopo))
    except Exception as exc:  # noqa: BLE001
        log.warning("rh_people falhou: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "globus_indisponivel",
            "mensagem": "Sem conexao com o banco da folha (GLOBUS)."})


@app.get("/api/rh/cnh")
def rh_cnh(dias: int = 90, filial: str = "", categoria: str = "") -> JSONResponse:
    """Vencimento de CNH dos motoristas ativos (GLOBUS).

    Devolve NOME e CHAPA — exceção deliberada à regra de só-agregados da folha:
    sem eles a tela não é acionável, porque ninguém cobra a renovação de "um
    motorista". CPF, salário e o número da CNH continuam fora.
    """
    from api.queries_folha import get_cnh
    try:
        return JSONResponse(get_cnh(dias=dias, filial=filial, categoria=categoria))
    except Exception as exc:  # noqa: BLE001
        log.warning("rh_cnh falhou: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "globus_indisponivel",
            "mensagem": "Sem conexao com o banco da folha (GLOBUS)."})


@app.get("/api/rh/folha-indicadores")
def rh_folha_indicadores() -> JSONResponse:
    try:
        return JSONResponse(queries_folha.get_folha_indicadores())
    except Exception as exc:  # noqa: BLE001
        return _folha_erro(exc)


@app.get("/api/operacao/pedagio")
def operacao_pedagio(dt_de: str = "", dt_ate: str = "", dias: int = 365) -> JSONResponse:
    """Validação de pedágio: vale-pedágio × CT-e × coleta, por eixo e modalidade.

    Os três números existem e NÃO batem, e a tela nomeia a diferença em vez de
    escolher um: o CT-e cobra a taxa do cliente, a coleta lança o pedágio da
    operação e o vale é o que se adianta ao transportador. Medido em 12 meses,
    R$ 4,86 mi × R$ 5,69 mi × R$ 1,76 mi.

    `dt_de`/`dt_ate` são os MESMOS parâmetros que o tag e a auditoria já
    aceitam. A rota nasceu só com `dias` e a tela mandava as datas do filtro
    para as TRÊS rotas — o FastAPI descartava as duas daqui em silêncio, e as
    abas do ERP ficavam em 365 dias enquanto o filtro dizia 90: duas leituras
    contraditórias na mesma tela, achado da revisão de 31/08/2026. `dias`
    continua como padrão para quando o filtro vier vazio.
    """
    import datetime as _dt
    try:
        dias = max(30, min(int(dias or 365), 730))
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Período inválido: informe os dias em número."})
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if valor and _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de and dt_ate:
        if dt_de > dt_ate:
            dt_de, dt_ate = dt_ate, dt_de
        de = _dt.date.fromisoformat(dt_de)
        ate = _dt.date.fromisoformat(dt_ate)
        dias = max(1, (ate - de).days)
    else:
        ate = _dt.date.today()
        de = ate - _dt.timedelta(days=dias)
    try:
        from api.pedagio import validacao as _v, pracas as _p, qualp as _q
        d, a = de.isoformat(), ate.isoformat()
        return JSONResponse({
            "de": d, "ate": a, "dias": dias,
            "mensal": _v.mensal(d, a),
            "por_eixo": _v.por_eixo(d, a),
            "por_modalidade": _v.por_modalidade(d, a),
            "confronto": _v.confronto(d, a),
            "cobertura": _v.cobertura(d, a),
            # Praça e tarifa: o confronto contra o que a ADMINISTRADORA cobrou,
            # que é a fonte de tarifa que já chega e não depende de assinar
            # API de ninguém. `observada` é limitada às 60 combinações de maior
            # volume — a tabela rola dentro do card e o resto é cauda.
            "tarifa": _p.estado_tarifa(),
            "confronto_praca": _p.confronto_praca(d, a),
            "por_administradora": _p.por_administradora(d, a),
            "observada": _p.observada(d, a)[:60],
            # QUEM gera a divergência, não só onde ela acontece: a quebra por
            # modalidade e a estratificação por placa/frota. O confronto por
            # praça diz "em que praça o cadastro está velho"; estes dizem "de
            # quem é o vale que sai diferente", e são donos diferentes.
            "por_modalidade_conf": _p.confronto_modalidade(d, a),
            "por_veiculo": _p.confronto_veiculo(d, a),
            # O MDF-e é SENSOR, não texto: os três campos de vale-pedágio do
            # manifesto estão vazios nas 126.295 linhas do histórico, então a
            # conferência legal não dá para fazer — e a tela DIZ isso em vez
            # de calar. No dia em que o ERP passar a preencher, muda sozinha.
            "mdfe": _p.mdfe_vale(d, a),
            # O REGIME do QualP vai junto: a tela precisa dizer se a conferência
            # de TARIFA está disponível ou se estamos nas três consultas diárias.
            "qualp": {"regime": _q.regime()},
            "fonte": "AVA · valepedagio + conhecimento + coleta · leitura",
        })
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("pedagio falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao levantar a validação de pedágio."})


# A fatura do tag NAO precisa de entrada propria em ROTA_TELAS: o casamento e
# por PREFIXO e "/api/operacao/pedagio" ja cobre estas duas, com a mesma tela.
_PED_FATURA_MAX_BYTES = 48 * 1024 * 1024   # a de ago/2026 tem 28 MB em 382 paginas


@app.get("/api/operacao/pedagio/tag")
def operacao_pedagio_tag(dt_de: str = "", dt_ate: str = "") -> JSONResponse:
    """O pedagio do TAG: quanto, de quem, e a que tarifa.

    Sem fatura importada a resposta NAO e um erro — e uma tela que diz o que
    fazer. Erro aqui se leria como defeito do sistema, e o estado real e
    "ninguem importou ainda".
    """
    from api import pglocal
    from api.pedagio import fatura_tag as _ft
    try:
        faturas = _ft.faturas()
        if not faturas:
            return JSONResponse({"vazio": True, "faturas": [],
                                 "mensagem": "Nenhuma fatura de tag importada ainda."})
        de, ate = dt_de or None, dt_ate or None
        return JSONResponse({
            "vazio": False, "de": de, "ate": ate, "faturas": faturas,
            "resumo": _ft.resumo(de, ate),
            "tarifa": _ft.tarifa_observada(de, ate)[:200],
            "confronto": _ft.confronto_erp(de, ate),
            "fonte": "CÓRTEX · ped_travessias (fatura da administradora) × AVA "
                     "pracapedagio_valor · leitura",
        })
    except pglocal.NaoConfigurado as exc:
        return JSONResponse(status_code=503, content={
            "erro": "sem_banco_local", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        # Tabela ausente e' migration pendente, nao avaria: o `auth.init_db()`
        # do startup aplica as pendentes, entao isto so aparece entre o deploy
        # e o restart. Dizer "erro ao levantar" ali mandaria procurar defeito
        # onde falta um reinicio.
        if pglocal.sem_tabela(exc):
            return JSONResponse(status_code=503, content={
                "erro": "migration_pendente",
                "mensagem": "As tabelas da fatura de pedágio ainda não foram "
                            "criadas neste banco (migration 0030). Elas entram "
                            "no próximo reinício da API."})
        log.warning("pedagio_tag falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao levantar o pedágio do tag."})


@app.get("/api/operacao/pedagio/auditoria")
def operacao_pedagio_auditoria(dt_de: str = "", dt_ate: str = "") -> JSONResponse:
    """A auditoria das travessias: o que contestar e o que cobrar de volta.

    ROTA SEPARADA, e nao um bloco a mais em `/tag`: a auditoria de eixo cruza
    as travessias com o MANIFESTO, que vem do AVA, e quem abre a aba do tag
    para ver o gasto do mes nao deve pagar por essa consulta. A aba so a chama
    ao abrir (`data-ao-abrir`).
    """
    from api import pglocal
    from api.pedagio import auditoria as _au
    try:
        return JSONResponse(_au.resumo(dt_de or None, dt_ate or None))
    except pglocal.NaoConfigurado as exc:
        return JSONResponse(status_code=503, content={
            "erro": "sem_banco_local", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return JSONResponse(status_code=503, content={
                "erro": "migration_pendente",
                "mensagem": "As tabelas da fatura de pedágio ainda não foram "
                            "criadas neste banco (migration 0030)."})
        log.warning("pedagio_auditoria falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao levantar a auditoria de pedágio."})


@app.post("/api/operacao/pedagio/tag/importar")
async def operacao_pedagio_tag_importar(req: Request, nome: str = "") -> JSONResponse:
    """Recebe a fatura em PDF como CORPO BRUTO — mesmo padrao do extrato.

    Sem multipart de proposito: `UploadFile` exige python-multipart, que nao e
    dependencia do projeto, e o `uv sync` do AutoDeploy e nao-fatal — a API
    poderia subir sem a dep e derrubar so este endpoint.

    A LEITURA VAI POR `sem_travar` PORQUE ELA DEMORA 14 SEGUNDOS. Sao 382
    paginas de PDF, e isto e uma rota `async def` (precisa do corpo): rodar o
    parser no event loop deixaria o CORTEX INTEIRO parado esses 14 s — nem a
    Torre, nem a Saude, nem o /api/health. Foi medido nesta casa com a Z-API a
    3 s derrubando o health para 5,7 s.
    """
    from api import pglocal
    from api.pedagio import fatura_tag as _ft
    from api.pedagio import semparar as _sp

    if _tamanho_excede(req.headers.get("content-length"), _PED_FATURA_MAX_BYTES):
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima do limite de "
                        f"{_PED_FATURA_MAX_BYTES // (1024 * 1024)} MB."})
    bruto = await req.body()
    if not bruto:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_vazio", "mensagem": "Nenhum conteúdo recebido."})
    if len(bruto) > _PED_FATURA_MAX_BYTES:
        # Segunda linha: Content-Length pode faltar ou mentir.
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande", "mensagem": "Arquivo acima do limite."})

    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "?")
    try:
        out = await sem_travar(_ft.importar, nome or "fatura.pdf", bruto, autor)
    except _sp.FaturaInvalida as exc:
        # O CORTEX funcionou e esta dizendo NAO, com um motivo que a pessoa
        # precisa LER. Isso e 4xx: em 5xx o Cloudflare TROCA o corpo pela
        # pagina de erro dele e a mensagem nunca chega a tela.
        return JSONResponse(status_code=422, content={
            "erro": "fatura_invalida", "mensagem": str(exc)})
    except _ft.ImportacaoRecusada as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "fatura_nao_fecha", "mensagem": str(exc),
            "conferencia": exc.conferencia})
    except pglocal.NaoConfigurado as exc:
        return JSONResponse(status_code=503, content={
            "erro": "sem_banco_local", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("pedagio_tag_importar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": f"Não foi possível gravar a fatura ({type(exc).__name__})."})

    auth.audit(autor, "pedagio_fatura_importar",
               alvo=str(out.get("numero_fatura")),
               detalhe=f"competencia={out.get('competencia')} "
                       f"travessias={out.get('travessias')} placas={out.get('placas')}")
    return JSONResponse(out)


@app.get("/api/rh/folha-estrutura")
def rh_folha_estrutura(meses: int = 12) -> JSONResponse:
    """Custo de folha por NATUREZA, sem os eventos que só circulam.

    A tela de Custo de Folha soma `tipoeven='P'` e chama de custo. Medido, esse
    número carrega ~14% de CIRCULAÇÃO — adiantamento que sai como provento e
    volta como desconto no mesmo mês, batendo centavo a centavo. Esta rota
    devolve o custo EFETIVO, a quebra por natureza e a decomposição da variação
    entre "menos gente" e "cada um custa menos".
    """
    from api.rh import folha_estrutura as _fe
    from api import db_folha as _dbf
    if not _dbf.configured():
        return JSONResponse({"configurado": False,
                             "mensagem": "Banco da folha não configurado."})
    try:
        meses = max(3, min(int(meses or 12), 36))
        dados = _fe.levantar(meses)
        return JSONResponse({"configurado": True, **dados,
                             "kpis": _fe.resumo(dados),
                             "fonte": "GLOBUS · VW_FICHAFINANEVENTOS · leitura"})
    except Exception as exc:  # noqa: BLE001
        return _folha_erro(exc)


@app.get("/api/rh/folha-custo")
def rh_folha_custo(comp: str | None = None) -> JSONResponse:
    import re
    if comp and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", comp):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "comp inválido: use AAAA-MM."})
    try:
        return JSONResponse(queries_folha.get_custo_folha(comp))
    except Exception as exc:  # noqa: BLE001
        return _folha_erro(exc)


@app.get("/api/rh/horas-extras")
def rh_horas_extras(comp: str | None = None) -> JSONResponse:
    import re
    if comp and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", comp):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "comp inválido: use AAAA-MM."})
    try:
        return JSONResponse(queries_folha.get_horas_extras(comp))
    except Exception as exc:  # noqa: BLE001
        return _folha_erro(exc)


@app.get("/api/qualidade")
def qualidade() -> JSONResponse:
    try:
        return JSONResponse(queries.get_qualidade())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("qualidade falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a qualidade."})


@app.get("/api/frota/comunicacao-rastreadora")
def comunicacao_rastreadora() -> JSONResponse:
    try:
        return JSONResponse(queries.get_comunicacao_rastreadora())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("comunicacao_rastreadora falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a comunicação da frota."})


@app.get("/api/frota/manutencao-preventiva")
def manutencao_preventiva(horizonte: int = 30) -> JSONResponse:
    if horizonte not in (15, 30, 60, 90):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "horizonte deve ser 15, 30, 60 ou 90."})
    try:
        return JSONResponse(queries.get_manutencao_preventiva(horizonte=horizonte))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("manutencao_preventiva falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar as revisões preventivas."})


@app.get("/api/frota/compras-os")
def frota_compras_os(filial: int | None = None,
                     dt_de: str | None = None,
                     dt_ate: str | None = None) -> JSONResponse:
    """Compras da ordem de serviço: prazo entre abrir a OS e formalizar a
    compra, mix por classe e peça recomprada cedo demais no mesmo veículo.

    Sub-aba da tela de Manutenção — herda o RBAC dela (`man`)."""
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=365)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    try:
        return JSONResponse(manutencao_compras.get_compras_os(filial, dt_de, dt_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("frota_compras_os falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar as compras da ordem de serviço."})


@app.get("/api/suprimentos/precos-pecas")
def suprimentos_precos_pecas(filial: int | None = None,
                             dt_de: str | None = None,
                             dt_ate: str | None = None) -> JSONResponse:
    """Preço de peças da manutenção: item fora do padrão do próprio produto e
    dispersão de preço entre fornecedores.

    O período padrão é de DOZE meses (a mediana por produto precisa de volume;
    com 90 dias metade dos produtos cai abaixo do mínimo de compras) e vem do
    próprio módulo, não daqui, para a tela e a API não divergirem."""
    padrao_de, padrao_ate = suprimentos_pecas.periodo_padrao()
    dt_de = dt_de or padrao_de
    dt_ate = dt_ate or padrao_ate
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    try:
        return JSONResponse(suprimentos_pecas.get_precos_pecas(filial, dt_de, dt_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("suprimentos_precos_pecas falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar os preços de peças."})


@app.get("/api/suprimentos/custos")
def suprimentos_custos(dt_de: str | None = None, dt_ate: str | None = None,
                       origem: str | None = None,
                       filial: str | None = None) -> JSONResponse:
    hoje = date.today()
    dt_de = dt_de or f"{hoje.year}-{hoje.month:02d}-01"
    dt_ate = dt_ate or hoje.isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    origem = (origem or "").strip() or None
    filial = (filial or "").strip() or None
    if origem and origem.upper() not in ("COM NF", "SEM NF",
                                         "ABASTECIMENTO INT", "ABASTECIMENTO EXT"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "origem deve ser COM NF, SEM NF, ABASTECIMENTO INT ou ABASTECIMENTO EXT."})
    try:
        return JSONResponse(queries.get_custos(dt_de, dt_ate, origem=origem, filial=filial))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("suprimentos_custos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar os custos."})


@app.get("/api/operacao/portaria")
def portaria() -> JSONResponse:
    try:
        return JSONResponse(queries.get_portaria())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("portaria falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a portaria."})


# ---------------------------------------------------------------- portal do cliente
# UMA ROTA SÓ, com `aba` como parâmetro, e não três rotas. O middleware é
# fail-closed por PREFIXO (`/api/portal/cliente` -> tela `cliop`): com três
# caminhos, esquecer de mapear um deles no futuro seria 403 para todo mundo —
# ruim, mas visível. O risco real é o inverso: acrescentar `/api/portal/…`
# fora do prefixo mapeado e abrir dado de cliente sem escopo. Um caminho só,
# com o escopo aplicado em UM lugar, é o que não tem essa borda.
@app.get("/api/portal/cliente")
def portal_cliente_dados(request: Request, aba: str = "agora",
                         dt_de: str | None = None, dt_ate: str | None = None,
                         dias: int = 45, meses: int = 12,
                         raiz: str | None = None) -> JSONResponse:
    """Minha Operação, para os dois leitores da tela.

    `raiz` existe para GENTE DA CASA escolher de quem quer ver, e é ignorado
    para quem tem vínculo — a decisão mora em `portal_cliente.alvo()`, que
    consulta o vínculo ANTES de olhar o parâmetro. É essa ordem que impede a
    tela de virar um buscador da operação alheia: um usuário de cliente pode
    mandar o `raiz` que quiser, que ele continua no CNPJ dele.

    Sem vínculo e sem escolha a resposta é 200 com a lista de clientes, não
    403: quem abriu a tela tem direito a ela, só ainda não disse de quem.
    """
    from . import portal_cliente

    try:
        alvo, travado = portal_cliente.alvo(request.state.sessao, raiz)
    except portal_cliente.PrecisaEscolher:
        try:
            return JSONResponse({"escolher": True, "travado": False,
                                 **portal_cliente.get_clientes(365)})
        except Exception as exc:  # noqa: BLE001
            log.warning("portal_cliente lista falhou: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={
                "erro": "erro_consulta",
                "mensagem": "Não foi possível listar os clientes."})
    try:
        # `travado` e `alvo` vão em TODA resposta: a tela precisa saber se
        # esconde o seletor, e quem está vendo precisa saber de quem é o
        # número na frente dele. Painel de cliente sem dizer qual cliente é
        # exatamente o jeito de alguém da casa ler a conta errada e agir.
        selo = {"travado": travado, "cliente_raiz": alvo,
                "cliente_nome": portal_cliente.nome_do_cliente(alvo)}
        if aba == "permanencia":
            hoje = date.today()
            dt_ate = dt_ate or hoje.isoformat()
            dt_de = dt_de or hoje.replace(day=1).isoformat()
            return JSONResponse({**portal_cliente.get_permanencia(alvo, dt_de, dt_ate), **selo})
        if aba == "historico":
            return JSONResponse({**portal_cliente.get_historico(alvo, max(1, min(24, meses))), **selo})
        return JSONResponse({**portal_cliente.get_agora(alvo, max(1, min(180, dias))), **selo})
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco de dados."})
    except Exception as exc:  # noqa: BLE001
        # TIPO da exceção no log, nunca o texto para fora.
        log.warning("portal_cliente falhou (%s): %s", aba, type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar a operação."})


@app.get("/api/operacao/sac-freetime")
def sac_freetime(dt_de: str | None = None, dt_ate: str | None = None) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=30)).isoformat()
    try:
        return JSONResponse(queries.get_sac_freetime(dt_de, dt_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("sac_freetime falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o SAC/freetime."})


@app.get("/api/jornada/motorista")
def jornada_motorista(doc: str | None = None, de: str | None = None,
                      ate: str | None = None) -> JSONResponse:
    """A ficha de um motorista, da apuração da RasterJOR.

    Substitui a rota de mesmo caminho que lia o ERP. O parâmetro mudou de `id`
    (token do ERP) para `doc` (o CPF, que é a chave natural em `jor_*`) — o
    nome antigo não sobreviveria à troca de fonte sem virar mentira.
    """
    if not (doc or "").strip():
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe o motorista."})
    try:
        from api.jornada.leitura import ficha_motorista
        r = ficha_motorista(doc, de, ate)
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_motorista: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_ficha",
            "mensagem": "Não foi possível montar a ficha do motorista."})
    if r.get("erro"):
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": r["erro"]})
    return JSONResponse(r)


@app.get("/api/jornada/raster")
def jornada_raster(de: str | None = None, ate: str | None = None) -> JSONResponse:
    """Jornada apurada pela RASTERJOR, lida do BANCO LOCAL do CÓRTEX.

    As tabelas `jor_*` são alimentadas pela coleta própria (a API do
    fornecedor) e pela carga inicial do histórico. Não se lê mais
    `sulista.rasterjor_*` no AVA: aquela rotina é externa e ficou 136 dias
    parada sem que o CÓRTEX pudesse saber.

    A janela padrão é ancorada no ÚLTIMO DADO, não em hoje — com a coleta
    parada, uma janela contada de hoje devolveria tela vazia, que se lê como
    "ninguém rodou" em vez de "parou de chegar".
    """
    from api.jornada.leitura import get_jornada_raster
    try:
        return JSONResponse(get_jornada_raster(de, ate))
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_raster falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar a jornada da RasterJOR."})


@app.get("/api/smartec/painel")
def smartec_painel() -> JSONResponse:
    """Tudo que a tela da Smartec precisa, numa chamada.

    Lê o BANCO LOCAL, nunca a API do fornecedor: a tela abre em milissegundos
    e não depende de a Smartec estar de pé. Quem fala com o fornecedor é a
    coleta, e ela tem trilha própria em `smt_carga`.
    """
    from api.smartec import leitura
    try:
        return JSONResponse({
            "kpis": leitura.kpis(),
            "multas": leitura.infracoes("multa", 400),
            "notificacoes": leitura.infracoes("notificacao", 600),
            "por_veiculo": leitura.por_veiculo("multa", 40),
            "por_infracao": leitura.por_infracao("multa", 15),
            "por_orgao": leitura.por_orgao("multa", 12),
            "mensal": leitura.mensal(),
            "licencas": leitura.licencas(),
            "antt": leitura.antt(200),
            "antt_situacao": leitura.antt_por_situacao(),
            "antt_mensal": leitura.antt_mensal(36),
            "por_motorista": leitura.por_motorista(30),
            "cobertura": leitura.cobertura(),
            "historico": leitura.historico(100),
            "cargas": leitura.cargas(20),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("smartec_painel falhou: %s: %s", type(exc).__name__, exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar os dados da Smartec."})


@app.post("/api/smartec/coletar")
async def smartec_coletar(req: Request) -> JSONResponse:
    """Dispara a coleta agora. MESMO caminho da tarefa agendada.

    `sem_travar` porque a coleta faz ~260 chamadas de rede e leva ~23 s: numa
    rota `async def` isso travaria o event loop e o CÓRTEX inteiro pelo tempo
    todo — nem a Torre, nem o /api/health. Foi assim que o envio de WhatsApp
    derrubou o painel por minutos.
    """
    from api.smartec import cliente as scli
    from api.smartec import coleta as scol
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    if not scli.configurado():
        # RECUSA NÃO É 5xx: o CÓRTEX funcionou e está dizendo NÃO com um
        # motivo que a pessoa precisa ler — e o Cloudflare troca o corpo dos
        # 5xx da origem pela página de erro dele, então a mensagem nunca
        # chegaria à tela.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "nao_configurado",
            "mensagem": "Token da Smartec não configurado. "
                        "Gestão › Credenciais › SMARTEC_TOKEN."})
    try:
        r = await sem_travar(scol.coletar_tudo)
    except Exception as exc:  # noqa: BLE001
        log.warning("smartec_coletar falhou: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_coleta",
            "mensagem": "Não foi possível rodar a coleta da Smartec."})
    auth.audit(autor or "?", "smartec_coletar",
               detalhe=" · ".join(f"{k}:{v.get('itens', 0)}"
                                  for k, v in r.get("recursos", {}).items()))
    return JSONResponse(r)


@app.get("/api/alertas")
def alertas_lista() -> JSONResponse:
    try:
        return JSONResponse({"alertas": alertas.build_alertas()})
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar os alertas."})


@app.get("/api/alertas/digest", response_class=PlainTextResponse)
def alertas_digest() -> PlainTextResponse:
    try:
        return PlainTextResponse(alertas.digest_texto())
    except Exception as exc:  # noqa: BLE001
        log.warning("digest falhou: %s", exc)
        return PlainTextResponse(f"Erro ao montar o digest: {exc}", status_code=500)


# --- Push (notificações no celular) — autoatendimento por usuário logado -----
@app.on_event("startup")
def _startup_push() -> None:
    # SÓ NO LÍDER: com `--workers`, o startup roda em cada processo e o digest
    # sairia uma vez por worker. Ver `api/lider.py`.
    if not lider.sou_o_agendador():
        return
    push.iniciar_scheduler()  # digest diário; no-op se VAPID não configurado


@app.on_event("startup")
def _startup_aviso_carga() -> None:
    """O relogio do aviso de carga. No-op se o WhatsApp nao esta configurado.

    MORA AQUI, e nao numa tarefa do Windows, por dois motivos que estao no
    docstring de `api/rastreio/agendador.py`: a hora cheia nao e o relogio de
    quem pediu, e a tarefa agendada do aviso NAO ESTAVA REGISTRADA nesta
    maquina — o que dispara o envio hoje nao esta escrito neste repositorio.
    """
    # SÓ NO LÍDER. Medido em 06/09/2026 com um app isolado: `--workers 4` roda
    # o startup 4 a 6 vezes (o uvicorn respawna worker no Windows), e este
    # relógio manda WhatsApp REAL para quem espera carga. Ver `api/lider.py`.
    if not lider.sou_o_agendador():
        return
    from api.rastreio import agendador
    agendador.iniciar()


@app.on_event("startup")
def _startup_auth() -> None:
    """Cria o schema de acesso, se ainda não existir.

    Saiu do import de `api/auth.py` na migração para o PostgreSQL: um DDL no
    import faria a API inteira NÃO SUBIR com o banco fora do ar — e sem API não
    há nem tela de erro para explicar o que houve. Aqui a falha é registrada e
    a aplicação sobe; a Saúde do Servidor mostra o banco em vermelho, que é
    onde se olha.
    """
    try:
        auth.init_db()
    except Exception as exc:  # noqa: BLE001
        log.error("nao foi possivel preparar o banco de acesso: %s: %s",
                  type(exc).__name__, exc)


@app.get("/api/push/config")
def push_config(request: Request) -> JSONResponse:
    sess = request.state.sessao or {}
    return JSONResponse({
        "habilitado": push.habilitado(),
        "vapid_public": push._pub(),
        "inscricoes": push.contar_subs(sess.get("email")),
    })


@app.post("/api/push/subscribe")
def push_subscribe(payload: dict, request: Request) -> JSONResponse:
    if not push.habilitado():
        return JSONResponse(status_code=503, content={
            "erro": "push_desligado", "mensagem": "Notificações não configuradas no servidor."})
    sess = request.state.sessao or {}
    try:
        push.salvar_sub(payload, sess.get("email"))
    except ValueError:
        return JSONResponse(status_code=400, content={
            "erro": "invalida", "mensagem": "Inscrição inválida."})
    except Exception as exc:  # noqa: BLE001
        log.warning("push subscribe: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro", "mensagem": "Não foi possível salvar a inscrição."})
    return JSONResponse({"ok": True, "inscricoes": push.contar_subs(sess.get("email"))})


@app.post("/api/push/unsubscribe")
def push_unsubscribe(payload: dict, request: Request) -> JSONResponse:
    ep = (payload or {}).get("endpoint")
    if ep:
        push.remover_sub(ep)
    return JSONResponse({"ok": True})


@app.post("/api/push/testar")
def push_testar(request: Request) -> JSONResponse:
    if not push.habilitado():
        return JSONResponse(status_code=503, content={
            "erro": "push_desligado", "mensagem": "Notificações não configuradas no servidor."})
    sess = request.state.sessao or {}
    subs = push.subs_do_usuario(sess.get("email"))
    if not subs:
        return JSONResponse(status_code=400, content={
            "erro": "sem_inscricao", "mensagem": "Ative as notificações neste aparelho primeiro."})
    n = push.send_push("Córtex Sulista",
                       "Notificação de teste — está funcionando! 🚛", "/#home", subs)
    return JSONResponse({"enviados": n})


@app.get("/api/financeiro/contabil")
def contabil(comp_de: str | None = None, comp_ate: str | None = None,
             busca: str | None = None) -> JSONResponse:
    import re
    hoje = date.today()
    comp_ate = comp_ate or f"{hoje.year}-{hoje.month:02d}"
    comp_de = comp_de or f"{hoje.year}-01"
    for nome, valor in (("comp_de", comp_de), ("comp_ate", comp_ate)):
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use AAAA-MM."})
    if comp_de > comp_ate:
        comp_de, comp_ate = comp_ate, comp_de
    busca = (busca or "").strip() or None
    try:
        return JSONResponse(queries.get_contabil(comp_de, comp_ate, busca=busca))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("contabil falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro na consulta contábil."})


@app.post("/api/financeiro/contabil/ajuste")
def contabil_ajuste(payload: dict, request: Request) -> JSONResponse:
    grupo, reduzido = payload.get("grupo"), payload.get("reduzido")
    agrupador = (payload.get("agrupador") or "").strip()
    if not isinstance(grupo, int) or not isinstance(reduzido, int):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "grupo e reduzido devem ser inteiros."})
    if agrupador and (len(agrupador) > 80 or "'" in agrupador or ";" in agrupador):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Agrupador inválido."})
    try:
        if agrupador:
            queries.salvar_ajuste(grupo, reduzido, agrupador,
                                  conta=str(payload.get("conta") or ""))
        else:
            queries.remover_ajuste(grupo, reduzido)
    except Exception as exc:  # noqa: BLE001
        log.warning("ajuste falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_ajuste", "mensagem": "Não foi possível salvar o ajuste."})
    # ajuste já persistido — a auditoria é best-effort e não pode reverter a resposta
    try:
        auth.audit(request.state.sessao["email"], "contabil_ajuste",
                   alvo=f"{grupo}|{reduzido}", detalhe=agrupador or "removido")
    except Exception as exc:  # noqa: BLE001
        log.warning("audit do ajuste falhou (ajuste foi salvo): %s", exc)
    return JSONResponse({"ok": True, "ajustes": len(queries.ler_ajustes())})


@app.get("/api/financeiro/contabil/export-sql", response_class=PlainTextResponse)
def contabil_export() -> PlainTextResponse:
    return PlainTextResponse(queries.export_sql_ajustes(),
                             headers={"Content-Disposition": "attachment; filename=ajustes_agrupador.sql"})


@app.get("/api/controladoria/orcamento/versoes")
def orcamento_versoes(ano: int | None = None) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    try:
        arm.init_db(arm.ESQUEMA)
        versoes = arm.listar_versoes(arm.ESQUEMA, ano)
        # seletor da tela: não-arquivadas primeiro (mais recentes primeiro),
        # arquivadas depois — histórico não deve competir com o que está em
        # uso pelo topo da lista.
        versoes.sort(key=lambda v: (v.get("status") == "arquivada", -v["id"]))
        return JSONResponse({"versoes": versoes})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_versoes falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao listar as versões do orçamento."})


@app.get("/api/controladoria/orcamento")
def orcamento(versao_id: int | None = None, ate_mes: int | None = None) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    from api.orcamento.servico import comparativo
    if ate_mes is not None and not (0 <= ate_mes <= 12):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "ate_mes deve estar entre 0 e 12."})
    try:
        arm.init_db(arm.ESQUEMA)
        if versao_id is None:
            # a versão vigente (não a de id mais alto cru): prefere aprovada,
            # nunca escolhe arquivada — sem isso, regerar (que arquiva uma
            # cópia do estado anterior) fazia a tela abrir sozinha no
            # snapshot congelado, por ele ter o id mais novo.
            vigente = arm.versao_vigente(arm.ESQUEMA)
            if vigente is None:
                return JSONResponse({"vazio": True,
                                     "mensagem": "Nenhuma versão de orçamento criada ainda."})
            versao_id = vigente["id"]
        return JSONResponse(comparativo(versao_id, ate_mes))
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Versão de orçamento inexistente."})
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar o orçamento."})


@app.post("/api/controladoria/orcamento/gerar")
async def orcamento_gerar(req: Request) -> JSONResponse:
    from api.orcamento.servico import METODOS_VALIDOS, gerar
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    ano = body.get("ano")
    fator = body.get("fator", 0.0)
    rotulo = (body.get("rotulo") or f"Orçamento {ano}").strip()
    if not isinstance(ano, int) or not (2020 <= ano <= 2100):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe um ano entre 2020 e 2100."})
    if not isinstance(fator, (int, float)) or not (-0.9 <= fator <= 3.0):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "O fator de tendência deve estar entre -0,9 e 3,0."})
    # "metodo" só importa para VERSÃO NOVA: ao regerar (versao_id presente), o
    # serviço ignora este parâmetro e usa o método gravado na própria versão.
    # Ausente (None) usa o default 'espelho'; presente mas vazio/whitespace é
    # valor INVÁLIDO, não "não informado" — `or` sozinho tratava os dois casos
    # como o mesmo default, mascarando um erro de integração (I5 da revisão
    # final).
    metodo_bruto = body.get("metodo")
    if metodo_bruto is None:
        metodo = "espelho"
    elif isinstance(metodo_bruto, str) and not metodo_bruto.strip():
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Método de derivação inválido: use 'espelho' ou 'semestre'."})
    else:
        metodo = metodo_bruto
    if metodo not in METODOS_VALIDOS:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Método de derivação inválido: use 'espelho' ou 'semestre'."})
    # versao_id presente = REGERAR aquela versão preservando os ajustes manuais
    versao_id = body.get("versao_id")
    if versao_id is not None and not (isinstance(versao_id, int)
                                      and not isinstance(versao_id, bool) and versao_id > 0):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "versao_id inválido."})
    # janela da base do método sazonal — só usada em geração nova com
    # metodo='semestre' (regerar ignora e a combinação com 'espelho' vira
    # ValueError dentro de gerar()); aqui só valida o TIPO do parâmetro.
    base_de = body.get("base_de")
    if base_de is not None and not isinstance(base_de, str):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "base_de deve ser texto AAAA-MM ou nulo."})
    base_ate = body.get("base_ate")
    if base_ate is not None and not isinstance(base_ate, str):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "base_ate deve ser texto AAAA-MM ou nulo."})
    try:
        quem = (req.state.sessao or {}).get("nome") or "sistema"
        return JSONResponse(gerar(ano, rotulo, float(fator), quem,
                                  versao_id=versao_id, metodo=metodo,
                                  base_de=base_de, base_ate=base_ate))
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "versao_inexistente",
            "mensagem": "Versão não encontrada. Recarregue a tela."})
    except ValueError as exc:
        # regerar sobre versão aprovada/arquivada levanta a MESMA exceção que
        # "sem histórico" (arm.ajustar/servico.gerar usam ValueError para os
        # dois casos) — distinguir pela mensagem para o contrato bater com
        # /ajustar, /aprovar e /reabrir, que já respondem "versao_imutavel"
        # (A4 da revisão final).
        erro = "versao_imutavel" if "imutável" in str(exc) else "sem_historico"
        return JSONResponse(status_code=422, content={
            "erro": erro, "mensagem": str(exc)})
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_gerar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao gerar o orçamento."})


@app.post("/api/controladoria/orcamento/ajustar")
async def orcamento_ajustar(req: Request) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    try:
        versao_id = int(body["versao_id"])
        conta = str(body["conta"])
        mes = int(body["mes"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe versao_id, conta e mes."})
    if not (1 <= mes <= 12):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "mes deve estar entre 1 e 12."})
    valor = body.get("valor")
    if valor is not None:
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "valor deve ser numérico ou nulo."})
    try:
        quem = (req.state.sessao or {}).get("nome") or "sistema"
        arm.ajustar(arm.ESQUEMA, versao_id, conta, mes, valor, quem)
        return JSONResponse({"ok": True})
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Célula inexistente nessa versão."})
    except ValueError as exc:
        # versão aprovada/arquivada é imutável — arm.ajustar bloqueia com
        # ValueError; sem este except ele caía no 500 genérico abaixo.
        return JSONResponse(status_code=422, content={
            "erro": "versao_imutavel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_ajustar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao salvar o ajuste."})


@app.post("/api/controladoria/orcamento/aprovar")
async def orcamento_aprovar(req: Request) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    versao_id = body.get("versao_id")
    if not (isinstance(versao_id, int) and not isinstance(versao_id, bool) and versao_id > 0):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe um versao_id válido (inteiro > 0)."})
    try:
        quem = (req.state.sessao or {}).get("nome") or "sistema"
        arm.aprovar(arm.ESQUEMA, versao_id, quem)
        versao = next(v for v in arm.listar_versoes(arm.ESQUEMA) if v["id"] == versao_id)
        return JSONResponse({"ok": True, "versao": versao})
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Versão de orçamento inexistente."})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "versao_imutavel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_aprovar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao aprovar a versão."})


@app.post("/api/controladoria/orcamento/reabrir")
async def orcamento_reabrir(req: Request) -> JSONResponse:
    from api.orcamento import armazenamento as arm
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    versao_id = body.get("versao_id")
    if not (isinstance(versao_id, int) and not isinstance(versao_id, bool) and versao_id > 0):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe um versao_id válido (inteiro > 0)."})
    try:
        arm.reabrir(arm.ESQUEMA, versao_id)
        versao = next(v for v in arm.listar_versoes(arm.ESQUEMA) if v["id"] == versao_id)
        return JSONResponse({"ok": True, "versao": versao})
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Versão de orçamento inexistente."})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "versao_imutavel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_reabrir falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao reabrir a versão."})


# ---------------------------------------------------------------- Gestão — atas e planos de ação

def _ges_erro(nome: str, exc: Exception, msg: str) -> JSONResponse:
    """Toda rota deste bloco erra do mesmo jeito.

    `DadoInvalido` é RECUSA — o CÓRTEX funcionou e está dizendo não, com um
    motivo que a pessoa precisa ler, então é 422 e a mensagem vai inteira.
    O resto é falha nossa: 500 com mensagem genérica e o TIPO da exceção no
    log, nunca `str(exc)` na tela.
    """
    from api.gestao.comum import DadoInvalido
    if isinstance(exc, DadoInvalido):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    log.warning("%s falhou: %s", nome, type(exc).__name__)
    return JSONResponse(status_code=500, content={
        "erro": "erro_consulta", "mensagem": msg})


def _ges_usuario(req: Request) -> tuple[str, int | None]:
    sess = getattr(req.state, "sessao", None) or {}
    return sess.get("email", ""), sess.get("id")


@app.get("/api/gestao/painel")
def gestao_painel(req: Request) -> JSONResponse:
    """A tela de acompanhamento inteira, numa chamada.

    Vai tudo junto — resumo, ranking, paradas, atrasadas e o catálogo de
    usuários/áreas — porque a tela não desenha nada sem o conjunto, e sete
    chamadas para montar uma tela é sete chances de meia tela na rede ruim.
    """
    try:
        from api.gestao import painel as gp
        dados = gp.tudo()
        _, uid = _ges_usuario(req)
        dados["minhas"] = gp.minhas(uid)
        return JSONResponse(dados)
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_painel", exc,
                         "Erro ao montar o painel de acompanhamento.")



# ===================== Ritual Semanal de Gestao (tela `gesrit`) =============
#
# NAO FICAM SOB /api/gestao, e isso e deliberado: aquele prefixo e checado como
# ADMIN no middleware, ANTES do mapeamento de telas. O ritual e preenchido por
# GERENTE, que nao e administrador -- sob aquele prefixo a tela nasceria inutil
# para exatamente o publico dela. Aqui vale o RBAC normal, pela tela `gesrit`
# em ROTA_TELAS.

@app.get("/api/ritual/painel")
def ritual_painel(ciclo_id: int = 0) -> JSONResponse:
    """O painel unico da semana. Sem `ciclo_id`, o ciclo corrente."""
    try:
        from api.gestao import ritual
        c = (ritual._um("SELECT * FROM ges_ciclos WHERE id=%s", (ciclo_id,))
             if ciclo_id else ritual.ciclo_corrente())
        if not c:
            # NAO CRIA CICLO SOZINHO. Um ciclo que nasce por alguem ter aberto a
            # tela encheria o historico de semanas que ninguem reuniu -- e a
            # taxa de cumprimento passaria a ser dividida por elas.
            return JSONResponse({"ciclo": None, "gerencias": [], "resumo": {},
                                 "pendencias": [], "bloqueios": [],
                                 "prioridades": [],
                                 "ciclos": ritual.ciclos_recentes(),
                                 "fonte": "banco do CORTEX (ges_*)"})
        p = ritual.painel(c["id"])
        p["cobranca"] = ritual.cobranca(c["id"])
        p["ciclos"] = ritual.ciclos_recentes()
        return JSONResponse(p)
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_painel", exc, "Erro ao montar o painel da semana.")


@app.get("/api/ritual/cadastro")
def ritual_cadastro() -> JSONResponse:
    """Gerencias, indicadores e o CATALOGO de fontes automaticas."""
    try:
        from api.gestao import ritual
        from api.gestao.comum import usuarios_ativos
        return JSONResponse({"gerencias": ritual.gerencias(),
                             "indicadores": ritual.indicadores(),
                             "fontes": ritual.fontes_publicas(),
                             "acoes": ritual.acoes_abertas(),
                             "usuarios": usuarios_ativos()})
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_cadastro", exc, "Erro ao ler o cadastro.")


@app.post("/api/ritual/ciclo")
async def ritual_abrir_ciclo(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from api.gestao import ritual
        quem, _ = _ges_usuario(req)
        return JSONResponse(ritual.abrir_ciclo(
            body.get("data_reuniao"), body.get("prazo") or "", quem))
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_abrir_ciclo", exc, "Erro ao abrir a semana.")


@app.post("/api/ritual/apontar")
async def ritual_apontar(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from api.gestao import ritual
        quem, _ = _ges_usuario(req)
        r = ritual.apontar(int(body.get("ciclo_id") or 0),
                           int(body.get("indicador_id") or 0),
                           body, quem)
        return JSONResponse({"ok": True, "id": r["id"]})
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_apontar", exc, "Erro ao gravar o apontamento.")


@app.post("/api/ritual/priorizar")
async def ritual_priorizar(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from api.gestao import ritual
        quem, _ = _ges_usuario(req)
        ritual.priorizar(int(body.get("ciclo_id") or 0),
                         int(body.get("indicador_id") or 0),
                         body.get("posicao"), quem)
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_priorizar", exc, "Erro ao marcar a prioridade.")


@app.post("/api/ritual/fechar")
async def ritual_fechar(req: Request) -> JSONResponse:
    """Aplica as regras do jogo. Recusa com a LISTA do que falta -- recusa sem
    motivo e a forma mais rapida de ensinar alguem a contornar a regra."""
    try:
        body = await req.json()
        from api.gestao import ritual
        quem, _ = _ges_usuario(req)
        return JSONResponse(ritual.fechar(int(body.get("ciclo_id") or 0), quem,
                                          forcar=bool(body.get("forcar"))))
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_fechar", exc, "Erro ao fechar a semana.")


@app.post("/api/ritual/reabrir")
async def ritual_reabrir(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from api.gestao import ritual
        quem, _ = _ges_usuario(req)
        return JSONResponse(ritual.reabrir(int(body.get("ciclo_id") or 0), quem))
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_reabrir", exc, "Erro ao reabrir a semana.")


@app.post("/api/ritual/indicador")
async def ritual_indicador(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from api.gestao import ritual
        if body.get("excluir"):
            return JSONResponse(ritual.excluir_indicador(int(body.get("id") or 0)))
        return JSONResponse(ritual.salvar_indicador(body))
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_indicador", exc, "Erro ao salvar o indicador.")


@app.post("/api/ritual/gerencia")
async def ritual_gerencia(req: Request) -> JSONResponse:
    try:
        body = await req.json()
        from api.gestao import ritual
        return JSONResponse(ritual.salvar_gerencia(body))
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("ritual_gerencia", exc, "Erro ao salvar a gerência.")


@app.get("/api/gestao/acoes")
def gestao_acoes(status: str = "", responsavel_id: int = 0, area: str = "",
                 reuniao_id: int = 0, atrasadas: int = 0, busca: str = "",
                 prazo_de: str = "", prazo_ate: str = "") -> JSONResponse:
    try:
        from api.gestao import acoes as ga
        from api.gestao.comum import AREAS, usuarios_ativos
        f = {"status": status or None, "responsavel_id": responsavel_id or None,
             "area": area or None, "reuniao_id": reuniao_id or None,
             "atrasadas": bool(atrasadas), "busca": busca,
             "prazo_de": prazo_de or None, "prazo_ate": prazo_ate or None}
        lista = ga.listar(**f)
        # "X de Y" no hint: top-N sem contador vira total falso.
        return JSONResponse({"acoes": lista, "total": ga.contar(**f),
                             "mostrando": len(lista),
                             "usuarios": usuarios_ativos(),
                             "areas": list(AREAS)})
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_acoes", exc, "Erro ao listar as ações.")


@app.get("/api/gestao/acoes/{acao_id}")
def gestao_acao(acao_id: int) -> JSONResponse:
    try:
        from api.gestao import acoes as ga
        a = ga.obter(acao_id)
        if not a:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Esta ação não existe mais."})
        return JSONResponse(a)
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_acao", exc, "Erro ao ler a ação.")


@app.post("/api/gestao/acoes")
async def gestao_acao_salvar(req: Request) -> JSONResponse:
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie a ação."})
    autor, _ = _ges_usuario(req)
    acao_id = body.get("id")
    acao_id = int(acao_id) if isinstance(acao_id, int) else None
    try:
        from api.gestao import acoes as ga
        d = ga.gravar(body, usuario=autor, acao_id=acao_id)
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_acao_salvar", exc,
                         "Não foi possível gravar a ação.")
    auth.audit(autor or "?", "gestao_acao",
               alvo=f"#{d['id']}",
               detalhe=(f"{'editada' if acao_id else 'criada'} · "
                        f"resp={d['responsavel']} · prazo={d['prazo']} · "
                        f"{d['status']} · {d['o_que'][:120]}"))
    return JSONResponse(d)


@app.post("/api/gestao/acoes/{acao_id}/andamento")
async def gestao_acao_andamento(acao_id: int, req: Request) -> JSONResponse:
    """O caminho curto do acompanhamento — escrever o que andou.

    Rota própria, e não o `POST /acoes` com o corpo inteiro, porque é a
    operação FREQUENTE: obrigar o formulário completo para dizer "o fornecedor
    retorna dia 12" é o que faz o histórico ficar vazio.
    """
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie o andamento."})
    autor, _ = _ges_usuario(req)
    try:
        from api.gestao import acoes as ga
        d = ga.registrar_andamento(
            acao_id, body.get("texto", ""), usuario=autor,
            status=body.get("status"), percentual=body.get("percentual"))
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_acao_andamento", exc,
                         "Não foi possível registrar o andamento.")
    auth.audit(autor or "?", "gestao_andamento", alvo=f"#{acao_id}",
               detalhe=f"{d['status']} · {str(body.get('texto',''))[:160]}")
    return JSONResponse(d)


@app.post("/api/gestao/acoes/{acao_id}/excluir")
def gestao_acao_excluir(acao_id: int, req: Request) -> JSONResponse:
    from api.gestao import acoes as ga
    apagada = ga.excluir(acao_id)
    if not apagada:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Esta ação não existe mais."})
    autor, _ = _ges_usuario(req)
    auth.audit(autor or "?", "gestao_acao_excluir", alvo=f"#{acao_id}",
               detalhe=f"{apagada['o_que'][:160]} · resp={apagada['responsavel']}")
    return JSONResponse({"ok": True})


@app.get("/api/gestao/atas")
def gestao_atas(status: str = "", tipo: str = "", area: str = "",
                de: str = "", ate: str = "", busca: str = "") -> JSONResponse:
    try:
        from api.gestao import atas as gt
        from api.gestao.comum import (AREAS, ROTULO_TIPO, TIPOS_REUNIAO,
                                      usuarios_ativos)
        f = {"status": status or None, "tipo": tipo or None,
             "area": area or None, "de": de or None, "ate": ate or None,
             "busca": busca}
        lista = gt.listar(**f)
        return JSONResponse({"atas": lista, "total": gt.contar(**f),
                             "mostrando": len(lista),
                             "usuarios": usuarios_ativos(),
                             "areas": list(AREAS),
                             "tipos": [{"chave": t, "rotulo": ROTULO_TIPO[t]}
                                       for t in TIPOS_REUNIAO]})
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_atas", exc, "Erro ao listar as atas.")


@app.get("/api/gestao/atas/{reuniao_id}")
def gestao_ata(reuniao_id: int) -> JSONResponse:
    try:
        from api.gestao import atas as gt
        a = gt.obter(reuniao_id)
        if not a:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Esta ata não existe mais."})
        return JSONResponse(a)
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_ata", exc, "Erro ao ler a ata.")


@app.post("/api/gestao/atas")
async def gestao_ata_salvar(req: Request) -> JSONResponse:
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Envie a ata."})
    autor, _ = _ges_usuario(req)
    reuniao_id = body.get("id")
    reuniao_id = int(reuniao_id) if isinstance(reuniao_id, int) else None
    try:
        from api.gestao import atas as gt
        d = gt.gravar(body, usuario=autor, reuniao_id=reuniao_id)
    except Exception as exc:  # noqa: BLE001
        return _ges_erro("gestao_ata_salvar", exc,
                         "Não foi possível gravar a ata.")
    auth.audit(autor or "?", "gestao_ata", alvo=d["codigo"],
               detalhe=(f"{'editada' if reuniao_id else 'criada'} · "
                        f"{d['status']} · {d['titulo'][:120]}"))
    return JSONResponse(d)


@app.post("/api/gestao/atas/{reuniao_id}/excluir")
def gestao_ata_excluir(reuniao_id: int, req: Request) -> JSONResponse:
    from api.gestao import atas as gt
    apagada = gt.excluir(reuniao_id)
    if not apagada:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Esta ata não existe mais."})
    autor, _ = _ges_usuario(req)
    # Quantas ações ficaram órfãs ENTRA na auditoria: é a consequência que a
    # pessoa não vê ao clicar, e a que alguém vai querer reconstituir depois.
    auth.audit(autor or "?", "gestao_ata_excluir", alvo=apagada["codigo"],
               detalhe=(f"{apagada['titulo'][:120]} · "
                        f"{apagada['acoes']} ações mantidas sem ata"))
    return JSONResponse({"ok": True, "acoes_orfas": apagada["acoes"]})


# ---------------------------------------------------------------- Previsão de fechamento

@app.get("/api/controladoria/previsao")
def previsao_fechamento(mes: str | None = None) -> JSONResponse:
    from api.previsao import get_previsao_fechamento
    if mes is not None and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", mes):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro mes inválido: use o formato AAAA-MM."})
    # ledger da revisão do Task 6: mes futuro (além do mês corrente) cai em
    # modo "fechado" e devolve uma DRE zerada silenciosa — comparação lexico-
    # gráfica de strings "AAAA-MM" funciona porque o formato já foi validado
    # acima (ano com 4 dígitos, mês com 2 dígitos zero-padded).
    if mes is not None and mes > date.today().strftime("%Y-%m"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro mes inválido: mês futuro (além do mês corrente)."})
    try:
        return JSONResponse(get_previsao_fechamento(mes))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a previsão."})


@app.get("/api/faturamento/detalhado")
def faturamento_detalhado(mes: str | None = None) -> JSONResponse:
    """Tela `fat`: emissões × meta por dia, modalidade, cliente e filial."""
    from api import faturamento as fatmod
    if mes is not None and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", mes):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro mes inválido: use o formato AAAA-MM."})
    if mes is not None and mes > date.today().strftime("%Y-%m"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Parâmetro mes inválido: mês futuro."})
    try:
        return JSONResponse(fatmod.get_detalhado(mes))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("faturamento detalhado falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar o faturamento detalhado."})


@app.get("/api/financeiro/tupy")
def financeiro_tupy(q: str = "") -> JSONResponse:
    """Portal Tupy (Monkey): a validação do espelho local de recebíveis."""
    from api.monkey import portal as mkyportal
    try:
        return JSONResponse(mkyportal.get_portal_tupy(q))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco local do CÓRTEX."})
    except Exception as exc:  # noqa: BLE001
        log.exception("portal tupy: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar o portal Tupy."})


@app.get("/api/operacao/gr")
def operacao_gr() -> JSONResponse:
    """Gerenciamento de Risco (Fase 1): o que o ERP já recebe do hub."""
    from api.rasterintegra import servico as grsvc
    try:
        return JSONResponse(grsvc.get_gr())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("gerenciamento de risco falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao montar o Gerenciamento de Risco."})


@app.get("/api/operacao/programacao/ciclos")
def programacao_ciclos() -> JSONResponse:
    """Histórico de ciclos (6m) — endpoint SEPARADO do radar de 120s: a
    agregação de coleta_ocorrencia é cara e vive sob cache de 1h."""
    from api import programacao_ciclos as pc
    try:
        return JSONResponse(pc.get_ciclos())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("ciclos da programacao falharam: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao medir os ciclos da programação."})


@app.post("/api/controladoria/previsao/ajuste")
async def previsao_ajuste(req: Request) -> JSONResponse:
    from api.previsao import armazenamento as parm
    from api.queries import DRE_MODELO, _RESP_CACHE
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    mes = str(body.get("mes") or "")
    linha = str(body.get("linha") or "")
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", mes):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "mes deve ser AAAA-MM."})
    rotulos = {r for r, _n, t, _s in DRE_MODELO if t != "formula"}
    if linha not in rotulos:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "linha deve ser uma linha DIRETA do modelo da DRE."})
    valor = body.get("valor")
    quem = (req.state.sessao or {}).get("nome") or "sistema"
    try:
        parm.init_db(parm.ESQUEMA)
        if valor is None:
            parm.remover_ajuste_prev(parm.ESQUEMA, mes, linha, quem)
        else:
            parm.salvar_ajuste_prev(parm.ESQUEMA, mes, linha,
                                    str(body.get("tipo") or "delta"),
                                    float(valor), str(body.get("motivo") or ""), quem)
        _RESP_CACHE.clear()
        return JSONResponse({"ok": True})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("previsao_ajuste falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao salvar o ajuste."})


# ---------------------------------------------------------------- Extrato bancário

_EXT_MAX_BYTES = 8 * 1024 * 1024   # extrato OFX real tem dezenas/centenas de KB


def _tamanho_excede(content_length: str | None, limite: int) -> bool:
    """True se o Content-Length declarado no header excede `limite`.

    Header ausente (ou não-numérico — ex.: requisição chunked, sem
    Content-Length) devolve False: não dá pra rejeitar pelo header quando ele
    não existe ou mente, então a checagem pós-leitura do corpo (em
    `extrato_importar`) continua como segunda linha de defesa. Nunca estoura
    exceção — header malformado não pode virar 500."""
    if not content_length:
        return False
    try:
        return int(content_length) > limite
    except ValueError:
        return False


@app.get("/api/financeiro/bancos")
def bancos(dt_de: str | None = None, dt_ate: str | None = None) -> JSONResponse:
    """Visao estrategica de bancos: saldo, volume e custo por instituicao.

    Separada de `/extrato` porque responde outra pergunta - "quanto tenho, onde
    e quanto custa?" contra "o ERP bate com o banco?". Le so o extrato local
    (mais UMA consulta ao ERP, dentro de `posicao`), entao e barata.
    """
    from api.extrato.bancos import painel
    hoje = date.today()
    de = dt_de or hoje.replace(day=1).isoformat()
    ate = dt_ate or hoje.isoformat()
    try:
        return JSONResponse(painel(de, ate))
    except Exception as exc:  # noqa: BLE001
        log.warning("bancos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a visão de bancos."})


@app.get("/api/financeiro/extrato")
def extrato(dt_de: str | None = None, dt_ate: str | None = None,
            conta_id: int | None = None) -> JSONResponse:
    from api.extrato.servico import painel
    # padrão = mês corrente (mesmo estilo dos outros endpoints deste arquivo,
    # que resolvem o período com date.today() — não há helper compartilhado)
    hoje = date.today()
    de = dt_de or hoje.replace(day=1).isoformat()
    ate = dt_ate or hoje.isoformat()
    try:
        return JSONResponse(painel(de, ate, conta_id))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a validação do extrato."})


_ANTEC_MAX_BYTES = 12 * 1024 * 1024   # a planilha da Maxion tem 85 KB; 12 MB cobre portal grande


@app.get("/api/operacao/milkrun")
def operacao_milkrun(de: str | None = None, ate: str | None = None,
                     tomador: str = "02162259", situacao: str = "",
                     fornecedor: str = "", placa: str = "",
                     tipo: str = "milk",
                     dia: str | None = None) -> JSONResponse:
    """Milk run do periodo: cada parada com o horario COMBINADO e o DETECTADO.

    O detectado vem do rastro, nao de digitacao — e a razao de a tela existir.
    `tipo` separa o milk run (solicitacao com mais de uma parada) do frete
    ponto a ponto, que divide a mesma tabela no ERP.
    `dia` continua aceito por compatibilidade com o link antigo.
    """
    from api.milkrun.servico import get_milkrun
    if dia and not de:
        de = ate = dia
    for nome, valor in (("de", de), ("ate", ate)):
        if valor and _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parametro {nome} invalido: use AAAA-MM-DD."})
    # o tomador entra em LIKE: so digito, para nao virar curinga
    if not re.fullmatch(r"\d{2,14}", tomador or ""):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Tomador invalido: informe so os digitos do CNPJ."})
    if (tipo or "") not in ("milk", "simples", ""):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Tipo invalido: use milk, simples ou vazio."})
    try:
        return JSONResponse(get_milkrun(de, ate, tomador, situacao,
                                        fornecedor, placa, tipo))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexao com o banco. O tunel SSH esta aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("operacao_milkrun falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a operacao."})


@app.get("/api/financeiro/credito")
def credito_ler() -> JSONResponse:
    """Limites de cheque empresa contratados."""
    from api.financeiro import credito
    try:
        return JSONResponse(credito.resumo())
    except Exception as exc:  # noqa: BLE001
        log.warning("credito_ler falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_leitura", "mensagem": "Erro ao ler os limites."})


@app.post("/api/financeiro/credito")
async def credito_gravar(req: Request) -> JSONResponse:
    """Grava a tabela inteira de limites (substitui a anterior).

    Tabela inteira e nao linha a linha de proposito: sao tres a cinco linhas
    que a tesouraria confere juntas quando o banco atualiza a taxa, e um PATCH
    por linha deixaria o conjunto meio salvo se o segundo pedido falhasse.
    """
    from api.financeiro import credito
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=422, content={
            "erro": "corpo_invalido", "mensagem": "Envie um JSON valido."})
    linhas = corpo.get("linhas") if isinstance(corpo, dict) else corpo
    if not isinstance(linhas, list):
        return JSONResponse(status_code=422, content={
            "erro": "corpo_invalido", "mensagem": "Envie a lista de limites."})
    try:
        credito.gravar(linhas)
        return JSONResponse(credito.resumo())
    except ValueError as exc:
        # a mensagem ja diz o que consertar (ex.: "confira se nao e a taxa ANUAL")
        return JSONResponse(status_code=422, content={
            "erro": "dado_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("credito_gravar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao gravar os limites."})


_PLANO_MAX_BYTES = 12 * 1024 * 1024


@app.post("/api/orcamento/plano/importar")
async def orcamento_plano_importar(req: Request, nome: str = "", ano: int = 0,
                                   rotulo: str = "",
                                   simular: int = 0) -> JSONResponse:
    """Importa a planilha do orcamento planejado como versao nova.

    `simular=1` le e concilia SEM gravar: e o que a tela usa para mostrar o
    que casou e o que ficou de fora ANTES de o numero entrar no sistema.
    Importar calado uma planilha que nao fecha e o jeito mais rapido de por
    numero errado no orcamento do ano.
    """
    from datetime import date as _date

    from api.orcamento import plano
    from api.orcamento import servico as orc_servico

    if _tamanho_excede(req.headers.get("content-length"), _PLANO_MAX_BYTES):
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima do limite de {_PLANO_MAX_BYTES // (1024 * 1024)} MB."})
    bruto = await req.body()
    if not bruto:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_vazio", "mensagem": "Nenhum conteudo recebido."})

    hoje = _date.today()
    ano = int(ano or hoje.year)
    # mesma janela de base que a derivacao usa para os pesos do rateio
    meses = orc_servico.janela_base(None, None, hoje)
    if len(meses) < 3:
        meses = [f"{hoje.year - 1:04d}-{m:02d}" for m in range(1, 13)]

    tmp = ROOT / "data" / f"_plano_upload_{ano}.xlsx"
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(bruto)
        if simular:
            return JSONResponse(plano.preparar(tmp, meses))
        usuario = getattr(getattr(req, "state", None), "usuario", "") or ""
        r = plano.importar(tmp, ano,
                           rotulo or f"Plano {ano} (planilha, {nome or 'importado'})",
                           str(usuario), meses)
        # o payload de resposta nao leva as 6 mil celulas: a tela so precisa do
        # relatorio de conciliacao
        r.pop("linhas", None)
        return JSONResponse(r)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_plano_importar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_importacao", "mensagem": "Erro ao importar a planilha."})
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


@app.get("/api/financeiro/antecipacoes")
def antecipacoes_listar() -> JSONResponse:
    """Envios importados, último por portal e sacados com convênio."""
    from api.antecipacoes import registro as reg
    try:
        # posicao VIGENTE por portal: com Maxion, Tupy e Adient no convenio,
        # devolver so o envio mais recente faria os outros dois sumirem da
        # tela sem aviso nenhum
        vigentes = reg.posicao_atual()
        # raiz do CNPJ do sacado -> envio vigente daquele portal
        _plan: dict = {}
        for t in reg.titulos_vigentes():
            raiz = (t.get("cnpj_sacado") or "")[:8]
            if raiz and raiz not in _plan:
                v = next((x for x in vigentes if x["id"] == t["envio_id"]), None)
                if v:
                    _plan[raiz] = {"ts": v["ts"], "arquivo": v["arquivo"],
                                   "titulos": v["titulos"]}
        return JSONResponse({
            "envios": reg.envios(),
            "vigentes": vigentes,
            "ultimo": vigentes[0] if vigentes else None,
            "titulos": reg.titulos_vigentes(),
            "totais": {
                "portais": len(vigentes),
                "titulos": sum(v["titulos"] for v in vigentes),
                "valor_saldo": round(sum(v["valor_saldo"] for v in vigentes), 2),
            },
            # cada sacado com a data da planilha dele. Sem isto a lista mistura
            # "tem convenio e planilha" com "tem convenio e nada importado", que
            # sao situacoes com pendencias opostas
            "sacados": [
                {**sac, "planilha_em": _plan.get(sac["cnpj"][:8], {}).get("ts"),
                 "planilha_arquivo": _plan.get(sac["cnpj"][:8], {}).get("arquivo"),
                 "planilha_titulos": _plan.get(sac["cnpj"][:8], {}).get("titulos")}
                for sac in reg.sacados()],
            "portais": [{"nome": m.nome, "rotulo": m.rotulo}
                        for m in __import__("api.antecipacoes.modelos",
                                            fromlist=["MODELOS"]).MODELOS],
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("antecipacoes_listar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao ler os envios."})


@app.post("/api/financeiro/antecipacoes/importar")
async def antecipacoes_importar(req: Request, nome: str = "") -> JSONResponse:
    """Recebe a planilha do portal como CORPO BRUTO — mesmo padrão do extrato
    (sem multipart, que exigiria python-multipart e derrubaria só este
    endpoint se o `uv sync` do AutoDeploy falhasse)."""
    from api.antecipacoes import conciliacao, leitor
    from api.antecipacoes import registro as reg

    if _tamanho_excede(req.headers.get("content-length"), _ANTEC_MAX_BYTES):
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima do limite de {_ANTEC_MAX_BYTES // (1024 * 1024)} MB."})
    bruto = await req.body()
    if not bruto or len(bruto) > _ANTEC_MAX_BYTES:
        return JSONResponse(status_code=413 if bruto else 422, content={
            "erro": "arquivo_invalido",
            "mensagem": "Nenhum conteúdo recebido." if not bruto
                        else "Arquivo acima do limite."})
    try:
        lido = leitor.ler(nome or "planilha", bruto)
        resumo = leitor.resumir(lido)
    except leitor.ArquivoInvalido as exc:
        # 422 e não 500: o arquivo é que está errado, e a mensagem já diz o
        # que fazer — a tela mostra ela literalmente.
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("antecipacoes_importar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_leitura", "mensagem": "Erro ao ler a planilha."})

    # A conciliação depende do AVA; se o banco estiver fora, a importação NÃO
    # pode falhar por isso — o arquivo já foi lido e vale por si.
    try:
        conc = conciliacao.conciliar(lido["titulos"])
    except Exception as exc:  # noqa: BLE001
        log.warning("conciliacao falhou: %s", exc)
        conc = {"disponivel": False,
                "motivo": "banco indisponível no momento da importação"}

    usuario = getattr(getattr(req, "state", None), "usuario", "") or ""
    try:
        # `bruto` vai junto: e dele que sai a impressao digital que reconhece
        # reimportacao do mesmo arquivo
        envio_id, ja_existia = reg.gravar_envio(lido, resumo, usuario=str(usuario),
                                                dados=bruto)
    except Exception as exc:  # noqa: BLE001
        log.warning("gravar_envio falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao gravar a importação."})

    return JSONResponse({
        "envio_id": envio_id,
        "ja_existia": ja_existia,
        "portal": lido["portal"], "portal_rotulo": lido["portal_rotulo"],
        "confianca": lido["confianca"],
        "linha_cabecalho": lido["linha_cabecalho"],
        "colunas_ignoradas": lido["colunas_ignoradas"],
        "rejeitadas": lido["rejeitadas"],
        "total_declarado": lido["total_declarado"],
        "total_calculado": lido["total_calculado"],
        "divergencia": lido["divergencia"],
        "resumo": resumo, "conciliacao": conc,
    })


@app.post("/api/financeiro/antecipacoes/sacado")
async def antecipacoes_sacado(req: Request) -> JSONResponse:
    """Liga/desliga o convênio de antecipação de um cliente."""
    from api.antecipacoes import registro as reg
    try:
        corpo = await req.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=422, content={
            "erro": "corpo_invalido", "mensagem": "Envie um JSON válido."})
    try:
        return JSONResponse(reg.definir_sacado(
            str(corpo.get("cnpj") or ""), nome=str(corpo.get("nome") or ""),
            elegivel=bool(corpo.get("elegivel", True)),
            observacao=str(corpo.get("observacao") or ""),
            portal=str(corpo.get("portal") or "")))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "dado_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("antecipacoes_sacado falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao gravar o cliente."})


@app.post("/api/financeiro/extrato/importar")
async def extrato_importar(req: Request, nome: str = "",
                           conta_id: int | None = None) -> JSONResponse:
    """Recebe o arquivo como CORPO BRUTO (um POST por arquivo).

    Sem multipart de propósito: `UploadFile` exige python-multipart, que não é
    dependência do projeto — e o `uv sync` do AutoDeploy é não-fatal, então a
    API poderia subir em produção sem a dep e derrubar só este endpoint.
    """
    from api.extrato.servico import importar
    # rejeita pelo header ANTES de materializar o corpo em memória: sem isso,
    # `await req.body()` bufferiza a requisição inteira (o processo é
    # single-process, sem limite de corpo em nível de app) antes mesmo de
    # chegar na checagem de tamanho abaixo — primeiro endpoint de upload por
    # corpo bruto do projeto, então essa superfície é nova aqui.
    if _tamanho_excede(req.headers.get("content-length"), _EXT_MAX_BYTES):
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima do limite de {_EXT_MAX_BYTES // (1024 * 1024)} MB."})
    bruto = await req.body()
    if not bruto:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_vazio", "mensagem": "Nenhum conteúdo recebido."})
    if len(bruto) > _EXT_MAX_BYTES:
        # segunda linha de defesa: Content-Length pode faltar ou mentir (ex.:
        # Transfer-Encoding: chunked não declara tamanho antecipado)
        return JSONResponse(status_code=413, content={
            "erro": "arquivo_grande",
            "mensagem": f"Arquivo acima do limite de {_EXT_MAX_BYTES // (1024 * 1024)} MB."})
    arquivo = (nome or "extrato.ofx").strip()
    try:
        return JSONResponse(importar(bruto, arquivo, conta_id=conta_id))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "arquivo_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_importar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_importacao", "mensagem": "Erro ao importar o extrato."})


@app.post("/api/financeiro/extrato/mapear")
async def extrato_mapear(req: Request) -> JSONResponse:
    """Vincula uma conta ao ERP e/ou salva o mapa de colunas do CSV.

    Sem `conta_id` e com `formato="csv"`, CRIA a conta: a identidade sai da conta
    bancária (`servico.ident_csv`), nunca do nome do arquivo — dois `extrato.csv`
    de bancos diferentes cairiam na mesma conta e misturariam lançamentos.
    """
    from api.extrato import armazenamento as arm
    from api.extrato.servico import ident_csv
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Corpo inválido."})
    conta_id = body.get("conta_id")
    # criação de conta CSV: precisa da conta do ERP para formar a identidade
    if conta_id is None:
        if body.get("formato") != "csv" or body.get("erp_banco") is None:
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": "Informe conta_id, ou formato=csv com a conta do ERP."})
        try:
            arm.init_db(arm.ESQUEMA)
            banco = int(body["erp_banco"])
            agencia = str(body.get("erp_agencia") or "")
            conta = str(body.get("erp_conta") or "")
            ident = ident_csv(banco, agencia, conta)
            rotulo = body.get("rotulo") or f"{banco} / ag {agencia} / cc {conta}"
            conta_id = arm.obter_ou_criar_conta(arm.ESQUEMA, ident, rotulo)
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "Conta do ERP inválida."})
    if not isinstance(conta_id, int):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "conta_id inválido."})
    try:
        arm.init_db(arm.ESQUEMA)
        if body.get("erp_banco") is not None:
            arm.mapear_conta(arm.ESQUEMA, conta_id, int(body["erp_banco"]),
                             str(body.get("erp_agencia") or ""),
                             str(body.get("erp_conta") or ""),
                             rotulo=(body.get("rotulo") or None))
        mapa = body.get("mapa_csv")
        if isinstance(mapa, dict):
            limpo = {k: int(v) for k, v in mapa.items() if isinstance(v, (int, float))}
            arm.salvar_mapa_csv(arm.ESQUEMA, conta_id, limpo)
        # devolve o conta_id: no fluxo CSV a tela precisa dele para reenviar o
        # arquivo (importar exige conta_id explicito para CSV)
        return JSONResponse({"ok": True, "conta_id": conta_id})
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Valores de mapeamento inválidos."})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_mapear falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao salvar o mapeamento."})


@app.delete("/api/financeiro/extrato/importacao/{imp_id}")
def extrato_apagar(imp_id: int) -> JSONResponse:
    from api.extrato import armazenamento as arm
    try:
        arm.init_db(arm.ESQUEMA)
        n = arm.apagar_importacao(arm.ESQUEMA, imp_id)
        return JSONResponse({"ok": True, "apagados": n})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_apagar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao desfazer a importação."})


@app.get("/api/financeiro/extrato/conciliacao")
def extrato_conciliacao(conta_id: int, dt_de: str, dt_ate: str) -> JSONResponse:
    """Conciliacao linha a linha de UMA conta (extrato local x razao do ERP).

    Separado do `/extrato` de propósito: aquele monta o painel das contas
    todas e é o que abre por padrão; este puxa o razão inteiro do período
    (centenas a milhares de linhas por conta) e só faz sentido sob demanda.
    """
    from api.extrato.servico import conciliar
    try:
        return JSONResponse(conciliar(conta_id, dt_de, dt_ate))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_conciliacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a conciliação."})


@app.get("/api/financeiro/extrato/contas-erp")
def extrato_contas_erp() -> JSONResponse:
    from api.extrato.servico import contas_erp
    try:
        return JSONResponse({"contas": contas_erp()})
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_contas_erp falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao listar as contas do ERP."})


@app.get("/api/controladoria/orcamento/exportar")
def orcamento_exportar(versao_id: int) -> Response:
    from api.orcamento.servico import exportar_csv
    if versao_id <= 0:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe um versao_id válido (inteiro > 0)."})
    try:
        conteudo, filename = exportar_csv(versao_id)
        return Response(content=conteudo, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except KeyError:
        return JSONResponse(status_code=404, content={
            "erro": "nao_encontrado", "mensagem": "Versão de orçamento inexistente."})
    except Exception as exc:  # noqa: BLE001
        log.warning("orcamento_exportar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao exportar o orçamento."})


@app.get("/api/tv/estradas")
def tv_estradas() -> JSONResponse:
    """Config do overlay de trânsito (TomTom).

    A chave sai em texto claro no payload (necessário: o Leaflet carrega os
    tiles direto do browser, client-side). Mitigação real é no PROVEDOR, não
    no código: restringir a chave por domínio/referrer no painel do TomTom
    para que não seja reutilizável fora do painel, mesmo se copiada daqui.

    LÊ DO COFRE, e não mais direto do ambiente — `credenciais.ler` já faz
    cofre-primeiro-ambiente-depois. Dois lugares guardando a mesma chave é
    exatamente o defeito que a Premiação teve por semanas: a tela de
    configuração salvava, dizia "salvo", e o cálculo lia o outro armazém.
    Enquanto os dois concordassem, ninguém veria.

    E DEVOLVE SÓ A CHAVE DO MAPA. A do servidor, quando existe, é a que NÃO
    está restrita por domínio — mandá-la para o navegador entregaria de graça
    justamente a que funciona em qualquer lugar.
    """
    from api.tomtom import cliente as tomtom
    chave = tomtom.chave_mapa() or ""
    return JSONResponse({"configurado": bool(chave), "key": chave})


@app.post("/api/operacao/milkrun/chat-stream")
def operacao_milkrun_chat(payload: dict) -> StreamingResponse:
    """Chat restrito ao roteiro do milk run, SEMPRE no modelo local.

    Sem fallback externo de proposito: o contexto leva placa e fornecedor, e
    esse dado nao sai da maquina (CLAUDE.md secao 8, regra 3). Com o Ollama
    fora, o chat diz que esta indisponivel em vez de degradar calado para
    escalares — a resposta pareceria boa e seria pior.
    """
    import json as _json
    from api.milkrun.copiloto import LocalIndisponivel, stream as _mk_stream

    mensagens = payload.get("mensagens")
    if _mensagens_invalidas(mensagens):
        def _erro():
            yield 'data: {"tipo":"erro","erro":"parametro_invalido"}\n\n'
        return StreamingResponse(_erro(), media_type="text/event-stream")
    de, ate = payload.get("de") or None, payload.get("ate") or None
    for nome, valor in (("de", de), ("ate", ate)):
        if valor and _bad_date(valor):
            def _errodata():
                yield ('data: {"tipo":"erro","erro":"parametro_invalido",'
                       '"mensagem":"Data invalida: use AAAA-MM-DD."}\n\n')
            return StreamingResponse(_errodata(), media_type="text/event-stream")
    tomador = payload.get("tomador") or "02162259"
    if not re.fullmatch(r"\d{2,14}", tomador):
        tomador = "02162259"
    tipo = payload.get("tipo") if payload.get("tipo") in ("milk", "simples", "") else "milk"

    def gen():
        try:
            for ev in _mk_stream(mensagens, de, ate, tomador, tipo or "milk"):
                yield "data: " + _json.dumps(ev, ensure_ascii=False) + "\n\n"
        except LocalIndisponivel as exc:
            yield "data: " + _json.dumps(
                {"tipo": "erro", "erro": "local_indisponivel",
                 "mensagem": str(exc)}, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            log.warning("milkrun chat falhou: %s", exc)
            yield 'data: {"tipo":"erro","erro":"stream_falhou"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/copiloto/status")
def copiloto_status() -> JSONResponse:
    # contexto = procedência do snapshot (telas, idade, fontes que falharam);
    # o front mostra no ⓘ da tela do copiloto
    ctx = copiloto.contexto()
    st = copiloto.ollama_status()
    if st["ok"]:
        return JSONResponse({"configurado": True, "local": True,
                             "modelo": f"{st['modelo']} (local)", "contexto": ctx})
    modelo = None
    try:
        lista = copiloto.modelos_free()
        modelo = lista[0] if lista else None
    except Exception as exc:  # noqa: BLE001
        log.warning("catalogo openrouter indisponivel: %s", exc)
    return JSONResponse({"configurado": bool(copiloto.api_key()), "local": False,
                         "modelo": modelo, "chave": copiloto.status_chave(),
                         "contexto": ctx})


_COP_ROLES = {"user", "assistant", "system"}
_COP_MSG_MAX = 8000


def _mensagens_invalidas(mensagens: object) -> bool:
    """Valida a FORMA de cada item (role/content), não só o tamanho da
    lista — antes um payload malformado ou com content gigante só era pego
    (às vezes) pelo try/except do copiloto.stream()/chat(), rio abaixo."""
    if not isinstance(mensagens, list) or not mensagens or len(mensagens) > 24:
        return True
    for m in mensagens:
        if not isinstance(m, dict) or m.get("role") not in _COP_ROLES:
            return True
        conteudo = m.get("content")
        if not isinstance(conteudo, str) or not conteudo.strip() or len(conteudo) > _COP_MSG_MAX:
            return True
    return False


@app.post("/api/copiloto/chat-stream")
def copiloto_chat_stream(payload: dict) -> StreamingResponse:
    import json as _json
    mensagens = payload.get("mensagens")
    if _mensagens_invalidas(mensagens):
        def _erro():
            yield 'data: {"tipo":"erro","erro":"parametro_invalido"}\n\n'
        return StreamingResponse(_erro(), media_type="text/event-stream")

    def gen():
        try:
            for ev in copiloto.stream(mensagens):
                yield "data: " + _json.dumps(ev, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            log.warning("stream falhou: %s", exc)
            yield 'data: {"tipo":"erro","erro":"stream_falhou"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/copiloto/chat")
def copiloto_chat(payload: dict) -> JSONResponse:
    mensagens = payload.get("mensagens")
    if _mensagens_invalidas(mensagens):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Envie 'mensagens' como lista de {role, content} (máx. 24)."})
    try:
        r = copiloto.chat(mensagens)
    except Exception as exc:  # noqa: BLE001
        log.warning("copiloto falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_copiloto", "mensagem": "Erro inesperado no copiloto."})
    if r.get("erro") == "sem_backend":
        return JSONResponse(status_code=503, content={
            "erro": "sem_backend",
            "mensagem": "Copiloto sem motor de IA: inicie o Ollama local (modelo gemma4) "
                        "ou adicione OPENROUTER_API_KEY ao .env e reinicie a API."})
    if r.get("erro") == "chave_invalida":
        return JSONResponse(status_code=503, content={
            "erro": "chave_invalida",
            "mensagem": "A OPENROUTER_API_KEY do .env foi recusada pelo OpenRouter."})
    if r.get("erro"):
        return JSONResponse(status_code=503, content={
            "erro": "modelos_indisponiveis",
            "mensagem": "Os modelos gratuitos estão indisponíveis agora (rate limit). Tente de novo em instantes.",
            "detalhe": r.get("detalhe", "")})
    return JSONResponse(r)


@app.get("/api/operacao/programacao")
def programacao() -> JSONResponse:
    try:
        return JSONResponse(queries.get_programacao())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("programacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a programação."})


@app.get("/api/operacao/seguranca")
def seguranca() -> JSONResponse:
    try:
        return JSONResponse(queries.get_seguranca())
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("seguranca falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a torre de segurança."})


@app.get("/api/frota/multas")
def multas(
    dt_de: str | None = None,
    dt_ate: str | None = None,
    placa: str | None = None,
    orgao: str | None = None,
) -> JSONResponse:
    from datetime import timedelta
    hoje = date.today()
    dt_ate = dt_ate or hoje.isoformat()
    dt_de = dt_de or (hoje - timedelta(days=365)).isoformat()
    for nome, valor in (("dt_de", dt_de), ("dt_ate", dt_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD."})
    if dt_de > dt_ate:
        dt_de, dt_ate = dt_ate, dt_de
    placa = (placa or "").strip() or None
    try:
        orgao_f = (orgao or '').strip() or None
        return JSONResponse(queries.get_multas(dt_de, dt_ate, placa=placa,
                                               orgao=orgao_f))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("multas falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar as multas."})


def _bad_date(value: str | None) -> bool:
    if value is None:
        return False
    try:
        date.fromisoformat(value)
        return False
    except ValueError:
        return True


_MES_PREM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _mes_prem_invalido(mes: str | None) -> bool:
    """M3: `mes` fora do formato AAAA-MM (500 genérico antes) ou com ano fora
    de uma faixa plausível — um mês inexistente tipo `1990-01` disparava
    coleta real e poluía o `index.json`/seletor da tela para sempre."""
    if mes is None:
        return False
    if not _MES_PREM_RE.match(mes):
        return True
    ano = int(mes[:4])
    return not (2020 <= ano <= date.today().year + 1)


_MES_PREM_ERRO = {
    "erro": "parametro_invalido",
    "mensagem": "Parâmetro mes inválido: use o formato AAAA-MM, com ano entre 2020 e o ano corrente + 1.",
}


@app.get("/api/frota/premiacao")
def premiacao(mes: str | None = None) -> JSONResponse:
    from api.premiacao import servico
    from api.gobrax.cliente import GobraxIndisponivel, GobraxNaoConfigurado
    if _mes_prem_invalido(mes):
        return JSONResponse(status_code=422, content=_MES_PREM_ERRO)
    try:
        return JSONResponse(servico.obter(mes))
    except (GobraxIndisponivel, GobraxNaoConfigurado) as exc:
        return JSONResponse(status_code=503, content={
            "erro": "gobrax_indisponivel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a premiação."})


@app.post("/api/frota/premiacao/atualizar")
async def premiacao_atualizar(req: Request) -> JSONResponse:
    from api.premiacao import servico
    from api.gobrax.cliente import GobraxIndisponivel, GobraxNaoConfigurado
    try:
        body = await req.json()
    except Exception:
        body = None
    mes = body.get("mes") if isinstance(body, dict) else None
    if _mes_prem_invalido(mes):
        return JSONResponse(status_code=422, content=_MES_PREM_ERRO)
    try:
        # sem mês = "Atualizar dados" da tela: recoleta o corrente E preenche
        # os últimos 6 meses que faltarem (backfill); com mês = só aquele mês
        if mes is None:
            return JSONResponse(servico.atualizar_tudo())
        return JSONResponse(servico.obter(mes, force=True))
    except (GobraxIndisponivel, GobraxNaoConfigurado) as exc:
        return JSONResponse(status_code=503, content={
            "erro": "gobrax_indisponivel", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_atualizar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao atualizar a premiação."})


@app.get("/api/premiacao/config")
def premiacao_config(competencia: str | None = None) -> JSONResponse:
    """Parâmetros e pesos vigentes, mais o catálogo para a tela se desenhar."""
    from api.premiacao import classificacao, config
    comp = (competencia or datetime.now().strftime("%Y-%m")).strip()
    try:
        d = config.ler(comp)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_config: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_config",
            "mensagem": "Não foi possível ler a configuração da premiação."})
    d["catalogo"] = config.catalogo()
    d["versoes"] = config.versoes()
    from api.premiacao import apuracao
    d["apuracao"] = apuracao.estado(comp)
    try:
        d["ocorrencias"] = classificacao.listar()
        d["pendentes"] = classificacao.pendentes()
    except Exception as exc:  # noqa: BLE001
        # sem o AVA a classificação não carrega, mas os PARÂMETROS carregam:
        # travar a tela inteira por causa de uma metade seria pior.
        d["ocorrencias"] = []
        d["pendentes"] = None
        d["erro_ocorrencias"] = type(exc).__name__
    return JSONResponse(d)


@app.post("/api/premiacao/config")
async def premiacao_config_salvar(req: Request) -> JSONResponse:
    """Grava a versão que passa a valer a partir da competência informada."""
    from api.premiacao import config
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    sess = getattr(req.state, "sessao", None) or {}
    try:
        d = config.salvar(
            (body.get("competencia") or "").strip(),
            body.get("params") or {}, body.get("eixos") or {},
            autor=sess.get("email", ""), nota=(body.get("nota") or "").strip())
    except ValueError as exc:
        # RECUSA por regra é 4xx: o Cloudflare troca o corpo dos 5xx pelo dele
        # e a mensagem que a pessoa precisa ler nunca chegaria à tela.
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_config_salvar: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_salvar",
            "mensagem": "Não foi possível gravar a configuração."})
    auth.audit(sess.get("email", "?"), "premiacao_config",
               alvo=body.get("competencia", ""),
               detalhe=(body.get("nota") or "")[:200])
    return JSONResponse(d)


@app.post("/api/premiacao/recoletar")
async def premiacao_recoletar(req: Request) -> JSONResponse:
    """Refaz a coleta das competências do período.

    `sem_travar` porque cada competência é uma volta na API da Gobrax: numa
    rota `async def`, isso travaria o event loop e o CÓRTEX inteiro pelo tempo
    da chamada — seis meses de recoleta deixariam o painel fora do ar.
    """
    from api.premiacao import apuracao
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    sess = getattr(req.state, "sessao", None) or {}
    autor = sess.get("email", "")
    de = (body.get("de") or "").strip()
    ate = (body.get("ate") or de).strip()
    try:
        r = await sem_travar(lambda: apuracao.recoletar(de, ate, autor=autor))
    except ValueError as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_recoletar: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_recoleta",
            "mensagem": "Não foi possível recoletar o período."})
    # Recoleta muda valor de prêmio: quem pediu e o que saiu ficam na trilha.
    auth.audit(autor or "?", "premiacao_recoletar", alvo=f"{de}..{ate}",
               detalhe="; ".join(
                   f"{c['competencia']}:{'ok' if c['ok'] else c['erro']}"
                   for c in r["competencias"])[:400])
    return JSONResponse(r)


@app.post("/api/premiacao/ocorrencias")
async def premiacao_ocorrencia_classe(req: Request) -> JSONResponse:
    """Classifica um tipo de ocorrência (demérito, neutro, mérito)."""
    from api.premiacao import classificacao
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    sess = getattr(req.state, "sessao", None) or {}
    try:
        classificacao.salvar(
            int(body.get("codigo")), (body.get("classe") or "").strip(),
            peso=float(body.get("peso") or 1), grupo=(body.get("grupo") or "").strip(),
            bloqueia=int(body.get("bloqueia") or 0),
            autor=sess.get("email", ""))
    except (ValueError, TypeError) as exc:
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_ocorrencia: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_salvar", "mensagem": "Não foi possível classificar."})
    auth.audit(sess.get("email", "?"), "premiacao_ocorrencia",
               alvo=str(body.get("codigo")), detalhe=str(body.get("classe")))
    return JSONResponse({"ok": True, "pendentes": classificacao.pendentes()})


@app.post("/api/premiacao/ocorrencias/sincronizar")
async def premiacao_ocorrencia_sync(req: Request) -> JSONResponse:
    """Traz tipos novos do ERP. NUNCA sobrescreve classificação já decidida."""
    from api.premiacao import classificacao
    sess = getattr(req.state, "sessao", None) or {}
    try:
        r = await sem_travar(lambda: classificacao.sincronizar(
            autor=sess.get("email", "")))
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_sync: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_sync",
            "mensagem": "Não foi possível ler o catálogo do ERP."})
    return JSONResponse({**r, "pendentes": classificacao.pendentes()})


# A ROTA `POST /api/frota/premiacao/params` SAIU EM 0.153.0.
# Ela gravava `data/premiacao_params.json`, que era um SEGUNDO armazém de
# parâmetro ao lado de `prem_versoes` — os dois com as mesmas três chaves e os
# mesmos padrões, então concordavam por coincidência enquanto ninguém editasse
# nada. Depois que o cálculo passou a ler a versão VIGENTE NA COMPETÊNCIA
# (`servico.params_da_competencia`), salvar por aqui não mudaria número nenhum:
# um formulário que diz "salvo" e não altera o prêmio. Quem configura é a aba
# Configuração, versionada. `api/premiacao/params.py` continua vivo como
# FALLBACK de leitura para quando o banco local estiver fora.


@app.get("/api/frota/premiacao/serie")
def premiacao_serie() -> JSONResponse:
    from api.premiacao import servico
    try:
        return JSONResponse(servico.serie())
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_serie falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a série da premiação."})


@app.get("/api/financeiro/overview")
def overview(
    filial: int | None = None,
    data_ref: str | None = None,
    horizonte: int = 12,
    venc_de: str | None = None,
    venc_ate: str | None = None,
) -> JSONResponse:
    horizonte = max(1, min(horizonte, 36))
    for nome, valor in (("data_ref", data_ref), ("venc_de", venc_de), ("venc_ate", venc_ate)):
        if _bad_date(valor):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido",
                "mensagem": f"Parâmetro {nome} inválido: use o formato AAAA-MM-DD.",
            })
    try:
        return JSONResponse(queries.get_overview(
            filial=filial, data_ref=data_ref, horizonte=horizonte,
            venc_de=venc_de, venc_ate=venc_ate))
    except psycopg.OperationalError as exc:
        log.warning("overview sem conexão: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("overview falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao executar a consulta no banco.",
        })


# ------------------------------------------------- Report de bug/melhoria

# Print de tela + até 5 anexos. Mesmo teto declarado no serviço, que refaz a
# conta sobre o dado já desserializado.
_REP_MAX_BYTES = 15 * 1024 * 1024


@app.get("/api/report/config")
def report_config() -> JSONResponse:
    """Compatibilidade com o index.html antigo em cache do navegador: o botão
    existe SEMPRE (o chamado é local-first, não depende do GitHub); o modal novo
    lê /api/suporte/meus/config. Some numa versão futura."""
    from api.reports import github as gh

    return JSONResponse({"ativo": True, "repo": gh.repo_configurado()})


@app.post("/api/report")
async def report_criar(req: Request, bg: BackgroundTasks) -> JSONResponse:
    """Alias de POST /api/suporte/meus/chamados (página antiga em cache)."""
    from api.suporte import rotas as sup_rotas

    return await sup_rotas.abrir(req, bg)
