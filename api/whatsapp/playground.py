"""Playground da API da Z-API — explorar o fornecedor sem sair do CÓRTEX.

PARA QUE SERVE: descobrir o que a Z-API responde de verdade. A documentação
deles é boa mas incompleta, e três defeitos desta integração vieram justamente
de supor a resposta em vez de olhar — o `/status` que devolve
`"error": "You are already connected."` quando está TUDO BEM foi um deles, e
custou uma manhã.

O QUE ELE **NÃO** É: um atalho para mandar mensagem sem passar pelas regras.
Essa é a linha que não se cruza aqui, e ela tem nome no CLAUDE.md — "não existe
modo teste mais frouxo". Por isso:

1. **NÃO HÁ URL LIVRE.** Só o que está no `CATALOGO` abaixo é chamável. Um
   proxy genérico ("digite o caminho") daria acesso a `/send-text` sem o freio
   diário, sem a janela de horário e sem a trilha — ou seja, exatamente o jeito
   de perder o número, embrulhado como ferramenta de diagnóstico.
2. **ENVIO É BLOQUEADO, com o caminho certo apontado.** Os endpoints de
   mensagem estão listados para se saber que existem, e recusam com "use o
   formulário de envio".
3. **ESCRITA PEDE CONFIRMAÇÃO E VAI PARA A AUDITORIA.** `/restart` e
   `/disconnect` derrubam o WhatsApp da empresa; `DELETE /queue` descarta
   mensagens que ainda não saíram.
4. **A RESPOSTA É SANITIZADA.** O token viaja na URL desta API, e um eco de
   erro pode trazê-la.

`RISCO` é o campo que a tela usa para decidir cor, confirmação e bloqueio — e
está no catálogo, junto do endpoint, para quem acrescentar um novo ter de
declarar o que ele faz.
"""
from __future__ import annotations

LEITURA, ESCRITA, ENVIO = "leitura", "escrita", "envio"

# Cada entrada: método, caminho (com {parâmetros}), risco, o que faz e o que
# esperar. `params` são os campos que a tela pede antes de executar.
CATALOGO: list[dict] = [
    # ------------------------------------------------------------ instância
    {"id": "status", "grupo": "Instância", "metodo": "GET", "caminho": "/status",
     "risco": LEITURA, "nome": "Estado da conexão",
     "descricao": "Se a instância está pareada e se o celular está na rede. "
                  "ATENÇÃO ao campo `error`: com tudo certo ele vem preenchido "
                  "com “You are already connected.” — é descrição, não falha."},
    {"id": "device", "grupo": "Instância", "metodo": "GET", "caminho": "/device",
     "risco": LEITURA, "nome": "Aparelho pareado",
     "descricao": "Modelo, sistema e versão do celular que sustenta a instância."},
    {"id": "qr-code", "grupo": "Instância", "metodo": "GET",
     "caminho": "/qr-code", "risco": LEITURA, "nome": "QR Code (texto)",
     "descricao": "O código para parear um número novo. Só devolve algo quando "
                  "a instância NÃO está conectada — com ela no ar, a resposta "
                  "é o aviso de que já está conectada."},
    {"id": "restart", "grupo": "Instância", "metodo": "POST",
     "caminho": "/restart", "risco": ESCRITA, "nome": "Reiniciar a instância",
     "descricao": "Derruba e reconecta. Serve quando a instância trava, e "
                  "durante alguns segundos NADA sai."},
    {"id": "disconnect", "grupo": "Instância", "metodo": "POST",
     "caminho": "/disconnect", "risco": ESCRITA,
     "nome": "DESCONECTAR o número",
     "descricao": "Desliga o WhatsApp da empresa da Z-API. Para voltar é "
                  "preciso ler o QR Code de novo, no celular. Enquanto isso, "
                  "nenhuma mensagem sai."},

    # --------------------------------------------------------------- grupos
    {"id": "groups", "grupo": "Grupos", "metodo": "GET", "caminho": "/groups",
     "risco": LEITURA, "nome": "Listar grupos",
     "params": [{"nome": "page", "rotulo": "Página", "padrao": "1"},
                {"nome": "pageSize", "rotulo": "Por página", "padrao": "50"}],
     "descricao": "Os grupos de que este número participa. É desta lista que "
                  "sai o seletor de grupo do formulário de envio."},
    {"id": "group-metadata", "grupo": "Grupos", "metodo": "GET",
     "caminho": "/group-metadata/{id}", "risco": LEITURA,
     "nome": "Detalhes de um grupo",
     "params": [{"nome": "id", "rotulo": "ID do grupo",
                 "dica": "120363...  (copie da lista de grupos)"}],
     "descricao": "Participantes, administradores e descrição do grupo."},

    # ------------------------------------------------------ chats e contatos
    {"id": "chats", "grupo": "Conversas", "metodo": "GET", "caminho": "/chats",
     "risco": LEITURA, "nome": "Listar conversas",
     "params": [{"nome": "page", "rotulo": "Página", "padrao": "1"},
                {"nome": "pageSize", "rotulo": "Por página", "padrao": "20"}],
     "descricao": "As conversas abertas, com a última mensagem de cada uma."},
    {"id": "contacts", "grupo": "Conversas", "metodo": "GET",
     "caminho": "/contacts", "risco": LEITURA, "nome": "Listar contatos",
     "params": [{"nome": "page", "rotulo": "Página", "padrao": "1"},
                {"nome": "pageSize", "rotulo": "Por página", "padrao": "20"}],
     "descricao": "A agenda do aparelho pareado."},

    # ----------------------------------------------------------------- fila
    {"id": "queue", "grupo": "Fila", "metodo": "GET", "caminho": "/queue",
     "risco": LEITURA, "nome": "Mensagens na fila",
     "descricao": "O que a Z-API aceitou e ainda não entregou. Fila grande "
                  "com o celular fora do ar é o cenário que dispara tudo de "
                  "uma vez quando o aparelho volta."},
    {"id": "queue-clear", "grupo": "Fila", "metodo": "DELETE",
     "caminho": "/queue", "risco": ESCRITA, "nome": "LIMPAR a fila",
     "descricao": "Descarta o que ainda não saiu. É o antídoto para o disparo "
                  "em lote quando o celular volta — e é irreversível: as "
                  "mensagens descartadas não são reenviadas."},

    # -------------------------------------------------------------- envio
    {"id": "send-text", "grupo": "Mensagens", "metodo": "POST",
     "caminho": "/send-text", "risco": ENVIO, "nome": "Enviar texto",
     "descricao": "Listado para se saber que existe. NÃO é executável aqui: "
                  "usar este caminho direto pularia o limite diário, a janela "
                  "de horário, a checagem de conexão e a trilha. Para mandar "
                  "mensagem existe o formulário de envio, logo acima."},
]

