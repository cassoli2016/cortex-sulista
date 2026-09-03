"""O e-mail de "esqueci minha senha" — o link que permite escolher a nova.

O QUE ESTE E-MAIL NÃO CARREGA: senha nenhuma. O de boas-vindas leva uma senha
provisória porque quem cadastrou o usuário decidiu criá-lo; aqui o pedido veio
da rua, de quem só digitou um e-mail numa tela de login pública. Mandar uma
senha nova por causa disso trocaria a senha de quem não pediu nada. O que vai
é um LINK de uso único e com prazo: até alguém abrir e escolher a senha, a
antiga continua valendo.

O HTML sai do layout compartilhado (`correio.painel`), como o de boas-vindas —
é de lá que vêm a moldura clara sem área escura, o estilo em linha e a defesa
contra o tema escuro do cliente de e-mail. Vai texto puro junto, sempre: quem
lê no relógio ou num cliente que não renderiza HTML ainda precisa do link.
"""
from __future__ import annotations

from . import config as cfg
from . import envio

ORIGEM = "redefinicao_de_senha"


def montar(nome: str, url_link: str, validade_min: int,
           teste: bool = False) -> tuple[str, str, str]:
    """Devolve (assunto, corpo_texto, corpo_html)."""
    from . import painel as p

    marca = "[TESTE] " if teste else ""
    assunto = f"{marca}CÓRTEX — redefinir sua senha"
    primeiro = (nome or "").strip().split(" ")[0] or "você"
    horas = validade_min // 60

    prazo = (f"{horas} hora" + ("s" if horas > 1 else "")) if horas >= 1 \
        else f"{validade_min} minutos"

    texto = "\n".join([
        f"Olá, {primeiro}.", "",
        "Alguém pediu para redefinir a senha da sua conta no CÓRTEX.",
        "Para escolher uma senha nova, abra o endereço abaixo:", "",
        f"  {url_link}", "",
        f"O link vale por {prazo} e serve UMA vez.", "",
        "Enquanto você não abrir o link, NADA muda: a sua senha atual continua",
        "valendo normalmente.", "",
        "Se não foi você que pediu, ignore esta mensagem — não é preciso fazer",
        "nada. Se isso se repetir, avise a equipe do painel.",
    ])

    html = p.documento(
        "Redefinir sua senha",
        [
            p.paragrafo(f"Olá, {primeiro}. Alguém pediu para redefinir a senha "
                        "da sua conta no CÓRTEX."),
            p.botao("Escolher uma senha nova", url_link),
            p.paragrafo(f"O link vale por {prazo} e serve uma única vez."),
            # O aviso de que NADA mudou ainda e o que impede a mensagem de
            # assustar quem nao pediu nada — e e verdade, nao consolo: o
            # pedido nao toca na conta (ver sql/cortex/0037_senha_reset.sql).
            p.paragrafo("Enquanto o link não for aberto, a sua senha atual "
                        "continua valendo. Se não foi você que pediu, ignore "
                        "esta mensagem: não é preciso fazer nada.",
                        destaque=True),
        ],
        subtitulo="Pedido feito na tela de login do painel",
        origem="tela de login do CÓRTEX",
        # Nao ha horario nem lista de destinatarios para mudar em lugar nenhum:
        # esta mensagem existe porque alguem clicou "esqueci minha senha".
        agendado=False,
    )
    return assunto, texto, html


def enviar(email: str, nome: str, url_link: str, validade_min: int, *,
           teste: bool = False) -> dict:
    """Manda o e-mail. Nunca levanta — devolve `{'ok', 'erro'}`.

    Quem chama IGNORA o resultado na resposta HTTP: a tela de login responde a
    mesma coisa com e-mail cadastrado ou não, e dizer "falhou o envio" ali
    entregaria que o e-mail existe. O resultado vai para o log e para a trilha
    de correio, que é onde o problema tem de aparecer.
    """
    if not cfg.configurado():
        return {"ok": False, "erro": "O envio de e-mail não está configurado "
                                     "(Gestão › Correio)."}
    assunto, texto, html = montar(nome, url_link, validade_min, teste=teste)
    # `usuario` vazio de propósito: não houve sessão: o pedido veio da tela
    # pública. A trilha guarda QUE saiu, para quem e quando — o token não vai
    # junto, pela mesma razão que a senha não vai na trilha do boas-vindas.
    return envio.enviar([email], assunto, texto, corpo_html=html,
                        origem=ORIGEM)
