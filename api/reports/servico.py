"""Valida o report, monta o markdown da issue e orquestra anexo + issue.

Tudo aqui é função pura sobre o payload já desserializado. O usuário vem da
SESSÃO (`api.auth`), nunca do corpo da requisição: quem reporta é quem está
logado, e aceitar isso do cliente deixaria qualquer um assinar em nome de
outro. O relógio entra por parâmetro para o nome do anexo ser determinístico
no teste.

Os anexos sobem ANTES da issue. Se a issue falhar, sobram blobs órfãos no repo
de reports - barato e invisível. A ordem inversa produziria issue sem anexo,
que é justamente o defeito que o usuário enxerga.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Protocol

# Um anexo grande sozinho e o total do POST. O teto total é o mesmo checado no
# `content-length` do endpoint - aqui é a segunda linha de defesa, sobre o dado
# já desserializado.
ANEXO_MAX_BYTES = 8 * 1024 * 1024
TOTAL_MAX_BYTES = 15 * 1024 * 1024
ANEXOS_MAX = 5
TITULO_MAX = 120
DESCRICAO_MAX = 8000
ERROS_MAX = 10

# Allowlist de extensão: o que serve para explicar um problema de painel.
# Executável, script e arquivo compactado ficam de fora de propósito - o repo
# de reports não é canal de transporte de binário.
EXTENSOES = frozenset({"png", "jpg", "jpeg", "gif", "webp", "pdf",
                       "csv", "txt", "log", "xlsx", "docx"})

TIPOS = {"bug": "Bug", "melhoria": "Melhoria"}
GRAVIDADES = ("alta", "media", "baixa")

# O rótulo da gravidade muda com o tipo: "Trava meu trabalho" não faz sentido
# num pedido de melhoria. A label do GitHub continua sendo uma só.
_GRAV_ROTULO = {
    "bug": {"alta": "Trava meu trabalho", "media": "Atrapalha", "baixa": "Pode esperar"},
    "melhoria": {"alta": "Muito importante", "media": "Seria bom", "baixa": "Ideia solta"},
}


class ClienteGitHub(Protocol):
    """O que o serviço precisa do GitHub - permite dublê no teste."""

    def subir_anexo(self, caminho: str, b64: str) -> str: ...

    def criar_issue(self, titulo: str, corpo: str,
                    rotulos: list[str]) -> tuple[int, str]: ...


def tamanho_b64(b64: str) -> int:
    """Bytes que a string base64 representa, sem decodificar.

    Decodificar só para medir dobraria o pico de memória de um POST que já
    pode ter 15 MB.
    """
    limpo = "".join(b64.split())
    return (len(limpo) // 4) * 3 - limpo.count("=")


def _extensao(nome: str) -> str:
    return (nome or "").rsplit(".", 1)[-1].lower().strip() if "." in (nome or "") else ""


def _slug(texto: str, limite: int = 40) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()
    return (limpo[:limite].strip("-")) or "report"


def validar(payload: dict) -> str | None:
    """Devolve a mensagem de erro em português, ou None se o report está bom."""
    if not isinstance(payload, dict):
        return "Corpo inválido."
    if payload.get("tipo") not in TIPOS:
        return "Escolha se é um bug ou uma melhoria."
    if payload.get("gravidade") not in GRAVIDADES:
        return "Escolha a gravidade."
    titulo = str(payload.get("titulo") or "").strip()
    if not titulo:
        return "Escreva um título."
    if len(titulo) > TITULO_MAX:
        return f"O título passa de {TITULO_MAX} caracteres."
    descricao = str(payload.get("descricao") or "").strip()
    if not descricao:
        return "Escreva a descrição."
    if len(descricao) > DESCRICAO_MAX:
        return f"A descrição passa de {DESCRICAO_MAX} caracteres."

    anexos = payload.get("anexos") or []
    if not isinstance(anexos, list):
        return "Anexos inválidos."
    if len(anexos) > ANEXOS_MAX:
        return f"No máximo {ANEXOS_MAX} anexos por report."
    total = 0
    for anexo in anexos:
        if not isinstance(anexo, dict) or not anexo.get("b64"):
            return "Anexo inválido."
        ext = _extensao(str(anexo.get("nome") or ""))
        if ext not in EXTENSOES:
            return f"Arquivo .{ext or '?'} não é aceito como anexo."
        tam = tamanho_b64(str(anexo["b64"]))
        if tam > ANEXO_MAX_BYTES:
            return f"Anexo acima de {ANEXO_MAX_BYTES // (1024 * 1024)} MB."
        total += tam
    if total > TOTAL_MAX_BYTES:
        return f"Os anexos somam mais de {TOTAL_MAX_BYTES // (1024 * 1024)} MB."
    return None


def caminho_anexo(titulo: str, indice: int, nome: str, quando: datetime) -> str:
    """Caminho do anexo no repo de reports.

    O nome vindo do cliente NUNCA é usado: só a extensão sobrevive. Nome de
    arquivo do navegador é caminho em potencial ("../../etc/passwd.png") e o
    endpoint da Contents API monta a URL com ele.
    """
    ext = _extensao(nome)
    ext = ext if ext in EXTENSOES else "bin"
    carimbo = quando.strftime("%Y%m%d-%H%M%S")
    return (f"anexos/{quando:%Y}/{quando:%m}/"
            f"{carimbo}-{_slug(titulo)}-{indice + 1}.{ext}")


def titulo_issue(payload: dict) -> str:
    titulo = " ".join(str(payload.get("titulo") or "").split())
    return f"[{TIPOS[payload['tipo']]}] {titulo}"


def rotulos(payload: dict) -> list[str]:
    tela = _slug(str((payload.get("contexto") or {}).get("tela") or "sem-tela"), 30)
    return [payload["tipo"], f"prioridade:{payload['gravidade']}",
            f"tela:{tela}", "cortex-report"]


def _celula(valor: str) -> str:
    """Valor de célula de tabela markdown: pipe quebraria a coluna."""
    return " ".join(str(valor or "—").split()).replace("|", "\\|") or "—"


def montar_corpo(payload: dict, usuario: dict, links: list[tuple[str, str]],
                 quando: datetime) -> str:
    ctx = payload.get("contexto") or {}
    tipo = payload["tipo"]
    grav = _GRAV_ROTULO[tipo][payload["gravidade"]]
    nome = usuario.get("nome") or "—"
    perfil = usuario.get("perfil") or "—"

    tela = ctx.get("tela_nome") or ctx.get("tela") or "—"
    hash_tela = ctx.get("tela")
    if hash_tela:
        tela = f"{tela} (`#{hash_tela}`)"

    partes = [
        f"**{TIPOS[tipo]}** relatado por **{_celula(nome)}** ({_celula(perfil)}) "
        f"· gravidade **{grav}**",
        "",
        "### Relato",
        "",
        str(payload.get("descricao") or "").strip(),
        "",
        "### Onde",
        "",
        "| | |",
        "|---|---|",
        f"| Tela | {_celula(tela)} |",
        f"| Filtros ativos | {_celula(ctx.get('filtros'))} |",
        f"| Endereço | {_celula(ctx.get('url'))} |",
        "",
    ]

    if links:
        partes += ["### Anexos", ""]
        # link, e não imagem: o proxy de imagem do GitHub não autentica em repo
        # privado, então `![](...)` renderizaria quadrado quebrado
        partes += [f"- [{nome_arq}]({url})" for nome_arq, url in links]
        partes += [""]

    partes += [
        "### Ambiente",
        "",
        "| | |",
        "|---|---|",
        f"| Versão | {_celula(ctx.get('versao'))} |",
        f"| Navegador | {_celula(ctx.get('navegador'))} |",
        f"| Tela | {_celula(ctx.get('tela_px'))} |",
        f"| Reportado por | {_celula(nome)} · {_celula(usuario.get('email'))} "
        f"· {_celula(perfil)} |",
        f"| Enviado em | {quando:%d/%m/%Y %H:%M} |",
        "",
    ]

    erros = [str(e) for e in (ctx.get("erros") or [])][:ERROS_MAX]
    if erros:
        partes += ["### Erros de JavaScript recentes", "", "```"]
        # crase tripla dentro do erro fecharia o bloco no meio
        partes += [e.replace("```", "'''") for e in erros]
        partes += ["```", ""]

    partes += ["<!-- cortex-report v1 -->"]
    return "\n".join(partes)


def registrar(payload: dict, usuario: dict, cliente: ClienteGitHub,
              quando: datetime | None = None) -> dict:
    """Sobe os anexos, cria a issue e devolve número + URL."""
    erro = validar(payload)
    if erro:
        raise ValueError(erro)
    quando = quando or datetime.now()

    links: list[tuple[str, str]] = []
    for i, anexo in enumerate(payload.get("anexos") or []):
        caminho = caminho_anexo(payload["titulo"], i, str(anexo.get("nome") or ""), quando)
        url = cliente.subir_anexo(caminho, str(anexo["b64"]))
        links.append((caminho.rsplit("/", 1)[-1], url))

    numero, url = cliente.criar_issue(
        titulo_issue(payload), montar_corpo(payload, usuario, links, quando),
        rotulos(payload))
    return {"numero": numero, "url": url}
