"""As rotas do Suporte — `/api/suporte/meus/*` (todo usuário logado, só os
próprios chamados) e `/api/suporte/atendimento/*` (tela `supfila`).

Regras da casa (molde `api/crm/rotas.py`): GET é `def`, POST é `async def`
com o trabalho em `sem_travar()`; recusa é 4xx (422 dado inválido, 409
transição inválida, 413 tamanho, 404 chamado alheio — nunca 403, que
confirmaria que existe); toda escrita entra no `audit_log` dentro do serviço.
Avisos e espelho rodam DEPOIS da resposta (BackgroundTasks), nunca levantam.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse

from .. import auth
from ..validacao import DadoInvalido
from . import avisos, chamados, comum, espelho
from .comum import TransicaoInvalida

log = logging.getLogger("cortex.suporte")
router = APIRouter(prefix="/api/suporte")
HTTP_RECUSA = 409
MAX_BYTES = comum.TOTAL_MAX_BYTES + 512 * 1024


def _sessao(req: Request) -> dict:
    return getattr(req.state, "sessao", None) or {}


def _e_suporte(sess: dict) -> bool:
    return bool(sess.get("admin") or "supfila" in (sess.get("telas") or []))


def _erro(nome: str, exc: Exception, msg: str) -> JSONResponse:
    if isinstance(exc, TransicaoInvalida):
        return JSONResponse(status_code=HTTP_RECUSA, content={"erro": "transicao_invalida", "mensagem": str(exc)})
    if isinstance(exc, DadoInvalido):
        return JSONResponse(status_code=422, content={"erro": "parametro_invalido", "mensagem": str(exc)})
    log.warning("%s falhou: %s", nome, type(exc).__name__)
    return JSONResponse(status_code=500, content={"erro": "erro_consulta", "mensagem": msg})


def _404() -> JSONResponse:
    return JSONResponse(status_code=404, content={"erro": "nao_encontrado", "mensagem": "Chamado não encontrado."})


async def _corpo(req: Request) -> dict:
    from api.main import _tamanho_excede
    if _tamanho_excede(req.headers.get("content-length"), MAX_BYTES):
        raise _Grande()
    bruto = await req.body()
    if len(bruto) > MAX_BYTES:
        raise _Grande()
    try:
        body = json.loads(bruto or b"")
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict):
        raise DadoInvalido("O corpo da requisição não é um objeto JSON.")
    return body


class _Grande(Exception):
    pass


_GRANDE = {"erro": "corpo_grande",
           "mensagem": f"O envio passa de {comum.TOTAL_MAX_BYTES // (1024 * 1024)} MB. Remova um anexo e tente de novo."}


async def _fazer(fn, *a, **k):
    from api.main import sem_travar
    return await sem_travar(fn, *a, **k)


def _depois(bg: BackgroundTasks, chamado_id: int, eventos: list[str], mensagem_id=None, texto: str = ""):
    """Avisos e espelho depois da resposta; cada um em try próprio dentro dos serviços."""
    for ev in eventos:
        bg.add_task(avisos.avisar, chamado_id, ev, mensagem_id=mensagem_id, texto=texto)
    if mensagem_id:
        bg.add_task(espelho.espelhar_mensagem, mensagem_id)
    if any(ev.startswith("status_") for ev in eventos):
        bg.add_task(espelho.espelhar_status, chamado_id)


# ====================================================================== meus
@router.get("/meus/config")
def meus_config(req: Request) -> JSONResponse:
    sess = _sessao(req)
    try:
        u = chamados.pglocal.um("SELECT email, telefone FROM usuarios WHERE id=%s", (sess.get("id"),),
                                esquema=comum._esq(None)) or {}
        cfg = comum.config()
        zap_ok, zap_motivo = avisos.Canais.whatsapp_pronto()
        ultimo = chamados.pglocal.um("SELECT avisar_email, avisar_whatsapp FROM sup_chamados WHERE usuario_id=%s "
                                     "ORDER BY id DESC LIMIT 1", (sess.get("id"),), esquema=comum._esq(None)) or {}
        return JSONResponse({
            "ativo": True,
            "tipos": [{"valor": t, "rotulo": comum.ROTULO_TIPO[t]} for t in comum.TIPOS],
            "gravidades": list(comum.GRAVIDADES),
            "canais": {
                "email": {"disponivel": bool(u.get("email")) and avisos.Canais.email_configurado(),
                          "destino": comum.mascarar_email(u.get("email")),
                          "motivo": "" if avisos.Canais.email_configurado() else "e-mail não configurado neste servidor"},
                "whatsapp": {"disponivel": bool(u.get("telefone")) and zap_ok,
                             "destino": comum.mascarar_telefone(u.get("telefone")),
                             "motivo": ("cadastre seu telefone em Minha conta" if not u.get("telefone") else zap_motivo)},
            },
            # sem chamado anterior, os dois nascem marcados (quando o canal existe); depois vale a última escolha
            "ultima_escolha": {"email": bool(ultimo.get("avisar_email", 1)), "whatsapp": bool(ultimo.get("avisar_whatsapp", 1))},
            "sla": {g: comum.sla_horas(cfg, g) for g in comum.GRAVIDADES},
            "anexos": {"max": comum.ANEXOS_MAX, "max_bytes": comum.ANEXO_MAX_BYTES, "total_bytes": comum.TOTAL_MAX_BYTES,
                       "extensoes": sorted(comum.EXTENSOES)},
            "sou_suporte": _e_suporte(sess),
        })
    except Exception as exc:  # noqa: BLE001
        return _erro("meus_config", exc, "Erro ao ler a configuração do suporte.")


@router.get("/meus")
def meus(req: Request, situacao: str = "ativos") -> JSONResponse:
    sess = _sessao(req)
    try:
        if situacao not in ("ativos", "encerrados", "todos"):
            raise DadoInvalido("situacao deve ser ativos, encerrados ou todos.")
        return JSONResponse(chamados.listar_meus(sess.get("id"), situacao))
    except Exception as exc:  # noqa: BLE001
        return _erro("meus", exc, "Erro ao listar seus chamados.")


@router.post("/meus/chamados")
async def abrir(req: Request, bg: BackgroundTasks) -> JSONResponse:
    sess = _sessao(req)
    try:
        payload = await _corpo(req)
        d = await _fazer(chamados.criar, sess, payload)
    except _Grande:
        return JSONResponse(status_code=413, content=_GRANDE)
    except Exception as exc:  # noqa: BLE001
        return _erro("abrir", exc, "Erro ao abrir o chamado.")
    bg.add_task(espelho.espelhar_abertura, d["id"])
    bg.add_task(avisos.avisar, d["id"], "aberto")
    return JSONResponse({"id": d["id"], "codigo": d["codigo"], "numero": d["codigo"],
                         "url": f"#sup?chamado={d['id']}", "status": d["status"]})


@router.get("/meus/chamados/{cid}")
def meu_chamado(req: Request, cid: int) -> JSONResponse:
    sess = _sessao(req)
    try:
        d = chamados.obter(cid, usuario_id=sess.get("id"))
        if not d:
            return _404()
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return _erro("meu_chamado", exc, "Erro ao ler o chamado.")


@router.post("/meus/chamados/{cid}/lido")
async def meu_lido(req: Request, cid: int) -> JSONResponse:
    sess = _sessao(req)
    try:
        ok = await _fazer(chamados.marcar_lido, cid, "usuario", sess.get("id"))
        return JSONResponse({"ok": True}) if ok else _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("meu_lido", exc, "Erro ao marcar como lido.")


@router.post("/meus/chamados/{cid}/mensagens")
async def minha_mensagem(req: Request, cid: int, bg: BackgroundTasks) -> JSONResponse:
    sess = _sessao(req)
    try:
        body = await _corpo(req)
        r = await _fazer(chamados.responder, cid, sess, "usuario", body.get("texto"), body.get("anexos"))
        if not r:
            return _404()
    except _Grande:
        return JSONResponse(status_code=413, content=_GRANDE)
    except Exception as exc:  # noqa: BLE001
        return _erro("minha_mensagem", exc, "Erro ao enviar a mensagem.")
    _depois(bg, cid, r["eventos"], r["mensagem_id"], str(body.get("texto") or "")[:2000])
    return JSONResponse({"ok": True, "mensagem_id": r["mensagem_id"]})


@router.post("/meus/chamados/{cid}/status")
async def meu_status(req: Request, cid: int, bg: BackgroundTasks) -> JSONResponse:
    """Quem abriu: confirmar (resolvido → fechado, com avaliação opcional),
    desistir (aberto → fechado) e reabrir (com texto)."""
    sess = _sessao(req)
    try:
        body = await _corpo(req)
        r = await _fazer(chamados.mudar_status, cid, sess, "usuario", body.get("status"),
                         texto=body.get("texto") or "", avaliacao=body.get("avaliacao"))
        if not r:
            return _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("meu_status", exc, "Erro ao mudar o chamado.")
    eventos = ["resposta_usuario"] if r["para"] == "aberto" else []
    _depois(bg, cid, eventos + [f"status_{r['para']}"] if r["para"] == "aberto" else [f"status_{r['para']}"],
            r.get("mensagem_id"), body.get("texto") or "")
    return JSONResponse({"ok": True, "status": r["para"]})


@router.post("/meus/chamados/{cid}/avaliar")
async def avaliar(req: Request, cid: int, bg: BackgroundTasks) -> JSONResponse:
    sess = _sessao(req)
    try:
        body = await _corpo(req)
        r = await _fazer(chamados.avaliar, cid, sess, body.get("nota"), body.get("texto") or "")
        if not r:
            return _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("avaliar", exc, "Erro ao registrar a avaliação.")
    _depois(bg, cid, r["eventos"])
    return JSONResponse({"ok": True})


@router.post("/meus/chamados/{cid}/canais")
async def meus_canais(req: Request, cid: int) -> JSONResponse:
    sess = _sessao(req)
    try:
        body = await _corpo(req)
        r = await _fazer(chamados.canais, cid, sess, body)
        if not r:
            return _404()
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return _erro("meus_canais", exc, "Erro ao alterar os avisos.")


def _anexo_resp(a: dict | None) -> Response:
    if not a:
        return _404()
    inline = a["mime"].startswith("image/") or a["mime"] == "application/pdf"
    return Response(content=a["bytes"], media_type=a["mime"], headers={
        "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename=\"{a['nome']}\"",
        "Cache-Control": "private, max-age=3600"})


@router.get("/meus/chamados/{cid}/anexos/{aid}")
def meu_anexo(req: Request, cid: int, aid: int) -> Response:
    sess = _sessao(req)
    try:
        return _anexo_resp(chamados.anexo(aid, usuario_id=sess.get("id")))
    except Exception as exc:  # noqa: BLE001
        return _erro("meu_anexo", exc, "Erro ao ler o anexo.")


# ============================================================== atendimento
@router.get("/atendimento/painel")
def painel(req: Request) -> JSONResponse:
    try:
        sync = espelho.sincronizar()
        avisos.despachar_adiados()
        return JSONResponse({"kpis": chamados.kpis_time(), "fila": chamados.listar_fila({}),
                             "atendentes": chamados.atendentes(), "espelho": sync,
                             "config": {k: v for k, v in comum.config().items() if k != "email_equipe"},
                             "status": [{"valor": s, "rotulo": comum.ROTULO_STATUS[s]} for s in comum.STATUS],
                             "motivos": [{"valor": m, "rotulo": comum.ROTULO_MOTIVO[m]} for m in comum.MOTIVOS_FECHAMENTO if m]})
    except Exception as exc:  # noqa: BLE001
        return _erro("painel", exc, "Erro ao montar a fila de suporte.")


@router.get("/atendimento/chamados")
def fila(req: Request, status: str | None = None, gravidade: str | None = None, tela: str | None = None,
         usuario_id: int | None = None, atribuido_id: int | None = None, busca: str | None = None,
         fechados: int = 0) -> JSONResponse:
    try:
        return JSONResponse(chamados.listar_fila({"status": status, "gravidade": gravidade, "tela": tela,
                                                  "usuario_id": usuario_id, "atribuido_id": atribuido_id,
                                                  "busca": busca, "fechados": bool(fechados)}))
    except Exception as exc:  # noqa: BLE001
        return _erro("fila", exc, "Erro ao listar os chamados.")


@router.get("/atendimento/chamados/{cid}")
def chamado_atendimento(req: Request, cid: int) -> JSONResponse:
    try:
        d = chamados.obter(cid, suporte=True)
        return JSONResponse(d) if d else _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("chamado_atendimento", exc, "Erro ao ler o chamado.")


@router.post("/atendimento/chamados/{cid}/lido")
async def lido_suporte(req: Request, cid: int) -> JSONResponse:
    try:
        ok = await _fazer(chamados.marcar_lido, cid, "suporte", None)
        return JSONResponse({"ok": True}) if ok else _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("lido_suporte", exc, "Erro ao marcar como lido.")


@router.post("/atendimento/chamados/{cid}/assumir")
async def assumir(req: Request, cid: int, bg: BackgroundTasks) -> JSONResponse:
    sess = _sessao(req)
    try:
        body = await _corpo(req) if int(req.headers.get("content-length") or 0) > 0 else {}
        r = await _fazer(chamados.assumir, cid, sess, body.get("usuario_id"))
        if not r:
            return _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("assumir", exc, "Erro ao assumir o chamado.")
    _depois(bg, cid, r["eventos"])
    return JSONResponse({"ok": True})


@router.post("/atendimento/chamados/{cid}/mensagens")
async def mensagem_suporte(req: Request, cid: int, bg: BackgroundTasks) -> JSONResponse:
    sess = _sessao(req)
    try:
        body = await _corpo(req)
        r = await _fazer(chamados.responder, cid, sess, "suporte", body.get("texto"), body.get("anexos"),
                         interna=bool(body.get("interna")))
        if not r:
            return _404()
    except _Grande:
        return JSONResponse(status_code=413, content=_GRANDE)
    except Exception as exc:  # noqa: BLE001
        return _erro("mensagem_suporte", exc, "Erro ao enviar a resposta.")
    _depois(bg, cid, r["eventos"], r["mensagem_id"], str(body.get("texto") or "")[:2000])
    return JSONResponse({"ok": True, "mensagem_id": r["mensagem_id"]})


@router.post("/atendimento/chamados/{cid}/status")
async def status_suporte(req: Request, cid: int, bg: BackgroundTasks) -> JSONResponse:
    sess = _sessao(req)
    try:
        body = await _corpo(req)
        r = await _fazer(chamados.mudar_status, cid, sess, "suporte", body.get("status"),
                         texto=body.get("texto") or "", motivo=body.get("motivo") or "")
        if not r:
            return _404()
    except Exception as exc:  # noqa: BLE001
        return _erro("status_suporte", exc, "Erro ao mudar o status.")
    _depois(bg, cid, [f"status_{r['para']}"], r.get("mensagem_id"), body.get("texto") or "")
    return JSONResponse({"ok": True, "status": r["para"]})


@router.post("/atendimento/chamados/{cid}/espelhar")
async def espelhar(req: Request, cid: int) -> JSONResponse:
    try:
        r = await _fazer(espelho.espelhar_tudo, cid)
        if not r.get("issue", {}).get("ok"):
            return JSONResponse(status_code=HTTP_RECUSA, content={"erro": "github_falhou",
                                                                  "mensagem": r.get("issue", {}).get("motivo") or "O espelho não respondeu."})
        return JSONResponse(r)
    except Exception as exc:  # noqa: BLE001
        return _erro("espelhar", exc, "Erro ao espelhar no GitHub.")


@router.post("/atendimento/github/sincronizar")
async def sincronizar(req: Request) -> JSONResponse:
    try:
        r = await _fazer(espelho.sincronizar, None, None, True)
        r["adiados"] = len(await _fazer(avisos.despachar_adiados))
        return JSONResponse(r)
    except Exception as exc:  # noqa: BLE001
        return _erro("sincronizar", exc, "Erro ao sincronizar com o GitHub.")


@router.get("/atendimento/chamados/{cid}/anexos/{aid}")
def anexo_suporte(req: Request, cid: int, aid: int) -> Response:
    try:
        return _anexo_resp(chamados.anexo(aid, suporte=True))
    except Exception as exc:  # noqa: BLE001
        return _erro("anexo_suporte", exc, "Erro ao ler o anexo.")


@router.get("/atendimento/avisos")
def avisos_recentes(req: Request) -> JSONResponse:
    try:
        rows = chamados.pglocal.query(
            "SELECT a.id, a.chamado_id, c.codigo, a.canal, a.lado, a.evento, a.destinatario, a.resultado, a.detalhe, "
            "a.tentar_apos, a.criado_em FROM sup_avisos a JOIN sup_chamados c ON c.id=a.chamado_id ORDER BY a.id DESC LIMIT 200",
            esquema=comum._esq(None))
        return JSONResponse([{**r, "criado_em": comum.iso(r["criado_em"]), "tentar_apos": comum.iso(r["tentar_apos"])} for r in rows])
    except Exception as exc:  # noqa: BLE001
        return _erro("avisos_recentes", exc, "Erro ao listar os avisos.")


@router.get("/atendimento/indicadores")
def indicadores(req: Request, dias: int = 90) -> JSONResponse:
    try:
        return JSONResponse(chamados.indicadores(dias))
    except Exception as exc:  # noqa: BLE001
        return _erro("indicadores", exc, "Erro ao montar os indicadores.")


@router.get("/atendimento/config")
def config_ler(req: Request) -> JSONResponse:
    sess = _sessao(req)
    try:
        cfg = comum.config()
        from ..reports import github as gh
        return JSONResponse({"config": cfg, "padrao": comum.CONFIG_PADRAO, "admin": bool(sess.get("admin")),
                             "github": {"configurado": gh.configurado(), "repo": gh.repo_configurado()},
                             "email_configurado": avisos.Canais.email_configurado(),
                             "whatsapp": dict(zip(("pronto", "motivo"), avisos.Canais.whatsapp_pronto()))})
    except Exception as exc:  # noqa: BLE001
        return _erro("config_ler", exc, "Erro ao ler a configuração.")


@router.post("/atendimento/config")
async def config_gravar(req: Request) -> JSONResponse:
    sess = _sessao(req)
    if not sess.get("admin"):
        return JSONResponse(status_code=403, content={"erro": "sem_acesso", "mensagem": "Só administrador altera a configuração do suporte."})
    try:
        body = await _corpo(req)
        cfg = await _fazer(comum.gravar_config, body, sess.get("email") or "")
        auth.audit(sess.get("email") or "", "sup_config", "sup_config", ", ".join(sorted(body.keys())))
        return JSONResponse({"ok": True, "config": cfg})
    except Exception as exc:  # noqa: BLE001
        return _erro("config_gravar", exc, "Erro ao gravar a configuração.")
