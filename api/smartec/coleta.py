"""Coleta da Smartec — orquestra as varreduras e registra cada passagem.

O CUSTO DE CADA RECURSO NÃO É O MESMO, e é isso que decide a cadência
====================================================================
A API tem duas famílias, e misturá-las numa rotina só seria caro de um lado e
inútil do outro:

  FROTA INTEIRA em UMA chamada   veículos, licenças, calendário de
                                 licenciamento, órgãos, catálogo do CTB,
                                 acessos SNE/ANTT, autuações da ANTT
  UMA CHAMADA POR VEÍCULO        multas, notificações, IPVA, taxa de
                                 licenciamento, restrições, cronotacógrafo

Para as multas isso não é problema, porque existe
`VEICULOS MULTAS SNE DETRAN`: uma chamada devolve QUEM tem multa em aberto, e
só esses são visitados. Medido em 31/08/2026 — 96 veículos, 212 multas, **4,9
segundos** com 4 trabalhadores. Varrer os 303 cadastrados custaria três vezes
mais para encontrar exatamente as mesmas 212.

Os recursos por-veículo que NÃO têm esse atalho (IPVA, taxa, restrições) ficam
fora da coleta periódica e rodam sob demanda. Uma tarefa agendada que varre
303 veículos todo dia gasta o mesmo no domingo em que ninguém abre a tela —
é a lição do TTL da TomTom.

QUATRO TRABALHADORES, E O NÚMERO TEM MOTIVO
===========================================
A TomTom recusou a partir de ~6 req/s e o CÓRTEX perdeu 15 de 47 chamadas por
não ter medido isso antes. Aqui 4 passou sem um único erro nas 96; não subi
porque o ganho seria de segundos num trabalho que roda de hora em hora, e o
custo de descobrir o teto é uma coleta perdida.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import armazenamento as arm
from . import cliente

log = logging.getLogger(__name__)

TRABALHADORES = 4

# Recursos que a coleta periódica cobre. A ordem importa pouco, menos por
# `veiculos`, que é o denominador de tudo e vai primeiro.
RECURSOS_PERIODICOS = (
    "veiculos", "acessos", "multas", "notificacoes", "licencas",
    "licenciamento", "antt", "catalogos",
)


def _hoje() -> date:
    return date.today()


def _br(dia: date) -> str:
    return dia.strftime("%d/%m/%Y")


def _mes_base(dia: date | None = None) -> str:
    """A Smartec pede o mês base como `01/mm/aaaa` — sempre dia 1.

    Mandar o dia de hoje é aceito em alguns endpoints e recusado noutros, com
    mensagens diferentes. Normalizar aqui evita descobrir isso um endpoint por
    vez.
    """
    dia = dia or _hoje()
    return dia.strftime("01/%m/%Y")


# ───────────────────────────────────────────────────── coletas de frota
def coletar_veiculos(esquema: str | None = None) -> dict:
    carga = arm.carga_abrir("veiculos", esquema)
    try:
        itens = cliente.chamar("veiculos")
        n = arm.gravar_veiculos(itens, esquema)
        arm.carga_fechar(carga, "ok" if n else "vazio", n, 1, "", esquema)
        return {"recurso": "veiculos", "itens": n, "chamadas": 1}
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, 1, f"{type(exc).__name__}: {exc}",
                         esquema)
        raise


def coletar_acessos(esquema: str | None = None) -> dict:
    """SNE e ANTT. É a coleta mais barata e a mais importante para o alarme."""
    carga = arm.carga_abrir("acessos", esquema)
    try:
        n = 0
        chamadas = 0
        for chave, servico in (("acessos_sne", "sne"), ("acessos_antt", "antt")):
            itens = cliente.chamar(chave)
            chamadas += 1
            n += arm.gravar_acessos(itens, servico, esquema)
        arm.carga_fechar(carga, "ok" if n else "vazio", n, chamadas, "", esquema)
        return {"recurso": "acessos", "itens": n, "chamadas": chamadas}
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, 1, f"{type(exc).__name__}: {exc}",
                         esquema)
        raise


def coletar_licencas(esquema: str | None = None) -> dict:
    carga = arm.carga_abrir("licencas", esquema)
    try:
        itens = cliente.paginar("licencas")
        n = arm.gravar_licencas(itens, esquema)
        arm.carga_fechar(carga, "ok" if n else "vazio", n, 1, "", esquema)
        return {"recurso": "licencas", "itens": n, "chamadas": 1}
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, 1, f"{type(exc).__name__}: {exc}",
                         esquema)
        raise


def coletar_licenciamento(esquema: str | None = None) -> dict:
    """Só o CALENDÁRIO — a taxa por veículo é sob demanda."""
    carga = arm.carga_abrir("licenciamento", esquema)
    try:
        itens = cliente.chamar("licenciamento_calendario",
                               DataBase=_mes_base())
        n = arm.gravar_licenciamento_calendario(itens, esquema)
        arm.carga_fechar(carga, "ok" if n else "vazio", n, 1, "", esquema)
        return {"recurso": "licenciamento", "itens": n, "chamadas": 1}
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, 1, f"{type(exc).__name__}: {exc}",
                         esquema)
        raise


def coletar_antt(dias: int = 180, esquema: str | None = None) -> dict:
    """Autuações da ANTT.

    O endpoint filtra por DATA DE EMISSÃO DO PDF, não por data da infração —
    a doc do fornecedor diz isso com todas as letras ("é o dia que o PDF foi
    gerado"). Confundir os dois faria a janela parecer errada: uma autuação de
    abril pode ser emitida em agosto, e é pela emissão que ela aparece.
    """
    carga = arm.carga_abrir("antt", esquema)
    try:
        itens = cliente.paginar("antt", DataEmissao=_br(_hoje() -
                                                        timedelta(days=dias)))
        n = arm.gravar_antt(itens, esquema)
        arm.carga_fechar(carga, "ok" if n else "vazio", n, 1, "", esquema)
        return {"recurso": "antt", "itens": n, "chamadas": 1}
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, 1, f"{type(exc).__name__}: {exc}",
                         esquema)
        raise


def coletar_catalogos(esquema: str | None = None) -> dict:
    """Órgãos, adesão ao SNE e o catálogo de infrações do CTB.

    Muda uma vez por ano, então roda junto por conveniência e não por
    necessidade. O catálogo do CTB é o que dá VALOR DE REFERÊNCIA à multa
    recente que ainda não foi valorada — ver a nota sobre maturação em
    `leitura.py`.
    """
    carga = arm.carga_abrir("catalogos", esquema)
    try:
        orgaos = cliente.chamar("orgaos")
        sne = cliente.chamar("orgaos_sne")
        ctb = cliente.chamar("infracoes_ctb")
        n = arm.gravar_orgaos(orgaos, sne, esquema)
        n += arm.gravar_infracoes_ctb(ctb, esquema)
        arm.carga_fechar(carga, "ok" if n else "vazio", n, 3, "", esquema)
        return {"recurso": "catalogos", "itens": n, "chamadas": 3}
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, 3, f"{type(exc).__name__}: {exc}",
                         esquema)
        raise


# ───────────────────────────────────────────── infrações (por veículo)
def _varrer(chave_lista: str, chave_item: str, especie: str,
            campos_lista: dict, campos_item: dict,
            esquema: str | None = None) -> dict:
    """O padrão das infrações: lista quem tem, depois busca de cada um.

    `completa` é o que autoriza o fechamento das ausentes, e ele só é True se
    NENHUMA das chamadas por veículo falhou. Ver `armazenamento.fechar_ausentes`
    — com uma falha no meio, fechar marcaria a frota como resolvida por causa
    de um timeout.
    """
    carga = arm.carga_abrir(especie, esquema)
    # Instante ANTES da primeira gravação: é a fronteira que separa "visto
    # nesta passagem" de "não veio". Ver fechar_ausentes.
    inicio = datetime.now(timezone.utc)
    chamadas = 1
    try:
        veiculos = cliente.chamar(chave_lista, **campos_lista)
    except Exception as exc:  # noqa: BLE001
        arm.carga_fechar(carga, "erro", 0, chamadas,
                         f"{type(exc).__name__}: {exc}", esquema)
        raise

    if not veiculos:
        # Zero veículos com multa é um resultado LEGÍTIMO e precisa ser
        # distinguível de falha — daí o status "vazio" em vez de "ok".
        arm.carga_fechar(carga, "vazio", 0, chamadas,
                         "nenhum veículo com pendência", esquema)
        return {"recurso": especie, "itens": 0, "veiculos": 0,
                "chamadas": chamadas, "completa": True}

    falhas: list[str] = []
    coletados: list[str] = []
    total = 0

    def _um(v: dict):
        rnv = str(v.get("Renavam") or "").strip()
        if not rnv:
            return rnv, None, "sem renavam"
        try:
            return rnv, cliente.chamar(chave_item, Renavam=rnv,
                                       **campos_item), None
        except Exception as exc:  # noqa: BLE001
            return rnv, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=TRABALHADORES) as ex:
        for rnv, itens, err in ex.map(_um, veiculos):
            chamadas += 1
            if err:
                falhas.append(f"{rnv}: {err}")
                continue
            coletados.append(rnv.lstrip("0"))
            total += arm.gravar_infracoes(itens or [], especie, esquema)

    completa = not falhas
    fechadas = arm.fechar_ausentes(especie, coletados, completa, inicio,
                                   esquema)

    msg = ""
    if falhas:
        msg = (f"{len(falhas)} de {len(veiculos)} veículos falharam — as "
               f"resolvidas NÃO foram fechadas nesta passagem. "
               f"1ª: {falhas[0][:200]}")
    arm.carga_fechar(carga, "erro" if falhas else ("ok" if total else "vazio"),
                     total, chamadas, msg, esquema)
    return {"recurso": especie, "itens": total, "veiculos": len(veiculos),
            "chamadas": chamadas, "completa": completa,
            "falhas": len(falhas), "fechadas": fechadas}


def coletar_multas(esquema: str | None = None) -> dict:
    return _varrer("veiculos_com_multa", "multas", "multa", {}, {}, esquema)


def coletar_notificacoes(dias: int = 365, esquema: str | None = None) -> dict:
    """Notificações a partir de uma data de pesquisa.

    A janela é generosa de propósito: a notificação é o estágio em que ainda
    cabe indicar condutor, e uma janela curta esconderia justamente a que
    ainda dá para tratar.
    """
    desde = _br(_hoje() - timedelta(days=dias))
    return _varrer("veiculos_com_notificacao", "notificacoes", "notificacao",
                   {"DataPesquisa": desde}, {"DataPesquisa": desde}, esquema)


# ───────────────────────────────────────────────────── sob demanda
def coletar_restricoes(renavams: list[str], esquema: str | None = None) -> dict:
    """Restrições de uma LISTA de veículos. Sob demanda, não agendada."""
    carga = arm.carga_abrir("restricoes", esquema)
    base = _mes_base()
    n = 0
    chamadas = 0
    falhas: list[str] = []

    def _um(rnv: str):
        try:
            return rnv, cliente.chamar("restricoes", Renavam=rnv,
                                       DataBase=base), None
        except Exception as exc:  # noqa: BLE001
            return rnv, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=TRABALHADORES) as ex:
        for rnv, resp, err in ex.map(_um, renavams):
            chamadas += 1
            if err:
                falhas.append(f"{rnv}: {err}")
                continue
            if isinstance(resp, dict):
                n += arm.gravar_restricoes(rnv, "", resp, esquema)
    arm.carga_fechar(carga, "erro" if falhas else ("ok" if n else "vazio"),
                     n, chamadas, falhas[0][:300] if falhas else "", esquema)
    return {"recurso": "restricoes", "itens": n, "chamadas": chamadas,
            "falhas": len(falhas)}


def coletar_custos_veiculo(renavams: list[str],
                           esquema: str | None = None) -> dict:
    """IPVA e taxa de licenciamento de uma lista de veículos."""
    carga = arm.carga_abrir("custos_veiculo", esquema)
    base = _mes_base()
    n = 0
    chamadas = 0
    falhas: list[str] = []

    def _um(rnv: str):
        try:
            ipva = cliente.chamar("ipva", Renavam=rnv, DataBase=base)
            taxa = cliente.chamar("licenciamento_valor", Renavam=rnv,
                                  DataBase=base)
            return rnv, (ipva, taxa), None
        except Exception as exc:  # noqa: BLE001
            return rnv, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=TRABALHADORES) as ex:
        for rnv, par, err in ex.map(_um, renavams):
            chamadas += 2
            if err:
                falhas.append(f"{rnv}: {err}")
                continue
            ipva, taxa = par
            n += arm.gravar_ipva(ipva or [], esquema)
            n += arm.gravar_licenciamento_valor(taxa or [], esquema)
    arm.carga_fechar(carga, "erro" if falhas else ("ok" if n else "vazio"),
                     n, chamadas, falhas[0][:300] if falhas else "", esquema)
    return {"recurso": "custos_veiculo", "itens": n, "chamadas": chamadas,
            "falhas": len(falhas)}


# ───────────────────────────────────────────────────── orquestração
def coletar_tudo(esquema: str | None = None) -> dict:
    """A passagem periódica: só o que devolve a frota inteira barato.

    NÃO PARA NO PRIMEIRO ERRO. Falha do catálogo do CTB não pode impedir a
    coleta das multas — são recursos independentes, e desistir de sete porque
    um caiu é a mesma armadilha do snapshot sequencial do Copiloto.
    """
    if not cliente.configurado():
        return {"ok": False, "erro": "sem_token",
                "mensagem": "Token da Smartec não configurado."}

    passos = (
        ("veiculos", coletar_veiculos),
        ("acessos", coletar_acessos),
        ("multas", coletar_multas),
        ("notificacoes", coletar_notificacoes),
        ("licencas", coletar_licencas),
        ("licenciamento", coletar_licenciamento),
        ("antt", coletar_antt),
        ("catalogos", coletar_catalogos),
    )
    resultado: dict = {"ok": True, "recursos": {}, "erros": {}}
    for nome, fn in passos:
        try:
            resultado["recursos"][nome] = fn(esquema=esquema)
        except Exception as exc:  # noqa: BLE001
            log.warning("smartec: coleta de %s falhou: %s", nome, exc)
            resultado["erros"][nome] = f"{type(exc).__name__}: {exc}"
            resultado["ok"] = False
    return resultado
