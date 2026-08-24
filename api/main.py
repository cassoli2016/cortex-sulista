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
from datetime import date
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import (alertas, auth, copiloto, db, documentacao, dre_cliente, push, queries,
               queries_folha, servidor)

log = logging.getLogger("cortex.financeiro")


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
        e = estatisticas.sincronizar(comp)
        o = odometro.sincronizar(comp)
        return JSONResponse({"competencia": comp, "estatisticas": e["gravadas"],
                             "odometro": o["gravadas"]})
    except ColetaVazia as exc:
        log.warning("coleta de telemetria vazia: %s", exc)
        return JSONResponse(status_code=502, content={
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
        return JSONResponse(status_code=502, content={
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
        return JSONResponse(status_code=502, content={
            "erro": "gobrax_indisponivel",
            "mensagem": "A Gobrax não respondeu para este veículo."})
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_conducao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a condução."})


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
        return JSONResponse(status_code=502, content={
            "erro": "gobrax_indisponivel", "mensagem": "A Gobrax não respondeu."})
    except Exception as exc:  # noqa: BLE001
        log.warning("telemetria_rastro falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o rastro."})


# ---------------------------------------------------------------- Integrações (credenciais)

@app.get("/api/gestao/credenciais")
def gestao_credenciais() -> JSONResponse:
    """Status das credenciais de integração. NUNCA devolve o valor."""
    from api import credenciais
    # /api/gestao/* já é restrito a admin pelo AuthMiddleware (api/auth.py:654)
    return JSONResponse({"credenciais": credenciais.listar()})


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

    r = enviar(destinatarios, assunto, corpo, usuario=autor, origem=origem)
    auth.audit(autor or "?", "email_enviar",
               alvo=", ".join(r["destinatarios"])[:200],
               detalhe=("ok" if r["ok"] else f"falha: {r['erro']}")[:200])
    if not r["ok"]:
        return JSONResponse(status_code=502, content={
            "erro": "envio_falhou", "mensagem": r["erro"]})
    return JSONResponse({"ok": True, "destinatarios": r["destinatarios"]})


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
        return JSONResponse(atualizar_base(
            (hoje - timedelta(days=365)).isoformat(), hoje.isoformat()))
    except BaseVazia as exc:
        log.warning("sync do rntrc veio vazia: %s", exc)
        return JSONResponse(status_code=502, content={
            "erro": "sync_vazia",
            "mensagem": ("A base da ANTT não trouxe nenhum dos transportadores "
                         "procurados. A base anterior foi mantida."),
        })
    except LayoutInesperado as exc:
        log.warning("layout do csv do rntrc mudou: %s", exc)
        return JSONResponse(status_code=502, content={
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


@app.get("/api/jornada/painel")
def jornada_painel(comp_de: str | None = None, comp_ate: str | None = None,
                   busca: str | None = None) -> JSONResponse:
    r = _comp_defaults(comp_de, comp_ate)
    if isinstance(r, JSONResponse):
        return r
    comp_de, comp_ate = r
    busca = (busca or "").strip() or None
    try:
        return JSONResponse(queries.get_jornada(comp_de, comp_ate, busca))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_painel falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a jornada."})


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


@app.get("/api/rh/folha-indicadores")
def rh_folha_indicadores() -> JSONResponse:
    try:
        return JSONResponse(queries_folha.get_folha_indicadores())
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
def jornada_motorista(id: str | None = None, comp_de: str | None = None,
                      comp_ate: str | None = None) -> JSONResponse:
    tok = (id or "").strip()
    if not tok:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe o motorista."})
    r = _comp_defaults(comp_de, comp_ate)
    if isinstance(r, JSONResponse):
        return r
    comp_de, comp_ate = r
    try:
        return JSONResponse(queries.get_motorista_jornada(tok, comp_de, comp_ate))
    except psycopg.OperationalError as exc:
        log.warning("banco inacessivel: %s", exc)
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?"})
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_motorista falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o motorista."})


# Rentabilidade por Cliente APOSENTADA (2026-07-17): superada pela DRE por
# Cliente (bottom-up, reconciliada). A matriz margem x receita migrou p/ a DRE
# por Cliente. queries.get_rentabilidade fica dormente (sem rota/menu).


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
        arm.init_db(arm.DB_PATH)
        versoes = arm.listar_versoes(arm.DB_PATH, ano)
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
        arm.init_db(arm.DB_PATH)
        if versao_id is None:
            # a versão vigente (não a de id mais alto cru): prefere aprovada,
            # nunca escolhe arquivada — sem isso, regerar (que arquiva uma
            # cópia do estado anterior) fazia a tela abrir sozinha no
            # snapshot congelado, por ele ter o id mais novo.
            vigente = arm.versao_vigente(arm.DB_PATH)
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
        arm.ajustar(arm.DB_PATH, versao_id, conta, mes, valor, quem)
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
        arm.aprovar(arm.DB_PATH, versao_id, quem)
        versao = next(v for v in arm.listar_versoes(arm.DB_PATH) if v["id"] == versao_id)
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
        arm.reabrir(arm.DB_PATH, versao_id)
        versao = next(v for v in arm.listar_versoes(arm.DB_PATH) if v["id"] == versao_id)
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
        parm.init_db(parm.DB_PATH)
        if valor is None:
            parm.remover_ajuste_prev(parm.DB_PATH, mes, linha, quem)
        else:
            parm.salvar_ajuste_prev(parm.DB_PATH, mes, linha,
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
            arm.init_db(arm.DB_PATH)
            banco = int(body["erp_banco"])
            agencia = str(body.get("erp_agencia") or "")
            conta = str(body.get("erp_conta") or "")
            ident = ident_csv(banco, agencia, conta)
            rotulo = body.get("rotulo") or f"{banco} / ag {agencia} / cc {conta}"
            conta_id = arm.obter_ou_criar_conta(arm.DB_PATH, ident, rotulo)
        except (TypeError, ValueError):
            return JSONResponse(status_code=422, content={
                "erro": "parametro_invalido", "mensagem": "Conta do ERP inválida."})
    if not isinstance(conta_id, int):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "conta_id inválido."})
    try:
        arm.init_db(arm.DB_PATH)
        if body.get("erp_banco") is not None:
            arm.mapear_conta(arm.DB_PATH, conta_id, int(body["erp_banco"]),
                             str(body.get("erp_agencia") or ""),
                             str(body.get("erp_conta") or ""),
                             rotulo=(body.get("rotulo") or None))
        mapa = body.get("mapa_csv")
        if isinstance(mapa, dict):
            limpo = {k: int(v) for k, v in mapa.items() if isinstance(v, (int, float))}
            arm.salvar_mapa_csv(arm.DB_PATH, conta_id, limpo)
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
        arm.init_db(arm.DB_PATH)
        n = arm.apagar_importacao(arm.DB_PATH, imp_id)
        return JSONResponse({"ok": True, "apagados": n})
    except Exception as exc:  # noqa: BLE001
        log.warning("extrato_apagar falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_gravacao", "mensagem": "Erro ao desfazer a importação."})


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
    """Config do overlay de trânsito (TomTom). A chave fica no .env.

    A chave sai em texto claro no payload (necessário: o Leaflet carrega os
    tiles direto do browser, client-side). Mitigação real é no PROVEDOR, não
    no código: restringir a chave por domínio/referrer no painel do TomTom
    para que não seja reutilizável fora do painel, mesmo se copiada daqui.
    """
    import os
    chave = os.environ.get("TOMTOM_API_KEY", "").strip()
    return JSONResponse({"configurado": bool(chave), "key": chave})


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


@app.post("/api/frota/premiacao/params")
async def premiacao_params(req: Request) -> JSONResponse:
    from api.premiacao import params as premiacao_params_mod
    try:
        body = await req.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Corpo da requisição inválido: envie um objeto JSON."})
    try:
        efetivo = premiacao_params_mod.salvar_params(body)
        return JSONResponse({"ok": True, "params": efetivo})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao_params falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao salvar os parâmetros."})


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
        return JSONResponse(status_code=502, content={
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
