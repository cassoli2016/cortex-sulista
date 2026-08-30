"""Ajustes do envio por WhatsApp — data/whatsapp_config.json.

Mesma divisão que o correio faz entre `config.py` e o cofre:

- **Aqui** ficam o interruptor, os limites, a janela de horário e a assinatura.
  Nada disso é segredo, e quem configura precisa CONFERIR o que está valendo —
  o cofre mascara valores (`ab12…wxyz`), o que tornaria impossível.
- **No cofre** (`credenciais.ZAPI_TOKEN` e `ZAPI_CLIENT_TOKEN`) ficam os
  tokens, que nunca voltam para a tela.

POR QUE OS PADRÕES SÃO TÍMIDOS. A Z-API não é a API oficial do WhatsApp: ela
conecta um número real por trás de um WhatsApp Web, e a documentação do próprio
fornecedor é explícita sobre banimento — o fator número 1 é a quantidade de
DESTINATÁRIOS DISTINTOS alcançados numa janela curta, e há relato de bloqueio
depois de 10 mensagens para números diferentes em conta nova. Perder o número
não é "a integração caiu": é o WhatsApp comercial da Sulista fora do ar, com o
histórico de conversa dos clientes dentro.

Por isso:

- `ativo` nasce DESLIGADO. Configurar não é autorizar a disparar.
- `limite_dia` nasce em 60 destinatários distintos por dia, não em "sem
  limite". Quem precisar de mais sobe conscientemente, olhando o aviso.
- a janela nasce 08:00–20:00. Mensagem de empresa às 3 da manhã é reclamação
  no dia seguinte, e o WhatsApp lê denúncia de usuário.

Todos os três são editáveis na tela. O que não existe é o padrão perigoso.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .. import segredo_arquivo

ROOT = Path(__file__).resolve().parent.parent.parent
CAMINHO = ROOT / "data" / "whatsapp_config.json"

PADRAO: dict = {
    # Interruptor geral. Desligado, `envio.enviar` recusa antes de qualquer
    # chamada — inclusive a de uma rotina automática que ninguém lembrava que
    # estava agendada.
    "ativo": False,
    # Destinatários DISTINTOS por dia. Não é "mensagens": mandar 300 mensagens
    # para 5 clientes é um comportamento normal de atendimento; mandar 1
    # mensagem para 300 números diferentes é o padrão que derruba a conta.
    "limite_dia": 60,
    # Segundos entre uma mensagem e a seguinte, repassado à Z-API como
    # `delayMessage` (a fila deles aceita 1..15). O padrão deles já é 1~3
    # aleatório; subir para 5 troca velocidade por semelhança com humano.
    "intervalo_seg": 5,
    "janela_inicio": "08:00",
    "janela_fim": "20:00",
    # Vai no fim de toda mensagem. Sem isso o destinatário recebe um texto de
    # um número que não tem salvo e não sabe quem está falando — que é
    # exatamente o perfil de mensagem que as pessoas denunciam.
    "assinatura": "",
    "atualizado_em": None,
}

# Range aceito pela fila da Z-API para delayMessage.
INTERVALO_MIN, INTERVALO_MAX = 1, 15

# Teto do limite diário. Não é a Z-API que impõe — é a leitura do risco: acima
# disso o desenho certo é a API OFICIAL do WhatsApp (Cloud API), com template
# aprovado, e não um número pendurado no WhatsApp Web.
LIMITE_MAX = 500

_RE_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _carregar() -> dict:
    try:
        return json.loads(CAMINHO.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # arquivo ausente/corrompido não derruba a aplicação: o envio fica
        # "não configurado", que é o estado seguro
        return {}


def ler() -> dict:
    return {**PADRAO, **_carregar()}


def _hhmm(txt: str) -> int:
    h, m = txt.split(":")
    return int(h) * 60 + int(m)


def dentro_da_janela(agora: datetime | None = None, *,
                     inicio: str | None = None, fim: str | None = None) -> bool:
    """A janela é fechada nas pontas ao contrário: 08:00–20:00 aceita 08:00 e
    recusa 20:01. Janela invertida (22:00–06:00) atravessa a meia-noite.

    `inicio`/`fim` permitem perguntar por OUTRA janela que não a geral — é o
    que um modelo com horário próprio usa (alerta de ocorrência para motorista
    às 3h é legítimo; cobrança no mesmo horário é reclamação). Sem eles, vale a
    configuração geral.
    """
    c = ler()
    agora = agora or datetime.now()
    minutos = agora.hour * 60 + agora.minute
    ini = _hhmm(inicio or c["janela_inicio"])
    fimm = _hhmm(fim or c["janela_fim"])
    if ini <= fimm:
        return ini <= minutos <= fimm
    return minutos >= ini or minutos <= fimm


def status() -> dict:
    """O que a tela de Gestão recebe."""
    from . import cliente
    c = ler()
    return {
        **c,
        "credenciais_ok": cliente.configurado(),
        # Diz SE cada segredo existe, nunca QUAL — a mesma regra da senha do
        # SMTP. A instância vai mascarada porque a tela precisa distinguir
        # "qual das instâncias está aqui" sem revelar metade da credencial.
        "instancia": cliente.instancia_mascarada(),
        "token_ok": bool(cliente.token()),
        "client_token_ok": bool(cliente.client_token()),
        "pronto": bool(c["ativo"] and cliente.configurado()),
        "dentro_da_janela": dentro_da_janela(),
        "limite_max": LIMITE_MAX,
    }


def gravar(dados: dict) -> dict:
    """Valida antes de gravar, para a tela dizer o que está errado agora."""
    novo = {**ler()}

    novo["ativo"] = bool(dados.get("ativo"))

    try:
        limite = int(dados.get("limite_dia", novo["limite_dia"]))
    except (TypeError, ValueError):
        raise ValueError("Limite diário inválido: use um número.") from None
    if limite < 1:
        raise ValueError("O limite diário precisa ser de ao menos 1 destinatário.")
    if limite > LIMITE_MAX:
        raise ValueError(
            f"Limite diário acima de {LIMITE_MAX} destinatários. Volume assim "
            "pede a API oficial do WhatsApp (Cloud API), com template "
            "aprovado — pela Z-API o risco é o número ser banido.")
    novo["limite_dia"] = limite

    try:
        intervalo = int(dados.get("intervalo_seg", novo["intervalo_seg"]))
    except (TypeError, ValueError):
        raise ValueError("Intervalo inválido: use um número de segundos.") from None
    if not (INTERVALO_MIN <= intervalo <= INTERVALO_MAX):
        raise ValueError(
            f"Intervalo entre mensagens: use de {INTERVALO_MIN} a "
            f"{INTERVALO_MAX} segundos (é o que a fila da Z-API aceita).")
    novo["intervalo_seg"] = intervalo

    for campo, rotulo in (("janela_inicio", "início"), ("janela_fim", "fim")):
        valor = str(dados.get(campo, novo[campo]) or "").strip()
        if not _RE_HORA.match(valor):
            raise ValueError(f"Horário de {rotulo} inválido: use HH:MM.")
        novo[campo] = valor

    novo["assinatura"] = str(dados.get("assinatura", novo["assinatura"]) or "").strip()[:120]
    novo["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    CAMINHO.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO.write_text(json.dumps(novo, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    try:
        segredo_arquivo.proteger(CAMINHO)   # ACL de verdade, não só chmod
    except OSError:   # pragma: no cover - Windows pode recusar; não é fatal
        pass
    return status()
