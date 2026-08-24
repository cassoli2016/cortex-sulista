"""Envio SMTP propriamente dito.

Duas garantias que o resto do sistema depende:

1. **Nunca levanta exceção para o chamador.** Devolve sempre
   `{"ok": bool, "erro": str}`. Um relatório agendado que estoura exceção
   derrubaria a rotina inteira por causa de um servidor fora do ar.
2. **Sempre grava na trilha** (`registro`), inclusive quando falha — é o
   registro da falha que responde "o cliente diz que não recebeu".

TIMEOUT é obrigatório: `smtplib` sem timeout herda o do socket (que pode ser
infinito) e prende o worker do uvicorn — a API inteira ficaria pendurada
esperando um servidor SMTP que não responde.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from api.correio import config as cfg
from api.correio import registro

TIMEOUT = 20


def _mensagem(destinatarios: list[str], assunto: str, corpo: str,
              corpo_html: str | None, c: dict) -> EmailMessage:
    msg = EmailMessage()
    nome = (c.get("remetente_nome") or "").strip()
    msg["From"] = f"{nome} <{c['remetente']}>" if nome else c["remetente"]
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto
    # set_content antes de add_alternative: o texto puro é o fallback de quem
    # lê sem HTML, e a ordem define qual o cliente de e-mail prefere.
    msg.set_content(corpo or "")
    if corpo_html:
        msg.add_alternative(corpo_html, subtype="html")
    return msg


def _erro_legivel(exc: Exception) -> str:
    """Mensagem que ajuda a consertar, sem vazar credencial.

    `SMTPAuthenticationError` traz a resposta bruta do servidor, que em alguns
    provedores ecoa o usuário — por isso a tradução em vez do str(exc) cru.
    """
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("Servidor recusou a autenticação: confira usuário e senha. "
                "Em contas com verificação em duas etapas costuma ser "
                "necessária uma senha de aplicativo.")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "O servidor recusou o(s) destinatário(s) informado(s)."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return ("O servidor recusou o remetente. Normalmente o remetente "
                "precisa ser o mesmo do usuário autenticado.")
    if isinstance(exc, (TimeoutError, OSError)) and not isinstance(exc, smtplib.SMTPException):
        return (f"Não foi possível falar com o servidor SMTP em {TIMEOUT}s. "
                "Confira host, porta e se o firewall libera a saída.")
    if isinstance(exc, smtplib.SMTPException):
        return f"Erro do servidor SMTP: {type(exc).__name__}."
    return f"Falha inesperada no envio: {type(exc).__name__}."


def enviar(destinatarios, assunto: str, corpo: str, *,
           corpo_html: str | None = None, usuario: str = "",
           origem: str = "", registrar: bool = True) -> dict:
    """Envia e devolve {'ok', 'erro', 'destinatarios'}. Nunca levanta."""
    dests = cfg.separar_destinatarios(destinatarios)
    resultado = {"ok": False, "erro": "", "destinatarios": dests}

    if not dests:
        resultado["erro"] = "Informe ao menos um destinatário."
    elif [e for e in dests if not cfg.email_valido(e)]:
        invalidos = ", ".join(e for e in dests if not cfg.email_valido(e))
        resultado["erro"] = f"Destinatário inválido: {invalidos}"
    elif not (assunto or "").strip():
        resultado["erro"] = "Informe o assunto."
    elif not cfg.configurado():
        resultado["erro"] = ("Envio de e-mail não configurado. "
                             "Configure o servidor SMTP em Gestão › E-mail.")

    if resultado["erro"]:
        if registrar:
            registro.gravar(dests, assunto, corpo, usuario=usuario,
                            origem=origem, ok=False, erro=resultado["erro"])
        return resultado

    c = cfg.ler()
    senha = cfg.senha()
    msg = _mensagem(dests, assunto, corpo, corpo_html, c)

    try:
        if c["seguranca"] == "ssl":
            servidor = smtplib.SMTP_SSL(c["host"], c["porta"], timeout=TIMEOUT,
                                        context=ssl.create_default_context())
        else:
            servidor = smtplib.SMTP(c["host"], c["porta"], timeout=TIMEOUT)
        with servidor:
            if c["seguranca"] == "starttls":
                servidor.starttls(context=ssl.create_default_context())
            # sem usuário configurado o login é PULADO de propósito: relay
            # interno autenticado por IP recusa AUTH e o envio falharia
            if c.get("usuario") and senha:
                servidor.login(c["usuario"], senha)
            servidor.send_message(msg)
        resultado["ok"] = True
    except Exception as exc:  # noqa: BLE001 - contrato: nunca levanta
        resultado["erro"] = _erro_legivel(exc)

    if registrar:
        registro.gravar(dests, assunto, corpo, usuario=usuario, origem=origem,
                        ok=resultado["ok"], erro=resultado["erro"])
    return resultado
