"""Espelho do chamado na issue do repositório privado (`REPORT_REPO`).

O chamado é a FONTE; a issue é a bancada do time. Saída best-effort DEPOIS do
commit local (audit antes da ação externa): falha vira `github_erro` no
chamado e linha `canal='github'` na trilha — nunca 5xx, nunca perde o chamado.
Entrada sob demanda (Fila, com TTL): comentários novos viram mensagem
`origem='github'` e disparam aviso como resposta do painel; issue fechada lá
resolve aqui uma vez. Idempotência: `github_numero` e `github_comment_id`
UNIQUE parciais + marcador HTML que exclui o que é nosso.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime

from .. import pglocal
from ..reports import github as gh
from . import comum
from .comum import _esq, agora

log = logging.getLogger("cortex.suporte.espelho")

MARCA = "<!-- cortex-sup {tipo}:{id} -->"
_MARCA_RE = re.compile(r"<!--\s*cortex-sup\s+\w+:\d+\s*-->")
_LABELS_STATUS = {s: f"status:{s}" for s in comum.STATUS}


def _cliente(cfg: dict):
    if cfg.get("github_espelho", "1") != "1":
        return None, "espelho desligado na configuração"
    c = gh.do_ambiente()
    if c is None:
        return None, "espelho desligado — sem GITHUB_TOKEN/REPORT_REPO"
    return c, ""


def _trilha(esq, chamado_id, resultado, detalhe="", mensagem_id=None):
    pglocal.executar(
        "INSERT INTO sup_avisos (chamado_id, mensagem_id, canal, lado, evento, destinatario, resultado, detalhe) "
        "VALUES (%s,%s,'github','suporte','espelho','issue',%s,%s)",
        (chamado_id, mensagem_id, resultado, (detalhe or "")[:400]), esquema=esq)


def _corpo_issue(ch: dict, anexos: list[tuple[str, str]]) -> str:
    ctx = ch.get("contexto") or {}
    linhas = [f"**{comum.ROTULO_TIPO.get(ch['tipo'], ch['tipo'])} · gravidade {ch['gravidade']}** — aberto por "
              f"{ch['usuario_nome'] or 'usuário'} via CÓRTEX ({ch['codigo']}).", "",
              "### Relato", "", ch["descricao"], ""]
    if anexos:
        linhas += ["### Anexos", ""] + [f"- [{n}]({u})" for n, u in anexos] + [""]
    linhas += ["### Onde", "",
               f"- Tela: {ctx.get('tela_nome') or ctx.get('tela') or '-'}",
               f"- Filtros: `{ctx.get('filtros') or '-'}`",
               f"- Versão: {ctx.get('versao') or '-'}",
               f"- Navegador: {ctx.get('navegador') or '-'} · {ctx.get('tela_px') or ''}", ""]
    erros = ctx.get("erros") or []
    if erros:
        linhas += ["### Erros de JS", "", "```"] + [str(e)[:300] for e in erros[:10]] + ["```", ""]
    linhas += [f"Chamado no painel: `#sup?chamado={ch['id']}`", MARCA.format(tipo="chamado", id=ch["id"])]
    return "\n".join(linhas)


def _rotulos(ch: dict) -> list[str]:
    return ["cortex-report", ch["tipo"], f"prioridade:{ch['gravidade']}",
            f"tela:{ch['tela'] or 'n-d'}", _LABELS_STATUS[ch["status"]]]


def espelhar_abertura(chamado_id: int, esquema: str | None = None, cliente=None) -> dict:
    """Cria a issue (uma vez) com os anexos do relato. Nunca levanta."""
    esq = _esq(esquema)
    cfg = comum.config(esq)
    cli, motivo = (cliente, "") if cliente is not None else _cliente(cfg)
    ch = pglocal.um("SELECT id, codigo, usuario_nome, tipo, gravidade, titulo, descricao, tela, contexto, status, "
                    "github_numero FROM sup_chamados WHERE id=%s", (chamado_id,), esquema=esq)
    if not ch:
        return {"ok": False, "motivo": "chamado inexistente"}
    if cli is None:
        _trilha(esq, chamado_id, "sem_canal", motivo)
        return {"ok": False, "motivo": motivo}
    if ch["github_numero"]:
        return {"ok": True, "numero": ch["github_numero"], "ja_existia": True}
    try:
        links = []
        anexos = pglocal.query("SELECT id, nome, mime, bytes FROM sup_anexos WHERE chamado_id=%s AND mensagem_id IS NULL ORDER BY id",
                               (chamado_id,), esquema=esq)
        quando = agora()
        for a in anexos:
            caminho = f"anexos/{quando:%Y/%m}/{ch['codigo']}-{a['id']}.{a['nome'].rsplit('.', 1)[-1]}"
            url = cli.subir_anexo(caminho, base64.b64encode(bytes(a["bytes"])).decode("ascii"))
            pglocal.executar("UPDATE sup_anexos SET github_url=%s WHERE id=%s", (url, a["id"]), esquema=esq)
            links.append((a["nome"], url))
        titulo = f"[{ch['codigo']}] [{comum.ROTULO_TIPO.get(ch['tipo'], ch['tipo'])}] {ch['titulo']}"
        ch_c = dict(ch)
        if isinstance(ch_c.get("contexto"), str):
            import json
            ch_c["contexto"] = json.loads(ch_c["contexto"] or "{}")
        numero, url = cli.criar_issue(titulo, _corpo_issue(ch_c, links), _rotulos(ch))
        pglocal.executar("UPDATE sup_chamados SET github_numero=%s, github_url=%s, github_erro='', github_sync_em=now() WHERE id=%s",
                         (numero, url, chamado_id), esquema=esq)
        _trilha(esq, chamado_id, "enviado", f"issue #{numero}")
        return {"ok": True, "numero": numero, "url": url}
    except gh.ErroGitHub as exc:
        pglocal.executar("UPDATE sup_chamados SET github_erro=%s WHERE id=%s", (str(exc)[:400], chamado_id), esquema=esq)
        _trilha(esq, chamado_id, "recusado", str(exc))
        return {"ok": False, "motivo": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("espelho abertura %s: %s", chamado_id, type(exc).__name__)
        pglocal.executar("UPDATE sup_chamados SET github_erro=%s WHERE id=%s", (type(exc).__name__, chamado_id), esquema=esq)
        _trilha(esq, chamado_id, "recusado", type(exc).__name__)
        return {"ok": False, "motivo": type(exc).__name__}


def espelhar_mensagem(mensagem_id: int, esquema: str | None = None, cliente=None) -> dict:
    """Comenta a mensagem (humana ou de sistema) na issue — uma vez."""
    esq = _esq(esquema)
    cfg = comum.config(esq)
    m = pglocal.um("SELECT m.id, m.chamado_id, m.papel, m.autor_nome, m.texto, m.evento, m.interna, m.origem, "
                   "m.github_comment_id, m.criado_em, c.github_numero, c.codigo FROM sup_mensagens m "
                   "JOIN sup_chamados c ON c.id=m.chamado_id WHERE m.id=%s", (mensagem_id,), esquema=esq)
    if not m or m["origem"] == "github" or m["github_comment_id"] or not m["github_numero"]:
        return {"ok": False, "motivo": "nada a espelhar"}
    cli, motivo = (cliente, "") if cliente is not None else _cliente(cfg)
    if cli is None:
        return {"ok": False, "motivo": motivo}
    quem = {"usuario": "usuário", "suporte": "suporte", "sistema": "sistema"}[m["papel"]]
    cab = f"**{m['autor_nome'] or 'CÓRTEX'} · {quem}{' · nota interna' if m['interna'] else ''} · via CÓRTEX**"
    corpo = f"{cab}\n\n{m['texto']}\n\n{MARCA.format(tipo='msg', id=m['id'])}"
    try:
        cid = cli.comentar(m["github_numero"], corpo)
        pglocal.executar("UPDATE sup_mensagens SET github_comment_id=%s, espelhada_em=now() WHERE id=%s", (cid, mensagem_id), esquema=esq)
        return {"ok": True, "comment_id": cid}
    except gh.ErroGitHub as exc:
        _trilha(esq, m["chamado_id"], "recusado", str(exc), mensagem_id)
        return {"ok": False, "motivo": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("espelho mensagem %s: %s", mensagem_id, type(exc).__name__)
        return {"ok": False, "motivo": type(exc).__name__}


def espelhar_status(chamado_id: int, esquema: str | None = None, cliente=None) -> dict:
    """Labels de status e open/closed conforme o chamado."""
    esq = _esq(esquema)
    cfg = comum.config(esq)
    ch = pglocal.um("SELECT id, status, tipo, gravidade, tela, github_numero FROM sup_chamados WHERE id=%s",
                    (chamado_id,), esquema=esq)
    if not ch or not ch["github_numero"]:
        return {"ok": False, "motivo": "sem issue"}
    cli, motivo = (cliente, "") if cliente is not None else _cliente(cfg)
    if cli is None:
        return {"ok": False, "motivo": motivo}
    try:
        estado = "closed" if ch["status"] in ("resolvido", "fechado") else "open"
        cli.alterar_issue(ch["github_numero"], state=estado, labels=_rotulos(ch),
                          state_reason=("completed" if ch["status"] == "resolvido" else "not_planned") if estado == "closed" else None)
        pglocal.executar("UPDATE sup_chamados SET github_sync_em=now(), github_erro='' WHERE id=%s", (chamado_id,), esquema=esq)
        return {"ok": True}
    except gh.ErroGitHub as exc:
        _trilha(esq, chamado_id, "recusado", str(exc))
        return {"ok": False, "motivo": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("espelho status %s: %s", chamado_id, type(exc).__name__)
        return {"ok": False, "motivo": type(exc).__name__}


def espelhar_tudo(chamado_id: int, esquema: str | None = None, cliente=None) -> dict:
    """Reintento manual: issue se falta, mensagens sem id, estado. Idempotente."""
    esq = _esq(esquema)
    r = espelhar_abertura(chamado_id, esq, cliente)
    feitos = {"issue": r}
    msgs = pglocal.query("SELECT id FROM sup_mensagens WHERE chamado_id=%s AND github_comment_id IS NULL "
                         "AND origem<>'github' ORDER BY id", (chamado_id,), esquema=esq)
    feitos["mensagens"] = [espelhar_mensagem(m["id"], esq, cliente) for m in msgs] if r.get("ok") else []
    feitos["status"] = espelhar_status(chamado_id, esq, cliente) if r.get("ok") else {"ok": False}
    return feitos


# ---------------------------------------------------------------- entrada
_ULTIMA_SYNC: dict = {"em": None}


def sincronizar(esquema: str | None = None, cliente=None, forcar: bool = False,
                agora_dt: datetime | None = None) -> dict:
    """Lê comentários e estado das issues dos chamados não encerrados.

    Devolve o que mudou. NUNCA chamada pela tela do usuário, pelo Copiloto ou
    pela Saúde — só pela Fila (TTL) e pelo botão Sincronizar.
    """
    esq = _esq(esquema)
    cfg = comum.config(esq)
    t = agora_dt or agora()
    ttl = int(cfg.get("github_ttl_min") or 5)
    if not forcar and _ULTIMA_SYNC["em"] and (t - _ULTIMA_SYNC["em"]).total_seconds() < ttl * 60:
        return {"pulou": True, "motivo": f"sincronizado há menos de {ttl} min"}
    cli, motivo = (cliente, "") if cliente is not None else _cliente(cfg)
    if cli is None:
        return {"pulou": True, "motivo": motivo}
    _ULTIMA_SYNC["em"] = t
    from . import avisos, chamados
    resultado = {"chamados": 0, "importados": 0, "estados": 0, "falhas": []}
    rows = pglocal.query("SELECT id, codigo, status, github_numero, github_sync_em, status_em FROM sup_chamados "
                         "WHERE github_numero IS NOT NULL AND status<>'fechado' ORDER BY id", esquema=esq)
    for ch in rows:
        resultado["chamados"] += 1
        inicio = t
        try:
            comentarios = cli.comentarios(ch["github_numero"], since=ch["github_sync_em"])
            for c in comentarios:
                corpo = str(c.get("body") or "")
                if _MARCA_RE.search(corpo):
                    continue           # eco do que nós mesmos escrevemos
                cid = int(c.get("id") or 0)
                if not cid:
                    continue
                autor = str((c.get("user") or {}).get("login") or "github")
                with pglocal.get_conn(esq) as conn:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO sup_mensagens (chamado_id, papel, autor_nome, texto, origem, github_comment_id, espelhada_em) "
                                    "VALUES (%s,'suporte',%s,%s,'github',%s,now()) ON CONFLICT (github_comment_id) WHERE github_comment_id IS NOT NULL DO NOTHING RETURNING id",
                                    (ch["id"], autor, corpo[:comum.TEXTO_MAX], cid))
                        novo = cur.fetchone()
                        if novo:
                            cur.execute("UPDATE sup_chamados SET atualizado_em=now() WHERE id=%s", (ch["id"],))
                if novo:
                    resultado["importados"] += 1
                    avisos.avisar(ch["id"], "resposta_suporte", mensagem_id=novo["id"], texto=corpo[:2000], esquema=esq)
            issue = cli.issue(ch["github_numero"])
            estado = str(issue.get("state") or "open")
            fechada_em = issue.get("closed_at")
            if estado == "closed" and ch["status"] not in ("resolvido", "fechado"):
                quem = str((issue.get("closed_by") or {}).get("login") or "github")
                r = chamados.mudar_status(ch["id"], {"id": None, "nome": f"{quem} (GitHub)", "email": "github"},
                                          "suporte", "resolvido", texto=f"Resolvido no GitHub por {quem}.", esquema=esq)
                if r:
                    resultado["estados"] += 1
                    avisos.avisar(ch["id"], "status_resolvido", mensagem_id=r.get("mensagem_id"), esquema=esq)
            elif estado == "open" and ch["status"] == "resolvido" and fechada_em is None:
                r = chamados.mudar_status(ch["id"], {"id": None, "nome": "GitHub", "email": "github"},
                                          "suporte", "aberto", texto="Reaberto no GitHub.", esquema=esq)
                if r:
                    resultado["estados"] += 1
                    avisos.avisar(ch["id"], "status_aberto", mensagem_id=r.get("mensagem_id"), esquema=esq)
            pglocal.executar("UPDATE sup_chamados SET github_sync_em=%s, github_erro='' WHERE id=%s", (inicio, ch["id"]), esquema=esq)
        except gh.ErroGitHub as exc:
            resultado["falhas"].append({"codigo": ch["codigo"], "motivo": str(exc)})
            _trilha(esq, ch["id"], "recusado", str(exc))
        except Exception as exc:  # noqa: BLE001
            log.warning("espelho sincronizar %s: %s", ch["codigo"], type(exc).__name__)
            resultado["falhas"].append({"codigo": ch["codigo"], "motivo": type(exc).__name__})
    return resultado
