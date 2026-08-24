"""Configuração do servidor de e-mail (SMTP) — data/email_config.json.

Separação deliberada de responsabilidade com `api/credenciais.py`:

- **Aqui** ficam host, porta, remetente, usuário e modo de segurança. Não são
  segredo: quem configura precisa CONFERIR o que está lá, e o cofre mascara
  valores (`ab12…wxyz`), o que tornaria impossível saber se o host está certo.
- **No cofre** (`credenciais.SMTP_SENHA`) fica só a senha, que nunca volta
  para a tela.

Mesma regra do cofre para o arquivo: nasce 0600 e fica fora do git.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CAMINHO = ROOT / "data" / "email_config.json"

# 587 = STARTTLS (o mais comum), 465 = SSL direto, 25 = sem criptografia.
SEGURANCAS = ("starttls", "ssl", "nenhuma")

PADRAO: dict = {
    "host": "",
    "porta": 587,
    "seguranca": "starttls",
    "usuario": "",
    "remetente": "",
    "remetente_nome": "CÓRTEX",
    "atualizado_em": None,
}

# Validação intencionalmente permissiva: o objetivo é barrar erro de digitação
# ("fulano@", "sem arroba"), não implementar a RFC 5322 — endereço que passa
# aqui e não existe volta como erro do próprio servidor SMTP, que é a fonte
# de verdade sobre isso.
_RE_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")


def email_valido(endereco: str) -> bool:
    return bool(_RE_EMAIL.match((endereco or "").strip()))


# Portas de LEITURA de caixa postal. Nenhuma delas fala SMTP: quem configura
# "o e-mail" costuma ter em mãos os dados de POP/IMAP que o provedor manda no
# mesmo bloco, e digita 995 aqui. O servidor responde no protocolo errado e o
# erro que volta ("SMTPConnectError") nao ajuda em nada -- aconteceu de
# verdade, cinco testes seguidos falharam por isso. Barrar na gravacao, com a
# correcao escrita, custa uma linha e evita a caça ao erro.
PORTAS_LEITURA = {110: "POP3", 143: "IMAP", 993: "IMAP sobre SSL",
                  995: "POP3 sobre SSL"}

# host de leitura -> host de envio equivalente, para os provedores que a
# operacao usa. Fora desta lista a checagem cai no prefixo (pop./imap.).
HOSTS_ENVIO = {
    "outlook.office365.com": "smtp.office365.com",
    "outlook.com": "smtp.office365.com",
    "pop.gmail.com": "smtp.gmail.com",
    "imap.gmail.com": "smtp.gmail.com",
}


def problema_de_leitura(host: str, porta: int) -> str | None:
    """Diz, em uma frase, que os dados informados sao de LER e-mail.

    Devolve None quando nao ha indicio disso. Usado na gravacao (barra) e na
    mensagem de erro do envio (explica), para os dois falarem a mesma lingua.
    """
    h = (host or "").strip().lower()
    alvo = HOSTS_ENVIO.get(h)
    if not alvo and (h.startswith("pop.") or h.startswith("imap.")):
        alvo = "smtp." + h.split(".", 1)[1]

    if porta in PORTAS_LEITURA:
        frase = (f"A porta {porta} e de {PORTAS_LEITURA[porta]}, que serve para "
                 f"LER a caixa postal - nao para enviar.")
        if alvo:
            return (frase + f" Para enviar use o host {alvo}, porta 587 e "
                    "seguranca STARTTLS.")
        return frase + " Para enviar use a porta 587 (STARTTLS) ou 465 (SSL)."
    if alvo:
        return (f"O servidor {host} e o de leitura da caixa postal. Para "
                f"enviar use {alvo}, porta 587 e seguranca STARTTLS.")
    return None


def separar_destinatarios(texto: str | list) -> list[str]:
    """Aceita lista, ou string com vírgula/ponto-e-vírgula/quebra de linha.

    Quem digita destinatário em campo de texto separa como está acostumado —
    exigir um separador específico só gera erro sem motivo.
    """
    if isinstance(texto, list):
        brutos = texto
    else:
        brutos = re.split(r"[,;\n]+", str(texto or ""))
    return [e.strip() for e in brutos if (e or "").strip()]


def _carregar() -> dict:
    try:
        return json.loads(CAMINHO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # arquivo ausente/corrompido não derruba a aplicação: o envio de
        # e-mail simplesmente fica "não configurado"
        return {}


def ler() -> dict:
    """Config efetiva (padrão + o que estiver gravado). NUNCA traz a senha."""
    return {**PADRAO, **_carregar()}


def senha() -> str | None:
    """Senha do cofre. Só o envio chama isto — nenhum endpoint devolve."""
    from api import credenciais
    return credenciais.ler("SMTP_SENHA")


def configurado() -> bool:
    """Mínimo para tentar um envio: host e remetente.

    Usuário/senha ficam de fora porque relay interno autenticado por IP é
    caso real — exigir credencial aqui bloquearia uma configuração legítima.
    """
    c = ler()
    return bool(c.get("host") and c.get("remetente"))


def status() -> dict:
    """O que a tela de Gestão recebe. Diz SE há senha, nunca QUAL."""
    return {
        **ler(),
        "configurado": configurado(),
        # via senha(), não direto no cofre: um único ponto lê o segredo
        "senha_configurada": bool(senha()),
    }


def gravar(dados: dict) -> dict:
    """Grava a configuração. Valida antes para a tela poder dizer o que está
    errado — o erro do SMTP só apareceria no primeiro envio."""
    atual = ler()
    novo = {**atual}

    host = str(dados.get("host") or "").strip()
    if not host:
        raise ValueError("Informe o servidor SMTP (host).")
    novo["host"] = host

    try:
        porta = int(dados.get("porta") or 0)
    except (TypeError, ValueError):
        raise ValueError("Porta inválida: use um número (ex.: 587).") from None
    if not (1 <= porta <= 65535):
        raise ValueError("Porta inválida: use um número entre 1 e 65535.")
    aviso = problema_de_leitura(host, porta)
    if aviso:
        raise ValueError(aviso)
    novo["porta"] = porta

    seg = str(dados.get("seguranca") or "starttls").strip().lower()
    if seg not in SEGURANCAS:
        raise ValueError(f"Segurança inválida: use {', '.join(SEGURANCAS)}.")
    novo["seguranca"] = seg

    remetente = str(dados.get("remetente") or "").strip()
    if not email_valido(remetente):
        raise ValueError("Remetente inválido: informe um e-mail completo.")
    novo["remetente"] = remetente

    novo["usuario"] = str(dados.get("usuario") or "").strip()
    novo["remetente_nome"] = str(dados.get("remetente_nome") or "CÓRTEX").strip() or "CÓRTEX"
    novo["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO.write_text(json.dumps(novo, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        CAMINHO.chmod(0o600)
    except OSError:   # pragma: no cover - Windows pode recusar; não é fatal
        pass
    return status()
