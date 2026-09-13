# -*- coding: utf-8 -*-
"""As rotas do WMS — `/api/wms/*`, as cinco telas do grupo WMS.

Molde `api/equipamentos/rotas.py`: GET é `def`, POST é `async def` com o
trabalho em `sem_travar()` (senão uma consulta ao ERP trava o servidor
INTEIRO), recusa é 409 com a mensagem inteira, e 5xx só para falha nossa —
o Cloudflare troca o corpo dos 5xx pela página dele.

O RBAC é por PREFIXO em `auth.ROTA_TELAS`, e a divisão dos prefixos é o
desenho de acesso: quem confere recebimento não mexe em cadastro, e o saldo
(`/api/wms/estoque/saldo`) é lido por três telas enquanto movimentar
(`/api/wms/estoque`) é só da tela de estoque. NÃO é `/api/gestao`: aquele
prefixo é admin, e quem opera armazém não é administrador.
"""
from __future__ import annotations

import json
import logging
from functools import partial

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import cadastro, erp, estoque, expedicao, inventario, painel, recebimento
from .comum import ler
from ..validacao import DadoInvalido

log = logging.getLogger("cortex.wms")
router = APIRouter(prefix="/api/wms")
HTTP_RECUSA = 409


def _quem(req: Request) -> str:
    s = getattr(req.state, "sessao", None) or {}
    return s.get("email") or s.get("nome") or ""


def _recusa(exc: DadoInvalido) -> JSONResponse:
    erro = "erp_indisponivel" if isinstance(exc, erp.ErpIndisponivel) else "recusa"
    return JSONResponse(status_code=HTTP_RECUSA, content={"erro": erro, "mensagem": str(exc)})


def _falha(nome: str, exc: Exception) -> JSONResponse:
    from .. import pglocal
    log.warning("wms.%s falhou: %s", nome, type(exc).__name__)
    if pglocal.sem_tabela(exc):
        msg = "As tabelas do WMS não existem neste banco — rode scripts/migrar_schema.py (migration 0090)."
    else:
        msg = "Não foi possível completar a operação do WMS."
    return JSONResponse(status_code=500, content={"erro": "erro_wms", "mensagem": msg})


def _ler(nome: str, fn, *a, **k) -> JSONResponse:
    try:
        return JSONResponse(fn(*a, **k))
    except DadoInvalido as exc:
        return _recusa(exc)
    except Exception as exc:  # noqa: BLE001
        return _falha(nome, exc)


async def _corpo(req: Request) -> dict:
    try:
        d = json.loads(await req.body() or b"{}")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


async def _escrever(nome: str, fn, *a, **k) -> JSONResponse:
    from api.main import sem_travar
    try:
        return JSONResponse(await sem_travar(partial(fn, *a, **k)))
    except DadoInvalido as exc:
        return _recusa(exc)
    except Exception as exc:  # noqa: BLE001
        return _falha(nome, exc)


# ═══════════════════════════════════════════════════ catálogo e produtos
@router.get("/catalogo")
def catalogo() -> JSONResponse:
    return _ler("catalogo", cadastro.catalogo)


@router.get("/produtos")
def produtos(depositante: str | None = None, busca: str | None = None,
             armazem: int | None = None, ativos: int = 1, limite: int = 500) -> JSONResponse:
    return _ler("produtos", cadastro.listar_produtos, depositante=depositante, busca=busca,
                armazem_id=armazem, so_ativos=bool(ativos), limite=limite)


# ═══════════════════════════════════════════════════ painel
@router.get("/painel")
def painel_(armazem: int) -> JSONResponse:
    return _ler("painel", painel.panorama, armazem)


# ═══════════════════════════════════════════════════ Avacorp (só leitura)
def _nf_com_situacao(chave: str) -> dict:
    from .comum import chave_nf
    ch = chave_nf(chave, obrigatoria=True)
    nf = erp.buscar_nf(ch)
    if nf is None:
        raise DadoInvalido("Esta chave não está em nenhuma coleta do Avacorp — a Sulista não "
                           "coletou esta nota. Siga com o recebimento manual.")
    ja = ler("""SELECT id, status FROM wms_recebimento
                 WHERE nf_chave = %s AND status <> 'cancelado' LIMIT 1""", (ch,))
    nf["ja_recebida"] = ja[0] if ja else None
    return nf


