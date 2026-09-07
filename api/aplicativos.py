# -*- coding: utf-8 -*-
"""O registro dos APLICATIVOS da casa — a fonte única da tela `apps`.

O QUE É UM APLICATIVO AQUI, e o que não é
=========================================

Aplicativo é **página própria, servida fora do painel**, com endereço próprio e
público próprio: hoje o rastreio de carga (`/r`, para quem espera a mercadoria)
e o app do motorista (`/motorista`). Cada um tem o seu jeito de entrar — o
rastreio não pede login porque o token já vem no link; o motorista entra pelo
número do celular com código no WhatsApp.

Tela do painel NÃO é aplicativo: ela mora dentro do `index.html`, é alcançada
por hash e o acesso vem do RBAC. Quem confunde os dois acaba com uma tela
listada como app, ou com um app que ninguém acha.

POR QUE ESTE ARQUIVO EXISTE
===========================

O pedido de quem opera foi: *"todos os aplicativos que criarmos devem ir direto
para esse menu"*. "Direto" não se consegue com disciplina — se conseguisse, a
casa não teria a regra de que TELA NOVA TEM SEIS REGISTROS, que existe
justamente porque alguém sempre esquece um.

Então são duas peças, e a segunda é que faz a promessa valer:

1. **Este registro é a única fonte.** A tela `apps` desenha o que estiver aqui;
   ninguém escreve cartão à mão no HTML.
2. **`tests/test_aplicativos.py` cobra o registro pelo DISCO.** Todo
   `api/static/*.html` que não seja o painel tem de estar aqui, e a rota de
   cada um tem de responder. Publicar `api/static/frota.html` e esquecer o
   registro deixa a suíte VERMELHA com o nome do arquivo esquecido — não
   silenciosamente fora do menu.

A ordem de `APLICATIVOS` é a ordem dos cartões na tela. É a única coisa aqui
que é gosto; o resto é contrato.
"""
from __future__ import annotations

#: O painel. Não é aplicativo, e é o único `.html` de `static/` que fica fora
#: do registro — está aqui nomeado para o guard não precisar adivinhar.
PAINEL = "index.html"


APLICATIVOS: list[dict] = [
    {
        "id": "rastreio",
        "nome": "Rastreio de carga",
        "arquivo": "rastreio.html",
        # `/r` e não `/rastreio`: o endereço entra numa mensagem que a pessoa lê
        # no celular, e com o token o link tinha 96 caracteres — três linhas,
        # um paredão azul que ninguém clica. Com `/r` fica em 59.
        "rota": "/r",
        "rotas_alternativas": ["/rastreio"],
        "publico": "Quem espera a carga — cliente, destinatário, portaria",
        "entrada": "Sem login: o token da viagem já vai no link",
        "descricao": ("Onde está a carga, sem precisar ligar para o SAC. É a "
                      "única parte do CÓRTEX que responde a quem não tem conta "
                      "— quem despachou e quem recebe não são usuários do "
                      "sistema, e exigir cadastro empurraria todo mundo para o "
                      "telefone."),
    },
    {
        "id": "motorista",
        "nome": "App do motorista",
        "arquivo": "motorista.html",
        "rota": "/motorista",
        "rotas_alternativas": [],
        "publico": "Motorista da frota própria e agregado",
        "entrada": "Pelo número do celular, com código no WhatsApp",
        "descricao": ("A viagem do dia, os documentos e o histórico na mão de "
                      "quem dirige. A entrada responde igual para número que "
                      "existe e que não existe — senão a tela viraria uma "
                      "máquina de descobrir quem dirige para esta empresa."),
    },
]


def por_id(app_id: str) -> dict | None:
    return next((a for a in APLICATIVOS if a["id"] == app_id), None)


def arquivos_registrados() -> set[str]:
    """Os `.html` que o registro conhece — o que o guard compara com o disco."""
    return {a["arquivo"] for a in APLICATIVOS}


def rotas(app: dict) -> list[str]:
    """Todos os endereços de um aplicativo, o principal primeiro."""
    return [app["rota"], *app.get("rotas_alternativas", [])]


def qr_svg(url: str, escala: int = 4) -> str | None:
    """O QR do endereço, como SVG embutido — ou `None` sem a biblioteca.

    QR NÃO É ENFEITE AQUI: os dois aplicativos são de celular. O motorista não
    vai digitar um endereço na cabine, e quem manda o link de rastreio muitas
    vezes está mostrando a tela para alguém do outro lado do balcão.

    SVG e EMBUTIDO, não `<img src>`: a página do painel não busca imagem de
    host nenhum em runtime (a casa vendoriza tudo), e um SVG inline escala sem
    borrar em qualquer tamanho de tela.

    `None` em vez de erro quando o `segno` não está instalado: numa instalação
    sem a dependência sincronizada, a tela mostra o link e o botão de copiar —
    perde o QR e continua servindo. Aplicativo que some do menu porque faltou
    uma biblioteca de desenho seria pior que aplicativo sem QR.
    """
    try:
        import segno
    except ImportError:  # pragma: no cover - instalação sem a dependência
        return None
    # `error='m'` (~15% de recuperação): o QR aparece em tela e em papel
    # impresso na portaria; a correção alta engorda o desenho sem ganho real
    # para leitura de perto.
    return segno.make(url, error="m").svg_inline(scale=escala)


def listar(base: str = "") -> list[dict]:
    """O registro pronto para a tela: com endereço absoluto e QR.

    `base` é a origem que o navegador está usando (`https://cortex…`), e vem de
    QUEM PEDIU, não de configuração: o CÓRTEX responde por mais de um caminho
    (o túnel Cloudflare, o ngrok ao lado dele, e `127.0.0.1` na bancada), e um
    endereço fixo aqui mandaria a pessoa copiar um link que não é o dela.
    """
    saida = []
    for a in APLICATIVOS:
        url = f"{base.rstrip('/')}{a['rota']}" if base else a["rota"]
        saida.append({
            "id": a["id"],
            "nome": a["nome"],
            "publico": a["publico"],
            "entrada": a["entrada"],
            "descricao": a["descricao"],
            "rota": a["rota"],
            "url": url,
            "qr": qr_svg(url) if base else None,
        })
    return saida
