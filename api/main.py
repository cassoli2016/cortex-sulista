"""CÓRTEX — API do MVP do painel Financeiro.

Backend leve (roda neste Mac por enquanto). Lê o ERP AVA pelo túnel SSH e serve
o painel financeiro. Requer o túnel ativo (127.0.0.1:15432).

Rodar:  uv run uvicorn api.main:app --reload --port 8000
Abrir:  http://127.0.0.1:8000
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import alertas, auth, copiloto, db, dre_cliente, queries, servidor

log = logging.getLogger("cortex.financeiro")
# docs/openapi desligados: o painel é exposto na internet via Cloudflare Tunnel
app = FastAPI(title="Cortex Sulista — Financeiro (MVP)",
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(auth.AuthMiddleware)
app.include_router(auth.router_auth)
app.include_router(auth.router_gestao)
STATIC = Path(__file__).resolve().parent / "static"


@app.get("/")
def index() -> FileResponse:
    # o painel evolui com frequência: o navegador deve sempre revalidar
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
            "erro": "erro_coleta", "mensagem": "Erro ao coletar a saúde do servidor.",
            "detalhe": str(exc)})


@app.get("/api/financeiro/filtros")
def filtros() -> JSONResponse:
    try:
        return JSONResponse(queries.get_filtros())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"erro": "banco_inacessivel", "detalhe": str(exc)})


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("dre falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao executar a consulta da DRE.",
            "detalhe": str(exc),
        })


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("dre-cliente falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao calcular a DRE por cliente.",
            "detalhe": str(exc),
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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("ordens_compra falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar ordens de compra.",
            "detalhe": str(exc),
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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("agregados falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao consultar agregados e terceiros.",
            "detalhe": str(exc),
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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("make_vs_buy falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao calcular o make-vs-buy.",
            "detalhe": str(exc),
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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("combustivel falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar combustível.",
            "detalhe": str(exc)})


@app.get("/api/frota/manutencao")
def manutencao(
    filial: int | None = None,
    dt_de: str | None = None,
    dt_ate: str | None = None,
    placa: str | None = None,
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
    placa = (placa or "").strip() or None
    try:
        return JSONResponse(queries.get_manutencao(filial, dt_de, dt_ate, placa=placa))
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("manutencao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar manutenção.",
            "detalhe": str(exc)})


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("comercial falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o comercial.",
            "detalhe": str(exc)})


@app.get("/api/visao-geral")
def visao_geral() -> JSONResponse:
    try:
        return JSONResponse(queries.get_visao_geral())
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("visao_geral falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a visão geral.",
            "detalhe": str(exc)})


@app.get("/api/financeiro/cobranca")
def cobranca(filial: int | None = None, cliente: str | None = None) -> JSONResponse:
    cliente = (cliente or "").strip() or None
    try:
        return JSONResponse(queries.get_cobranca(filial, cliente=cliente))
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("cobranca falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a cobrança.",
            "detalhe": str(exc)})


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("analise_km falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a análise de km.",
            "detalhe": str(exc)})


@app.get("/api/operacao/torre")
def torre(filial: int | None = None) -> JSONResponse:
    try:
        return JSONResponse(queries.get_torre(filial))
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("torre falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a torre de controle.",
            "detalhe": str(exc)})


@app.get("/api/frota/veiculos")
def veiculos(modalidade: str | None = None, situacao: str = "ativos") -> JSONResponse:
    if modalidade and modalidade not in ("TRA", "LOC", "AGR", "TER"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "modalidade deve ser TRA, LOC, AGR ou TER."})
    if situacao not in ("ativos", "todos"):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "situacao deve ser ativos ou todos."})
    try:
        return JSONResponse(queries.get_veiculos(modalidade=modalidade, situacao=situacao))
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("veiculos falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar os veículos.",
            "detalhe": str(exc)})


@app.get("/api/frota/veiculo")
def veiculo_ficha(placa: str | None = None) -> JSONResponse:
    placa = (placa or "").strip()
    if not placa:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": "Informe a placa do veículo."})
    try:
        return JSONResponse(queries.get_veiculo_ficha(placa))
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("veiculo_ficha falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o veículo.",
            "detalhe": str(exc)})


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("cliente_ficha falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o cliente.",
            "detalhe": str(exc)})


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_painel falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar a jornada.",
            "detalhe": str(exc)})


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("jornada_motorista falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar o motorista.",
            "detalhe": str(exc)})


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
            "erro": "erro_consulta", "mensagem": "Erro ao montar os alertas.",
            "detalhe": str(exc)})


@app.get("/api/alertas/digest", response_class=PlainTextResponse)
def alertas_digest() -> PlainTextResponse:
    try:
        return PlainTextResponse(alertas.digest_texto())
    except Exception as exc:  # noqa: BLE001
        log.warning("digest falhou: %s", exc)
        return PlainTextResponse(f"Erro ao montar o digest: {exc}", status_code=500)


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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("contabil falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro na consulta contábil.",
            "detalhe": str(exc)})


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
            "erro": "erro_ajuste", "mensagem": "Não foi possível salvar o ajuste.",
            "detalhe": str(exc)})
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


@app.get("/api/tv/estradas")
def tv_estradas() -> JSONResponse:
    """Config do overlay de trânsito (TomTom). A chave fica no .env."""
    import os
    chave = os.environ.get("TOMTOM_API_KEY", "").strip()
    return JSONResponse({"configurado": bool(chave), "key": chave})


@app.get("/api/copiloto/status")
def copiloto_status() -> JSONResponse:
    st = copiloto.ollama_status()
    if st["ok"]:
        return JSONResponse({"configurado": True, "local": True,
                             "modelo": f"{st['modelo']} (local)"})
    modelo = None
    try:
        lista = copiloto.modelos_free()
        modelo = lista[0] if lista else None
    except Exception as exc:  # noqa: BLE001
        log.warning("catalogo openrouter indisponivel: %s", exc)
    return JSONResponse({"configurado": bool(copiloto.api_key()), "local": False,
                         "modelo": modelo, "chave": copiloto.status_chave()})


@app.post("/api/copiloto/chat-stream")
def copiloto_chat_stream(payload: dict) -> StreamingResponse:
    import json as _json
    mensagens = payload.get("mensagens")
    if not isinstance(mensagens, list) or not mensagens or len(mensagens) > 24:
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
    if not isinstance(mensagens, list) or not mensagens or len(mensagens) > 24:
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido",
            "mensagem": "Envie 'mensagens' como lista de {role, content} (máx. 24)."})
    try:
        r = copiloto.chat(mensagens)
    except Exception as exc:  # noqa: BLE001
        log.warning("copiloto falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_copiloto", "mensagem": "Erro inesperado no copiloto.",
            "detalhe": str(exc)})
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
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("programacao falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a programação.",
            "detalhe": str(exc)})


@app.get("/api/operacao/seguranca")
def seguranca() -> JSONResponse:
    try:
        return JSONResponse(queries.get_seguranca())
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("seguranca falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao montar a torre de segurança.",
            "detalhe": str(exc)})


@app.get("/api/frota/multas")
def multas(
    dt_de: str | None = None,
    dt_ate: str | None = None,
    placa: str | None = None,
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
        return JSONResponse(queries.get_multas(dt_de, dt_ate, placa=placa))
    except psycopg.OperationalError as exc:
        return JSONResponse(status_code=503, content={
            "erro": "banco_inacessivel",
            "mensagem": "Sem conexão com o banco. O túnel SSH está aberto?",
            "detalhe": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.warning("multas falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta", "mensagem": "Erro ao consultar as multas.",
            "detalhe": str(exc)})


def _bad_date(value: str | None) -> bool:
    if value is None:
        return False
    try:
        date.fromisoformat(value)
        return False
    except ValueError:
        return True


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
            "detalhe": str(exc),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("overview falhou: %s", exc)
        return JSONResponse(status_code=500, content={
            "erro": "erro_consulta",
            "mensagem": "Erro ao executar a consulta no banco.",
            "detalhe": str(exc),
        })
