"""Motor da previsão de fechamento — 100% PURO (sem banco, sem datas de hoje).

Convenção de sinal = razão da DRE: receita POSITIVA, custo/despesa NEGATIVOS
(valor = credito - debito). Toda fórmula soma; nunca subtrai por natureza.
Cada estratégia devolve {"previsto", "estrategia", "premissas": [str]}.
"""
from __future__ import annotations

import unicodedata

from api.queries import DRE_MODELO
from api.previsao.completude import PISO_COMPLETUDE, completude_em

PESO_DIAS_PLENO = 3  # dias com meta decorridos para o ritmo observado valer 100%


def _brl(v: float) -> str:
    """Formata valor em R$ pt-BR (X.XXX,XX sem centavos, já que todas as estimativas são inteiras)."""
    s = f"{v:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _pct(v: float, casas: int = 1) -> str:
    """Formata percentual em pt-BR (XX,X%) — casas = casa decimais após a vírgula."""
    return f"{v*100:.{casas}f}%".replace(".", ",")


def _num(v: float, casas: int = 2) -> str:
    """Formata número decimal em pt-BR (X,XX) — para índices e outras métricas."""
    return f"{v:.{casas}f}".replace(".", ",")


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
        f"realizado fiscal MTD {_brl(real_acum)} sobre meta acumulada {_brl(meta_acum)}",
        f"ritmo aplicado ao restante da meta: {_pct(ritmo, 1)} "
        f"(observado peso {_pct(w, 0)}, historico 3m {_pct(base_hist, 1)})",
        f"meta restante do mes: {_brl(meta_rest)}",
    ])


def prever_pct_receita(receita_prev: float, pct: float, nome_pct: str) -> dict:
    return _res(receita_prev * pct, "pct_receita",
                [f"{_pct(pct, 2)} da receita prevista ({nome_pct})"])


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
                        f"completude esperada {_pct(frac, 0)} abaixo do piso "
                        f"{_pct(PISO_COMPLETUDE, 0)} - usando fallback"])
    return _res(razao_mtd / frac, "razao_completude", [
        f"razao MTD {_brl(razao_mtd)} dividido pela completude esperada {_pct(frac, 0)}"])


def prever_frete_compra(razao_mtd: float, vfc_mtd: float, receita_prev: float,
                        receita_mtd: float, razao_custo_receita: float) -> dict:
    conhecido = min(razao_mtd, -abs(vfc_mtd))  # mais negativo = mais custo conhecido
    receita_rest = max(0.0, receita_prev - receita_mtd)
    projetado = receita_rest * razao_custo_receita
    return _res(conhecido + projetado, "frete_compra", [
        f"conhecido: max(|razao| {_brl(abs(razao_mtd))}, |frete compra viagens| "
        f"{_brl(abs(vfc_mtd))})",
        f"projecao: {_pct(abs(razao_custo_receita), 1)} da receita restante prevista "
        f"(razao custo/receita 6m)"])


def prever_sazonal(vals6: list[float], indices6: list[float],
                   indice_alvo: float) -> dict:
    if not vals6:
        return _res(0.0, "sazonal", ["sem historico"])
    dessaz = [v / i for v, i in zip(vals6, indices6) if i]
    nivel = sum(dessaz) / len(dessaz) if dessaz else 0.0
    return _res(nivel * indice_alvo, "sazonal", [
        f"nivel 6m dessazonalizado {_brl(nivel)} x indice do mes {_num(indice_alvo, 2)}"])


CONSOLIDADO_EM = 0.97  # completude esperada a partir da qual o razao e a verdade


def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s.upper()).encode("ascii", "ignore").decode()


def linha_do_agrupador(ag: str) -> str | None:
    na = norm(ag)
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            continue
        for s in sel:
            ns = norm(s)
            if (tipo == "nome" and na == ns) or (tipo == "pref" and na.startswith(ns)):
                return rotulo
    return None


