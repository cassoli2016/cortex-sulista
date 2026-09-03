"""Chamados: gravar o que é decisão, calcular o que envelhece.

Toda escrita entra no `audit_log` ANTES de qualquer ação externa (§8.3); a
conversa é append-only; toda transição gera mensagem de sistema na mesma
transação. O que se devolve já vem serializável (timestamps em ISO).
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone

from .. import auth, pglocal
from ..validacao import DadoInvalido, escolha, texto as _texto
from . import comum
from .comum import ATIVOS, ROTULO_STATUS, TransicaoInvalida, _esq, agora, iso

log = logging.getLogger("cortex.suporte")

_CAMPOS = ("id, ano, sequencia, codigo, usuario_id, usuario_nome, tipo, gravidade, titulo, "
           "descricao, tela, contexto, status, status_em, status_por, atribuido_id, atribuido_nome, "
           "avisar_email, avisar_whatsapp, motivo_fechamento, avaliacao, avaliacao_texto, "
           "github_numero, github_url, github_erro, github_sync_em, lido_usuario_em, "
           "lido_suporte_em, criado_em, atualizado_em")


# ------------------------------------------------------------------ utilidades
def _h(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 3600.0, 2)


def _quem(sessao: dict) -> tuple[int | None, str, str]:
    return sessao.get("id"), (sessao.get("nome") or "").strip(), (sessao.get("email") or "")


def _proximo_codigo(cur, ano: int) -> tuple[int, str]:
    cur.execute("SELECT coalesce(max(sequencia), 0) AS s FROM sup_chamados WHERE ano=%s", (ano,))
    seq = int((cur.fetchone() or {}).get("s") or 0) + 1
    return seq, f"SUP-{ano}-{seq:04d}"


def _mensagem(cur, chamado_id: int, papel: str, texto: str, *, autor_id=None, autor_nome="",
              evento="", status_de="", status_para="", interna=0, origem="painel",
              github_comment_id=None) -> int:
    cur.execute(
        "INSERT INTO sup_mensagens (chamado_id, papel, autor_id, autor_nome, texto, evento, "
        "status_de, status_para, interna, origem, github_comment_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (chamado_id, papel, autor_id, autor_nome, texto, evento, status_de, status_para,
         interna, origem, github_comment_id))
    mid = int(cur.fetchone()["id"])
    cur.execute("UPDATE sup_chamados SET atualizado_em=now() WHERE id=%s", (chamado_id,))
    return mid


def _anexos_inserir(cur, chamado_id: int, mensagem_id, anexos: list[dict]) -> list[int]:
    ids = []
    for a in anexos:
        try:
            raw = base64.b64decode(a["b64"], validate=False)
        except Exception:  # noqa: BLE001
            raise DadoInvalido("Anexo inválido (base64).") from None
        if len(raw) > comum.ANEXO_MAX_BYTES:
            raise DadoInvalido(f"Anexo acima de {comum.ANEXO_MAX_BYTES // (1024 * 1024)} MB.")
        cur.execute(
            "INSERT INTO sup_anexos (chamado_id, mensagem_id, nome, mime, tamanho, bytes) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (chamado_id, mensagem_id, a["nome"], a["mime"], len(raw), raw))
        ids.append(int(cur.fetchone()["id"]))
    return ids


def _linha(cur, chamado_id: int) -> dict | None:
    cur.execute(f"SELECT {_CAMPOS} FROM sup_chamados WHERE id=%s", (chamado_id,))
    return cur.fetchone()


# ------------------------------------------------------------------ derivados
def derivados(ch: dict, msgs: list[dict], cfg: dict, hoje: datetime | None = None) -> dict:
    """Tudo que envelhece sozinho, calculado da hora de agora. Relógio injetável."""
    t = hoje or agora()
    publicas = [m for m in msgs if not m.get("interna")]
    do_usuario = [m for m in publicas if m["papel"] == "usuario"]
    do_suporte = [m for m in publicas if m["papel"] == "suporte"]
    status = ch["status"]
    esperando = "" if status == "fechado" else (
        "usuario" if status in ("aguardando_usuario", "resolvido") else "suporte")
    # última fala de quem abriu (ou a abertura) sem resposta do suporte depois
    ultima_usuario = max([ch["criado_em"]] + [m["criado_em"] for m in do_usuario])
    resposta_depois = any(m["criado_em"] > ultima_usuario for m in do_suporte)
    horas_sem_resposta = _h(ultima_usuario, t) if (esperando == "suporte" and not resposta_depois) else None
    sla = comum.sla_horas(cfg, ch["gravidade"])
    primeira = min([m["criado_em"] for m in do_suporte], default=None)
    lido_u, lido_s = ch.get("lido_usuario_em"), ch.get("lido_suporte_em")
    # a mensagem de abertura não é novidade para quem abriu
    novas_usuario = sum(1 for m in publicas if m["papel"] in ("suporte", "sistema")
                        and not (m.get("evento") == "status" and m.get("status_para") == "aberto" and not m.get("status_de"))
                        and (lido_u is None or m["criado_em"] > lido_u))
    novas_suporte = sum(1 for m in do_usuario if lido_s is None or m["criado_em"] > lido_s)
    return {
        "esperando": esperando,
        "horas_sem_resposta": horas_sem_resposta,
        "sla_horas": sla,
        "sla_estourado": bool(horas_sem_resposta is not None and horas_sem_resposta > sla),
        "primeira_resposta_h": _h(ch["criado_em"], primeira),
        "idade_h": _h(ch["criado_em"], t),
        "status_ha_h": _h(ch["status_em"], t),
        "novas_usuario": novas_usuario,
        "novas_suporte": novas_suporte,
        "mensagens": len(publicas),
        "rotulo_status": ROTULO_STATUS.get(status, status),
        "rotulo_tipo": comum.ROTULO_TIPO.get(ch["tipo"], ch["tipo"]),
    }


def _serializar(ch: dict) -> dict:
    d = dict(ch)
    for k in ("status_em", "github_sync_em", "lido_usuario_em", "lido_suporte_em",
              "criado_em", "atualizado_em"):
        d[k] = iso(d.get(k))
    if isinstance(d.get("contexto"), str):
        try:
            d["contexto"] = json.loads(d["contexto"])
        except ValueError:
            d["contexto"] = {}
    d["avisar_email"] = bool(d.get("avisar_email"))
    d["avisar_whatsapp"] = bool(d.get("avisar_whatsapp"))
    return d


def _msgs(cur, chamado_id: int, incluir_internas: bool) -> list[dict]:
    cur.execute(
        "SELECT id, chamado_id, papel, autor_id, autor_nome, texto, evento, status_de, status_para, "
        "interna, origem, github_comment_id, espelhada_em, criado_em FROM sup_mensagens "
        "WHERE chamado_id=%s ORDER BY id", (chamado_id,))
    rows = cur.fetchall()
    return [m for m in rows if incluir_internas or not m["interna"]]


def _anexos_meta(cur, chamado_id: int) -> list[dict]:
    cur.execute("SELECT id, chamado_id, mensagem_id, nome, mime, tamanho, github_url, criado_em "
                "FROM sup_anexos WHERE chamado_id=%s ORDER BY id", (chamado_id,))
    return [{**a, "criado_em": iso(a["criado_em"])} for a in cur.fetchall()]


# ------------------------------------------------------------------ abrir
def criar(sessao: dict, payload: dict, esquema: str | None = None) -> dict:
    uid, nome, email = _quem(sessao)
    if not uid:
        raise DadoInvalido("Sessão sem usuário.")
    tipo = escolha(payload.get("tipo"), comum.TIPOS, "Tipo")
    grav = escolha(payload.get("gravidade"), comum.GRAVIDADES, "Gravidade")
    titulo = _texto(payload.get("titulo"), "o título", maximo=comum.TITULO_MAX, obrigatorio=True)
    descricao = _texto(payload.get("descricao"), "a descrição", maximo=comum.TEXTO_MAX, obrigatorio=True)
    ctx = payload.get("contexto") if isinstance(payload.get("contexto"), dict) else {}
    ctx = {k: (v if isinstance(v, (str, int, float, bool, list)) else str(v))
           for k, v in ctx.items() if k in ("tela", "tela_nome", "filtros", "url", "versao",
                                            "navegador", "tela_px", "erros")}
    if isinstance(ctx.get("erros"), list):
        ctx["erros"] = [str(e)[:500] for e in ctx["erros"][:10]]
    tela = str(ctx.get("tela") or "")[:40]
    anexos = comum.validar_anexos(payload.get("anexos"))
    canais = payload.get("canais") if isinstance(payload.get("canais"), dict) else {}
    avisar_email = 0 if canais.get("email") is False else 1
    avisar_whatsapp = 1 if canais.get("whatsapp") else 0
    esq = _esq(esquema)
    if avisar_whatsapp and not _telefone_do_usuario(uid, esq):
        raise DadoInvalido("Para receber aviso por WhatsApp, cadastre seu telefone em Minha conta.")
    ano = agora().astimezone().year
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            cid = None
            for tentativa in range(2):
                seq, codigo = _proximo_codigo(cur, ano)
                try:
                    cur.execute("SAVEPOINT sp_codigo")
                    cur.execute(
                        "INSERT INTO sup_chamados (ano, sequencia, codigo, usuario_id, usuario_nome, tipo, "
                        "gravidade, titulo, descricao, tela, contexto, status_por, avisar_email, "
                        "avisar_whatsapp) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ano, seq, codigo, uid, nome, tipo, grav, titulo, descricao, tela,
                         json.dumps(ctx, ensure_ascii=False), nome, avisar_email, avisar_whatsapp))
                    cid = int(cur.fetchone()["id"])
                    cur.execute("RELEASE SAVEPOINT sp_codigo")
                    break
                except pglocal.psycopg.errors.UniqueViolation:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_codigo")
                    if tentativa == 1:
                        raise DadoInvalido("Outro chamado foi aberto no mesmo instante. Tente de novo.")
            _anexos_inserir(cur, cid, None, anexos)
            _mensagem(cur, cid, "sistema", f"Chamado {codigo} aberto por {nome or 'usuário'}.",
                      evento="status", status_de="", status_para="aberto", origem="sistema")
            cur.execute("INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(%s,%s,%s,%s,%s,%s)",
                        (auth._agora(), email, "sup_abrir", codigo,
                         f"{tipo} · {grav} · tela {tela or '-'} · avisos: email={avisar_email} whatsapp={avisar_whatsapp}", ""))
    return obter(cid, esquema=esq, usuario_id=uid)


def _telefone_do_usuario(uid: int, esq) -> str:
    r = pglocal.um("SELECT telefone FROM usuarios WHERE id=%s", (uid,), esquema=esq)
    return (r or {}).get("telefone") or ""


# ------------------------------------------------------------------ ler
def obter(chamado_id: int, esquema: str | None = None, *, usuario_id: int | None = None,
          suporte: bool = False, hoje: datetime | None = None) -> dict | None:
    """Dono ou suporte; alheio devolve None (a rota transforma em 404)."""
    esq = _esq(esquema)
    cfg = comum.config(esq)
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            ch = _linha(cur, chamado_id)
            if not ch:
                return None
            if not suporte and (usuario_id is None or ch["usuario_id"] != usuario_id):
                return None
            msgs = _msgs(cur, chamado_id, incluir_internas=suporte)
            anexos = _anexos_meta(cur, chamado_id)
            avisos = []
            if suporte:
                cur.execute("SELECT id, mensagem_id, canal, lado, evento, destinatario, resultado, detalhe, "
                            "tentar_apos, criado_em FROM sup_avisos WHERE chamado_id=%s ORDER BY id DESC LIMIT 60",
                            (chamado_id,))
                avisos = [{**a, "criado_em": iso(a["criado_em"]), "tentar_apos": iso(a["tentar_apos"])}
                          for a in cur.fetchall()]
    d = _serializar(ch)
    d.update(derivados(ch, msgs, cfg, hoje))
    d["mensagens_lista"] = [{**m, "criado_em": iso(m["criado_em"]), "espelhada_em": iso(m["espelhada_em"]),
                             "interna": bool(m["interna"])} for m in msgs]
    d["anexos"] = anexos
    if suporte:
        d["avisos"] = avisos
    return d


def marcar_lido(chamado_id: int, papel: str, usuario_id: int | None, esquema: str | None = None) -> bool:
    esq = _esq(esquema)
    if papel == "usuario":
        n = pglocal.executar("UPDATE sup_chamados SET lido_usuario_em=now() WHERE id=%s AND usuario_id=%s",
                             (chamado_id, usuario_id), esquema=esq)
    else:
        n = pglocal.executar("UPDATE sup_chamados SET lido_suporte_em=now() WHERE id=%s", (chamado_id,), esquema=esq)
    return n > 0


def _kpis_pessoais(rows: list[dict], cfg: dict) -> dict:
    ativos = [r for r in rows if r["status"] in ATIVOS]
    return {
        "abertos": len(ativos),
        "aguardando_voce": sum(1 for r in rows if r["status"] in ("aguardando_usuario", "resolvido")),
        "novas": sum(r["novas_usuario"] for r in rows),
        "resolvidos_30d": sum(1 for r in rows if r["status"] in ("resolvido", "fechado")
                              and r["status_ha_h"] is not None and r["status_ha_h"] <= 30 * 24),
    }


def _listar(where: str, params: tuple, esq, suporte: bool, hoje=None) -> list[dict]:
    cfg = comum.config(esq)
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_CAMPOS} FROM sup_chamados WHERE {where} ORDER BY atualizado_em DESC LIMIT 500", params)
            chs = cur.fetchall()
            ids = [c["id"] for c in chs]
            por: dict[int, list] = {i: [] for i in ids}
            if ids:
                cur.execute("SELECT id, chamado_id, papel, interna, criado_em FROM sup_mensagens "
                            "WHERE chamado_id = ANY(%s) ORDER BY id", (ids,))
                for m in cur.fetchall():
                    por[m["chamado_id"]].append(m)
    out = []
    for ch in chs:
        d = _serializar(ch)
        d.pop("descricao", None)
        d.pop("contexto", None)
        d.update(derivados(ch, por[ch["id"]], cfg, hoje))
        out.append(d)
    return out


def listar_meus(usuario_id: int, situacao: str = "ativos", esquema: str | None = None, hoje=None) -> dict:
    esq = _esq(esquema)
    todos = _listar("usuario_id=%s", (usuario_id,), esq, suporte=False, hoje=hoje)
    if situacao == "ativos":
        sel = [c for c in todos if c["status"] in ATIVOS or c["status"] == "resolvido"]
    elif situacao == "encerrados":
        sel = [c for c in todos if c["status"] == "fechado"]
    else:
        sel = todos
    cfg = comum.config(esq)
    return {"chamados": sel, "total": len(todos), "kpis": _kpis_pessoais(todos, cfg),
            "primeira_resposta_mediana_h": _mediana_primeira_resposta(esq),
            "sla": {g: comum.sla_horas(cfg, g) for g in comum.GRAVIDADES}}


def _mediana_primeira_resposta(esq, dias: int = 30) -> dict:
    rows = pglocal.query(
        "SELECT c.id, c.criado_em, min(m.criado_em) AS primeira FROM sup_chamados c "
        "LEFT JOIN sup_mensagens m ON m.chamado_id=c.id AND m.papel='suporte' AND m.interna=0 "
        "WHERE c.criado_em >= now() - (%s || ' days')::interval GROUP BY c.id, c.criado_em", (str(dias),), esquema=esq)
    horas = sorted(_h(r["criado_em"], r["primeira"]) for r in rows if r["primeira"] is not None)
    if not horas:
        return {"n": 0, "sem_resposta": len(rows), "mediana_h": None, "p90_h": None}
    k = int(0.5 * (len(horas) - 1) + 0.5)
    k9 = int(0.9 * (len(horas) - 1) + 0.5)
    return {"n": len(horas), "sem_resposta": len(rows) - len(horas),
            "mediana_h": horas[k], "p90_h": horas[k9]}


# ------------------------------------------------------------------ escrever
def _abrir_tx(esq):
    return pglocal.get_conn(esq)


def responder(chamado_id: int, sessao: dict, papel: str, texto: str, anexos=None, *,
              interna: bool = False, esquema: str | None = None) -> dict:
    """Mensagem humana. Dono em aguardando_usuario devolve o chamado ao suporte.
    Devolve {"mensagem_id", "chamado", "eventos": [...]} para os avisos."""
    uid, nome, email = _quem(sessao)
    t = _texto(texto, "a mensagem", maximo=comum.TEXTO_MAX, obrigatorio=True)
    anexos = comum.validar_anexos(anexos)
    if interna and papel != "suporte":
        raise DadoInvalido("Só o suporte escreve nota interna.")
    esq = _esq(esquema)
    eventos = []
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            ch = _linha(cur, chamado_id)
            if not ch or (papel == "usuario" and ch["usuario_id"] != uid):
                return {}
            if ch["status"] == "fechado":
                raise TransicaoInvalida("Este chamado está encerrado — reabra antes de responder.")
            mid = _mensagem(cur, chamado_id, papel, t, autor_id=uid, autor_nome=nome, interna=1 if interna else 0)
            _anexos_inserir(cur, chamado_id, mid, anexos)
            if papel == "usuario" and ch["status"] == "aguardando_usuario":
                comum.transicao("aguardando_usuario", "em_atendimento", "usuario")
                cur.execute("UPDATE sup_chamados SET status='em_atendimento', status_em=now(), status_por=%s WHERE id=%s",
                            (nome, chamado_id))
                _mensagem(cur, chamado_id, "sistema", "Resposta recebida — de volta ao suporte.",
                          evento="status", status_de="aguardando_usuario", status_para="em_atendimento", origem="sistema")
                eventos.append("de_volta_ao_suporte")
            if papel == "suporte" and ch["status"] == "aberto" and not interna:
                cur.execute("UPDATE sup_chamados SET status='em_atendimento', status_em=now(), status_por=%s, "
                            "atribuido_id=coalesce(atribuido_id,%s), atribuido_nome=CASE WHEN atribuido_nome='' THEN %s ELSE atribuido_nome END WHERE id=%s",
                            (nome, uid, nome, chamado_id))
                _mensagem(cur, chamado_id, "sistema", f"Em atendimento por {nome}.",
                          evento="status", status_de="aberto", status_para="em_atendimento", origem="sistema")
                eventos.append("em_atendimento")
            if papel == "suporte":
                cur.execute("UPDATE sup_chamados SET lido_suporte_em=now() WHERE id=%s", (chamado_id,))
            else:
                cur.execute("UPDATE sup_chamados SET lido_usuario_em=now() WHERE id=%s", (chamado_id,))
            cur.execute("INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(%s,%s,%s,%s,%s,%s)",
                        (auth._agora(), email, "sup_responder", ch["codigo"],
                         f"{papel}{' · nota interna' if interna else ''} · {len(anexos)} anexo(s)", ""))
    eventos.append("nota_interna" if interna else ("resposta_suporte" if papel == "suporte" else "resposta_usuario"))
    return {"mensagem_id": mid, "chamado_id": chamado_id, "eventos": eventos}


def mudar_status(chamado_id: int, sessao: dict, papel: str, para: str, *, texto: str = "",
                 motivo: str = "", avaliacao=None, esquema: str | None = None) -> dict:
    uid, nome, email = _quem(sessao)
    para = escolha(para, comum.STATUS, "Status")
    t = _texto(texto, "o texto", maximo=comum.TEXTO_MAX)
    motivo = escolha(motivo, comum.MOTIVOS_FECHAMENTO, "Motivo", padrao="")
    esq = _esq(esquema)
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            ch = _linha(cur, chamado_id)
            if not ch or (papel == "usuario" and ch["usuario_id"] != uid):
                return {}
            de = ch["status"]
            comum.transicao(de, para, papel, texto=t, motivo=motivo)
            mid = None
            if t:
                mid = _mensagem(cur, chamado_id, papel, t, autor_id=uid, autor_nome=nome)
            frase = {
                "em_atendimento": f"Em atendimento por {nome}.",
                "aguardando_usuario": f"{nome} precisa de uma resposta sua.",
                "resolvido": f"Marcado como resolvido por {nome} — confirme se resolveu.",
                "fechado": ("Encerrado por " + nome + (" — " + comum.ROTULO_MOTIVO.get(motivo, motivo) if motivo else "")),
                "aberto": f"Reaberto por {nome}.",
            }[para]
            _mensagem(cur, chamado_id, "sistema", frase, evento="status", status_de=de, status_para=para, origem="sistema")
            extra = ""
            if para == "em_atendimento" and papel == "suporte":
                extra = ", atribuido_id=%s, atribuido_nome=%s"
            campos = ["status=%s", "status_em=now()", "status_por=%s", "motivo_fechamento=%s"]
            params = [para, nome, motivo if para == "fechado" else ""]
            if para == "em_atendimento" and papel == "suporte":
                campos += ["atribuido_id=%s", "atribuido_nome=%s"]
                params += [uid, nome]
            if para == "fechado" and papel == "usuario" and de == "resolvido" and avaliacao is not None:
                try:
                    nota = int(avaliacao)
                except (TypeError, ValueError):
                    raise DadoInvalido("A avaliação vai de 1 a 5.") from None
                if not 1 <= nota <= 5:
                    raise DadoInvalido("A avaliação vai de 1 a 5.")
                campos += ["avaliacao=%s"]
                params += [nota]
            if papel == "suporte":
                campos += ["lido_suporte_em=now()"]
            else:
                campos += ["lido_usuario_em=now()"]
            params.append(chamado_id)
            cur.execute(f"UPDATE sup_chamados SET {', '.join(campos)} WHERE id=%s", params)
            cur.execute("INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(%s,%s,%s,%s,%s,%s)",
                        (auth._agora(), email, "sup_status", ch["codigo"], f"{de} → {para} · {papel}"
                         + (f" · {motivo}" if motivo else ""), ""))
    return {"chamado_id": chamado_id, "mensagem_id": mid, "de": de, "para": para,
            "eventos": [f"status_{para}"]}


def assumir(chamado_id: int, sessao: dict, atribuido_id: int | None = None, esquema: str | None = None) -> dict:
    uid, nome, email = _quem(sessao)
    esq = _esq(esquema)
    alvo_id, alvo_nome = uid, nome
    if atribuido_id and int(atribuido_id) != uid:
        u = pglocal.um("SELECT id, nome FROM usuarios WHERE id=%s AND ativo=1", (int(atribuido_id),), esquema=esq)
        if not u:
            raise DadoInvalido("Atendente não encontrado.")
        alvo_id, alvo_nome = u["id"], u["nome"]
    eventos = []
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            ch = _linha(cur, chamado_id)
            if not ch:
                return {}
            if ch["status"] == "fechado":
                raise TransicaoInvalida("Este chamado está encerrado — reabra antes de assumir.")
            de = ch["status"]
            para = "em_atendimento" if de in ("aberto",) else de
            cur.execute("UPDATE sup_chamados SET atribuido_id=%s, atribuido_nome=%s, status=%s, "
                        "status_em=CASE WHEN status<>%s THEN now() ELSE status_em END, status_por=%s, lido_suporte_em=now() WHERE id=%s",
                        (alvo_id, alvo_nome, para, para, nome, chamado_id))
            _mensagem(cur, chamado_id, "sistema",
                      f"Assumido por {alvo_nome}." if alvo_id == uid else f"Atribuído a {alvo_nome} por {nome}.",
                      evento="atribuicao", status_de=de, status_para=para, origem="sistema")
            if para != de:
                eventos.append("status_em_atendimento")
            cur.execute("INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(%s,%s,%s,%s,%s,%s)",
                        (auth._agora(), email, "sup_assumir", ch["codigo"], f"para {alvo_nome}", ""))
    return {"chamado_id": chamado_id, "eventos": eventos}


def avaliar(chamado_id: int, sessao: dict, nota, texto: str = "", esquema: str | None = None) -> dict:
    uid, nome, email = _quem(sessao)
    try:
        n = int(nota)
    except (TypeError, ValueError):
        raise DadoInvalido("A avaliação vai de 1 a 5.") from None
    if not 1 <= n <= 5:
        raise DadoInvalido("A avaliação vai de 1 a 5.")
    t = _texto(texto, "o comentário", maximo=1000)
    esq = _esq(esquema)
    with pglocal.get_conn(esq) as conn:
        with conn.cursor() as cur:
            ch = _linha(cur, chamado_id)
            if not ch or ch["usuario_id"] != uid:
                return {}
            if ch["status"] not in ("resolvido", "fechado"):
                raise TransicaoInvalida("Avalie depois que o chamado for resolvido.")
            cur.execute("UPDATE sup_chamados SET avaliacao=%s, avaliacao_texto=%s, atualizado_em=now() WHERE id=%s",
                        (n, t, chamado_id))
            _mensagem(cur, chamado_id, "sistema", f"Avaliação {n}/5" + (f": {t}" if t else ""),
                      evento="avaliacao", origem="sistema")
            cur.execute("INSERT INTO audit_log(ts, usuario, acao, alvo, detalhe, ip) VALUES(%s,%s,%s,%s,%s,%s)",
                        (auth._agora(), email, "sup_avaliar", ch["codigo"], f"{n}/5", ""))
    return {"chamado_id": chamado_id, "eventos": ["avaliacao"] if n <= 2 else []}


def canais(chamado_id: int, sessao: dict, dados: dict, esquema: str | None = None) -> dict:
    """Edição parcial: chave ausente = não mexe."""
    uid, nome, email = _quem(sessao)
    esq = _esq(esquema)
    campos, params = [], []
    if "email" in dados:
        campos.append("avisar_email=%s"); params.append(1 if dados["email"] else 0)
    if "whatsapp" in dados:
        if dados["whatsapp"] and not _telefone_do_usuario(uid, esq):
            raise DadoInvalido("Para receber aviso por WhatsApp, cadastre seu telefone em Minha conta.")
        campos.append("avisar_whatsapp=%s"); params.append(1 if dados["whatsapp"] else 0)
    if not campos:
        return {"chamado_id": chamado_id}
    params += [chamado_id, uid]
    n = pglocal.executar(f"UPDATE sup_chamados SET {', '.join(campos)} WHERE id=%s AND usuario_id=%s", params, esquema=esq)
    if not n:
        return {}
    return {"chamado_id": chamado_id}


# ------------------------------------------------------------------ atendimento
def listar_fila(filtros: dict | None = None, esquema: str | None = None, hoje=None) -> dict:
    f = filtros or {}
    esq = _esq(esquema)
    where, params = ["1=1"], []
    if f.get("status"):
        where.append("status=%s"); params.append(escolha(f["status"], comum.STATUS, "Status"))
    elif not f.get("fechados"):
        where.append("status<>'fechado'")
    if f.get("gravidade"):
        where.append("gravidade=%s"); params.append(escolha(f["gravidade"], comum.GRAVIDADES, "Gravidade"))
    if f.get("tela"):
        where.append("tela=%s"); params.append(str(f["tela"])[:40])
    if f.get("usuario_id"):
        where.append("usuario_id=%s"); params.append(int(f["usuario_id"]))
    if f.get("atribuido_id"):
        where.append("atribuido_id=%s"); params.append(int(f["atribuido_id"]))
    if f.get("busca"):
        where.append("(codigo ILIKE %s OR titulo ILIKE %s OR usuario_nome ILIKE %s)")
        b = f"%{str(f['busca']).strip()}%"; params += [b, b, b]
    rows = _listar(" AND ".join(where), tuple(params), esq, suporte=True, hoje=hoje)
    # prioridade só para ORDENAR (nunca gravada): bola com o suporte, SLA estourado, gravidade, idade
    peso_g = {"alta": 0, "media": 1, "baixa": 2}
    rows.sort(key=lambda c: (0 if c["esperando"] == "suporte" else 1, 0 if c["sla_estourado"] else 1,
                             peso_g.get(c["gravidade"], 3), -(c["horas_sem_resposta"] or 0), -(c["idade_h"] or 0)))
    total = pglocal.um("SELECT count(*) AS n FROM sup_chamados", esquema=esq)["n"]
    return {"chamados": rows, "mostrando": len(rows), "total": total}


def kpis_time(esquema: str | None = None, hoje=None) -> dict:
    esq = _esq(esquema)
    rows = _listar("status<>'fechado'", (), esq, suporte=True, hoje=hoje)
    med = _mediana_primeira_resposta(esq)
    aval = pglocal.um("SELECT avg(avaliacao)::float8 AS media, count(avaliacao)::int AS n FROM sup_chamados "
                      "WHERE avaliacao IS NOT NULL AND criado_em >= now() - interval '30 days'", esquema=esq) or {}
    return {
        "abertos": len(rows),
        "com_suporte": sum(1 for r in rows if r["esperando"] == "suporte"),
        "sla_estourados": sum(1 for r in rows if r["sla_estourado"]),
        "aguardando_usuario": sum(1 for r in rows if r["status"] == "aguardando_usuario"),
        "resolvidos_a_confirmar": sum(1 for r in rows if r["status"] == "resolvido"),
        "sem_atendente": sum(1 for r in rows if r["esperando"] == "suporte" and not r["atribuido_id"]),
        "novas_para_suporte": sum(r["novas_suporte"] for r in rows),
        "primeira_resposta": med,
        "avaliacao_media": aval.get("media"), "avaliacoes": aval.get("n") or 0,
        "espelho_com_erro": sum(1 for r in rows if r.get("github_erro")),
    }


def indicadores(dias: int = 90, esquema: str | None = None, hoje=None) -> dict:
    esq = _esq(esquema)
    t = hoje or agora()
    dias = max(7, min(365, int(dias or 90)))
    ini = t - timedelta(days=dias)
    rows = pglocal.query(f"SELECT {_CAMPOS} FROM sup_chamados WHERE criado_em >= %s", (ini,), esquema=esq)
    # semanas GERADAS: semana sem chamado aparece com zero, a corrente marcada parcial
    semanas = []
    inicio_sem = (t - timedelta(days=t.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    n_sem = max(4, min(26, dias // 7))
    for i in range(n_sem - 1, -1, -1):
        s0 = inicio_sem - timedelta(weeks=i); s1 = s0 + timedelta(weeks=1)
        semanas.append({"semana": s0.date().isoformat(),
                        "abertos": sum(1 for r in rows if s0 <= r["criado_em"] < s1),
                        "resolvidos": sum(1 for r in rows if r["status"] in ("resolvido", "fechado")
                                          and r["status_em"] is not None and s0 <= r["status_em"] < s1),
                        "parcial": i == 0})
    por = lambda campo: sorted(  # noqa: E731
        ({"chave": k, "n": sum(1 for r in rows if (r[campo] or "") == k)} for k in {(r[campo] or "") for r in rows}),
        key=lambda x: -x["n"])
    med = _mediana_primeira_resposta(esq, dias)
    resolucao = sorted(_h(r["criado_em"], r["status_em"]) for r in rows if r["status"] in ("resolvido", "fechado"))
    k = int(0.5 * (len(resolucao) - 1) + 0.5) if resolucao else 0
    aval = [r["avaliacao"] for r in rows if r["avaliacao"]]
    return {
        "dias": dias, "total": len(rows), "semanas": semanas,
        "por_tipo": por("tipo"), "por_gravidade": por("gravidade"),
        "por_tela": por("tela")[:10], "por_tela_total": len({(r["tela"] or "") for r in rows}),
        "primeira_resposta": med,
        "resolucao_mediana_h": resolucao[k] if resolucao else None, "resolvidos": len(resolucao),
        "avaliacao_media": (sum(aval) / len(aval)) if aval else None, "avaliacoes": len(aval),
    }


def resumo(esquema: str | None = None) -> dict:
    """Só escalares — vai ao Copiloto (modelo externo): nada de título, nome, e-mail."""
    k = kpis_time(esquema)
    ind = indicadores(30, esquema)
    return {
        "abertos": k["abertos"], "com_suporte": k["com_suporte"], "sla_estourados": k["sla_estourados"],
        "aguardando_usuario": k["aguardando_usuario"], "sem_atendente": k["sem_atendente"],
        "resolvidos_30d": ind["resolvidos"], "abertos_30d": ind["total"],
        "primeira_resposta_mediana_h_30d": k["primeira_resposta"]["mediana_h"],
        "primeira_resposta_n_30d": k["primeira_resposta"]["n"],
        "avaliacao_media_30d": k["avaliacao_media"], "avaliacoes_30d": k["avaliacoes"],
        "por_tipo_30d": {x["chave"]: x["n"] for x in ind["por_tipo"]},
        "espelho_com_erro": k["espelho_com_erro"],
    }


def diagnostico(esquema: str | None = None) -> dict:
    """O que a Saúde mede: só banco local, sem rede."""
    esq = _esq(esquema)
    try:
        k = kpis_time(esq)
        ultimo = pglocal.um("SELECT max(criado_em) AS em FROM sup_avisos WHERE resultado='enviado'", esquema=esq) or {}
        adiados = pglocal.um("SELECT count(*) AS n, min(tentar_apos) AS mais_antigo FROM sup_avisos "
                             "WHERE resultado='adiado' AND tentar_apos < now() - interval '4 hours'", esquema=esq) or {}
        gh = pglocal.um("SELECT resultado, detalhe, criado_em FROM sup_avisos WHERE canal='github' ORDER BY id DESC LIMIT 1",
                        esquema=esq)
        return {"ok": True, "kpis": k, "ultimo_aviso_em": iso(ultimo.get("em")),
                "adiados_vencidos": adiados.get("n") or 0,
                "github_ultimo": ({**gh, "criado_em": iso(gh["criado_em"])} if gh else None)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "sem_tabela": pglocal.sem_tabela(exc), "erro": type(exc).__name__}


def anexo(anexo_id: int, esquema: str | None = None, *, usuario_id: int | None = None,
          suporte: bool = False) -> dict | None:
    esq = _esq(esquema)
    r = pglocal.um("SELECT a.id, a.nome, a.mime, a.tamanho, a.bytes, a.criado_em, c.usuario_id "
                   "FROM sup_anexos a JOIN sup_chamados c ON c.id=a.chamado_id WHERE a.id=%s", (anexo_id,), esquema=esq)
    if not r:
        return None
    if not suporte and (usuario_id is None or r["usuario_id"] != usuario_id):
        return None
    return {"id": r["id"], "nome": r["nome"], "mime": r["mime"], "tamanho": r["tamanho"],
            "bytes": bytes(r["bytes"]), "criado_em": iso(r["criado_em"])}


def atendentes(esquema: str | None = None) -> list[dict]:
    """Usuários ativos com a tela `supfila` ou administradores."""
    esq = _esq(esquema)
    return pglocal.query(
        "SELECT DISTINCT u.id, u.nome FROM usuarios u JOIN perfis p ON p.id=u.perfil_id "
        "LEFT JOIN perfil_telas pt ON pt.perfil_id=p.id AND pt.tela='supfila' "
        "WHERE u.ativo=1 AND (p.admin=1 OR pt.tela IS NOT NULL) ORDER BY u.nome", esquema=esq)
