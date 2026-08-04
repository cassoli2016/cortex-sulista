"""Motor da previsão de fechamento — 100% PURO (sem banco, sem datas de hoje).

Convenção de sinal = razão da DRE: receita POSITIVA, custo/despesa NEGATIVOS
(valor = credito - debito). Toda fórmula soma; nunca subtrai por natureza.
Cada estratégia devolve {"previsto", "estrategia", "premissas": [str]}.
"""
from __future__ import annotations

from api.previsao.completude import PISO_COMPLETUDE

PESO_DIAS_PLENO = 3  # dias com meta decorridos para o ritmo observado valer 100%


def _res(previsto: float, estrategia: str, premissas: list[str]) -> dict:
    return {"previsto": float(previsto), "estrategia": estrategia,
            "premissas": premissas}


def mediana(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    meio = n // 2
    return s[meio] if n % 2 else (s[meio - 1] + s[meio]) / 2.0


def prever_receita(real_acum: float, meta_acum: float, meta_mes: float,
                   ating_hist: float | None, dias_meta_decorridos: int) -> dict:
    base_hist = ating_hist if ating_hist is not None else 1.0
    ritmo_obs = (real_acum / meta_acum) if meta_acum else None
    w = min(1.0, max(0, dias_meta_decorridos) / PESO_DIAS_PLENO)
    ritmo = (w * ritmo_obs + (1 - w) * base_hist) if ritmo_obs is not None else base_hist
    meta_rest = max(0.0, meta_mes - meta_acum)
    previsto = real_acum + meta_rest * ritmo
    return _res(previsto, "driver_fiscal", [
        f"realizado fiscal MTD R$ {real_acum:,.0f} sobre meta acumulada R$ {meta_acum:,.0f}",
        f"ritmo aplicado ao restante da meta: {ritmo:.1%} "
        f"(observado peso {w:.0%}, historico 3m {base_hist:.1%})",
        f"meta restante do mes: R$ {meta_rest:,.0f}",
    ])


def prever_pct_receita(receita_prev: float, pct: float, nome_pct: str) -> dict:
    return _res(receita_prev * pct, "pct_receita",
                [f"{pct:.2%} da receita prevista ({nome_pct})"])


def prever_nivel(hist: list[float], rotulo_fonte: str) -> dict:
    if not hist:
        return _res(0.0, "nivel", [f"sem historico ({rotulo_fonte})"])
    m = mediana(hist)
    return _res(m, "nivel",
                [f"mediana de {len(hist)} meses fechados ({rotulo_fonte})"])


def prever_razao_completude(razao_mtd: float, frac: float, fallback: dict) -> dict:
    if frac < PISO_COMPLETUDE:
        return _res(fallback["previsto"], fallback["estrategia"],
                    fallback["premissas"] + [
                        f"completude esperada {frac:.0%} abaixo do piso "
                        f"{PISO_COMPLETUDE:.0%} - usando fallback"])
    return _res(razao_mtd / frac, "razao_completude", [
        f"razao MTD R$ {razao_mtd:,.0f} dividido pela completude esperada {frac:.0%}"])


def prever_frete_compra(razao_mtd: float, vfc_mtd: float, receita_prev: float,
                        receita_mtd: float, razao_custo_receita: float) -> dict:
    conhecido = min(razao_mtd, -abs(vfc_mtd))  # mais negativo = mais custo conhecido
    receita_rest = max(0.0, receita_prev - receita_mtd)
    projetado = receita_rest * razao_custo_receita
    return _res(conhecido + projetado, "frete_compra", [
        f"conhecido: max(|razao| R$ {abs(razao_mtd):,.0f}, |frete compra viagens| "
        f"R$ {abs(vfc_mtd):,.0f})",
        f"projecao: {abs(razao_custo_receita):.1%} da receita restante prevista "
        f"(razao custo/receita 6m)"])


def prever_sazonal(vals6: list[float], indices6: list[float],
                   indice_alvo: float) -> dict:
    if not vals6:
        return _res(0.0, "sazonal", ["sem historico"])
    dessaz = [v / i for v, i in zip(vals6, indices6) if i]
    nivel = sum(dessaz) / len(dessaz) if dessaz else 0.0
    return _res(nivel * indice_alvo, "sazonal", [
        f"nivel 6m dessazonalizado R$ {nivel:,.0f} x indice do mes {indice_alvo:.2f}"])