_ESTRATEGIA_PREFIXOS = [
    ("CV - FRETE AGREGADOS", "frete_compra"),
    ("CV - FRETE TERCEIROS", "frete_compra"),
    ("CF - FOLHA", "nivel"),
    ("CF - PESSOAL", "nivel"),
    ("OVERHEAD - FOLHA", "nivel"),
    ("CR - ", "nivel"),
    ("CV - ", "razao_completude"),
    ("CF - ", "razao_completude"),
    ("OVERHEAD - ", "razao_completude"),
    ("FINANC - ", "sazonal"),
    ("INDENIZA", "sazonal"),
    ("OUTRAS ", "sazonal"),
    ("(1, ", "sazonal"),
    ("DESPESAS N", "sazonal"),
    ("RECEITA - VENDA", "sazonal"),
    ("ANULA", "sazonal"),
    ("DESCONTOS", "sazonal"),
]


def estrategia_do_agrupador(ag: str) -> str:
    na = norm(ag)
    for pref, estrat in _ESTRATEGIA_PREFIXOS:
        if na.startswith(norm(pref)):
            return estrat
    return "runrate"


def montar_cascata(direta: dict[str, float]) -> dict[str, float]:
    """Preenche todas as linhas do DRE_MODELO: diretas primeiro, fórmulas em
    ordem de declaração (mesma 2-passada do get_dre)."""
    out: dict[str, float] = {}
    for rotulo, _nivel, tipo, _sel in DRE_MODELO:
        if tipo != "formula":
            out[rotulo] = float(direta.get(rotulo, 0.0))
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            out[rotulo] = sum(out.get(r, 0.0) for r in sel)
    return out


def banda_fallback(base: float, hist6: list[float],
                   frac_restante: float) -> tuple[float, float]:
    if len(hist6) < 2:
        return base, base
    media = sum(hist6) / len(hist6)
    var = sum((v - media) ** 2 for v in hist6) / len(hist6)
    meio = (var ** 0.5) * max(0.0, min(1.0, frac_restante))
    return base - meio, base + meio


def banda_calibrada(base: float, calib_linha: dict | None,
                    dia_util: int) -> tuple[float, float] | None:
    if not calib_linha:
        return None
    dias = sorted(int(d) for d in calib_linha)
    if not dias:
        return None
    d = max(dias[0], min(dias[-1], dia_util))
    lo = max(x for x in dias if x <= d)
    hi = min(x for x in dias if x >= d)
    w = 0.0 if hi == lo else (d - lo) / (hi - lo)
    def _mix(campo: str) -> float:
        a = calib_linha[str(lo)][campo]
        b = calib_linha[str(hi)][campo]
        return a + (b - a) * w
    esc = abs(base)
    return base + _mix("p20") * esc, base + _mix("p80") * esc


def aplicar_ajuste(previsto: float, ajuste: dict | None) -> tuple[float, float]:
    if not ajuste:
        return previsto, 0.0
    if ajuste["tipo"] == "delta":
        return previsto + ajuste["valor"], ajuste["valor"]
    return ajuste["valor"], ajuste["valor"] - previsto


def estimar_m1(razao_ag: dict[str, float], curva: dict, dia_rel: int,
               fallback_por_ag: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ag, valor in razao_ag.items():
        rot = linha_do_agrupador(ag)
        frac = completude_em(curva, ag, rot, dia_rel)
        if frac >= CONSOLIDADO_EM:
            out[ag] = _res(valor, "consolidado",
                           [f"razao {_pct(frac, 0)} escriturado - consolidado"])
        elif frac < PISO_COMPLETUDE:
            fb = fallback_por_ag.get(ag) or _res(valor, "razao_parcial",
                                                 ["sem fallback disponivel"])
            out[ag] = _res(fb["previsto"], fb["estrategia"], fb["premissas"] + [
                f"completude esperada {_pct(frac, 0)} abaixo do piso - fallback"])
        else:
            out[ag] = _res(valor / frac, "razao_completude", [
                f"razao parcial {_brl(valor)} / completude esperada {_pct(frac, 0)}"])
    return out
