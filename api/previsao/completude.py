"""Curva de escrituração do razão — PURO (sem banco).

dia_rel = dias desde o 1º dia do mês de COMPETÊNCIA em que o lançamento foi
INCLUÍDO (lancamento.dtinc). Medido nos meses fechados: a fração acumulada do
|movimento| final visível em cada dia. É o divisor da estratégia
razao_completude (mês corrente) e do estimador do mês em fechamento (M-1).

Usa |valor| (movimento absoluto), não o líquido: sinal alternado faria a
fração oscilar e até passar de 1.
"""
from __future__ import annotations

DIA_MAX = 45          # depois disso consideramos o mês 100% escriturado
PISO_COMPLETUDE = 0.30  # abaixo disso NUNCA dividir — usar estratégia de nível


def _frac_media(por_mes: dict[str, dict[int, float]]) -> dict[int, float]:
    """De {mes: {dia: valor_abs}} para {dia: frac acumulada media entre meses}."""
    fracs_por_dia: dict[int, list[float]] = {d: [] for d in range(DIA_MAX + 1)}
    for _mes, dias in por_mes.items():
        total = sum(dias.values())
        if total <= 0:
            continue
        acum = 0.0
        serie: dict[int, float] = {}
        for d in range(DIA_MAX + 1):
            acum += dias.get(d, 0.0)
            serie[d] = acum / total
        for d, f in serie.items():
            fracs_por_dia[d].append(f)
    return {d: (sum(fs) / len(fs)) if fs else 0.0 for d, fs in fracs_por_dia.items()}


def montar_curva(rows: list[dict],
                 mapa_ag_linha: dict[str, str | None]) -> dict:
    ag_mes: dict[str, dict[str, dict[int, float]]] = {}
    linha_mes: dict[str, dict[str, dict[int, float]]] = {}
    glob_mes: dict[str, dict[int, float]] = {}
    for r in rows:
        dia = max(0, min(DIA_MAX, int(r["dia_rel"])))
        v = abs(float(r["valor_abs"]))
        ag = r["agrupador"]
        mes = r["mes"]
        d1 = ag_mes.setdefault(ag, {}).setdefault(mes, {})
        d1[dia] = d1.get(dia, 0.0) + v
        rot = mapa_ag_linha.get(ag)
        if rot:
            d2 = linha_mes.setdefault(rot, {}).setdefault(mes, {})
            d2[dia] = d2.get(dia, 0.0) + v
        d3 = glob_mes.setdefault(mes, {})
        d3[dia] = d3.get(dia, 0.0) + v
    return {
        "ag": {ag: _frac_media(m) for ag, m in ag_mes.items()},
        "linha": {rot: _frac_media(m) for rot, m in linha_mes.items()},
        "global": _frac_media(glob_mes),
    }


def completude_em(curva: dict, agrupador: str | None, linha: str | None,
                  dia_rel: int) -> float:
    dia = max(0, min(DIA_MAX, int(dia_rel)))
    for serie in (
        curva.get("ag", {}).get(agrupador) if agrupador else None,
        curva.get("linha", {}).get(linha) if linha else None,
        curva.get("global") or None,
    ):
        if serie:
            return max(0.0, min(1.0, serie.get(dia, 1.0 if dia >= DIA_MAX else 0.0)))
    return 1.0
