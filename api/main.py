"""CÓRTEX — API do MVP do painel Financeiro.

Backend leve (roda neste Mac por enquanto). Lê o ERP AVA pelo túnel SSH e serve
o painel financeiro. Requer o túnel ativo (127.0.0.1:15432).

Rodar:  uv run uvicorn api.main:app --reload --port 8000
Abrir:  http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import logging
import re
import tomllib
from datetime import date, datetime
from pathlib import Path

from api import segredo_arquivo

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.responses import JSONResponse as _JSONResponseBase
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import (alertas, auth, copiloto, db, documentacao, dre_cliente, push, queries,
               queries_folha, servidor)


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
# a raiz do repositorio -- usada por rota que grava arquivo temporario
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"


@app.get("/")
def index() -> FileResponse:
    # o painel evolui com frequência: o navegador deve sempre revalidar
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # servido da RAIZ (não de /static) para o escopo do SW ser "/" — senão
    # navigator.serviceWorker.ready nunca resolve (escopo /static/ não controla /)
    return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


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


_OC_STATUS_VALIDOS = {"aprovacao", "aguardando", "atrasada", "recebida"}


@app.get("/api/suprimentos/oc-pendentes")
def oc_pendentes(dias_min: int = 180) -> JSONResponse:
    """OCs abertas sem nota, por tempo em aberto. Não segue o filtro de
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
    return JSONResponse({
        "competencia": comp,
        "kpis": {"veiculos": len(linhas), "sem_leitura": sem_leitura,
                 "com_leitura": len(linhas) - sem_leitura},
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
    try:
        # o valor sai daqui direto para o cofre: nada de log, nada de eco
        st = credenciais.gravar(str(body["nome"]), str(body.get("valor") or ""))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("falha ao gravar credencial %s: %s",
                    body.get("nome"), type(exc).__name__)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao",
            "mensagem": "Não foi possível gravar a credencial."})
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
                                               conferir_titularidade, ler)
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
            valida_ate=lido["valida_ate"], titular=lido["titular"], senha=senha)
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
def rh_ferias(dias: int = 90, filial: str = "") -> JSONResponse:
    """Vencimento de ferias pela regra da CLT (aquisitivo + 12 meses = dobra).

    Devolve NOME e CHAPA pela mesma razao da tela de CNH: ninguem agenda as
    ferias de "um funcionario". Salario, CPF e dado bancario ficam fora.
    """
    from api.queries_folha import get_ferias
    try:
        return JSONResponse(get_ferias(dias=dias, filial=filial))
    except Exception as exc:  # noqa: BLE001
        log.warning("rh_ferias falhou: %s", exc)
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
def operacao_pedagio(dias: int = 365) -> JSONResponse:
    """Validação de pedágio: vale-pedágio × CT-e × coleta, por eixo e modalidade.

    Os três números existem e NÃO batem, e a tela nomeia a diferença em vez de
    escolher um: o CT-e cobra a taxa do cliente, a coleta lança o pedágio da
    operação e o vale é o que se adianta ao transportador. Medido em 12 meses,
    R$ 4,86 mi × R$ 5,69 mi × R$ 1,76 mi.
    """
    import datetime as _dt
    try:
        dias = max(30, min(int(dias or 365), 730))
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Período inválido: informe os dias em número."})
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


@app.get("/api/suprimentos/custos")
def suprimentos_custos(dt_de: str | None = None, dt_ate: str | None = None,
                       origem: str | None = None,
                       filial: str | None = None) -> JSONResponse:
    hoje = date.today()
    dt_de = dt_de or f"{hoje.year}-{hoje.month:02d}-01"
    dt_ate = dt_ate or hoje.isoformat()
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
    push.iniciar_scheduler()  # digest diário; no-op se VAPID não configurado


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
    """Diz ao painel se o botão de report deve existir.

    Sem GITHUB_TOKEN/REPORT_REPO o recurso nasce desligado, sem erro, e o botão
    nem chega a ser inserido no DOM — mesmo padrão de GOBRAX e VAPID.
    """
    from api.reports import github as gh

    return JSONResponse({"ativo": gh.configurado(), "repo": gh.repo_configurado()})


def _report_responder(bruto: bytes, usuario: dict, cliente) -> JSONResponse:
    """Miolo síncrono do POST: corpo já lido, usuário da SESSÃO e cliente GitHub.

    Separado do endpoint porque o projeto não tem harness de sessão: assim o
    mapeamento erro → status é testável sem subir a app com cookie válido.
    """
    from api.reports import servico as srv
    from api.reports.github import ErroGitHub

    if cliente is None:
        return JSONResponse(status_code=503, content={
            "erro": "nao_configurado",
            "mensagem": "O envio de report não está configurado neste servidor."})
    try:
        payload = json.loads(bruto or b"")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse(status_code=422, content={
            "erro": "corpo_invalido", "mensagem": "Corpo inválido."})
    try:
        dado = srv.registrar(payload, usuario, cliente)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "report_invalido", "mensagem": str(exc)})
    except ErroGitHub as exc:
        # mensagem do próprio GitHub ("Bad credentials", "Not Found") — já é
        # sanitizada e é o que a pessoa precisa ver para saber que não é culpa
        # dela; o token nunca passa por aqui
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "github_falhou", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        # detalhe interno fica no log do servidor, nunca na resposta: uma
        # exceção de biblioteca pode carregar cabeçalho/credencial no texto
        log.warning("report falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_report", "mensagem": "Erro ao registrar o report."})

    auth.audit(usuario.get("email") or "", "report_criado",
               f"issue #{dado['numero']}", str(payload.get("titulo") or ""))
    return JSONResponse(dado)


@app.post("/api/report")
async def report_criar(req: Request) -> JSONResponse:
    """Registra o report como issue. Um POST só, anexos em base64 no JSON.

    Mesmas duas linhas de defesa de tamanho do `extrato_importar`: o header
    antes de materializar o corpo, e o tamanho real depois — Content-Length
    pode faltar ou mentir.
    """
    from api.reports import github as gh

    grande = {"erro": "report_grande",
              "mensagem": f"O report passa de {_REP_MAX_BYTES // (1024 * 1024)} MB. "
                          "Remova um anexo e tente de novo."}
    if _tamanho_excede(req.headers.get("content-length"), _REP_MAX_BYTES):
        return JSONResponse(status_code=413, content=grande)
    bruto = await req.body()
    if len(bruto) > _REP_MAX_BYTES:
        return JSONResponse(status_code=413, content=grande)
    sessao = getattr(req.state, "sessao", None) or {}
    return _report_responder(bruto, sessao, gh.do_ambiente())
