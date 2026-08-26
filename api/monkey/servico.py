"""Coleta da Monkey e gravação no MESMO lugar onde a planilha grava.

Só a Tupy usa esta API — Maxion e Adient continuam por planilha. Por isso o
sistema passa a conviver com duas origens, e a tela precisa dizer qual é qual:
"Tupy: API, lida há 10 minutos" é uma garantia diferente de "Maxion: planilha
de 24/08".

A gravação reusa `registro.gravar_envio()` de propósito. Ele já resolve a
substituição do portal (posição nova apaga os títulos da anterior, mantendo a
trilha do envio) e a impressão que evita duplicata. Escrever um caminho
paralelo para a API criaria duas regras de "qual é a posição atual" — e um dia
elas discordariam.

VÁRIOS CNPJs: a Sulista tem um perfil (e um sellerId) por CNPJ na Monkey. A
coleta percorre todos e grava UMA posição só, porque para a tela "Tupy" é um
portal — a origem de cada título continua distinguível pelo CNPJ do cedente que
vem no próprio payload.

IMPRESSÃO DA COLETA: hash do conteúdo normalizado, não do horário. A coleta
agendada roda de tempos em tempos; se nada mudou no portal, ela não pode criar
um envio novo, senão a lista de importações mente sobre a frequência com que o
dado REALMENTE muda.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from ..antecipacoes import registro
from . import cliente as cli
from . import normaliza as nz

PORTAL = "tupy"
PORTAL_ROTULO = "Tupy (Monkey Exchange)"
ORIGEM = "api"


def _data(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def _para_gravar(linhas: list[dict], resumo: dict, quando: datetime) -> dict:
    """Formato que `gravar_envio` espera — o mesmo do leitor de planilha."""
    titulos = []
    for t in linhas:
        venc = _data(t["vencimento"])
        if venc is None:
            # sem vencimento não há antecipação possível nem posição no fluxo;
            # a planilha trata como rejeitada e aqui vale a mesma regra
            continue
        titulos.append({**t, "emissao": _data(t["emissao"]), "vencimento": venc})

    rejeitadas = [t for t in linhas if _data(t["vencimento"]) is None]
    return {
        "arquivo": f"API Monkey · coleta de {quando:%d/%m/%Y %H:%M}",
        "portal": PORTAL,
        "portal_rotulo": PORTAL_ROTULO,
        # a API não declara total nenhum: não há o que reconciliar contra, e
        # inventar um "declarado" igual ao somado faria a divergência sair
        # sempre zero e parecer conferência que não houve
        "total_declarado": None,
        "divergencia": None,
        "rejeitadas": rejeitadas,
        "titulos": titulos,
    }


def _impressao(linhas: list[dict]) -> bytes:
    """Conteúdo que identifica a coleta. Ordenado para que a mesma posição
    devolvida em ordem diferente continue sendo a mesma coleta."""
    chave = sorted(
        (t["documento"], t["vencimento"], t["valor_saldo"], t["situacao_api"])
        for t in linhas)
    return json.dumps(chave, ensure_ascii=False).encode()


def coletar(usuario: str = "coleta automática", http=None) -> dict:
    """Lê a Monkey e grava a posição da Tupy. Devolve o resumo da coleta."""
    if not cli.configurado():
        raise cli.MonkeyNaoConfigurado(
            "integração da Monkey não configurada — rode "
            "scripts/verificar_monkey.py para ver o que falta")

    # UMA gravação com tudo junto, nunca uma por CNPJ: `gravar_envio`
    # substitui a posição do portal, então gravar em sequência deixaria só o
    # último sellerId e os outros quatro sumiriam sem erro nenhum.
    por_seller = cli.Cliente(http=http).recebiveis_por_seller()
    brutos = [r for lote in por_seller.values() for r in lote]
    d = nz.lote(brutos)
    linhas, resumo = d["titulos"], d["resumo"]
    agora = datetime.now()

    lido = _para_gravar(linhas, resumo, agora)
    res = {
        "titulos": len(lido["titulos"]),
        "valor_nominal": resumo["valor_nominal"],
        "valor_saldo": resumo["valor_saldo"],
        # o sacado vem do próprio título; a API não traz lista à parte
        "sacados": [{"cnpj": c, "nome": next(
            (t["nome_sacado"] for t in linhas if t["cnpj_sacado"] == c), "")}
            for c in resumo["sacados"]],
    }

    envio_id, ja_existia = registro.gravar_envio(
        lido, res, usuario=usuario, dados=_impressao(linhas))
    registro.marcar_origem(envio_id, ORIGEM)

    return {
        "envio_id": envio_id,
        "sem_mudanca": ja_existia,
        "ambiente": cli.ambiente(),
        "recebidos": len(brutos),
        "gravados": len(lido["titulos"]),
        "rejeitados_sem_vencimento": len(lido["rejeitadas"]),
        "antecipaveis": resumo["antecipaveis"],
        "valor_antecipavel": resumo["valor_antecipavel"],
        "por_status": resumo["por_status"],
        # quebra por CNPJ: seller que parou de responder some da soma sem
        # deixar rastro, e aqui ele aparece como zero
        "por_seller": {s: len(linhas_s) for s, linhas_s in por_seller.items()},
        "coletado_em": agora.strftime("%Y-%m-%d %H:%M"),
    }
