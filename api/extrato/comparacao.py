"""Cruzamento do extrato importado com o `contacorrente_saldo` do ERP.

Função pura: recebe as duas listas e devolve a comparação por conta x dia. Isso
mantém o cálculo testável sem AVA e sem SQLite.

Saldo: o extrato traz o saldo final (LEDGERBAL) numa data só, então o saldo dos
demais dias é DERIVADO a partir dessa âncora, somando/subtraindo o líquido de
cada dia. Sem âncora, `ext_saldo` fica None e o dia é julgado só pelo fluxo -
dizer "saldo divergente" sem ter saldo do banco seria falso positivo.
"""
from __future__ import annotations

from datetime import date

TOLERANCIA = 0.01


def agregar_extrato(lancs: list[dict]) -> dict[str, dict]:
    por_dia: dict[str, dict] = {}
    for l in lancs:
        d = por_dia.setdefault(l["dt"], {"credito": 0.0, "debito": 0.0,
                                         "liquido": 0.0, "qtd": 0})
        valor = float(l["valor"])
        if valor >= 0:
            d["credito"] += valor
        else:
            d["debito"] += -valor
        d["liquido"] += valor
        d["qtd"] += 1
    return por_dia


def saldo_derivado(por_dia: dict[str, dict], saldos: list[dict]) -> dict[str, float | None]:
    if not saldos:
        return {}
    ancora = max(saldos, key=lambda s: s["dt"])
    datas = sorted(set(por_dia) | {ancora["dt"]})
    out: dict[str, float | None] = {ancora["dt"]: float(ancora["saldo"])}
    # para trás: saldo do dia anterior = saldo do dia - liquido do dia
    i = datas.index(ancora["dt"])
    for k in range(i, 0, -1):
        liq = por_dia.get(datas[k], {}).get("liquido", 0.0)
        out[datas[k - 1]] = out[datas[k]] - liq
    # para frente: saldo do dia = saldo anterior + liquido do dia
    for k in range(i + 1, len(datas)):
        liq = por_dia.get(datas[k], {}).get("liquido", 0.0)
        out[datas[k]] = out[datas[k - 1]] + liq
    return out


