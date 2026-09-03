"""Avisos: cada tentativa deixa UMA das três respostas na trilha (CLAUDE.md §7):

    enviado    mandou (com o id da trilha do canal)
    sem_canal  calou porque não havia o que mandar: canal não marcado, sem
               telefone, sem inscrição de push, SMTP/Z-API não configurados,
               a pessoa já leu, já foi avisada e ainda não abriu
    recusado   tentou e o canal disse não (freio, modelo desligado, erro)
    adiado     WhatsApp fora da janela — sai na próxima passagem

O aviso lê o chamado NA HORA DO ENVIO (frescor antes do conteúdo) e nunca
levanta: falha de canal é linha na trilha, não 500. Nada aqui dispara coleta
externa; o WhatsApp e o e-mail passam pelos caminhos normais da casa (freio,
janela, trilha própria). O sino é DERIVADO — não passa por esta tabela.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from .. import pglocal, push
from . import comum
from .comum import _esq, iso, mascarar_email, mascarar_telefone

log = logging.getLogger("cortex.suporte.avisos")

FRASES = {
    "em_atendimento": "alguém do suporte assumiu",
    "resposta_suporte": "nova resposta do suporte",
    "status_aguardando_usuario": "o suporte precisa de uma resposta sua",
    "status_resolvido": "marcado como resolvido — confirme se resolveu",
    "status_fechado": "encerrado pelo suporte",
    "status_aberto": "reaberto",
    "status_em_atendimento": "em atendimento",
    "resposta_usuario": "quem abriu respondeu",
    "de_volta_ao_suporte": "quem abriu respondeu — de volta ao suporte",
    "avaliacao": "avaliação baixa recebida",
    "aberto": "chamado novo",
}
_AO_USUARIO = {"em_atendimento", "resposta_suporte", "status_aguardando_usuario", "status_resolvido",
               "status_fechado", "status_aberto", "status_em_atendimento"}
_AO_TIME = {"aberto", "resposta_usuario", "de_volta_ao_suporte", "avaliacao"}


def link_chamado(chamado_id: int) -> str:
    from ..whatsapp import valores
    return f"{valores.URL_PAINEL}/#sup?chamado={chamado_id}"


def _registrar(esq, chamado_id, mensagem_id, canal, lado, evento, destinatario, resultado, detalhe="",
               trilha_id=None, tentar_apos=None) -> int:
    r = pglocal.um(
        "INSERT INTO sup_avisos (chamado_id, mensagem_id, canal, lado, evento, destinatario, resultado, detalhe, "
        "trilha_id, tentar_apos) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (chamado_id, mensagem_id, canal, lado, evento, destinatario, resultado, (detalhe or "")[:400],
         trilha_id, tentar_apos), esquema=esq)
    return int(r["id"]) if r else 0


# ---------------------------------------------------------------- canais
class Canais:
    """Ponto único de injeção: os testes trocam cada canal por um dublê."""

    @staticmethod
    def email(dests: list[str], assunto: str, corpo: str, corpo_html: str) -> dict:
        from ..correio import envio
        return envio.enviar(dests, assunto, corpo, corpo_html=corpo_html, usuario="suporte", origem="suporte")

    @staticmethod
    def email_configurado() -> bool:
        from ..correio import config as ccfg
        return ccfg.configurado()

    @staticmethod
    def whatsapp(telefone: str, chave: str, valores: dict, instancia: str | None) -> dict:
        from ..whatsapp import envio
        return envio.enviar_modelo([telefone], chave, valores, usuario="suporte", origem="suporte",
                                   instancia=instancia or None)

    @staticmethod
    def whatsapp_pronto() -> tuple[bool, str]:
        from ..whatsapp import cliente, config as wcfg
        if not cliente.configurado():
            return False, "WhatsApp não configurado neste servidor"
        try:
            st = wcfg.ler()
        except Exception:  # noqa: BLE001
            st = {}
        if st.get("ativo") in (0, False, "0"):
            return False, "envio de WhatsApp desligado em Gestão"
        return True, ""

    @staticmethod
    def whatsapp_na_janela() -> tuple[bool, datetime | None]:
        from ..whatsapp import config as wcfg
        try:
            if wcfg.dentro_da_janela():
                return True, None
            c = wcfg.ler()
            hh, mm = (str(c.get("janela_inicio") or "08:00")).split(":")
            hoje = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            prox = hoje if hoje > datetime.now() else hoje + timedelta(days=1)
            return False, prox.astimezone()
        except Exception:  # noqa: BLE001
            return True, None

    @staticmethod
    def push(titulo: str, corpo: str, url: str, subs: list[dict]) -> int:
        return push.send_push(titulo, corpo, url, subs)

    @staticmethod
    def push_subs(email: str) -> list[dict]:
        if not push.habilitado():
            return []
        return push.subs_do_usuario(email)


def _usuario(uid, esq) -> dict:
    return pglocal.um("SELECT id, nome, email, telefone, ativo FROM usuarios WHERE id=%s", (uid,), esquema=esq) or {}


def _ja_avisado_sem_ler(esq, chamado_id: int, canal: str, lido_em) -> bool:
    """Já saiu um aviso 'enviado' neste canal depois da última leitura?"""
    r = pglocal.um("SELECT max(criado_em) AS em FROM sup_avisos WHERE chamado_id=%s AND canal=%s "
                   "AND lado='usuario' AND resultado='enviado'", (chamado_id, canal), esquema=esq) or {}
    em = r.get("em")
    return bool(em and (lido_em is None or em > lido_em))


def _corpo_email(ch: dict, evento: str, texto: str) -> tuple[str, str, str]:
    from ..correio import painel as p
    frase = FRASES.get(evento, evento)
    assunto = f"[CÓRTEX] {ch['codigo']} — {frase}"
    link = link_chamado(ch["id"])
    linhas = [f"Chamado {ch['codigo']}: {ch['titulo']}", "", f"Novidade: {frase}.", ""]
    if texto:
        linhas += ["Mensagem do suporte:", "", texto, ""]
    linhas += [f"Veja e responda pelo painel: {link}", "",
               "Este e-mail não recebe resposta — responda pelo painel.", "", "— CÓRTEX · Sulista"]
    corpo = "\n".join(linhas)
    blocos = [p.cabecalho(f"Chamado {ch['codigo']}", frase),
              p.campos([("Assunto", ch["titulo"]), ("Status", comum.ROTULO_STATUS.get(ch["status"], ch["status"]))])]
    if texto:
        blocos.append(p.secao("Mensagem do suporte"))
        blocos.append(p.paragrafo(texto))
    blocos.append(p.botao("Abrir o chamado", link))
    blocos.append(p.paragrafo("Este e-mail não recebe resposta — responda pelo painel."))
    try:
        html = p.documento(f"Chamado {ch['codigo']}", blocos, subtitulo=frase)
    except TypeError:
        html = p.documento(f"Chamado {ch['codigo']}", blocos)
    return assunto, corpo, html


def avisar(chamado_id: int, evento: str, *, mensagem_id: int | None = None, texto: str = "",
           esquema: str | None = None, canais: type = Canais) -> list[dict]:
    """Dispara os avisos de UM evento e devolve as linhas gravadas. Nunca levanta."""
    esq = _esq(esquema)
    out = []
    try:
        ch = pglocal.um("SELECT id, codigo, titulo, status, usuario_id, avisar_email, avisar_whatsapp, "
                        "lido_usuario_em, atribuido_id, gravidade FROM sup_chamados WHERE id=%s", (chamado_id,), esquema=esq)
        if not ch:
            return out
        cfg = comum.config(esq)
        if evento in _AO_USUARIO:
            out += _avisar_usuario(esq, ch, evento, mensagem_id, texto, cfg, canais)
        if evento in _AO_TIME:
            out += _avisar_time(esq, ch, evento, mensagem_id, texto, cfg, canais)
    except Exception as exc:  # noqa: BLE001
        log.warning("suporte avisos %s: %s", evento, type(exc).__name__)
    return out


def _avisar_usuario(esq, ch, evento, mensagem_id, texto, cfg, canais) -> list[dict]:
    out = []
    u = _usuario(ch["usuario_id"], esq)
    lado = "usuario"
    # frescor: se a pessoa já abriu a conversa depois do evento, cala
    lido = ch.get("lido_usuario_em")
    if mensagem_id and lido is not None:
        m = pglocal.um("SELECT criado_em FROM sup_mensagens WHERE id=%s", (mensagem_id,), esquema=esq)
        if m and m["criado_em"] <= lido:
            for canal in ("email", "whatsapp", "push"):
                out.append(_registrar(esq, ch["id"], mensagem_id, canal, lado, evento, "", "sem_canal",
                                      "já abriu a conversa depois deste evento"))
            return out
    # ---- e-mail
    email = (u.get("email") or "").strip()
    if not ch.get("avisar_email"):
        out.append(_registrar(esq, ch["id"], mensagem_id, "email", lado, evento, mascarar_email(email), "sem_canal", "canal não escolhido no chamado"))
    elif not email:
        out.append(_registrar(esq, ch["id"], mensagem_id, "email", lado, evento, "", "sem_canal", "sem e-mail no cadastro"))
    elif not canais.email_configurado():
        out.append(_registrar(esq, ch["id"], mensagem_id, "email", lado, evento, mascarar_email(email), "sem_canal", "e-mail não configurado em Gestão"))
    elif _ja_avisado_sem_ler(esq, ch["id"], "email", lido):
        out.append(_registrar(esq, ch["id"], mensagem_id, "email", lado, evento, mascarar_email(email), "sem_canal", "já avisado por e-mail e ainda não abriu"))
    else:
        assunto, corpo, html = _corpo_email(ch, evento, texto)
        r = canais.email([email], assunto, corpo, html)
        if r.get("ok"):
            out.append(_registrar(esq, ch["id"], mensagem_id, "email", lado, evento, mascarar_email(email), "enviado", "", r.get("id")))
        else:
            out.append(_registrar(esq, ch["id"], mensagem_id, "email", lado, evento, mascarar_email(email), "recusado", r.get("erro") or "falha no envio"))
    # ---- WhatsApp
    tel = (u.get("telefone") or "").strip()
    if not ch.get("avisar_whatsapp"):
        out.append(_registrar(esq, ch["id"], mensagem_id, "whatsapp", lado, evento, mascarar_telefone(tel), "sem_canal", "canal não escolhido no chamado"))
    elif not tel:
        out.append(_registrar(esq, ch["id"], mensagem_id, "whatsapp", lado, evento, "", "sem_canal", "sem telefone no cadastro"))
    else:
        pronto, motivo = canais.whatsapp_pronto()
        if not pronto:
            out.append(_registrar(esq, ch["id"], mensagem_id, "whatsapp", lado, evento, mascarar_telefone(tel), "sem_canal", motivo))
        elif _ja_avisado_sem_ler(esq, ch["id"], "whatsapp", lido):
            out.append(_registrar(esq, ch["id"], mensagem_id, "whatsapp", lado, evento, mascarar_telefone(tel), "sem_canal", "já avisado por WhatsApp e ainda não abriu"))
        else:
            na_janela, prox = canais.whatsapp_na_janela()
            if not na_janela:
                # UMA linha adiada por chamado: a novidade seguinte substitui
                pglocal.executar("DELETE FROM sup_avisos WHERE chamado_id=%s AND canal='whatsapp' AND resultado='adiado'",
                                 (ch["id"],), esquema=esq)
                out.append(_registrar(esq, ch["id"], mensagem_id, "whatsapp", lado, evento, mascarar_telefone(tel), "adiado",
                                      "fora da janela de envio — sai na próxima passagem", None, prox))
            else:
                out.append(_enviar_whatsapp(esq, ch, u, evento, mensagem_id, tel, cfg, canais))
    # ---- push
    subs = canais.push_subs(email) if email else []
    if not subs:
        out.append(_registrar(esq, ch["id"], mensagem_id, "push", lado, evento, "", "sem_canal",
                              "sem inscrição de push" if push.habilitado() else "push não configurado"))
    else:
        try:
            n = canais.push(f"CÓRTEX · {ch['codigo']}", FRASES.get(evento, evento), f"/#sup?chamado={ch['id']}", subs)
            out.append(_registrar(esq, ch["id"], mensagem_id, "push", lado, evento, f"{len(subs)} aparelho(s)",
                                  "enviado" if n else "recusado", "" if n else "nenhum aparelho aceitou"))
        except Exception as exc:  # noqa: BLE001
            out.append(_registrar(esq, ch["id"], mensagem_id, "push", lado, evento, f"{len(subs)} aparelho(s)", "recusado", type(exc).__name__))
    return out


def _enviar_whatsapp(esq, ch, u, evento, mensagem_id, tel, cfg, canais) -> int:
    primeiro = ((u.get("nome") or "").strip().split(" ") or [""])[0].title() or "tudo bem"
    valores = {"nome": comum.sem_chaves(primeiro), "numero": ch["codigo"],
               "evento": FRASES.get(evento, evento), "link": link_chamado(ch["id"])}
    r = canais.whatsapp(tel, cfg.get("modelo_zap") or "suporte-aviso", valores, cfg.get("instancia_zap") or None)
    if r.get("ok") and (r.get("enviados") or 0) > 0:
        res = (r.get("resultados") or [{}])[0]
        return _registrar(esq, ch["id"], mensagem_id, "whatsapp", "usuario", evento, mascarar_telefone(tel), "enviado", "",
                          res.get("trilha_id") or res.get("id"))
    erro = r.get("erro") or ((r.get("resultados") or [{}])[0].get("erro")) or "recusado pelo canal"
    resultado = "sem_canal" if re.search(r"desligad|não existe|nao existe", str(erro), re.I) else "recusado"
    return _registrar(esq, ch["id"], mensagem_id, "whatsapp", "usuario", evento, mascarar_telefone(tel), resultado, str(erro))


def _avisar_time(esq, ch, evento, mensagem_id, texto, cfg, canais) -> list[dict]:
    out = []
    dests = []
    if cfg.get("avisar_equipe_email", "1") == "1" and cfg.get("email_equipe"):
        from ..correio import config as ccfg
        dests = ccfg.separar_destinatarios(cfg["email_equipe"])
    if ch.get("atribuido_id"):
        a = _usuario(ch["atribuido_id"], esq)
        if a.get("email"):
            dests.append(a["email"])
    dests = list(dict.fromkeys(d for d in dests if d))
    if not dests:
        out.append(_registrar(esq, ch["id"], mensagem_id, "email", "suporte", evento, "", "sem_canal",
                              "e-mail da equipe não configurado"))
        return out
    if not canais.email_configurado():
        out.append(_registrar(esq, ch["id"], mensagem_id, "email", "suporte", evento, "equipe", "sem_canal",
                              "e-mail não configurado em Gestão"))
        return out
    frase = FRASES.get(evento, evento)
    assunto = f"[CÓRTEX suporte] {ch['codigo']} — {frase}"
    link = f"{link_chamado(0).split('#')[0]}#supfila?chamado={ch['id']}"
    corpo = "\n".join([f"Chamado {ch['codigo']} ({ch['gravidade']}): {ch['titulo']}", "", f"{frase}.", ""]
                      + ([texto, ""] if texto else []) + [f"Fila: {link}"])
    r = canais.email(dests, assunto, corpo, "")
    out.append(_registrar(esq, ch["id"], mensagem_id, "email", "suporte", evento, "equipe (" + str(len(dests)) + ")",
                          "enviado" if r.get("ok") else "recusado", "" if r.get("ok") else (r.get("erro") or "")))
    return out


def despachar_adiados(esquema: str | None = None, canais: type = Canais, agora: datetime | None = None) -> list[dict]:
    """Drena os WhatsApp adiados cujo horário chegou. Chamado pela passagem
    agendada de WhatsApp e ao abrir a Fila. Idempotente: a linha adiada é
    consumida (apagada) e substituída pelo resultado."""
    esq = _esq(esquema)
    out = []
    t = agora or datetime.now().astimezone()
    try:
        pend = pglocal.query("SELECT id, chamado_id, mensagem_id, evento FROM sup_avisos WHERE resultado='adiado' "
                             "AND (tentar_apos IS NULL OR tentar_apos <= %s) ORDER BY id", (t,), esquema=esq)
    except Exception as exc:  # noqa: BLE001
        log.warning("suporte despachar_adiados: %s", type(exc).__name__)
        return out
    if not pend:
        return out
    cfg = comum.config(esq)
    for a in pend:
        ch = pglocal.um("SELECT id, codigo, titulo, status, usuario_id, avisar_email, avisar_whatsapp, lido_usuario_em, "
                        "atribuido_id, gravidade FROM sup_chamados WHERE id=%s", (a["chamado_id"],), esquema=esq)
        pglocal.executar("DELETE FROM sup_avisos WHERE id=%s", (a["id"],), esquema=esq)
        if not ch:
            continue
        u = _usuario(ch["usuario_id"], esq)
        tel = (u.get("telefone") or "").strip()
        if ch["status"] == "fechado" or not ch.get("avisar_whatsapp") or not tel:
            out.append(_registrar(esq, ch["id"], a["mensagem_id"], "whatsapp", "usuario", a["evento"], mascarar_telefone(tel),
                                  "sem_canal", "chamado encerrado ou canal desligado antes de sair"))
            continue
        if _ja_avisado_sem_ler(esq, ch["id"], "whatsapp", ch.get("lido_usuario_em")):
            out.append(_registrar(esq, ch["id"], a["mensagem_id"], "whatsapp", "usuario", a["evento"], mascarar_telefone(tel),
                                  "sem_canal", "já avisado por WhatsApp e ainda não abriu"))
            continue
        na_janela, prox = canais.whatsapp_na_janela()
        if not na_janela:
            out.append(_registrar(esq, ch["id"], a["mensagem_id"], "whatsapp", "usuario", a["evento"], mascarar_telefone(tel),
                                  "adiado", "fora da janela de envio — sai na próxima passagem", None, prox))
            continue
        out.append(_enviar_whatsapp(esq, ch, u, a["evento"], a["mensagem_id"], tel, cfg, canais))
    return out


# ---------------------------------------------------------------- sino
def notificacoes(sessao: dict, esquema: str | None = None) -> list[dict]:
    """Itens DERIVADOS do estado: some ao ler o chamado, sem linha em not_lidas."""
    esq = _esq(esquema)
    uid = sessao.get("id")
    itens: list[dict] = []
    if not uid:
        return itens
    rows = pglocal.query(
        "SELECT c.id, c.codigo, c.titulo, c.status, c.lido_usuario_em, "
        "  (SELECT count(*) FROM sup_mensagens m WHERE m.chamado_id=c.id AND m.interna=0 AND m.papel IN ('suporte','sistema') "
        "     AND NOT (m.evento='status' AND m.status_para='aberto' AND m.status_de='') "
        "     AND (c.lido_usuario_em IS NULL OR m.criado_em > c.lido_usuario_em))::int AS novas "
        "FROM sup_chamados c WHERE c.usuario_id=%s AND c.status<>'fechado' ORDER BY c.atualizado_em DESC LIMIT 20",
        (uid,), esquema=esq)
    for r in rows:
        if r["novas"] <= 0:
            continue
        if r["status"] == "aguardando_usuario":
            txt = "O suporte precisa de uma resposta sua."
        elif r["status"] == "resolvido":
            txt = "Marcado como resolvido — confirme se resolveu."
        else:
            txt = f"{r['novas']} novidade(s) do suporte."
        itens.append({"chave": f"sup:{r['id']}", "tipo": "suporte",
                      "titulo": f"{r['codigo']} · {r['titulo'][:60]}", "texto": txt,
                      "acao": {"rotulo": "Abrir", "view": f"sup?chamado={r['id']}"}})
    if sessao.get("admin") or "supfila" in (sessao.get("telas") or []):
        k = pglocal.um("SELECT count(*) AS n FROM sup_chamados WHERE status IN ('aberto','em_atendimento')", esquema=esq) or {}
        n = k.get("n") or 0
        if n:
            itens.append({"chave": f"sup_fila:{n}", "tipo": "suporte_fila",
                          "titulo": f"{n} chamado(s) com o suporte", "texto": "A fila de atendimento tem trabalho.",
                          "acao": {"rotulo": "Abrir a fila", "view": "supfila"}})
    return itens
