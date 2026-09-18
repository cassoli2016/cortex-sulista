# -*- coding: utf-8 -*-
"""As rotas do programa de desempenho — aba Campanha da tela `prem`.

Mesmo arranjo das rotas do GMA: dentro da tela da premiação (quem conduz a
campanha é a gestão da frota) e NÃO sob `/api/gestao`, que é checado como ADMIN
antes do mapeamento de telas — lá a aba nasceria inútil para o público dela.

A ATA DO SORTEIO É A RESPOSTA DA ROTA, e ela é gravada antes de responder: o
sorteio é o único ponto aqui em que um clique decide quem leva um prêmio, e
"não sei se salvou" seria a pior resposta possível.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import armazenamento as arm, servico

log = logging.getLogger("cortex.campanha.rotas")
router = APIRouter(prefix="/api/campanha")
HTTP_RECUSA = 409


def _autor(req: Request) -> str:
    s = getattr(req.state, "sessao", None) or {}
    return s.get("usuario") or s.get("email") or ""


def _erro(nome: str, exc: Exception, msg: str) -> JSONResponse:
    log.warning("%s falhou: %s", nome, type(exc).__name__)
    return JSONResponse(status_code=500,
                        content={"erro": "erro_consulta", "mensagem": msg})


def _recusa(mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=HTTP_RECUSA,
                        content={"erro": "recusa", "mensagem": mensagem})


async def _corpo(req: Request) -> dict:
    try:
        return json.loads(await req.body() or b"{}") or {}
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}


def _auditar(req: Request, acao: str, alvo: str = "", detalhe: str = "") -> None:
    try:
        from api import auth
        auth.audit(_autor(req) or "?", acao, alvo=alvo, detalhe=detalhe)
    except Exception as exc:  # noqa: BLE001
        log.warning("campanha: auditoria falhou (%s)", type(exc).__name__)


@router.get("")
def listar() -> JSONResponse:
    """As campanhas e a vigente — é ela que a aba abre."""
    try:
        return JSONResponse({"campanhas": arm.listar(),
                             "vigente": arm.vigente(),
                             "padrao": arm.PADRAO})
    except Exception as exc:  # noqa: BLE001
        return _erro("campanha.listar", exc,
                     "Não foi possível ler as campanhas.")


@router.get("/{campanha_id}/ciclo")
def ciclo(campanha_id: int, ciclo: str | None = None) -> JSONResponse:
    """Os dois rankings do ciclo, com elegibilidade e motivo por linha."""
    try:
        d = servico.montar(int(campanha_id), ciclo)
        d["sorteios"] = arm.sorteios(int(campanha_id))
        d["foto"] = bool(arm.ler_foto(int(campanha_id), d["ciclo"]))
        return JSONResponse(d)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("campanha.ciclo", exc,
                     "Não foi possível montar o ciclo da campanha.")


@router.post("")
async def criar(req: Request) -> JSONResponse:
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "campanha_criar", alvo=str(c.get("nome") or ""),
                 detalhe=f"{c.get('de_ciclo')}..{c.get('ate_ciclo')}")
        return JSONResponse(await sem_travar(arm.criar, c, autor))
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("campanha.criar", exc, "Não foi possível criar a campanha.")


@router.post("/{campanha_id}/fotografar")
async def fotografar(campanha_id: int, req: Request) -> JSONResponse:
    """Congela a categoria do ciclo — é o que o regulamento manda divulgar."""
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "campanha_fotografar", alvo=str(c.get("ciclo") or ""))
        return JSONResponse(await sem_travar(
            servico.fotografar, int(campanha_id), str(c.get("ciclo") or ""),
            autor))
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("campanha.fotografar", exc,
                     "Não foi possível fechar o ciclo da campanha.")


@router.post("/{campanha_id}/sortear")
async def sortear(campanha_id: int, req: Request) -> JSONResponse:
    """O sorteio. A trilha entra ANTES, e a resposta é a ata."""
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    grupo = str(c.get("grupo") or "")
    try:
        _auditar(req, "campanha_sortear", alvo=f"{campanha_id}/{grupo}",
                 detalhe=str(c.get("ata") or ""))
        return JSONResponse(await sem_travar(
            servico.sortear, int(campanha_id), grupo, autor,
            semente=str(c.get("semente") or ""),
            excluidos=c.get("excluidos") or {}, ata=str(c.get("ata") or "")))
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("campanha.sortear", exc,
                     "Não foi possível realizar o sorteio.")
