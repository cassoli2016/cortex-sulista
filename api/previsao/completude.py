"""Curva de escrituração do razão — PURO (sem banco).

dia_rel = dias desde o 1º dia do mês de COMPETÊNCIA em que o lançamento foi
INCLUÍDO (lancamento.dtinc). Medido nos meses fechados: a fração acumulada do
|movimento| final visível em cada dia. É o divisor da estratégia
razao_completude (mês corrente) e do estimador do mês em fechamento (M-1).

Usa |valor| (movimento absoluto), não o líquido: sinal alternado faria a
fração oscilar e até passar de 1.

Escrituração BIMODAL (lote): algumas linhas não escrituram num ritmo único —
alguns meses fecham cedo (quase tudo lançado em poucos dias) e outros ficam
represados até um lote tardio (ex.: receita medida ao vivo: fev/mar/mai
escrituravam só 2-4% até D+34 contra 83-100% em abr/jun/jul, com o lote
tardio só chegando perto de D+58). A MÉDIA entre os meses não representa
NENHUM dos dois grupos — dividir a razão de um mês "cedo" por essa média
dobra a previsão; um mês "tardio" fica esmagado. `montar_curva` também
calcula, por dia, a DISPERSÃO (desvio-padrão populacional) das frações mês a
mês — um sinal de "a curva-média não é confiável aqui" — para as
estratégias em completude.py/motor.py decidirem NÃO dividir nesse caso.
"""
from __future__ import annotations

DIA_MAX = 45          # depois disso consideramos o mês 100% escriturado
PISO_COMPLETUDE = 0.30  # abaixo disso NUNCA dividir — usar estratégia de nível
DISPERSAO_MAX = 0.35  # acima disso a curva-media e' bimodal - NUNCA dividir


def _frac_e_dispersao(por_mes: dict[str, dict[int, float]]
                      ) -> tuple[dict[int, float], dict[int, float]]:
    """De {mes: {dia: valor_abs}} para (frac acumulada media entre meses,
    dispersao = desvio-padrao populacional das fracoes de cada mes nesse dia).

    Ambos retornam {} (dict vazio/falsy) quando NENHUM mês contribuiu
    movimento positivo, permitindo a cascata em completude_em/dispersao_em
    cair para o próximo nível ou o neutro.
    """
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
    # Se nenhum mês contribuiu dados (all lists empty), retorna {} (falsy)
    if not any(fracs_por_dia.values()):
        return {}, {}
    frac = {d: (sum(fs) / len(fs)) if fs else 0.0 for d, fs in fracs_por_dia.items()}
    disp: dict[int, float] = {}
    for d, fs in fracs_por_dia.items():
        if len(fs) < 2:
            disp[d] = 0.0  # 1 mes so' nao mede dispersao - trata como confiavel
            continue
        m = sum(fs) / len(fs)
        var = sum((f - m) ** 2 for f in fs) / len(fs)
        disp[d] = var ** 0.5
    return frac, disp


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
    ag_frac: dict[str, dict[int, float]] = {}
    ag_disp: dict[str, dict[int, float]] = {}
    for ag, m in ag_mes.items():
        ag_frac[ag], ag_disp[ag] = _frac_e_dispersao(m)
    linha_frac: dict[str, dict[int, float]] = {}
    linha_disp: dict[str, dict[int, float]] = {}
    for rot, m in linha_mes.items():
        linha_frac[rot], linha_disp[rot] = _frac_e_dispersao(m)
    glob_frac, glob_disp = _frac_e_dispersao(glob_mes)
    return {
        "ag": ag_frac, "linha": linha_frac, "global": glob_frac,
        # espelham "ag"/"linha"/"global" na forma ({rotulo: {dia: valor}}) —
        # consumidores que so' conhecem as 3 chaves originais ignoram estas.
        "ag_disp": ag_disp, "linha_disp": linha_disp, "global_disp": glob_disp,
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


def dispersao_em(curva: dict, agrupador: str | None, linha: str | None,
                 dia_rel: int) -> float:
    """Mesma cascata ag -> linha -> global de completude_em, para o desvio-
    padrão populacional das frações mês a mês (ver docstring do módulo).
    0.0 (neutro - "curva confiável") quando a série está ausente."""
    dia = max(0, min(DIA_MAX, int(dia_rel)))
    for serie in (
        curva.get("ag_disp", {}).get(agrupador) if agrupador else None,
        curva.get("linha_disp", {}).get(linha) if linha else None,
        curva.get("global_disp") or None,
    ):
        if serie:
            return max(0.0, serie.get(dia, 0.0))
    return 0.0
