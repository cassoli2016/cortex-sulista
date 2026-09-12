"""A CONTA de horas paradas — pura, sem banco, sem relógio.

Recebe a carga (os horários já com os ajustes aplicados), as linhas do
contrato de freetime do cliente e o perfil de cobrança dele; devolve, por
perna (carga e descarga), quanto tempo o veículo ficou, quanto disso o
contrato cobre, quanto excedeu e quanto vale. Tudo aqui é aritmética, e é por
isso que mora separado da consulta: a regra que MOVE DINHEIRO precisa poder
ser testada contra a planilha que o cliente recebia sem depender do ERP.

AS TRÊS PERGUNTAS DE CADA PERNA, e cada uma tem resposta diferente por cliente:

1. **Quando começa o relógio.** O relatório oficial do ERP conta a partir da
   JANELA, sempre — inclusive quando o caminhão chegou depois dela, e aí
   entram na conta horas em que o veículo nem estava lá. A planilha da
   primeira cliente conta do que vier DEPOIS: chegou antes da janela, vale a
   janela (esperar a hora marcada não é estadia); chegou atrasado, vale a
   chegada. E numa operação dela, em que a janela de carregamento do ERP é
   um horário DERIVADO da entrega e não um compromisso, conta da chegada.
   São três modos (`INICIOS`) e o perfil escolhe — nunca o código.

2. **Quanto o contrato cobre.** Vem de `api/freetime.resolver`, que é a regra
   ÚNICA da casa (a cláusula da mercadoria, senão a genérica). O perfil pode
   declarar exceção por mercadoria e destinatário — e a linha diz qual regra
   respondeu, porque "3h pelo contrato" e "3h porque alguém declarou" são o
   mesmo número e afirmações diferentes.

3. **Como o excedente vira dinheiro.** Por minuto (proporcional) ou
   arredondado PARA CIMA a uma fração. A conta é feita em SEGUNDOS, a unidade
   de origem, e só o valor final é arredondado ao centavo: arredondar a hora
   antes de multiplicar move o total de lado.
"""
from __future__ import annotations

import math
from datetime import datetime

from .. import freetime as _ft

# ── os modos de início do relógio ───────────────────────────────────────────
CHEGADA = "chegada"   # da chegada, ignorando a janela
JANELA = "janela"     # da janela, sempre (a fórmula do relatório do ERP)
MAIOR = "maior"       # do que vier depois: janela ou chegada
INICIOS = (CHEGADA, JANELA, MAIOR)

# ── arredondamento do excedente, em minutos (0 = por minuto, proporcional) ──
ARREDONDAMENTOS = (0, 15, 30, 60)

PERNAS = ("carga", "descarga")

# ── o estado de cada perna ──────────────────────────────────────────────────
OK = "ok"
SEM_APONTAMENTO = "sem_apontamento"   # falta chegada ou saída: não se calcula
SEM_CONTRATO = "sem_contrato"         # sem freetime: não se inventa um


def _norm_lista(v) -> tuple:
    return tuple(sorted({_ft.normalizar(x) for x in (v or []) if (x or "").strip()}))


def regra_casa(regra: dict, carga: dict, perna: str) -> bool:
    """A regra do perfil vale para esta perna desta carga?

    Mercadoria casa pela normalização da casa (maiúscula, acento, plural) e
    NADA MAIS — sem prefixo, sem "contém". Destinatário casa pelo CÓDIGO do
    cadastro, nunca pelo nome: o nome de uma planta muda de grafia no
    cadastro e a regra deixaria de valer sem ninguém ver.
    """
    p = regra.get("perna") or "ambas"
    if p != "ambas" and p != perna:
        return False
    mercs = _norm_lista(regra.get("mercadorias"))
    if mercs and _ft.normalizar(carga.get("mercadoria")) not in mercs:
        return False
    dests = {str(d).strip() for d in (regra.get("destinos") or []) if str(d).strip()}
    if dests and str(carga.get("destinatario_codigo") or "").strip() not in dests:
        return False
    return True


def primeira_regra(regras: list[dict], carga: dict, perna: str) -> dict | None:
    """A PRIMEIRA que casa responde. Ordem é decisão de quem cadastra —
    "rodas para a montadora: contrato; rodas para o resto: genérica" só se
    escreve assim, com a específica antes da geral."""
    for r in regras or []:
        if regra_casa(r, carga, perna):
            return r
    return None


