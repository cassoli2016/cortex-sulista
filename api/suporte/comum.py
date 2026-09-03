"""O que o módulo de Suporte compartilha: domínios, regras, máscaras e a
máquina de estados do chamado (função PURA — quem grava é `chamados.py`).

O DESENHO EM UMA FRASE: o chamado é o registro canônico (local-first); o
status é gravado porque é decisão humana; tudo que envelhece sozinho é
calculado na leitura; a issue do GitHub é espelho; e cada tentativa de aviso
deixa uma das três respostas na trilha.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .. import pglocal
from ..validacao import DadoInvalido

# Redirecionado pelos testes para o schema descartável (fixture `esquema_pg`).
# TODOS os stores do módulo leem daqui — é um ponto só para esquecer.
ESQUEMA: str | None = None

TIPOS = ("bug", "melhoria", "duvida")
GRAVIDADES = ("alta", "media", "baixa")
STATUS = ("aberto", "em_atendimento", "aguardando_usuario", "resolvido", "fechado")
ATIVOS = ("aberto", "em_atendimento", "aguardando_usuario")
ROTULO_STATUS = {
    "aberto": "Recebido", "em_atendimento": "Em atendimento",
    "aguardando_usuario": "Aguardando você", "resolvido": "Resolvido", "fechado": "Encerrado",
}
ROTULO_TIPO = {"bug": "Bug", "melhoria": "Melhoria", "duvida": "Dúvida"}
MOTIVOS_FECHAMENTO = ("", "duplicado", "nao_e_defeito", "sem_retorno", "resolvido_fora", "desistiu")
ROTULO_MOTIVO = {
    "duplicado": "duplicado de outro chamado", "nao_e_defeito": "não é defeito",
    "sem_retorno": "sem retorno do usuário", "resolvido_fora": "resolvido fora do painel",
    "desistiu": "quem abriu não precisa mais",
}
CANAIS_AVISO = ("email", "whatsapp", "push", "github")
RESULTADOS = ("enviado", "sem_canal", "recusado", "adiado")

TITULO_MAX = 120
TEXTO_MAX = 8000
ANEXOS_MAX = 5
ANEXO_MAX_BYTES = 8 * 1024 * 1024
TOTAL_MAX_BYTES = 15 * 1024 * 1024
EXTENSOES = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "csv", "txt", "log", "xlsx", "docx"}
MIMES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "csv": "text/csv", "txt": "text/plain",
    "log": "text/plain", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Regras editáveis (sup_config). Chave ausente = este padrão; `None` nunca é zero.
CONFIG_PADRAO = {
    "email_equipe": "",            # destinatários do aviso ao time (nasce vazio: repo público)
    "avisar_equipe_email": "1",
    "sla_horas_alta": "8",         # até a primeira resposta do suporte
    "sla_horas_media": "48",
    "sla_horas_baixa": "120",
    "modelo_zap": "suporte-aviso",
    "instancia_zap": "",           # '' = a principal
    "github_espelho": "1",
    "github_ttl_min": "5",
}
CONFIG_CHAVES = tuple(CONFIG_PADRAO)


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def agora() -> datetime:
    return datetime.now(timezone.utc)


def iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


# ------------------------------------------------------------------ máscaras
# PII fica em UM lugar (telefone inteiro só em zap_envios; e-mail em correio_envios).
# A trilha do suporte aparece na tela do atendente e o repo é público.
def mascarar_email(e: str | None) -> str:
    e = (e or "").strip()
    if "@" not in e:
        return "•••" if e else ""
    nome, dom = e.split("@", 1)
    return (nome[:1] + "•••" + (nome[-1:] if len(nome) > 2 else "")) + "@" + dom


def mascarar_telefone(t: str | None) -> str:
    d = "".join(ch for ch in str(t or "") if ch.isdigit())
    if len(d) < 6:
        return "•••" if d else ""
    return d[:4] + "•" * (len(d) - 6) + d[-2:]


# ------------------------------------------------------------------- config
def config(esquema: str | None = None) -> dict:
    """Padrão + sobrescritas gravadas. Sempre devolve TODAS as chaves."""
    c = dict(CONFIG_PADRAO)
    try:
        for r in pglocal.query("SELECT chave, valor FROM sup_config", esquema=_esq(esquema)):
            if r["chave"] in c:
                c[r["chave"]] = r["valor"]
    except Exception:  # noqa: BLE001 — sem tabela ainda: padrão
        pass
    return c


def sla_horas(cfg: dict, gravidade: str) -> int:
    try:
        return max(1, int(cfg.get(f"sla_horas_{gravidade}") or CONFIG_PADRAO[f"sla_horas_{gravidade}"]))
    except (TypeError, ValueError):
        return int(CONFIG_PADRAO.get(f"sla_horas_{gravidade}", "48"))


def gravar_config(dados: dict, quem: str, esquema: str | None = None) -> dict:
    """Edição PARCIAL: chave ausente não mexe; valor vazio volta ao padrão."""
    from ..correio import config as ccfg
    esq = _esq(esquema)
    for chave, valor in (dados or {}).items():
        if chave not in CONFIG_CHAVES:
            raise DadoInvalido(f"Configuração desconhecida: {chave}.")
        v = "" if valor is None else str(valor).strip()
        if chave.startswith("sla_horas_") and v:
            try:
                n = int(v)
            except ValueError:
                raise DadoInvalido("SLA em horas precisa ser um número inteiro.") from None
            if not 1 <= n <= 720:
                raise DadoInvalido("SLA em horas fica entre 1 e 720.")
            v = str(n)
        if chave == "email_equipe" and v:
            dests = ccfg.separar_destinatarios(v)
            ruins = [d for d in dests if not ccfg.email_valido(d)]
            if ruins:
                raise DadoInvalido("E-mail inválido: " + ", ".join(ruins))
            v = "; ".join(dests)
        if chave in ("avisar_equipe_email", "github_espelho") and v not in ("", "0", "1"):
            raise DadoInvalido(f"{chave} aceita 0 ou 1.")
        if chave == "github_ttl_min" and v:
            try:
                v = str(max(1, min(1440, int(v))))
            except ValueError:
                raise DadoInvalido("TTL em minutos precisa ser um número.") from None
        if v == "":
            pglocal.executar("DELETE FROM sup_config WHERE chave=%s", (chave,), esquema=esq)
        else:
            pglocal.executar(
                "INSERT INTO sup_config (chave, valor, atualizado_em, atualizado_por) "
                "VALUES (%s, %s, now(), %s) ON CONFLICT (chave) DO UPDATE SET valor=EXCLUDED.valor, "
                "atualizado_em=now(), atualizado_por=EXCLUDED.atualizado_por",
                (chave, v, quem), esquema=esq)
    return config(esq)


# -------------------------------------------------------------- estados
class TransicaoInvalida(DadoInvalido):
    """Transição fora da matriz — a mensagem vai para a tela, em 409."""


# (de, para, papel) → o que é obrigatório. papel: 'usuario' (dono) | 'suporte'.
_TRANSICOES: dict[tuple[str, str, str], dict] = {
    ("aberto", "em_atendimento", "suporte"): {},
    ("aguardando_usuario", "em_atendimento", "suporte"): {},
    ("resolvido", "em_atendimento", "suporte"): {},
    ("em_atendimento", "aguardando_usuario", "suporte"): {"texto": True},
    ("aberto", "aguardando_usuario", "suporte"): {"texto": True},
    ("aberto", "resolvido", "suporte"): {"texto": True},
    ("em_atendimento", "resolvido", "suporte"): {"texto": True},
    ("aguardando_usuario", "resolvido", "suporte"): {"texto": True},
    ("resolvido", "fechado", "usuario"): {},                     # confirmar
    ("resolvido", "fechado", "suporte"): {},
    ("aberto", "fechado", "usuario"): {},                        # desistiu
    ("aberto", "fechado", "suporte"): {"motivo": True},
    ("em_atendimento", "fechado", "suporte"): {"motivo": True},
    ("aguardando_usuario", "fechado", "suporte"): {"motivo": True},
    ("resolvido", "aberto", "usuario"): {"texto": True},         # reabrir
    ("fechado", "aberto", "usuario"): {"texto": True},
    ("resolvido", "aberto", "suporte"): {"texto": True},
    ("fechado", "aberto", "suporte"): {"texto": True},
    # resposta do usuário em aguardando_usuario volta para o suporte (evento)
    ("aguardando_usuario", "em_atendimento", "usuario"): {"automatico": True},
}


def transicao(de: str, para: str, papel: str, *, texto: str = "", motivo: str = "") -> None:
    """Levanta `TransicaoInvalida` com a frase certa; devolve None se pode."""
    regra = _TRANSICOES.get((de, para, papel))
    if regra is None:
        if de == para:
            raise TransicaoInvalida(f"O chamado já está em '{ROTULO_STATUS.get(de, de)}'.")
        if de == "fechado" and para != "aberto":
            raise TransicaoInvalida("Este chamado está encerrado — reabra antes de mexer nele.")
        raise TransicaoInvalida(
            f"Não dá para ir de '{ROTULO_STATUS.get(de, de)}' para '{ROTULO_STATUS.get(para, para)}'"
            + ("" if papel == "suporte" else " por quem abriu o chamado") + ".")
    if regra.get("texto") and not (texto or "").strip():
        raise DadoInvalido("Diga ao usuário o que mudou: o texto é obrigatório nesta ação.")
    if regra.get("motivo") and (motivo or "") not in MOTIVOS_FECHAMENTO[1:]:
        raise DadoInvalido("Escolha o motivo do encerramento.")


# ---------------------------------------------------------------- validação
_EXT = re.compile(r"\.([A-Za-z0-9]{1,5})$")


def extensao(nome: str) -> str:
    m = _EXT.search((nome or "").strip())
    return m.group(1).lower() if m else ""


def tamanho_b64(b64: str) -> int:
    s = (b64 or "").strip()
    if "," in s[:80] and s.startswith("data:"):
        s = s.split(",", 1)[1]
    pad = s[-2:].count("=")
    return max(0, (len(s) * 3) // 4 - pad)


def validar_anexos(anexos) -> list[dict]:
    """Os mesmos tetos do report antigo, conferidos sobre o dado desserializado."""
    if anexos in (None, ""):
        return []
    if not isinstance(anexos, list):
        raise DadoInvalido("Anexos inválidos.")
    if len(anexos) > ANEXOS_MAX:
        raise DadoInvalido(f"No máximo {ANEXOS_MAX} anexos por vez.")
    total = 0
    limpos = []
    for i, a in enumerate(anexos):
        if not isinstance(a, dict) or not a.get("b64"):
            raise DadoInvalido("Anexo inválido.")
        ext = extensao(str(a.get("nome") or ""))
        if ext not in EXTENSOES:
            raise DadoInvalido(f"Arquivo .{ext or '?'} não é aceito como anexo.")
        b64 = str(a["b64"])
        if b64.startswith("data:") and "," in b64[:80]:
            b64 = b64.split(",", 1)[1]
        tam = tamanho_b64(b64)
        if tam > ANEXO_MAX_BYTES:
            raise DadoInvalido(f"Anexo acima de {ANEXO_MAX_BYTES // (1024 * 1024)} MB.")
        total += tam
        limpos.append({"nome": f"anexo-{i + 1}.{ext}", "ext": ext, "mime": MIMES[ext],
                       "b64": b64, "tamanho": tam})
    if total > TOTAL_MAX_BYTES:
        raise DadoInvalido(f"Os anexos somam mais de {TOTAL_MAX_BYTES // (1024 * 1024)} MB.")
    return limpos


# Chaves de modelo (`{{x}}`) escritas pelo usuário não podem chegar ao
# renderizador do WhatsApp; e texto de usuário JAMAIS passa por str.format.
def sem_chaves(texto: str) -> str:
    return (texto or "").replace("{{", "{ {").replace("}}", "} }")