@router.get("/erp/nf/{chave}")
async def erp_nf(chave: str) -> JSONResponse:
    return await _escrever("erp.nf", _nf_com_situacao, chave)


@router.get("/erp/cadastro")
async def erp_cadastro(q: str = "") -> JSONResponse:
    return await _escrever("erp.cadastro", lambda: {"resultados": erp.buscar_cadastro(q)})


# ═══════════════════════════════════════════════════ cadastros
@router.get("/cadastro/armazens")
def armazens() -> JSONResponse:
    return _ler("armazens", lambda: {"armazens": cadastro.listar_armazens()})


@router.post("/cadastro/armazens")
async def armazem_criar(req: Request) -> JSONResponse:
    return await _escrever("armazem.criar", cadastro.criar_armazem, await _corpo(req), _quem(req))


@router.post("/cadastro/armazens/{armazem_id}")
async def armazem_editar(armazem_id: int, req: Request) -> JSONResponse:
    return await _escrever("armazem.editar", cadastro.editar_armazem, armazem_id,
                           await _corpo(req), _quem(req))


@router.get("/cadastro/enderecos")
def enderecos(armazem: int, tipo: str | None = None, situacao: str | None = None,
              busca: str | None = None, limite: int = 1500) -> JSONResponse:
    return _ler("enderecos", cadastro.listar_enderecos, armazem, tipo=tipo,
                situacao=situacao, busca=busca, limite=limite)


@router.post("/cadastro/enderecos")
async def endereco_criar(req: Request) -> JSONResponse:
    d = await _corpo(req)
    try:
        arm = int(d.get("armazem_id") or 0)
    except (TypeError, ValueError):
        arm = 0
    return await _escrever("endereco.criar", cadastro.criar_endereco, arm, d, _quem(req))


@router.post("/cadastro/enderecos/gerar")
async def enderecos_gerar(req: Request) -> JSONResponse:
    d = await _corpo(req)
    try:
        arm = int(d.get("armazem_id") or 0)
    except (TypeError, ValueError):
        arm = 0
    return await _escrever("enderecos.gerar", cadastro.gerar_enderecos, arm, d, _quem(req))


@router.post("/cadastro/enderecos/{endereco_id}")
async def endereco_editar(endereco_id: int, req: Request) -> JSONResponse:
    return await _escrever("endereco.editar", cadastro.editar_endereco, endereco_id,
                           await _corpo(req), _quem(req))


@router.get("/cadastro/depositantes")
def depositantes() -> JSONResponse:
    return _ler("depositantes", lambda: {"depositantes": cadastro.listar_depositantes()})


@router.post("/cadastro/depositantes")
async def depositante_criar(req: Request) -> JSONResponse:
    d = await _corpo(req)
    origem = "erp" if d.get("origem") == "erp" else "manual"
    return await _escrever("depositante.criar", cadastro.criar_depositante, d, _quem(req),
                           origem=origem)


@router.post("/cadastro/depositantes/{cnpj}")
async def depositante_editar(cnpj: str, req: Request) -> JSONResponse:
    return await _escrever("depositante.editar", cadastro.editar_depositante, cnpj,
                           await _corpo(req), _quem(req))


@router.get("/cadastro/produtos")
def produtos_cadastro(depositante: str | None = None, busca: str | None = None,
                      limite: int = 500) -> JSONResponse:
    return _ler("produtos.cadastro", cadastro.listar_produtos, depositante=depositante,
                busca=busca, limite=limite)


@router.post("/cadastro/produtos")
async def produto_criar(req: Request) -> JSONResponse:
    return await _escrever("produto.criar", cadastro.criar_produto, await _corpo(req), _quem(req))


@router.post("/cadastro/produtos/{produto_id}")
async def produto_editar(produto_id: int, req: Request) -> JSONResponse:
    return await _escrever("produto.editar", cadastro.editar_produto, produto_id,
                           await _corpo(req), _quem(req))


# ═══════════════════════════════════════════════════ recebimento
@router.get("/recebimento")
def recebimentos(armazem: int, status: str | None = None, dias: int = 30) -> JSONResponse:
    return _ler("recebimento.listar", recebimento.listar, armazem, status=status, dias=dias)