def _difere(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    # round antes de comparar: em ponto flutuante, abs(100.0 - 100.01) vale
    # 0.010000000000005116 (erro de representacao binaria), nao 0.01 exato.
    # Sem o round(), a tolerancia de 1 centavo deixaria de ser inclusiva para
    # justamente o caso que ela existe para cobrir.
    return round(abs(a - b), 2) > TOLERANCIA


def comparar(lancs: list[dict], saldos: list[dict], erp_rows: list[dict]) -> list[dict]:
    por_dia = agregar_extrato(lancs)
    saldo_ext = saldo_derivado(por_dia, saldos)
    erp = {r["dt"]: r for r in erp_rows}
    out: list[dict] = []
    # inclui as datas que so existem em saldo_ext: a ancora do LEDGERBAL pode cair
    # num dia sem lancamento E sem linha no ERP - sem isso a data nao aparece na
    # saida e um saldo do banco que o ERP nao registrou fica invisivel (mesma
    # classe de bug do "SO_ERP" indevido, um nivel mais raro).
    for dt in sorted(set(por_dia) | set(erp) | set(saldo_ext)):
        e = por_dia.get(dt)
        r = erp.get(dt)
        ext_c = e["credito"] if e else None
        ext_d = e["debito"] if e else None
        ext_s = saldo_ext.get(dt)
        erp_c = float(r["credito"]) if r and r.get("credito") is not None else None
        erp_d = float(r["debito"]) if r and r.get("debito") is not None else None
        erp_s = float(r["saldo"]) if r and r.get("saldo") is not None else None
        # "tem extrato" nao e so "tem lancamento": a ancora do LEDGERBAL pode cair
        # num dia sem movimento (ex.: fechamento do arquivo) e mesmo assim ter
        # ext_saldo. Julgar so por `e is None` classificava esse dia como SO_ERP e
        # jogava fora uma divergencia real de saldo (ficava invisivel pro farol).
        tem_extrato = e is not None or ext_s is not None
        tem_erp = r is not None
        if not tem_extrato:
            estado = "SO_ERP"
        elif not tem_erp:
            estado = "SO_EXTRATO"
        elif _difere(ext_c, erp_c) or _difere(ext_d, erp_d) or _difere(ext_s, erp_s):
            estado = "DIVERGE"
        else:
            estado = "OK"
        out.append({
            "dt": dt, "estado": estado, "qtd": (e["qtd"] if e else 0),
            "ext_credito": ext_c, "ext_debito": ext_d, "ext_saldo": ext_s,
            "erp_credito": erp_c, "erp_debito": erp_d, "erp_saldo": erp_s,
            "d_credito": (ext_c - erp_c) if not (ext_c is None or erp_c is None) else None,
            "d_debito": (ext_d - erp_d) if not (ext_d is None or erp_d is None) else None,
            "d_saldo": (ext_s - erp_s) if not (ext_s is None or erp_s is None) else None,
        })
    return out


def _dias_entre(de: str, ate: str) -> int:
    return (date.fromisoformat(ate) - date.fromisoformat(de)).days


def _maior_delta(dia: dict | None) -> tuple[float | None, str | None]:
    """Maior divergência em módulo entre saldo/crédito/débito do dia, com o
    sinal do escolhido e a origem (mesmo padrão de `servico.painel()` ao achar
    o "pior" dia, ~linhas 198-207 - reaproveitado aqui na fonte).

    DIVERGE pode disparar por qualquer um dos três campos (`comparar()`), e
    `d_saldo` é `None` sempre que falta saldo de um dos lados - garantido para
    TODA conta importada via CSV, porque `parser_csv` nunca traz saldo e o
    serviço só grava `saldo_extrato` no caminho OFX. Usar `d.get("d_saldo") or
    0.0` (truthiness) faria uma divergência real de crédito/débito virar
    "R$ 0,00" com direção arbitrária - por isso aqui é sempre `is not None`,
    nunca truthiness, e o candidato descartado (`None`) nunca compete no `max`.
    """
    if dia is None:
        return None, None
    candidatos = [(origem, v) for origem, v in
                  (("saldo", dia.get("d_saldo")), ("credito", dia.get("d_credito")),
                   ("debito", dia.get("d_debito"))) if v is not None]
    if not candidatos:
        return None, None
    origem, valor = max(candidatos, key=lambda item: abs(item[1]))
    return valor, origem


def farol(dias: list[dict], ultimo_upload: str | None, hoje: str,
          mapeada: bool = True) -> dict:
    """Estado da conta = o último dia coberto pelo extrato.

    Ordem de precedência: sem mapeamento ERP (não há o que comparar) > extrato
    velho (o verde de 12 dias atrás não diz nada sobre hoje) > divergência.

    `delta_origem` ("saldo"|"credito"|"debito"|None) diz de onde veio `delta` -
    necessário porque a semântica de direção só existe para saldo: `d_debito`
    positivo significa que o extrato debitou MAIS que o ERP, o que EMPURRA o
    saldo para BAIXO (o oposto de "acima"). Quem lê `delta_origem` decide se
    "acima"/"abaixo" fazem sentido (só quando == "saldo").
    """
    validos = [d for d in dias if d["estado"] in ("OK", "DIVERGE")]
    ultimo = max(validos, key=lambda d: d["dt"]) if validos else None
    dias_sem = _dias_entre(ultimo_upload, hoje) if ultimo_upload else None
    if not mapeada:
        return {"estado": "sem_mapa", "dt": (ultimo or {}).get("dt"),
                "delta": None, "delta_origem": None, "dias_sem_extrato": dias_sem}
    delta, origem = _maior_delta(ultimo)
    if ultimo is None or dias_sem is None or dias_sem > 7:
        return {"estado": "desatualizado", "dt": (ultimo or {}).get("dt"),
                "delta": delta, "delta_origem": origem, "dias_sem_extrato": dias_sem}
    if ultimo["estado"] == "DIVERGE":
        return {"estado": "diverge", "dt": ultimo["dt"],
                "delta": delta, "delta_origem": origem, "dias_sem_extrato": dias_sem}
    # estado OK: o dia pode ter um residuo sub-tolerancia em d_saldo/d_credito/
    # d_debito (ex.: arredondamento) mesmo sem DIVERGIR - reportar esse residuo
    # como se fosse "a diferenca do dia" contradiz o proprio veredito "bate com
    # o banco" que este farol acabou de dar. delta/delta_origem ficam None,
    # mesmo contrato de "sem_mapa" (nenhum valor a mostrar).
    return {"estado": "ok", "dt": ultimo["dt"], "delta": None, "delta_origem": None,
            "dias_sem_extrato": dias_sem}