POR_ID = {e["id"]: e for e in CATALOGO}


def catalogo() -> list[dict]:
    """O catálogo para a tela, sem nada a esconder — é documentação."""
    return [dict(e) for e in CATALOGO]


class ChamadaRecusada(ValueError):
    """A tela mostra esta mensagem no lugar do resultado."""


def preparar(ident: str, params: dict | None = None) -> tuple[str, str]:
    """`(metodo, caminho)` pronto para o cliente. Levanta se não pode.

    Monta o caminho AQUI, e não na tela, porque é este o ponto que garante que
    só o catálogo é alcançável: a tela manda um id e uns valores, nunca uma URL.
    """
    e = POR_ID.get(str(ident or ""))
    if not e:
        raise ChamadaRecusada(f"Endpoint “{ident}” não está no catálogo.")
    if e["risco"] == ENVIO:
        raise ChamadaRecusada(
            "Enviar mensagem por aqui pularia o limite diário, a janela de "
            "horário e a trilha. Use o formulário “Enviar mensagem”.")

    caminho = e["caminho"]
    valores = params or {}
    for p in e.get("params", []):
        nome = p["nome"]
        bruto = str(valores.get(nome) or p.get("padrao") or "").strip()
        marca = "{" + nome + "}"
        if marca in caminho:
            if not bruto:
                raise ChamadaRecusada(f"Informe {p.get('rotulo', nome)}.")
            # o valor entra numa URL: só o que é seguro num segmento de
            # caminho passa, senão um "../" alcançaria outro endpoint
            if not bruto.replace("-", "").replace("@", "").replace(".", "").isalnum():
                raise ChamadaRecusada(
                    f"{p.get('rotulo', nome)} tem caractere que não vale num "
                    "endereço.")
            caminho = caminho.replace(marca, bruto)
        elif bruto:
            if not bruto.isalnum():
                raise ChamadaRecusada(
                    f"{p.get('rotulo', nome)} deve ser um número.")
            caminho += ("&" if "?" in caminho else "?") + f"{nome}={bruto}"
    return e["metodo"], caminho