@router.get("/recebimento/doca")
def recebimento_doca(armazem: int) -> JSONResponse:
    return _ler("recebimento.doca", estoque.doca, armazem)


@router.get("/recebimento/{recebimento_id}")
def recebimento_detalhe(recebimento_id: int) -> JSONResponse:
    return _ler("recebimento.detalhe", recebimento.detalhe, recebimento_id)


def _abrir_recebimento(d: dict, usuario: str) -> dict:
    """Com chave e sem `manual`, a nota vem do Avacorp; o resto, à mão. A
    consulta ao ERP roda aqui dentro — já fora do laço de eventos."""
    if not d.get("manual") and d.get("nf_chave"):
        from .comum import chave_nf
        nf = erp.buscar_nf(chave_nf(d["nf_chave"], obrigatoria=True))
        if nf is None:
            raise DadoInvalido("Esta chave não está em nenhuma coleta do Avacorp — use o "
                               "recebimento manual.")
        return recebimento.abrir(d, usuario, nf_erp=nf)
    return recebimento.abrir(d, usuario)


@router.post("/recebimento")
async def recebimento_abrir(req: Request) -> JSONResponse:
    return await _escrever("recebimento.abrir", _abrir_recebimento, await _corpo(req), _quem(req))


@router.post("/recebimento/armazenar")
async def recebimento_armazenar(req: Request) -> JSONResponse:
    d = await _corpo(req)
    return await _escrever("recebimento.armazenar", estoque.transferir, d, _quem(req))


@router.post("/recebimento/{recebimento_id}/conferir")
async def recebimento_conferir(recebimento_id: int, req: Request) -> JSONResponse:
    d = await _corpo(req)
    return await _escrever("recebimento.conferir", recebimento.conferir, recebimento_id,
                           d.get("itens"), _quem(req))


@router.post("/recebimento/{recebimento_id}/fechar")
async def recebimento_fechar(recebimento_id: int, req: Request) -> JSONResponse:
    return await _escrever("recebimento.fechar", recebimento.fechar, recebimento_id, _quem(req))


@router.post("/recebimento/{recebimento_id}/cancelar")
async def recebimento_cancelar(recebimento_id: int, req: Request) -> JSONResponse:
    d = await _corpo(req)
    return await _escrever("recebimento.cancelar", recebimento.cancelar, recebimento_id,
                           d.get("motivo"), _quem(req))


# ═══════════════════════════════════════════════════ estoque
@router.get("/estoque/saldo")
def saldo(armazem: int, depositante: str | None = None, tipo: str | None = None,
          endereco: int | None = None, produto: int | None = None, busca: str | None = None,
          limite: int = 800) -> JSONResponse:
    return _ler("saldo", estoque.saldo, armazem, depositante=depositante, tipo=tipo,
                endereco_id=endereco, produto_id=produto, busca=busca, limite=limite)


@router.get("/estoque/kardex")
def kardex(armazem: int, produto: int | None = None, endereco: int | None = None,
           doc: str | None = None, busca: str | None = None, dias: int = 30,
           limite: int = 400) -> JSONResponse:
    return _ler("kardex", estoque.kardex, armazem, produto_id=produto, endereco_id=endereco,
                doc_tipo=doc, busca=busca, dias=dias, limite=limite)


@router.get("/estoque/bloqueios")
def bloqueios(armazem: int) -> JSONResponse:
    return _ler("bloqueios", cadastro.listar_enderecos, armazem, situacao="bloqueado")


@router.post("/estoque/transferir")
async def transferir(req: Request) -> JSONResponse:
    return await _escrever("transferir", estoque.transferir, await _corpo(req), _quem(req))


@router.post("/estoque/ajustar")
async def ajustar(req: Request) -> JSONResponse:
    return await _escrever("ajustar", estoque.ajustar, await _corpo(req), _quem(req))


@router.post("/estoque/enderecos/{endereco_id}/bloquear")
async def bloquear(endereco_id: int, req: Request) -> JSONResponse:
    d = await _corpo(req)
    return await _escrever("bloquear", estoque.bloquear, endereco_id, d.get("motivo"), _quem(req))


