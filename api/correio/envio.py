"""Envio SMTP propriamente dito.

Duas garantias que o resto do sistema depende:

1. **Nunca levanta exceção para o chamador.** Devolve sempre
   `{"ok": bool, "erro": str}`. Um relatório agendado que estoura exceção
   derrubaria a rotina inteira por causa de um servidor fora do ar.
2. **Sempre grava na trilha** (`registro`), inclusive quando falha — é o
   registro da falha que responde "o cliente diz que não recebeu".

ANEXO tem TETO e o teto é NOSSO, não do servidor. Sem ele a mensagem sai,
o servidor recusa lá na frente com "message too large" e o que volta para
quem chamou é uma falha de SMTP genérica — depois de já se ter lido do banco
e montado tudo. Recusar aqui diz o que fazer (mandar em partes) enquanto
ainda dá para dividir.

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

# Teto do conjunto de anexos de UMA mensagem, já em base64 (que é como o anexo
# viaja, e infla o arquivo em ~33%). 15 MB porque é o menor teto comum entre os
# servidores que se costuma encontrar — Google, Microsoft 365 e relay interno
# ficam todos acima disso, e ficar abaixo do menor deles é o único jeito de a
# recusa acontecer AQUI, onde ainda dá para dividir em partes.
MAX_ANEXOS_BYTES = 15 * 1024 * 1024

# Extensão -> (maintype, subtype). Lista curta de propósito: o que não estiver
# aqui vai como `application/octet-stream`, que todo cliente sabe salvar. Errar
# o tipo declarado é pior que ser genérico — um XML anunciado como texto chega
# renderizado no corpo em alguns clientes, e o importador não acha o arquivo.
TIPOS = {".xml": ("application", "xml"), ".pdf": ("application", "pdf"),
         ".zip": ("application", "zip"), ".csv": ("text", "csv"),
         ".txt": ("text", "plain")}


def _tipo_de(nome: str) -> tuple[str, str]:
    ponto = nome.rfind(".")
    return TIPOS.get(nome[ponto:].lower() if ponto >= 0 else "",
                     ("application", "octet-stream"))


def _bytes_de(conteudo) -> bytes:
    """Texto vira UTF-8; bytes passam intactos.

    O XML assinado é o caso que obriga a distinção: reserializar ou reencodar
    quebra a assinatura, e o arquivo passa a ser recusado por quem for validar.
    Aqui ele chega como `str` já pronto e sai como os mesmos bytes.
    """
    return conteudo.encode("utf-8") if isinstance(conteudo, str) else bytes(conteudo)


def problema_de_anexo(anexos) -> str:
    """Por que estes anexos não podem ir — ou string vazia.

    Confere ANTES de abrir conexão: descobrir na entrega que a mensagem é
    grande demais custa a conexão, o tempo e uma mensagem de erro do servidor
    que não diz o que fazer.
    """
    total = 0
    for a in anexos or []:
        if not (a.get("nome") or "").strip():
            return "Anexo sem nome de arquivo."
        # base64 cresce 4 bytes a cada 3; é o tamanho DEPOIS disso que o
        # servidor mede, e era ele que faltava na conta.
        total += (len(_bytes_de(a.get("conteudo") or b"")) + 2) // 3 * 4
    if total > MAX_ANEXOS_BYTES:
        return (f"Os anexos somam {total/1024/1024:.1f} MB depois de "
                f"codificados e o teto é {MAX_ANEXOS_BYTES//1024//1024} MB. "
                f"Mande em partes.")
    return ""


def _mensagem(destinatarios: list[str], assunto: str, corpo: str,
              corpo_html: str | None, c: dict,
              anexos: list[dict] | None = None) -> EmailMessage:
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
        # IMAGEM EMBUTIDA (`cid:`), nunca por URL. Imagem remota e bloqueada
        # por padrao na maior parte dos clientes e ainda entregaria ao servidor
        # quem abriu e quando. So entra a que o HTML REALMENTE referencia — um
        # anexo que ninguem exibe e peso a toa em toda mensagem.
        from api.correio import painel as _layout
        parte_html = msg.get_payload()[-1]
        for cid, dados in _layout.imagens_embutidas().items():
            if ("cid:" + cid) in corpo_html:
                parte_html.add_related(dados, maintype="image", subtype="png",
                                       cid="<%s>" % cid)
    for a in anexos or []:
        # `add_attachment` converte a mensagem para multipart/mixed sozinho,
        # inclusive quando já existe a alternativa HTML — por isso os anexos
        # entram DEPOIS, e não há make_mixed() à mão.
        principal, secundario = _tipo_de(a["nome"])
        msg.add_attachment(_bytes_de(a.get("conteudo") or b""),
                           maintype=principal, subtype=secundario,
                           filename=a["nome"])
    return msg


def _erro_legivel(exc: Exception, c: dict | None = None) -> str:
    """Mensagem que ajuda a consertar, sem vazar credencial.

    `SMTPAuthenticationError` traz a resposta bruta do servidor, que em alguns
    provedores ecoa o usuário — por isso a tradução em vez do str(exc) cru.

    Toda falha de conexão diz CONTRA QUEM tentou. "Erro do servidor SMTP:
    SMTPConnectError." era literalmente tudo o que a tela mostrava: não dava
    para saber se o host estava errado, se a porta estava errada ou se o
    firewall bloqueava — e as três têm conserto diferente.
    """
    c = c or {}
    onde = ""
    if c.get("host"):
        onde = (f" (tentou {c['host']}:{c.get('porta')} com segurança "
                f"{c.get('seguranca')})")

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        extra = ""
        if "office365" in str(c.get("host", "")).lower():
            # 535 5.7.139 no M365 quase nunca e senha errada: o tenant desliga
            # o SMTP AUTH por padrao e ele precisa ser habilitado na caixa.
            extra = (" No Microsoft 365, o SMTP autenticado vem DESLIGADO por "
                     "padrão na caixa postal — o administrador precisa habilitar "
                     "\"Authenticated SMTP\" para este usuário.")
        return ("Servidor recusou a autenticação: confira usuário e senha. "
                "Em contas com verificação em duas etapas costuma ser "
                "necessária uma senha de aplicativo." + extra + onde)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "O servidor recusou o(s) destinatário(s) informado(s)."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return ("O servidor recusou o remetente. Normalmente o remetente "
                "precisa ser o mesmo do usuário autenticado." + onde)

    # A config pode ser anterior à validação de porta de leitura, ou ter sido
    # editada no arquivo à mão: o diagnóstico vale mais que a exceção.
    leitura = cfg.problema_de_leitura(c.get("host", ""), c.get("porta") or 0)
    if leitura and isinstance(exc, (smtplib.SMTPException, OSError, TimeoutError)):
        return leitura + onde

    if isinstance(exc, (TimeoutError, OSError)) and not isinstance(exc, smtplib.SMTPException):
        return (f"Não foi possível falar com o servidor SMTP em {TIMEOUT}s. "
                "Confira host, porta e se o firewall libera a saída." + onde)
    if isinstance(exc, smtplib.SMTPConnectError):
        return ("O servidor atendeu mas não respondeu como um servidor SMTP. "
                "Isso costuma ser porta de outro protocolo ou host errado."
                + onde)
    if isinstance(exc, smtplib.SMTPException):
        return f"Erro do servidor SMTP: {type(exc).__name__}.{onde}"
    return f"Falha inesperada no envio: {type(exc).__name__}.{onde}"


def enviar(destinatarios, assunto: str, corpo: str, *,
           corpo_html: str | None = None, usuario: str = "",
           origem: str = "", registrar: bool = True,
           anexos: list[dict] | None = None) -> dict:
    """Envia e devolve {'ok', 'erro', 'destinatarios'}. Nunca levanta.

    `anexos` é uma lista de `{"nome": "arquivo.xml", "conteudo": str | bytes}`.
    O tipo MIME sai da extensão (`TIPOS`) — quem chama não precisa acertá-lo, e
    não pode errá-lo.
    """
    dests = cfg.separar_destinatarios(destinatarios)
    resultado = {"ok": False, "erro": "", "destinatarios": dests}

    if not dests:
        resultado["erro"] = "Informe ao menos um destinatário."
    elif [e for e in dests if not cfg.email_valido(e)]:
        invalidos = ", ".join(e for e in dests if not cfg.email_valido(e))
        resultado["erro"] = f"Destinatário inválido: {invalidos}"
    elif not (assunto or "").strip():
        resultado["erro"] = "Informe o assunto."
    elif problema_de_anexo(anexos):
        resultado["erro"] = problema_de_anexo(anexos)
    elif not cfg.configurado():
        resultado["erro"] = ("Envio de e-mail não configurado. "
                             "Configure o servidor SMTP em Gestão › E-mail.")

    # A TRILHA REGISTRA O QUE SAIU, e um e-mail com anexo é o arquivo, não o
    # texto: sem esta linha o registro de um envio de XML mostraria um corpo
    # curto e nenhum sinal de que 20 documentos fiscais deixaram a empresa.
    corpo_trilha = corpo or ""
    if anexos:
        corpo_trilha += ("\n\n[anexos: " + str(len(anexos)) + "] "
                         + ", ".join(a.get("nome", "?") for a in anexos))

    if resultado["erro"]:
        if registrar:
            registro.gravar(dests, assunto, corpo_trilha, usuario=usuario,
                            origem=origem, ok=False, erro=resultado["erro"])
        return resultado

    c = cfg.ler()
    senha = cfg.senha()
    msg = _mensagem(dests, assunto, corpo, corpo_html, c, anexos)

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
        resultado["erro"] = _erro_legivel(exc, c)

    if registrar:
        registro.gravar(dests, assunto, corpo_trilha, usuario=usuario,
                        origem=origem, ok=resultado["ok"],
                        erro=resultado["erro"])
    return resultado
