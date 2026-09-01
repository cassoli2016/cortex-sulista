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
from . import espelho
from . import normaliza as nz

import logging

log = logging.getLogger(__name__)

PORTAL = "tupy"
PORTAL_ROTULO = "Tupy (Monkey Exchange)"
ORIGEM = "api"


def _data(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def _para_gravar(linhas: list[dict], resumo: dict, quando: datetime) -> dict:
    """Formato que `gravar_envio` espera — o mesmo do leitor de planilha.

    Só entra a POSIÇÃO: título vendido/liquidado/cancelado já saiu do
    portal, e a API devolve o histórico INTEIRO do convênio (48,6 mil na
    primeira coleta real — nenhum em aberto). O resumo continua contando
    tudo; a posição gravada é o recorte em aberto."""
    titulos = []
    for t in linhas:
        if t["situacao_api"] in nz.FORA_DA_POSICAO:
            continue
        venc = _data(t["vencimento"])
        if venc is None:
            # sem vencimento não há antecipação possível nem posição no fluxo;
            # a planilha trata como rejeitada e aqui vale a mesma regra
            continue
        titulos.append({**t, "emissao": _data(t["emissao"]), "vencimento": venc})

    rejeitadas = [t for t in linhas
                  if t["situacao_api"] not in nz.FORA_DA_POSICAO
                  and _data(t["vencimento"]) is None]
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

    # A Sulista tem UM sellerId por CNPJ (5 hoje). Os sellers são somados e
    # gravados numa posição SÓ: gravar_envio SUBSTITUI a posição do portal,
    # então gravar por CNPJ deixaria só o último e os outros sumiriam sem
    # erro nenhum. O mesmo Cliente atende todos — o token é um só.
    #
    # O CEDENTE de cada título é o próprio seller, e o payload não o traz:
    # o CNPJ/nome vêm de /uaa/me (companies) e são anotados no bruto antes
    # da normalização (`_seller_cnpj`/`_seller_nome`).
    c = cli.Cliente(http=http)
    empresas = {e["companyId"]: e for e in c.empresas()}
    brutos: list[dict] = []
    pares: list[tuple[str, dict]] = []   # (seller_id, bruto) para o espelho
    sellers = cli.seller_ids()
    for sid in sellers:
        c.seller = sid
        emp = empresas.get(sid, {})
        for r in c.recebiveis():
            r["_seller_cnpj"] = emp.get("cnpj", "")
            r["_seller_nome"] = emp.get("nome", "")
            brutos.append(r)
            pares.append((sid, r))
    d = nz.lote(brutos)
    linhas, resumo = d["titulos"], d["resumo"]
    # a POSIÇÃO é o recorte em aberto — valores, sacados e a IMPRESSÃO da
    # coleta saem dela: um histórico que só muda de SOLD para PAID não pode
    # criar envio novo, porque a posição não mudou
    posicao = [t for t in linhas if t["situacao_api"] not in nz.FORA_DA_POSICAO]
    agora = datetime.now()

    lido = _para_gravar(linhas, resumo, agora)
    res = {
        "titulos": len(lido["titulos"]),
        "valor_nominal": round(sum(t["valor_nominal"] for t in posicao), 2),
        "valor_saldo": round(sum(t["valor_saldo"] for t in posicao), 2),
        # o sacado vem do próprio título; a API não traz lista à parte
        "sacados": [{"cnpj": cj, "nome": next(
            (t["nome_sacado"] for t in posicao if t["cnpj_sacado"] == cj), "")}
            for cj in sorted({t["cnpj_sacado"] for t in posicao
                              if t["cnpj_sacado"]})],
    }

    envio_id, ja_existia = registro.gravar_envio(
        lido, res, usuario=usuario, dados=_impressao(posicao))
    registro.marcar_origem(envio_id, ORIGEM)

    # o ESPELHO (mky_recebiveis) guarda a varredura INTEIRA — é dele que a
    # tela de validação do portal responde sem re-paginar a API. Falha aqui
    # não derruba a posição (o produto primário), mas fica ESCRITA.
    esp_gravados = 0
    try:
        esp_gravados, esp_sem_chave = espelho.upsert(pares)
        espelho.registrar_carga(agora, len(pares), esp_gravados, esp_sem_chave)
    except Exception as exc:  # noqa: BLE001
        log.warning("espelho monkey falhou: %s", type(exc).__name__)
        try:
            espelho.registrar_carga(agora, len(pares), 0, 0,
                                    f"{type(exc).__name__}: {str(exc)[:200]}")
        except Exception:  # noqa: BLE001 — trilha indisponível junto do banco
            pass

    return {
        "envio_id": envio_id,
        "sem_mudanca": ja_existia,
        "ambiente": cli.ambiente(),
        "sellers": len(sellers),
        "recebidos": len(brutos),
        "espelho": esp_gravados,
        "fora_da_posicao": len(linhas) - len(posicao),
        "gravados": len(lido["titulos"]),
        "rejeitados_sem_vencimento": len(lido["rejeitadas"]),
        "antecipaveis": resumo["antecipaveis"],
        "valor_antecipavel": resumo["valor_antecipavel"],
        "por_status": resumo["por_status"],
        "coletado_em": agora.strftime("%Y-%m-%d %H:%M"),
    }


def diagnostico() -> dict:
    """Estado da integração, sem expor segredo — alimenta a tela de Saúde.

    Não chama a API: a Saúde recarrega a cada 5 s e uma volta em
    `/receivables` pagina até o portal inteiro. O que se mede é a POSIÇÃO
    GRAVADA — que é o que a tela de Antecipações mostra.
    """
    ultimo = registro.ultimo_envio(PORTAL) or {}
    esp = None
    try:
        from api import pglocal
        esp = pglocal.um("SELECT to_char(terminado_em, 'YYYY-MM-DD HH24:MI')"
                         " AS quando, gravados, erro FROM mky_carga"
                         " ORDER BY id DESC LIMIT 1")
    except Exception:  # noqa: BLE001 — espelho ausente não derruba a Saúde
        pass
    return {
        "espelho": dict(esp) if esp else None,
        "configurado": cli.configurado(),
        "modo_auth": cli.modo_auth() or "nenhuma",
        "seller_id": bool(cli.seller_id()),
        "sellers": len(cli.seller_ids()),
        "ambiente": cli.ambiente(),
        "coletado_em": ultimo.get("ts") if ultimo.get("origem") == ORIGEM else None,
        "titulos": ultimo.get("titulos") or 0,
        "valor_saldo": ultimo.get("valor_saldo") or 0.0,
    }
