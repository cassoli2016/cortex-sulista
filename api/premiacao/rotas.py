# -*- coding: utf-8 -*-
"""As rotas da Gestão de Motoristas (GMA) — tela `prem`, grupo Telemetria.

A TELA HERDA O ID `prem`, e isso é RBAC: id novo faria a premiação sumir do
menu de quem já tem acesso hoje. A régua nova substitui a antiga no mesmo
lugar, e é por isso que estas rotas convivem com as de `/api/premiacao/config`
e `/api/frota/premiacao` (a régua que ainda paga) sob a mesma tela.

O PREFIXO NÃO É `/api/gestao`: aquele é checado como ADMIN no middleware antes
do mapeamento de telas, e quem mexe na premiação é a gestão da FROTA. A lição
do Ritual Semanal — a tela nasceria inútil para o público dela.

O DINHEIRO SAI POR UMA ABA BLOQUEÁVEL. As rotas de pagamento, valores, ajuste
e fechamento são exclusivas da aba Premiação (`acessos.ABAS["prem.premiacao"]`),
para que se possa dar a tela a quem acompanha conduta sem dar a folha junto.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import (ciclo as ciclo_mod, fechamento, identidade, parametros, premio,
               ranking)

log = logging.getLogger("cortex.premiacao.rotas")
router = APIRouter(prefix="/api/premiacao/gma")
HTTP_RECUSA = 409


def _sessao(req: Request) -> dict:
    return getattr(req.state, "sessao", None) or {}


def _autor(req: Request) -> str:
    s = _sessao(req)
    return s.get("usuario") or s.get("email") or ""


def _erro(nome: str, exc: Exception, msg: str) -> JSONResponse:
    log.warning("%s falhou: %s", nome, type(exc).__name__)
    return JSONResponse(status_code=500,
                        content={"erro": "erro_consulta", "mensagem": msg})


def _recusa(mensagem: str) -> JSONResponse:
    """Recusa legível é 4xx. 5xx o Cloudflare troca pela página dele e a
    mensagem nunca chega a quem precisa dela."""
    return JSONResponse(status_code=HTTP_RECUSA,
                        content={"erro": "recusa", "mensagem": mensagem})


async def _corpo(req: Request) -> dict:
    try:
        return json.loads(await req.body() or b"{}") or {}
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}


def _auditar(req: Request, acao: str, alvo: str = "", detalhe: str = "") -> None:
    """Trilha ANTES de a ação valer — e nunca derruba a ação se falhar."""
    try:
        from api import auth
        auth.audit(_autor(req) or "?", acao, alvo=alvo, detalhe=detalhe)
    except Exception as exc:  # noqa: BLE001
        log.warning("premiacao: auditoria falhou (%s)", type(exc).__name__)


# ────────────────────────────────────────────────────────────────── leitura

@router.get("/ciclo")
def ciclo(ciclo: str | None = None) -> JSONResponse:
    """O ciclo montado: uma linha por motorista, com as quatro fontes."""
    try:
        return JSONResponse(ranking.montar(ciclo))
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.ciclo", exc, "Não foi possível montar o ciclo.")


@router.get("/pagamento")
def pagamento(ciclo: str | None = None) -> JSONResponse:
    """O que se paga — a FOTO se o ciclo está fechado, o cálculo se não."""
    try:
        return JSONResponse(fechamento.pagamento(ciclo))
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.pagamento", exc,
                     "Não foi possível montar o pagamento do ciclo.")


@router.get("/catalogo")
def catalogo(ciclo: str | None = None) -> JSONResponse:
    """O que a tela precisa para desenhar as réguas e os formulários."""
    alvo = ciclo or ciclo_mod.atual()
    try:
        d = parametros.catalogo_publico()
        d["ciclo"] = alvo
        d["rotulo"] = ciclo_mod.rotulo(alvo)
        d["ciclos"] = list(reversed(ciclo_mod.janela(alvo, 13)))
        d["parametros_do_ciclo"] = {g: parametros.ler(alvo, g)
                                    for g in parametros.GRUPOS}
        d["depara"] = parametros.depara()
        d["cadastro"] = identidade.estado()
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.catalogo", exc,
                     "Não foi possível ler o catálogo da premiação.")


@router.get("/valores")
def valores(ciclo: str | None = None) -> JSONResponse:
    """A tabela de valores vigente no ciclo (aba Premiação)."""
    alvo = ciclo or ciclo_mod.atual()
    try:
        return JSONResponse(premio.tabela(alvo))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.valores", exc,
                     "Não foi possível ler a tabela de valores.")


@router.get("/motoristas")
def motoristas() -> JSONResponse:
    """O cadastro da premiação, SEM CPF: a tela fala por código do cadastro.

    `identidade.listar` guarda o CPF porque é a chave com que o módulo cruza as
    quatro fontes — a ROTA é o limite em que ele para. Quem decide tipo e
    filial não precisa do CPF para isso.
    """
    try:
        linhas = [{k: v for k, v in m.items() if k != "cpf"}
                  for m in identidade.listar(ativos=False)]
        return JSONResponse({"estado": identidade.estado(), "linhas": linhas})
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.motoristas", exc,
                     "Não foi possível ler o cadastro de motoristas.")


# ────────────────────────────────────────────────────────────────── escrita

@router.post("/parametros")
async def salvar_parametros(req: Request) -> JSONResponse:
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "gma_parametros", alvo=f"{c.get('ciclo')}/{c.get('grupo')}",
                 detalhe=json.dumps(c.get("valores") or {}, ensure_ascii=False))
        r = await sem_travar(parametros.salvar, str(c.get("ciclo") or ""),
                             str(c.get("grupo") or ""), c.get("valores") or {},
                             autor, str(c.get("nota") or ""))
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.salvar_parametros", exc,
                     "Não foi possível salvar os parâmetros.")


@router.post("/valores")
async def salvar_valores(req: Request) -> JSONResponse:
    """A tabela de valores base. O corpo leva REAIS — e por isso a auditoria
    guarda só o que mudou e quem mudou, nunca o valor."""
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        filiais = c.get("filiais") or {}
        _auditar(req, "gma_valores", alvo=f"{c.get('ciclo')}/{c.get('grupo')}",
                 detalhe=f"{len(filiais)} filiais")
        r = await sem_travar(premio.salvar_tabela, str(c.get("ciclo") or ""),
                             str(c.get("grupo") or ""), filiais, autor,
                             str(c.get("nota") or ""))
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.salvar_valores", exc,
                     "Não foi possível salvar a tabela de valores.")


@router.post("/escada")
async def salvar_escada(req: Request) -> JSONResponse:
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        degraus = c.get("degraus") or []
        _auditar(req, "gma_escada", alvo=f"{c.get('ciclo')}/{c.get('grupo')}",
                 detalhe=f"{len(degraus)} degraus")
        r = await sem_travar(premio.salvar_escada, str(c.get("ciclo") or ""),
                             str(c.get("grupo") or ""), degraus, autor,
                             str(c.get("nota") or ""))
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.salvar_escada", exc,
                     "Não foi possível salvar a escada de tempo de casa.")


@router.post("/ajuste")
async def ajuste(req: Request) -> JSONResponse:
    """Decide à mão o valor base de uma pessoa no ciclo — ou desfaz a decisão.

    `valor` ausente ou nulo LIMPA o ajuste (o motorista volta à tabela). É a
    convenção da casa para edição parcial, e aqui ela é o botão "Restaurar".
    """
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    alvo = str(c.get("motorista") or "").strip()
    ciclo_alvo = str(c.get("ciclo") or "")
    if not alvo:
        return _recusa("Informe o motorista.")
    try:
        cpf = identidade.cpf_do_cadastro(alvo)
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.ajuste", exc, "Não foi possível ler o cadastro.")
    if not cpf:
        return _recusa("Motorista fora do cadastro da premiação.")
    try:
        if c.get("valor") in (None, ""):
            _auditar(req, "gma_ajuste_limpar", alvo=f"{ciclo_alvo}/{alvo}")
            r = await sem_travar(premio.limpar_ajuste, ciclo_alvo, cpf)
        else:
            # O detalhe da trilha NÃO leva o valor: o `audit_log` é lido por
            # quem administra o sistema, não por quem pode ver a folha.
            _auditar(req, "gma_ajuste", alvo=f"{ciclo_alvo}/{alvo}",
                     detalhe=str(c.get("motivo") or ""))
            r = await sem_travar(premio.ajustar, ciclo_alvo, cpf, c.get("valor"),
                                 str(c.get("motivo") or ""), autor)
        r.pop("cpf", None)
        r["motorista"] = alvo
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.ajuste", exc, "Não foi possível salvar o ajuste.")


@router.post("/fechar")
async def fechar(req: Request) -> JSONResponse:
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "gma_fechar", alvo=str(c.get("ciclo") or ""),
                 detalhe=str(c.get("nota") or ""))
        r = await sem_travar(fechamento.fechar, str(c.get("ciclo") or ""), autor,
                             str(c.get("nota") or ""), bool(c.get("forcar")))
        return JSONResponse(r)
    except (fechamento.CicloFechado, fechamento.CicloEmCurso) as exc:
        return _recusa(str(exc))
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.fechar", exc, "Não foi possível fechar o ciclo.")


@router.post("/reabrir")
async def reabrir(req: Request) -> JSONResponse:
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "gma_reabrir", alvo=str(c.get("ciclo") or ""),
                 detalhe=str(c.get("motivo") or ""))
        r = await sem_travar(fechamento.reabrir, str(c.get("ciclo") or ""), autor,
                             str(c.get("motivo") or ""))
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.reabrir", exc,
                     "Não foi possível reabrir o ciclo.")


@router.post("/depara")
async def depara(req: Request) -> JSONResponse:
    """Decide o que um código de ocorrência do ERP significa."""
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "gma_depara", alvo=str(c.get("codigo")),
                 detalhe=str(c.get("alvo") or ""))
        r = await sem_travar(parametros.salvar_depara, c.get("codigo"),
                             str(c.get("alvo") or ""), autor)
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.depara", exc,
                     "Não foi possível salvar o de-para.")


@router.post("/motorista")
async def motorista(req: Request) -> JSONResponse:
    """Tipo e filial decididos por quem opera — viram `origem='manual'`."""
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    c = await _corpo(req)
    try:
        _auditar(req, "gma_motorista", alvo=str(c.get("motorista") or ""),
                 detalhe=f"tipo={c.get('tipo')} filial={c.get('filial')}")
        r = await sem_travar(identidade.decidir, str(c.get("motorista") or ""),
                             autor, c.get("tipo"), c.get("filial"))
        return JSONResponse(r)
    except ValueError as exc:
        return _recusa(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.motorista", exc,
                     "Não foi possível salvar o motorista.")


@router.post("/sincronizar")
async def sincronizar(req: Request) -> JSONResponse:
    """Traz o cadastro da folha do Globus. Nunca sobrescreve decisão manual."""
    from api.main import sem_travar
    autor = _autor(req)
    if not autor:
        return _recusa("Sessão sem usuário.")
    try:
        _auditar(req, "gma_sincronizar")
        r = await sem_travar(identidade.sincronizar, autor)
        return JSONResponse(r)
    except Exception as exc:  # noqa: BLE001
        return _erro("premiacao.sincronizar", exc,
                     "Não foi possível sincronizar o cadastro com a folha.")
