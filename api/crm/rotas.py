"""As rotas do CRM — `/api/comercial/crm/*`.

Router próprio, incluído por `api/main.py`, pelo precedente de
`auth.router_gestao`: o `main.py` já tem mais de quatro mil linhas e é o
arquivo que duas frentes mexem ao mesmo tempo.

TRÊS REGRAS DA CASA, aplicadas aqui sem exceção:

1. **GET é `def`, POST é `async def`.** O FastAPI roda rota `def` num
   threadpool e rota `async def` NO PRÓPRIO EVENT LOOP. Como as rotas que
   recebem corpo precisam de `await req.json()`, elas nascem `async def` — e aí
   o `psycopg` dentro delas trava o loop, ou seja, o CÓRTEX inteiro, pelo tempo
   da consulta. Por isso todo POST passa o trabalho por `sem_travar()`.

2. **Recusa é 4xx, nunca 5xx.** `DadoInvalido` é o CÓRTEX funcionando e dizendo
   NÃO, com um motivo que a pessoa precisa LER — e o Cloudflare TROCA o corpo
   das respostas 5xx da origem pela página de erro dele, então uma recusa
   mandada como 500 chega à tela sem JSON nenhum, como "erro interno da API".
   Isso custou uma manhã no envio de WhatsApp.

3. **Toda escrita entra no `audit_log`** (CLAUDE.md §8.2), com o alvo e o que
   mudou — nunca com o conteúdo de campo livre inteiro.

O acesso é o da tela `crm`, por `ROTA_TELAS` em `api/auth.py`: o prefixo
`/api/comercial/crm` já está lá e cobre tudo o que vem abaixo dele.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import auth
from ..validacao import DadoInvalido

log = logging.getLogger("cortex.crm")

router = APIRouter(prefix="/api/comercial/crm")

# 409, como em `api/main.py`. Não é preciosismo de vocabulário: é o código que
# atravessa o túnel com o corpo intacto.
HTTP_RECUSA = 409


def _quem(req: Request) -> tuple[str, int | None]:
    sess = getattr(req.state, "sessao", None) or {}
    return sess.get("email", ""), sess.get("id")


def _erro(nome: str, exc: Exception, msg: str) -> JSONResponse:
    """Toda rota deste módulo erra do mesmo jeito.

    `DadoInvalido` vai inteiro para a tela em 422 — é a frase que explica o que
    corrigir. O resto é falha nossa: 500 com mensagem genérica e o TIPO da
    exceção no log, nunca `str(exc)`, que pode carregar credencial (a URL da
    Z-API é a credencial) ou caminho de arquivo.
    """
    if isinstance(exc, DadoInvalido):
        return JSONResponse(status_code=422, content={
            "erro": "parametro_invalido", "mensagem": str(exc)})
    log.warning("%s falhou: %s", nome, type(exc).__name__)
    return JSONResponse(status_code=500, content={
        "erro": "erro_consulta", "mensagem": msg})


async def _corpo(req: Request) -> dict:
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        raise DadoInvalido("O corpo da requisição não é um objeto JSON.")
    return body


async def _fazer(fn, *args, **kwargs):
    """Roda o trabalho bloqueante fora do event loop. Ver regra 1."""
    from api.main import sem_travar
    return await sem_travar(fn, *args, **kwargs)


# =========================================================== painel e catálogo

@router.get("/painel")
def crm_painel(req: Request) -> JSONResponse:
    """A tela inteira numa chamada — funil, previsão, carteira e alertas."""
    try:
        from . import painel
        dados = painel.tudo()
        _, uid = _quem(req)
        dados["minhas"] = painel.minhas(uid)
        return JSONResponse(dados)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_painel", exc, "Erro ao montar o painel do CRM.")


@router.get("/catalogo")
def crm_catalogo() -> JSONResponse:
    """As listas de apoio dos formulários, de uma vez.

    Numa chamada só porque a tela abre quatro formulários diferentes e buscar
    o catálogo em cada um seria quatro idas para desenhar `<select>`.
    """
    try:
        from . import atividades, contas, contratos, oportunidades, projetos
        from .comum import usuarios_ativos
        from . import ava, mensagens
        try:
            grupos = ava.agrupamentos()
            erp = None
        except Exception as exc:  # noqa: BLE001
            # ERP fora do ar não pode derrubar o catálogo: sem ele ainda dá
            # para cadastrar conta, oportunidade e atividade — só não dá para
            # VINCULAR ao grupo econômico. A tela diz isso no campo.
            grupos, erp = [], type(exc).__name__
        return JSONResponse({
            **contas.catalogo(), **oportunidades.catalogo(),
            "atividades": atividades.catalogo(),
            "contratos": contratos.catalogo(),
            "projetos": projetos.catalogo(),
            "usuarios": usuarios_ativos(),
            "agrupamentos": grupos,
            "erp_indisponivel": erp,
            "canais": mensagens.canais_disponiveis(),
        })
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_catalogo", exc, "Erro ao ler o catálogo do CRM.")


# ===================================================================== contas

@router.get("/contas")
def crm_contas(busca: str = "", situacao: str = "", dono_id: int = 0,
               segmento: str = "", arquivadas: int = 0) -> JSONResponse:
    try:
        from . import contas
        lista = contas.listar(busca=busca, situacao=situacao,
                              dono_id=dono_id or None, segmento=segmento,
                              incluir_arquivadas=bool(arquivadas))
        return JSONResponse({"contas": lista, "total": len(lista)})
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contas", exc, "Erro ao listar as contas.")


@router.get("/contas/{conta_id}")
def crm_conta(conta_id: int) -> JSONResponse:
    try:
        from . import contas
        c = contas.obter(conta_id)
        if not c:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Esta conta não existe mais."})
        return JSONResponse(c)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_conta", exc, "Erro ao ler a conta.")


@router.post("/contas")
async def crm_conta_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        conta_id = body.get("id")
        conta_id = int(conta_id) if isinstance(conta_id, int) else None
        from . import contas
        d = await _fazer(contas.gravar, body, usuario=autor, conta_id=conta_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_conta_salvar", exc,
                     "Não foi possível gravar a conta.")
    auth.audit(autor or "?", "crm_conta", alvo=f"#{d['id']}",
               detalhe=f"{'editada' if conta_id else 'criada'} · {d['nome']}")
    return JSONResponse(d)


@router.post("/contas/{conta_id}/arquivar")
async def crm_conta_arquivar(conta_id: int, req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        arq = bool(body.get("arquivada", True))
        from . import contas
        d = await _fazer(contas.arquivar, conta_id, arquivada=arq,
                         usuario=autor)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_conta_arquivar", exc,
                     "Não foi possível arquivar a conta.")
    auth.audit(autor or "?", "crm_conta_arquivar", alvo=f"#{conta_id}",
               detalhe=("arquivada" if arq else "reativada") + f" · {d['nome']}")
    return JSONResponse(d)


@router.get("/contas/{conta_id}/pendencias")
def crm_conta_pendencias(conta_id: int) -> JSONResponse:
    """O que a exclusão levaria junto — para a confirmação da tela dizer.

    A confirmação precisa mostrar o número ANTES: é a consequência que não se
    vê ao clicar, exatamente como a exclusão de ata na Gestão avisa quantas
    ações ficarão órfãs.
    """
    try:
        from . import contas
        return JSONResponse(contas.pendencias(conta_id))
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_conta_pendencias", exc, "Erro ao conferir a conta.")


@router.post("/contas/{conta_id}/excluir")
async def crm_conta_excluir(conta_id: int, req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import contas
        c = await _fazer(contas.obter, conta_id, com_erp=False)
        if not c:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado", "mensagem": "Esta conta não existe mais."})
        await _fazer(contas.excluir, conta_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_conta_excluir", exc,
                     "Não foi possível excluir a conta.")
    auth.audit(autor or "?", "crm_conta_excluir", alvo=f"#{conta_id}",
               detalhe=c["nome"])
    return JSONResponse({"ok": True})


# =================================================================== contatos

@router.post("/contatos")
async def crm_contato_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        ident = body.get("id")
        ident = int(ident) if isinstance(ident, int) else None
        from . import contas
        d = await _fazer(contas.gravar_contato, body, usuario=autor,
                         contato_id=ident)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contato_salvar", exc,
                     "Não foi possível gravar o contato.")
    auth.audit(autor or "?", "crm_contato", alvo=f"#{d['id']}",
               detalhe=f"{'editado' if ident else 'criado'} · {d['nome']}")
    return JSONResponse(d)


@router.post("/contatos/{contato_id}/excluir")
async def crm_contato_excluir(contato_id: int, req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import contas
        await _fazer(contas.excluir_contato, contato_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contato_excluir", exc,
                     "Não foi possível excluir o contato.")
    auth.audit(autor or "?", "crm_contato_excluir", alvo=f"#{contato_id}")
    return JSONResponse({"ok": True})


# =============================================================== oportunidades

@router.get("/oportunidades")
def crm_oportunidades(conta_id: int = 0, estagio: str = "", dono_id: int = 0,
                      busca: str = "", tipo: str = "",
                      fechadas: int = 0) -> JSONResponse:
    try:
        from . import oportunidades
        lista = oportunidades.listar(
            conta_id=conta_id or None, estagio=estagio,
            dono_id=dono_id or None, busca=busca, tipo=tipo,
            incluir_fechadas=bool(fechadas))
        return JSONResponse({"oportunidades": lista, "total": len(lista)})
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_oportunidades", exc,
                     "Erro ao listar as oportunidades.")


@router.get("/oportunidades/{oportunidade_id}")
def crm_oportunidade(oportunidade_id: int) -> JSONResponse:
    try:
        from . import oportunidades
        o = oportunidades.obter(oportunidade_id)
        if not o:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado",
                "mensagem": "Esta oportunidade não existe mais."})
        return JSONResponse(o)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_oportunidade", exc, "Erro ao ler a oportunidade.")


@router.post("/oportunidades")
async def crm_oportunidade_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        ident = body.get("id")
        ident = int(ident) if isinstance(ident, int) else None
        from . import oportunidades
        d = await _fazer(oportunidades.gravar, body, usuario=autor,
                         oportunidade_id=ident)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_oportunidade_salvar", exc,
                     "Não foi possível gravar a oportunidade.")
    auth.audit(autor or "?", "crm_oportunidade", alvo=d["codigo"],
               detalhe=(f"{'editada' if ident else 'criada'} · "
                        f"{d['estagio']} · {d['titulo']}"))
    return JSONResponse(d)


@router.post("/oportunidades/{oportunidade_id}/mover")
async def crm_oportunidade_mover(oportunidade_id: int,
                                 req: Request) -> JSONResponse:
    """O arraste do kanban. Rota curta porque é a operação frequente."""
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import oportunidades
        d = await _fazer(oportunidades.mover, oportunidade_id,
                         body.get("estagio", ""), usuario=autor,
                         motivo_perda=body.get("motivo_perda", ""),
                         perda_detalhe=body.get("perda_detalhe", ""))
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_oportunidade_mover", exc,
                     "Não foi possível mover a oportunidade.")
    auth.audit(autor or "?", "crm_oportunidade_mover", alvo=d["codigo"],
               detalhe=(f"→ {d['estagio']}"
                        + (f" · {d['motivo_perda']}" if d.get("motivo_perda") else "")))
    return JSONResponse(d)


@router.post("/oportunidades/{oportunidade_id}/excluir")
async def crm_oportunidade_excluir(oportunidade_id: int,
                                   req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import oportunidades
        o = await _fazer(oportunidades.obter, oportunidade_id)
        if not o:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado",
                "mensagem": "Esta oportunidade não existe mais."})
        await _fazer(oportunidades.excluir, oportunidade_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_oportunidade_excluir", exc,
                     "Não foi possível excluir a oportunidade.")
    auth.audit(autor or "?", "crm_oportunidade_excluir", alvo=o["codigo"],
               detalhe=o["titulo"])
    return JSONResponse({"ok": True})


# ====================================================================== lanes

@router.post("/lanes")
async def crm_lane_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        ident = body.get("id")
        ident = int(ident) if isinstance(ident, int) else None
        from . import oportunidades
        d = await _fazer(oportunidades.gravar_lane, body, lane_id=ident)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_lane_salvar", exc, "Não foi possível gravar a lane.")
    # O alerta de piso vai para a auditoria: cotação abaixo do mínimo legal é
    # exatamente o que alguém vai querer reconstituir depois.
    alerta = (d.get("calc") or {}).get("alerta") or {}
    auth.audit(autor or "?", "crm_lane", alvo=f"#{d['id']}",
               detalhe=(f"{'editada' if ident else 'criada'} · {d['rotulo']}"
                        + (f" · {alerta.get('texto')}" if alerta else "")))
    return JSONResponse(d)


@router.post("/lanes/{lane_id}/excluir")
async def crm_lane_excluir(lane_id: int, req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import oportunidades
        await _fazer(oportunidades.excluir_lane, lane_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_lane_excluir", exc,
                     "Não foi possível excluir a lane.")
    auth.audit(autor or "?", "crm_lane_excluir", alvo=f"#{lane_id}")
    return JSONResponse({"ok": True})


# ================================================================= atividades

@router.get("/atividades")
def crm_atividades(conta_id: int = 0, oportunidade_id: int = 0,
                   responsavel_id: int = 0, status: str = "",
                   atrasadas: int = 0, ate: str = "") -> JSONResponse:
    try:
        from . import atividades
        f = {"conta_id": conta_id or None,
             "oportunidade_id": oportunidade_id or None,
             "responsavel_id": responsavel_id or None, "status": status,
             "atrasadas": bool(atrasadas), "ate": ate}
        lista = atividades.listar(**f)
        # "X de Y" no hint: top-N sem contador vira total falso.
        return JSONResponse({"atividades": lista, "mostrando": len(lista),
                             "total": atividades.contar(**f)})
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_atividades", exc, "Erro ao listar as atividades.")


@router.post("/atividades")
async def crm_atividade_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        ident = body.get("id")
        ident = int(ident) if isinstance(ident, int) else None
        from . import atividades
        d = await _fazer(atividades.gravar, body, usuario=autor,
                         atividade_id=ident)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_atividade_salvar", exc,
                     "Não foi possível gravar a atividade.")
    auth.audit(autor or "?", "crm_atividade", alvo=f"#{d['id']}",
               detalhe=f"{'editada' if ident else 'criada'} · {d['assunto']}")
    return JSONResponse(d)


@router.post("/atividades/{atividade_id}/concluir")
async def crm_atividade_concluir(atividade_id: int,
                                 req: Request) -> JSONResponse:
    """Conclui e registra a interação — o caminho curto do follow-up.

    Quem acabou de ligar está com o resumo na cabeça, e é o único momento em
    que ele vai escrever. Pedir depois, num formulário separado, é o que faz o
    histórico ficar vazio.
    """
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import atividades
        d = await _fazer(atividades.concluir, atividade_id, usuario=autor,
                         resumo=body.get("resumo", ""),
                         registrar_interacao=body.get("registrar", True) is not False)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_atividade_concluir", exc,
                     "Não foi possível concluir a atividade.")
    auth.audit(autor or "?", "crm_atividade_concluir", alvo=f"#{atividade_id}",
               detalhe=d["assunto"])
    return JSONResponse(d)


@router.post("/atividades/{atividade_id}/excluir")
async def crm_atividade_excluir(atividade_id: int,
                                req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import atividades
        await _fazer(atividades.excluir, atividade_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_atividade_excluir", exc,
                     "Não foi possível excluir a atividade.")
    auth.audit(autor or "?", "crm_atividade_excluir", alvo=f"#{atividade_id}")
    return JSONResponse({"ok": True})


# ================================================================== interações

@router.get("/interacoes")
def crm_interacoes(conta_id: int = 0, oportunidade_id: int = 0,
                   limite: int = 100) -> JSONResponse:
    try:
        from . import atividades
        return JSONResponse({"interacoes": atividades.interacoes(
            conta_id=conta_id or None,
            oportunidade_id=oportunidade_id or None, limite=limite)})
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_interacoes", exc, "Erro ao ler o histórico.")


@router.post("/interacoes")
async def crm_interacao_registrar(req: Request) -> JSONResponse:
    """Append-only: existe gravar, não existe editar nem excluir.

    Interação editável deixa de ser prova de que o contato houve — quem errou
    o texto acrescenta outra, como em `ges_andamentos`.
    """
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import atividades
        d = await _fazer(atividades.registrar, body, usuario=autor)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_interacao_registrar", exc,
                     "Não foi possível registrar a interação.")
    auth.audit(autor or "?", "crm_interacao", alvo=f"#{d['id']}",
               detalhe=f"{d['canal']} · conta #{d['conta_id']}")
    return JSONResponse(d)


# =================================================================== contratos

@router.get("/contratos")
def crm_contratos(conta_id: int = 0, situacao: str = "",
                  dono_id: int = 0) -> JSONResponse:
    try:
        from . import contratos
        lista = contratos.listar(conta_id=conta_id or None, situacao=situacao,
                                 dono_id=dono_id or None)
        return JSONResponse({"contratos": lista, "total": len(lista)})
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contratos", exc, "Erro ao listar os contratos.")


@router.get("/contratos/{contrato_id}")
def crm_contrato(contrato_id: int) -> JSONResponse:
    try:
        from . import contratos
        c = contratos.obter(contrato_id)
        if not c:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado",
                "mensagem": "Este contrato não existe mais."})
        return JSONResponse(c)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contrato", exc, "Erro ao ler o contrato.")


@router.post("/contratos")
async def crm_contrato_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        ident = body.get("id")
        ident = int(ident) if isinstance(ident, int) else None
        from . import contratos
        d = await _fazer(contratos.gravar, body, usuario=autor,
                         contrato_id=ident)
        # Contrato novo nascido de uma oportunidade herda a tabela de preço —
        # CÓPIA, não referência: a proposta é o que foi oferecido e o contrato é
        # o que foi assinado, e corrigir a proposta não pode reescrever um
        # documento com valor jurídico.
        if (not ident and d.get("oportunidade_id")
                and body.get("copiar_lanes") is not False):
            n = await _fazer(contratos.copiar_lanes_da_oportunidade,
                             d["id"], d["oportunidade_id"])
            if n:
                d = await _fazer(contratos.obter, d["id"])
                d["lanes_copiadas"] = n
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contrato_salvar", exc,
                     "Não foi possível gravar o contrato.")
    auth.audit(autor or "?", "crm_contrato", alvo=d["codigo"],
               detalhe=f"{'editado' if ident else 'criado'} · {d['objeto']}")
    return JSONResponse(d)


@router.post("/contratos/{contrato_id}/reajuste")
async def crm_contrato_reajuste(contrato_id: int, req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import contratos
        d = await _fazer(contratos.registrar_reajuste, contrato_id,
                         percentual=body.get("percentual"),
                         quando=body.get("quando"), usuario=autor)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contrato_reajuste", exc,
                     "Não foi possível registrar o reajuste.")
    auth.audit(autor or "?", "crm_contrato_reajuste", alvo=d["codigo"],
               detalhe=f"{d['percentual_ultimo']}% em {d['ultimo_reajuste']}")
    return JSONResponse(d)


@router.post("/contratos/{contrato_id}/excluir")
async def crm_contrato_excluir(contrato_id: int, req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import contratos
        c = await _fazer(contratos.obter, contrato_id)
        if not c:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado",
                "mensagem": "Este contrato não existe mais."})
        await _fazer(contratos.excluir, contrato_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_contrato_excluir", exc,
                     "Não foi possível excluir o contrato.")
    auth.audit(autor or "?", "crm_contrato_excluir", alvo=c["codigo"],
               detalhe=c["objeto"])
    return JSONResponse({"ok": True})


# =================================================================== mensagens

@router.post("/contatos/{contato_id}/whatsapp")
async def crm_whatsapp(contato_id: int, req: Request) -> JSONResponse:
    """Manda um WhatsApp para o contato e registra a interação.

    Passa pelo MESMO caminho de sempre (`api/whatsapp/envio.py`): mesma trilha,
    mesmo limite diário, mesma janela de horário, mesma auditoria. Não existe
    "modo CRM" mais frouxo — um caminho paralelo viraria o atalho para disparar
    sem as regras.

    Recusa do envio volta em `HTTP_RECUSA` (409) com o motivo INTEIRO: "o envio
    está desligado", "o limite do dia acabou", "a instância não está pareada"
    são todas o CÓRTEX funcionando e dizendo não.
    """
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import mensagens
        r = await _fazer(mensagens.whatsapp, contato_id,
                         mensagem=body.get("mensagem", ""),
                         modelo=body.get("modelo", ""),
                         valores=body.get("valores") or {},
                         oportunidade_id=body.get("oportunidade_id"),
                         usuario=autor, instancia=body.get("instancia"))
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_whatsapp", exc, "Não foi possível enviar.")
    envio = r.get("envio") or {}
    auth.audit(autor or "?", "crm_whatsapp", alvo=f"contato #{contato_id}",
               detalhe=("enviado" if envio.get("ok")
                        else f"recusado · {envio.get('erro', '')}"[:200]))
    if not envio.get("ok"):
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "envio_recusado",
            "mensagem": envio.get("erro") or "O envio não foi aceito.",
            "envio": envio})
    return JSONResponse(r)


@router.post("/contatos/{contato_id}/email")
async def crm_email(contato_id: int, req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import mensagens
        r = await _fazer(mensagens.email, contato_id,
                         assunto=body.get("assunto", ""),
                         corpo=body.get("corpo", ""),
                         oportunidade_id=body.get("oportunidade_id"),
                         usuario=autor)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_email", exc, "Não foi possível enviar o e-mail.")
    envio = r.get("envio") or {}
    auth.audit(autor or "?", "crm_email", alvo=f"contato #{contato_id}",
               detalhe=("enviado" if envio.get("ok")
                        else f"recusado · {envio.get('erro', '')}"[:200]))
    if not envio.get("ok"):
        return JSONResponse(status_code=HTTP_RECUSA, content={
            "erro": "envio_recusado",
            "mensagem": envio.get("erro") or "O envio não foi aceito.",
            "envio": envio})
    return JSONResponse(r)


# ==================================================================== projetos

@router.get("/projetos")
def crm_projetos(conta_id: int = 0, status: str = "", responsavel_id: int = 0,
                 busca: str = "", fechados: int = 0) -> JSONResponse:
    try:
        from . import projetos
        lista = projetos.listar(conta_id=conta_id or None, status=status,
                                responsavel_id=responsavel_id or None,
                                busca=busca, incluir_fechados=bool(fechados))
        return JSONResponse({"projetos": lista, "total": len(lista)})
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_projetos", exc, "Erro ao listar os projetos.")


@router.get("/projetos/{projeto_id}")
def crm_projeto(projeto_id: int) -> JSONResponse:
    try:
        from . import projetos
        p = projetos.obter(projeto_id)
        if not p:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado",
                "mensagem": "Este projeto não existe mais."})
        return JSONResponse(p)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_projeto", exc, "Erro ao ler o projeto.")


@router.post("/projetos")
async def crm_projeto_salvar(req: Request) -> JSONResponse:
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        ident = body.get("id")
        ident = int(ident) if isinstance(ident, int) else None
        from . import projetos
        d = await _fazer(projetos.gravar, body, usuario=autor,
                         projeto_id=ident)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_projeto_salvar", exc,
                     "Não foi possível gravar o projeto.")
    auth.audit(autor or "?", "crm_projeto", alvo=d["codigo"],
               detalhe=(f"{'editado' if ident else 'criado'} · "
                        f"{d['status']} · {d['nome']}"))
    return JSONResponse(d)


@router.post("/oportunidades/{oportunidade_id}/projeto")
async def crm_projeto_da_oportunidade(oportunidade_id: int,
                                      req: Request) -> JSONResponse:
    """Abre o projeto a partir da venda ganha, copiando as lanes.

    É o caminho normal de criação: o projeto herda conta, título, responsável e
    o escopo prometido. Criar solto continua possível pelo `POST /projetos`,
    para o projeto que não nasceu de oportunidade nenhuma.
    """
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import projetos
        d = await _fazer(projetos.de_oportunidade, oportunidade_id, body,
                         usuario=autor)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_projeto_da_oportunidade", exc,
                     "Não foi possível abrir o projeto.")
    auth.audit(autor or "?", "crm_projeto", alvo=d["codigo"],
               detalhe=(f"aberto da oportunidade #{oportunidade_id} · "
                        f"{d.get('lanes_copiadas', 0)} lane(s) copiada(s)"))
    return JSONResponse(d)


@router.post("/projetos/{projeto_id}/andamento")
async def crm_projeto_andamento(projeto_id: int, req: Request) -> JSONResponse:
    """O caminho curto do acompanhamento — escrever o que andou.

    Rota própria pela mesma razão do andamento de ação na Gestão: é a operação
    FREQUENTE, e obrigar o formulário completo para dizer "o cliente confirmou
    a doca" é o que faz o histórico ficar vazio.
    """
    try:
        body = await _corpo(req)
        autor, _ = _quem(req)
        from . import projetos
        d = await _fazer(projetos.registrar_andamento, projeto_id,
                         texto_=body.get("texto", ""),
                         status=body.get("status", ""),
                         percentual=body.get("percentual"), usuario=autor)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_projeto_andamento", exc,
                     "Não foi possível registrar o andamento.")
    auth.audit(autor or "?", "crm_projeto_andamento", alvo=d["codigo"],
               detalhe=f"{d['status']} · {d['percentual']}%")
    return JSONResponse(d)


@router.post("/projetos/{projeto_id}/excluir")
async def crm_projeto_excluir(projeto_id: int, req: Request) -> JSONResponse:
    try:
        autor, _ = _quem(req)
        from . import projetos
        p = await _fazer(projetos.obter, projeto_id, com_erp=False)
        if not p:
            return JSONResponse(status_code=404, content={
                "erro": "nao_encontrado",
                "mensagem": "Este projeto não existe mais."})
        await _fazer(projetos.excluir, projeto_id)
    except Exception as exc:  # noqa: BLE001
        return _erro("crm_projeto_excluir", exc,
                     "Não foi possível excluir o projeto.")
    auth.audit(autor or "?", "crm_projeto_excluir", alvo=p["codigo"],
               detalhe=p["nome"])
    return JSONResponse({"ok": True})