def clausula(linhas: list[dict], mercadoria: str | None,
             forcar_generica: bool = False) -> dict | None:
    """A cláusula do contrato para esta carga, pela regra ÚNICA da casa.

    `forcar_generica` existe para a exceção declarada no perfil ("esta
    mercadoria NÃO usa a cláusula que o nome sugere"): volta a genérica do
    contrato, e, sem genérica, o último recurso de `freetime.resolver`.
    """
    if not linhas:
        return None
    if forcar_generica:
        for ln in linhas:
            if not ln.get("mercadoria"):
                return dict(ln, origem=_ft.GENERICO)
        return _ft.resolver(linhas, None)
    return _ft.resolver(linhas, mercadoria)


def inicio_do_relogio(janela: datetime | None, chegada: datetime | None,
                      modo: str) -> tuple[datetime | None, str | None]:
    """Quando o relógio da perna começa, e POR QUÊ (qual dos dois horários).

    Sem chegada não há relógio em modo nenhum: sem prova de que o veículo
    estava lá, a janela sozinha não é estadia.
    """
    if chegada is None:
        return None, None
    if modo == CHEGADA or janela is None:
        return chegada, CHEGADA
    if modo == JANELA:
        return janela, JANELA
    return (janela, JANELA) if janela > chegada else (chegada, CHEGADA)


def arredondar(segundos: float, minutos: int) -> float:
    """O excedente cobrado. `0` = proporcional; senão, PARA CIMA à fração."""
    if segundos <= 0:
        return 0.0
    if not minutos:
        return float(segundos)
    passo = minutos * 60
    return float(math.ceil(segundos / passo - 1e-9) * passo)


def _horas(v) -> float | None:
    """Freetime do contrato: `timedelta` (o ERP), número de horas, ou None."""
    if v is None:
        return None
    if hasattr(v, "total_seconds"):
        return v.total_seconds() / 3600
    return float(v)


def perna(carga: dict, nome: str, contrato: list[dict], perfil: dict) -> dict:
    """A conta de UMA perna. `carga` traz `<nome>_janela/_chegada/_saida`."""
    janela = carga.get(nome + "_janela")
    chegada = carga.get(nome + "_chegada")
    saida = carga.get(nome + "_saida")

    regra = primeira_regra(perfil.get("regras") or [], carga, nome)
    # `None` num campo da regra é HERDA, nunca zero (regra da casa).
    modo = (regra or {}).get("inicio") or perfil.get("inicio_" + nome) or MAIOR
    cl = clausula(contrato, carga.get("mercadoria"),
                  forcar_generica=(regra or {}).get("clausula") == "generica")

    ft_h = (regra or {}).get("freetime_h")
    if ft_h is None and cl is not None:
        ft_h = _horas(cl.get("ft_carga_h" if nome == "carga" else "ft_descarga_h"))
    valor_h = (regra or {}).get("valor_h")
    if valor_h is None and cl is not None:
        v = cl.get("valor_coleta" if nome == "carga" else "valor_entrega")
        valor_h = float(v) if v is not None else None

    inicio, inicio_de = inicio_do_relogio(janela, chegada, modo)
    out = {
        "janela": janela, "chegada": chegada, "saida": saida,
        "inicio": inicio, "inicio_de": inicio_de, "modo": modo,
        "freetime_h": ft_h, "valor_h": valor_h,
        "clausula": (cl or {}).get("origem"),
        "clausula_mercadoria": (cl or {}).get("mercadoria") or None,
        "regra": (regra or {}).get("nome") or (None if regra is None else "regra sem nome"),
        "tempo_s": None, "excedente_s": 0.0, "cobrado_s": 0.0, "valor": 0.0,
    }
    if inicio is None or saida is None:
        out["estado"] = SEM_APONTAMENTO
        return out
    # O TEMPO PODE SER NEGATIVO, e fica negativo: saiu antes da janela é um
    # FATO que a planilha mostra, não um erro a esconder. Só o excedente é
    # limitado a zero.
    out["tempo_s"] = (saida - inicio).total_seconds()
    if ft_h is None or valor_h is None:
        out["estado"] = SEM_CONTRATO
        return out
    out["estado"] = OK
    out["excedente_s"] = max(0.0, out["tempo_s"] - ft_h * 3600)
    out["cobrado_s"] = arredondar(out["excedente_s"],
                                  int(perfil.get("arredondamento_min") or 0))
    out["valor"] = round(out["cobrado_s"] / 3600 * valor_h, 2)
    return out


def calcular(carga: dict, contrato: list[dict], perfil: dict) -> dict:
    """As duas pernas e o total da carga."""
    pernas = {n: perna(carga, n, contrato, perfil) for n in PERNAS}
    return {
        "carga": pernas["carga"], "descarga": pernas["descarga"],
        "valor": round(sum(p["valor"] for p in pernas.values()), 2),
        "cobrado_s": sum(p["cobrado_s"] for p in pernas.values()),
    }