@router.post("/estoque/enderecos/{endereco_id}/desbloquear")
async def desbloquear(endereco_id: int, req: Request) -> JSONResponse:
    return await _escrever("desbloquear", estoque.desbloquear, endereco_id, _quem(req))


@router.get("/estoque/inventarios")
def inventarios(armazem: int) -> JSONResponse:
    return _ler("inventarios", inventario.listar, armazem)


@router.get("/estoque/inventarios/{inventario_id}")
def inventario_detalhe(inventario_id: int) -> JSONResponse:
    return _ler("inventario.detalhe", inventario.detalhe, inventario_id)


@router.post("/estoque/inventarios")
async def inventario_abrir(req: Request) -> JSONResponse:
    return await _escrever("inventario.abrir", inventario.abrir, await _corpo(req), _quem(req))


@router.post("/estoque/inventarios/{inventario_id}/contar")
async def inventario_contar(inventario_id: int, req: Request) -> JSONResponse:
    d = await _corpo(req)
    try:
        end = int(d.get("endereco_id") or 0)
    except (TypeError, ValueError):
        end = 0
    return await _escrever("inventario.contar", inventario.contar, inventario_id, end,
                           d.get("itens"), _quem(req))


@router.post("/estoque/inventarios/{inventario_id}/fechar")
async def inventario_fechar(inventario_id: int, req: Request) -> JSONResponse:
    return await _escrever("inventario.fechar", inventario.fechar, inventario_id, _quem(req))


@router.post("/estoque/inventarios/{inventario_id}/cancelar")
async def inventario_cancelar(inventario_id: int, req: Request) -> JSONResponse:
    return await _escrever("inventario.cancelar", inventario.cancelar, inventario_id, _quem(req))


# ═══════════════════════════════════════════════════ expedição
@router.get("/expedicao/pedidos")
def pedidos(armazem: int, dias: int = 30) -> JSONResponse:
    return _ler("pedidos", expedicao.listar, armazem, dias=dias)


@router.get("/expedicao/pedidos/{pedido_id}")
def pedido_detalhe(pedido_id: int) -> JSONResponse:
    return _ler("pedido.detalhe", expedicao.detalhe, pedido_id)


@router.get("/expedicao/tarefas")
def tarefas(armazem: int) -> JSONResponse:
    return _ler("tarefas", expedicao.tarefas_pendentes, armazem)


def _proposta(chave: str, depositante: str | None) -> dict:
    from .comum import chave_nf
    nf = erp.buscar_nf(chave_nf(chave, obrigatoria=True))
    if nf is None:
        raise DadoInvalido("Esta chave não está em nenhuma coleta do Avacorp.")
    return expedicao.proposta_de_nf(nf, depositante)


@router.get("/expedicao/nf/{chave}")
async def pedido_de_nf(chave: str, depositante: str | None = None) -> JSONResponse:
    return await _escrever("pedido.nf", _proposta, chave, depositante)


@router.post("/expedicao/pedidos")
async def pedido_criar(req: Request) -> JSONResponse:
    return await _escrever("pedido.criar", expedicao.criar, await _corpo(req), _quem(req))


@router.post("/expedicao/pedidos/{pedido_id}/liberar")
async def pedido_liberar(pedido_id: int, req: Request) -> JSONResponse:
    return await _escrever("pedido.liberar", expedicao.liberar, pedido_id, _quem(req))


@router.post("/expedicao/pedidos/{pedido_id}/expedir")
async def pedido_expedir(pedido_id: int, req: Request) -> JSONResponse:
    return await _escrever("pedido.expedir", expedicao.expedir, pedido_id, await _corpo(req),
                           _quem(req))


@router.post("/expedicao/pedidos/{pedido_id}/cancelar")
async def pedido_cancelar(pedido_id: int, req: Request) -> JSONResponse:
    d = await _corpo(req)
    return await _escrever("pedido.cancelar", expedicao.cancelar, pedido_id, d.get("motivo"),
                           _quem(req))


@router.post("/expedicao/tarefas/{tarefa_id}/confirmar")
async def tarefa_confirmar(tarefa_id: int, req: Request) -> JSONResponse:
    d = await _corpo(req)
    return await _escrever("tarefa.confirmar", expedicao.confirmar_tarefa, tarefa_id,
                           d.get("qtd"), _quem(req))
