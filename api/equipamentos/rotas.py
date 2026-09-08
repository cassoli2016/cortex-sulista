# -*- coding: utf-8 -*-
"""As rotas do cadastro de equipamentos — tela `eqp`, grupo TMS.

Molde `api/suporte/rotas.py`: GET é `def`, POST é `async def` com o trabalho em
`sem_travar()`, recusa é 4xx (5xx só para falha nossa, porque o Cloudflare
troca o corpo dos 5xx pela página dele e a mensagem nunca chega).

O PREFIXO NÃO É `/api/gestao`, E ISSO É DELIBERADO
==================================================
Aquele prefixo é checado como ADMIN no middleware ANTES do mapeamento de
telas. Quem cadastra equipamento não é administrador — é quem toca a frota.
Sob `/api/gestao` a tela nasceria inútil para o público dela, que foi a lição
do Ritual Semanal.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import armazenamento as arm
from . import coleta, leitura
from .campos import POR_NOME

log = logging.getLogger("cortex.equipamentos")
router = APIRouter(prefix="/api/equipamentos")
HTTP_RECUSA = 409


def _sessao(req: Request) -> dict:
    return getattr(req.state, "sessao", None) or {}


def _erro(nome: str, exc: Exception, msg: str) -> JSONResponse:
    log.warning("%s falhou: %s", nome, type(exc).__name__)
    return JSONResponse(status_code=500,
                        content={"erro": "erro_consulta", "mensagem": msg})


def _recusa(mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=HTTP_RECUSA,
                        content={"erro": "recusa", "mensagem": mensagem})


# ────────────────────────────────────────────────────────────────── leitura

@router.get("")
def listar(vinculo: str | None = None, categoria: str | None = None,
           busca: str | None = None, limite: int = 500) -> JSONResponse:
    try:
        # Teto do teto: `limite` vem do navegador, e um `limite=999999`
        # carregaria a tabela inteira numa resposta. Parâmetro que entra em
        # consulta é validado, sempre.
        limite = max(1, min(int(limite or 500), 2000))
        return JSONResponse(leitura.listar(vinculo=vinculo,
                                           categoria=categoria,
                                           busca=busca, limite=limite))
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.listar", exc,
                     "Não foi possível ler o cadastro de equipamentos.")


@router.get("/panorama")
def panorama() -> JSONResponse:
    try:
        return JSONResponse(leitura.panorama())
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.panorama", exc,
                     "Não foi possível montar o panorama do cadastro.")


@router.get("/catalogo")
def catalogo() -> JSONResponse:
    try:
        return JSONResponse(leitura.catalogo())
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.catalogo", exc,
                     "Não foi possível ler o catálogo de campos.")


@router.get("/divergencias")
def divergencias(limite: int = 200) -> JSONResponse:
    try:
        limite = max(1, min(int(limite or 200), 1000))
        return JSONResponse(leitura.divergencias_gerais(limite))
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.divergencias", exc,
                     "Não foi possível comparar as fontes.")


@router.get("/{placa}")
def detalhe(placa: str) -> JSONResponse:
    try:
        d = leitura.detalhe(placa)
        if d is None:
            return JSONResponse(status_code=404,
                                content={"erro": "nao_encontrado",
                                         "mensagem": "Equipamento não está "
                                                     "no cadastro."})
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.detalhe", exc,
                     "Não foi possível abrir o equipamento.")


# ────────────────────────────────────────────────────────────────── escrita

@router.post("/sincronizar")
async def sincronizar(req: Request) -> JSONResponse:
    """Puxa a frota do ERP e o que a Smartec ja coletou.

    Todo I/O bloqueante em rota `async def` passa por `sem_travar()` — senão
    trava o servidor INTEIRO pelo tempo da leitura de 1.446 veículos no AVA.
    O `TestClient` não pega isso; só uvicorn de verdade pega.
    """
    from api.main import sem_travar
    sess = _sessao(req)
    try:
        r = await sem_travar(coleta.sincronizar)
        arm.auditar(sess.get("usuario"), "eqp_sincronizar_erp",
                    detalhe=json.dumps(r, ensure_ascii=False))
        return JSONResponse(r)
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.sincronizar", exc,
                     "Não foi possível sincronizar com o ERP.")


@router.post("/smartec")
async def sincronizar_smartec(req: Request) -> JSONResponse:
    """Traz o que a Smartec ja coletou para o cadastro.

    Nao fala com o fornecedor: le as tabelas `smt_*` que a coleta da Smartec
    enche todo dia. Quem consulta a Smartec de verdade e
    `api/smartec/coleta.py` -- e e la que mora o custo.
    """
    from api.main import sem_travar
    sess = _sessao(req)
    try:
        r = await sem_travar(coleta.sincronizar_smartec)
        arm.auditar(sess.get("usuario"), "eqp_sincronizar_smartec",
                    detalhe=json.dumps(r, ensure_ascii=False))
        return JSONResponse(r)
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.smartec", exc,
                     "Nao foi possivel trazer os dados da Smartec.")


@router.post("/{placa}/campo")
async def editar(placa: str, req: Request) -> JSONResponse:
    """Corrige um campo à mão. Vence toda fonte automática.

    É o que faz o cadastro ser DO CÓRTEX e não um espelho do ERP.
    """
    from api.main import sem_travar
    sess = _sessao(req)
    autor = sess.get("usuario") or ""
    if not autor:
        return _recusa("Sessão sem usuário.")
    try:
        corpo = json.loads(await req.body() or b"{}")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        corpo = {}
    campo = (corpo.get("campo") or "").strip()
    if campo not in POR_NOME:
        return _recusa("Campo desconhecido: " + (campo or "(vazio)"))

    # CHAVE AUSENTE = não mexe; CHAVE VAZIA = limpa. Aqui "limpar" significa
    # DESFAZER a correção — o campo volta a seguir as fontes automáticas.
    # Gravar string vazia prenderia o campo à mão para sempre, e a próxima
    # coleta boa não o alcançaria mais.
    from . import consolidacao
    placa = (placa or "").strip().upper()
    valor = corpo.get("valor")
    motivo = (corpo.get("motivo") or "").strip() or None
    try:
        if valor is None or str(valor).strip() == "":
            await sem_travar(arm.apagar_edicao, placa, campo)
            acao = "removida"
        else:
            await sem_travar(arm.gravar_edicao, placa, campo,
                             str(valor).strip(), autor, motivo)
            acao = "gravada"
        await sem_travar(consolidacao.reconstruir, [placa])
        arm.auditar(autor, "eqp_editar_campo", alvo=placa,
                    detalhe=f"{campo} {acao}")
        return JSONResponse({"ok": True, "acao": acao,
                             "equipamento": leitura.detalhe(placa)})
    except Exception as exc:  # noqa: BLE001
        return _erro("equipamentos.editar", exc,
                     "Não foi possível gravar a correção.")
