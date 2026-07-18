"""Consultas da FOLHA (ERP GLOBUS, Oracle) — leitura, agregadas.

Fonte: Querys Sulista/GLOBUS. Conecta via api/db_folha (thick, read-only).
PII: a folha é o dado mais sensível — estas funções entregam SÓ agregados
(headcount e custo por área/função/filial/competência). Nunca expõem nome,
CPF, salário individual ou dado bancário.
"""
from __future__ import annotations

from . import db_folha as db

EMPRESA = 1   # codigoempresa da Sulista no GLOBUS


def _q(sql: str, params: dict | None = None) -> list[dict]:
    return db.query(sql, params or {})


# ============================================================================
# Headcount — quadro ativo, admissões/demissões, tempo de casa, diversidade
# ============================================================================
def get_headcount() -> dict:
    p = {"emp": EMPRESA}
    base = "FROM vw_funcionarios WHERE codigoempresa = :emp AND situacaofunc = 'A'"

    tot = _q(f"""SELECT COUNT(*) ativos, ROUND(SUM(salbase),2) massa_base,
                 ROUND(AVG((SYSDATE - dtadmfunc)/365),1) tempo_casa_anos,
                 SUM(CASE WHEN sexofunc='F' THEN 1 ELSE 0 END) mulheres,
                 SUM(CASE WHEN sexofunc='M' THEN 1 ELSE 0 END) homens {base}""", p)[0]

    adm12 = _q("""SELECT COUNT(*) n FROM vw_funcionarios
                  WHERE codigoempresa = :emp
                    AND dtadmfunc >= ADD_MONTHS(TRUNC(SYSDATE), -12)""", p)[0]["n"]

    por_filial = _q(f"SELECT descsecao rotulo, COUNT(*) n {base} GROUP BY descsecao ORDER BY 2 DESC", p)
    por_area = _q(f"SELECT descarea rotulo, COUNT(*) n {base} GROUP BY descarea ORDER BY 2 DESC "
                  "FETCH FIRST 15 ROWS ONLY", p)
    por_funcao = _q(f"SELECT descfuncao rotulo, COUNT(*) n {base} GROUP BY descfuncao ORDER BY 2 DESC "
                    "FETCH FIRST 15 ROWS ONLY", p)

    tempo_casa = _q(f"""SELECT faixa, COUNT(*) n FROM (
        SELECT CASE
          WHEN (SYSDATE - dtadmfunc)/30 <= 3  THEN '01 · até 3 meses'
          WHEN (SYSDATE - dtadmfunc)/30 <= 12 THEN '02 · até 1 ano'
          WHEN (SYSDATE - dtadmfunc)/30 <= 24 THEN '03 · até 2 anos'
          WHEN (SYSDATE - dtadmfunc)/30 <= 60 THEN '04 · até 5 anos'
          ELSE '05 · acima de 5 anos' END faixa
        {base}) GROUP BY faixa ORDER BY faixa""", p)

    # movimentação 12m (admissões confiáveis; demissões por término de contrato,
    # só datas passadas — aproximado)
    adm_m = _q("""SELECT TO_CHAR(dtadmfunc,'YYYY-MM') m, COUNT(*) n FROM vw_funcionarios
                  WHERE codigoempresa = :emp AND dtadmfunc >= ADD_MONTHS(TRUNC(SYSDATE),-12)
                  GROUP BY TO_CHAR(dtadmfunc,'YYYY-MM')""", p)
    # Demissões pela FOLHA DE RESCISÃO: funcionário com evento de aviso prévio
    # na competência (fonte real; DATATERMINOCONTRATO subcontava muito).
    dem_m = _q("""SELECT TO_CHAR(ff.competficha,'YYYY-MM') m, COUNT(DISTINCT ff.codintfunc) n
                  FROM flp_fichaeventos ff
                  JOIN flp_eventos fe ON ff.codevento = fe.codevento
                  JOIN flp_funcionarios fu ON fu.codintfunc = ff.codintfunc AND fu.codigoempresa = :emp
                  WHERE UPPER(fe.desceven) LIKE 'AVISO PREVIO%'
                    AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -12)
                  GROUP BY TO_CHAR(ff.competficha,'YYYY-MM')""", p)
    adm_map = {r["m"]: r["n"] for r in adm_m}
    dem_map = {r["m"]: r["n"] for r in dem_m}
    from datetime import date
    hoje = date.today()
    movimentacao = []
    for i in range(11, -1, -1):
        y = hoje.year + (hoje.month - 1 - i) // 12
        mo = (hoje.month - 1 - i) % 12 + 1
        k = f"{y}-{mo:02d}"
        movimentacao.append({"mes": k, "admissoes": adm_map.get(k, 0), "demissoes": dem_map.get(k, 0)})
    dem12 = sum(d["demissoes"] for d in movimentacao)

    def _rows(rs):
        return [{"rotulo": (r["rotulo"] or "—"), "n": r["n"]} for r in rs]

    return {
        "kpis": {
            "ativos": tot["ativos"], "admissoes_12m": adm12, "demissoes_12m": dem12,
            "massa_base": tot["massa_base"] or 0.0,
            "tempo_casa_anos": tot["tempo_casa_anos"] or 0.0,
            "mulheres": tot["mulheres"], "homens": tot["homens"],
            # turnover anual aproximado = média(adm, dem) / headcount (demissão é estimada)
            "turnover_pct": round(100 * ((adm12 + dem12) / 2) / tot["ativos"], 1) if tot["ativos"] else 0.0,
        },
        "por_filial": _rows(por_filial),
        "por_area": _rows(por_area),
        "por_funcao": _rows(por_funcao),
        "tempo_casa": [{"faixa": r["faixa"], "n": r["n"]} for r in tempo_casa],
        "movimentacao": movimentacao,
        "fonte": "GLOBUS · VW_FUNCIONARIOS (quadro ativo, empresa 1) · agregado · leitura",
    }


# ============================================================================
# Custo de folha — proventos/descontos por competência e centro de custo
# ============================================================================
def _comp_default() -> str:
    r = _q("""SELECT MAX(TO_CHAR(competficha,'YYYY-MM')) c FROM vw_fichafinaneventos
              WHERE codigoempresa = :emp AND competficha < TRUNC(SYSDATE,'MM')""",
           {"emp": EMPRESA})
    return (r[0]["c"] if r and r[0]["c"] else None)


def get_custo_folha(comp: str | None = None) -> dict:
    comp = comp or _comp_default()
    p = {"emp": EMPRESA, "comp": comp}
    PROV = "SUM(CASE WHEN tipoeven='P' THEN valorficha ELSE 0 END)"
    DESC = "SUM(CASE WHEN tipoeven='D' THEN valorficha ELSE 0 END)"

    tot = _q(f"""SELECT ROUND({PROV},2) prov, ROUND({DESC},2) descontos,
                 COUNT(DISTINCT codfunc) funcs
                 FROM vw_fichafinaneventos
                 WHERE codigoempresa=:emp AND TO_CHAR(competficha,'YYYY-MM')=:comp""", p)[0]

    por_cc_raw = _q(f"""SELECT codarea, ROUND({PROV},2) prov, ROUND({DESC},2) descontos,
                        COUNT(DISTINCT codfunc) funcs
                        FROM vw_fichafinaneventos
                        WHERE codigoempresa=:emp AND TO_CHAR(competficha,'YYYY-MM')=:comp
                        GROUP BY codarea ORDER BY prov DESC""", p)
    area_map = {r["codarea"]: r["descarea"] for r in _q(
        "SELECT DISTINCT codarea, descarea FROM vw_funcionarios "
        "WHERE codigoempresa=:emp AND descarea IS NOT NULL", {"emp": EMPRESA})}
    por_cc = [{
        "cc": area_map.get(r["codarea"], f"Área {r['codarea']}"),
        "prov": r["prov"] or 0.0, "descontos": r["descontos"] or 0.0,
        "liquido": round((r["prov"] or 0.0) - (r["descontos"] or 0.0), 2),
        "funcs": r["funcs"],
    } for r in por_cc_raw]

    top_prov = _q(f"""SELECT desceven ev, ROUND(SUM(valorficha),2) tot
                      FROM vw_fichafinaneventos
                      WHERE codigoempresa=:emp AND TO_CHAR(competficha,'YYYY-MM')=:comp AND tipoeven='P'
                      GROUP BY desceven ORDER BY 2 DESC FETCH FIRST 12 ROWS ONLY""", p)
    top_desc = _q(f"""SELECT desceven ev, ROUND(SUM(valorficha),2) tot
                      FROM vw_fichafinaneventos
                      WHERE codigoempresa=:emp AND TO_CHAR(competficha,'YYYY-MM')=:comp AND tipoeven='D'
                      GROUP BY desceven ORDER BY 2 DESC FETCH FIRST 12 ROWS ONLY""", p)

    serie = _q(f"""SELECT TO_CHAR(competficha,'YYYY-MM') comp, ROUND({PROV},2) prov, ROUND({DESC},2) descontos
                   FROM vw_fichafinaneventos WHERE codigoempresa=:emp
                     AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'), -12)
                   GROUP BY TO_CHAR(competficha,'YYYY-MM') ORDER BY 1""", {"emp": EMPRESA})
    comps = _q("""SELECT TO_CHAR(competficha,'YYYY-MM') c FROM vw_fichafinaneventos
                  WHERE codigoempresa=:emp GROUP BY TO_CHAR(competficha,'YYYY-MM')
                  ORDER BY 1 DESC FETCH FIRST 12 ROWS ONLY""", {"emp": EMPRESA})

    prov, desc = tot["prov"] or 0.0, tot["descontos"] or 0.0
    return {
        "competencia": comp,
        "competencias": [c["c"] for c in comps],
        "kpis": {
            "proventos": prov, "descontos": desc, "liquido": round(prov - desc, 2),
            "funcs": tot["funcs"],
            "custo_medio": round(prov / tot["funcs"], 2) if tot["funcs"] else 0.0,
        },
        "por_cc": por_cc,
        "top_proventos": [{"ev": r["ev"], "tot": r["tot"]} for r in top_prov],
        "top_descontos": [{"ev": r["ev"], "tot": r["tot"]} for r in top_desc],
        "serie": [{"comp": r["comp"], "prov": r["prov"] or 0.0, "descontos": r["descontos"] or 0.0} for r in serie],
        "fonte": "GLOBUS · VW_FICHAFINANEVENTOS (proventos/descontos) · agregado · leitura",
    }


# ============================================================================
# Indicadores de folha — férias, CNH (motoristas), hora extra, banco de horas
# ============================================================================
_FER_LBL = {"1-VENCIDA": "Vencida", "2-ate 30d": "Vence em 30 dias",
            "3-ate 90d": "Vence em 90 dias", "4-acima 90d": "Acima de 90 dias"}
_CNH_LBL = {"1-VENCIDA": "Vencida", "2-ate 30d": "Vence em 30 dias",
            "3-ate 60d": "Vence em 60 dias", "4-acima 60d": "Acima de 60 dias"}


def get_folha_indicadores() -> dict:
    p = {"emp": EMPRESA}

    # Férias (faixas de vencimento) — subquery pois Oracle não agrupa por alias.
    ferias = _q("""SELECT faixa, COUNT(*) n FROM (
        SELECT CASE WHEN ADD_MONTHS(fe.proxaquifinfer,11)-SYSDATE < 0 THEN '1-VENCIDA'
          WHEN ADD_MONTHS(fe.proxaquifinfer,11)-SYSDATE < 30 THEN '2-ate 30d'
          WHEN ADD_MONTHS(fe.proxaquifinfer,11)-SYSDATE < 90 THEN '3-ate 90d'
          ELSE '4-acima 90d' END faixa
        FROM vw_ferias fe JOIN vw_funcionarios vf
          ON fe.codintfunc=vf.codintfunc AND vf.situacaofunc='A' AND vf.codigoempresa=:emp
        ) GROUP BY faixa""", p)

    # CNH dos motoristas (faixas de validade) — sem CPF (PII).
    cnh = _q("""SELECT faixa, COUNT(*) n FROM (
        SELECT CASE WHEN fd.dtdocto-SYSDATE < 0 THEN '1-VENCIDA'
          WHEN fd.dtdocto-SYSDATE < 30 THEN '2-ate 30d'
          WHEN fd.dtdocto-SYSDATE < 60 THEN '3-ate 60d' ELSE '4-acima 60d' END faixa
        FROM flp_documentos fd
        JOIN flp_funcionarios ff ON fd.codintfunc=ff.codintfunc AND ff.situacaofunc='A' AND ff.codigoempresa=:emp
        JOIN vw_funcionarios vf ON fd.codintfunc=vf.codintfunc AND vf.descfuncaocompleta LIKE 'MOTO%'
        WHERE fd.tipodocto='CNH') GROUP BY faixa""", p)

    # Hora extra (custo por competência, 12m, HE 50% x 100%).
    he = _q("""SELECT TO_CHAR(ff.competficha,'YYYY-MM') comp,
        CASE WHEN fe.desceven LIKE '%50%' THEN '50' ELSE '100' END tipo,
        ROUND(SUM(ff.valorficha),2) tot
        FROM flp_fichaeventos ff JOIN flp_eventos fe ON ff.codevento=fe.codevento
        WHERE (fe.desceven LIKE '%50%' OR fe.desceven LIKE '%100%') AND ff.tipofolha='1'
          AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-12)
        GROUP BY TO_CHAR(ff.competficha,'YYYY-MM'), CASE WHEN fe.desceven LIKE '%50%' THEN '50' ELSE '100' END""", {})

    # Banco de horas (saldo por competência, 12m).
    bh = _q("""SELECT TO_CHAR(competencia,'YYYY-MM') comp, ROUND(SUM(credito),1) cred,
        ROUND(SUM(debito),1) deb, ROUND(SUM(saldonacompet),1) saldo, COUNT(*) n
        FROM frq_bancohoras WHERE competencia >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-12)
        GROUP BY TO_CHAR(competencia,'YYYY-MM') ORDER BY 1""", {})

    ferias_l = sorted(({"faixa": _FER_LBL.get(r["faixa"], r["faixa"]), "ordem": r["faixa"], "n": r["n"]}
                       for r in ferias), key=lambda x: x["ordem"])
    cnh_l = sorted(({"faixa": _CNH_LBL.get(r["faixa"], r["faixa"]), "ordem": r["faixa"], "n": r["n"]}
                    for r in cnh), key=lambda x: x["ordem"])
    he_map: dict = {}
    for r in he:
        d = he_map.setdefault(r["comp"], {"comp": r["comp"], "he50": 0.0, "he100": 0.0})
        d["he50" if r["tipo"] == "50" else "he100"] += (r["tot"] or 0.0)
    he_serie = sorted(he_map.values(), key=lambda x: x["comp"])
    bh_serie = [{"comp": r["comp"], "credito": r["cred"] or 0.0, "debito": r["deb"] or 0.0,
                 "saldo": r["saldo"] or 0.0, "colab": r["n"]} for r in bh]

    fer_venc = next((r["n"] for r in ferias_l if r["ordem"] == "1-VENCIDA"), 0)
    fer_30 = next((r["n"] for r in ferias_l if r["ordem"] == "2-ate 30d"), 0)
    cnh_venc = next((r["n"] for r in cnh_l if r["ordem"] == "1-VENCIDA"), 0)
    cnh_30 = next((r["n"] for r in cnh_l if r["ordem"] == "2-ate 30d"), 0)
    from datetime import date as _date
    mes_atual = _date.today().strftime("%Y-%m")
    he_pas = [h for h in he_serie if h["comp"] <= mes_atual] or he_serie
    bh_pas = [b for b in bh_serie if b["comp"] <= mes_atual] or bh_serie
    he_ult = he_pas[-1] if he_pas else {"he50": 0.0, "he100": 0.0}
    bh_ult = bh_pas[-1] if bh_pas else {"saldo": 0.0, "colab": 0}

    return {
        "kpis": {
            "ferias_vencidas": fer_venc, "ferias_30": fer_30,
            "cnh_vencidas": cnh_venc, "cnh_30": cnh_30,
            "he_mes": round(he_ult["he50"] + he_ult["he100"], 2),
            "bh_saldo": bh_ult["saldo"],
        },
        "ferias": ferias_l, "cnh": cnh_l,
        "hora_extra": he_serie, "banco_horas": bh_serie,
        "fonte": ("GLOBUS · VW_FERIAS + FLP_DOCUMENTOS (CNH) + FLP_FICHAEVENTOS (HE) + "
                  "FRQ_BANCOHORAS · agregado, sem PII · leitura"),
    }


# ============================================================================
# Horas extras — composição por evento, famílias, série 12m e por área
# ============================================================================
# Eventos que compõem a hora extra (proventos; exclui FGTS/base, DSR de
# comissão e descontos). Famílias: HE 50/100 diurna, HE noturna, adicional
# noturno e DSR/reflexos.
_HE_WHERE = (
    "ff.tipofolha='1' AND fe.tipoeven='P' "
    "AND UPPER(fe.desceven) NOT LIKE '%COMISSAO%' AND ("
    "UPPER(fe.desceven) LIKE 'H.E%' OR UPPER(fe.desceven) LIKE 'HORAS EXTRA%' "
    "OR UPPER(fe.desceven) LIKE 'HORA EXTRA%' OR UPPER(fe.desceven) LIKE 'DIF%HORA%EXTRA%' "
    "OR UPPER(fe.desceven) LIKE '%ADICIONAL NOT%' OR UPPER(fe.desceven) LIKE '%ADIC NOTURNO%' "
    "OR UPPER(fe.desceven) LIKE '%ADIC. NOTURNO%' OR UPPER(fe.desceven) LIKE 'DIFERENCA ADIC NOT%' "
    "OR (UPPER(fe.desceven) LIKE 'DSR%' AND (UPPER(fe.desceven) LIKE '%EXTRA%' "
    "OR UPPER(fe.desceven) LIKE '%ADIC%NOT%')))"
)
_HE_J = ("FROM flp_fichaeventos ff "
         "JOIN flp_eventos fe ON ff.codevento = fe.codevento "
         "JOIN flp_funcionarios fu ON fu.codintfunc = ff.codintfunc AND fu.codigoempresa = :emp")

_HE_FAM_COD = {"HE 50% (diurna)": "he50", "HE 100% (diurna)": "he100",
               "HE noturna": "noturna", "Adicional noturno": "adic", "DSR / reflexos": "dsr"}
_HE_FAM_ORDEM = ["HE 50% (diurna)", "HE 100% (diurna)", "HE noturna",
                 "Adicional noturno", "DSR / reflexos"]


def _he_familia(desc: str) -> str:
    u = (desc or "").upper()
    if u.startswith("DSR"):
        return "DSR / reflexos"
    if "ADIC" in u and "EXTRA" not in u:
        return "Adicional noturno"
    if "NOT" in u:
        return "HE noturna"
    if "100" in u:
        return "HE 100% (diurna)"
    return "HE 50% (diurna)"


def get_horas_extras(comp: str | None = None) -> dict:
    p = {"emp": EMPRESA}
    comps = _q("""SELECT DISTINCT TO_CHAR(competficha,'YYYY-MM') c FROM vw_fichafinaneventos
                  WHERE codigoempresa=:emp AND competficha < TRUNC(SYSDATE,'MM')
                    AND competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-13)
                  ORDER BY 1 DESC""", p)
    comps_l = [c["c"] for c in comps]
    if not comp or comp not in comps_l:
        comp = comps_l[0] if comps_l else None
    p["comp"] = comp

    # eventos na competência
    ev_rows = _q(f"""SELECT fe.desceven ev, ROUND(SUM(ff.valorficha),2) tot,
                        COUNT(DISTINCT ff.codintfunc) funcs
                     {_HE_J}
                     WHERE {_HE_WHERE} AND TO_CHAR(ff.competficha,'YYYY-MM')=:comp
                     GROUP BY fe.desceven ORDER BY 2 DESC NULLS LAST""", p)
    total_mes = round(sum((r["tot"] or 0.0) for r in ev_rows), 2)
    eventos = [{"ev": r["ev"], "familia": _he_familia(r["ev"]), "tot": r["tot"] or 0.0,
                "funcs": r["funcs"],
                "pct": round(100 * (r["tot"] or 0.0) / total_mes, 1) if total_mes else 0.0}
               for r in ev_rows]
    funcs_mes = _q(f"""SELECT COUNT(DISTINCT ff.codintfunc) n {_HE_J}
                       WHERE {_HE_WHERE} AND TO_CHAR(ff.competficha,'YYYY-MM')=:comp""", p)[0]["n"]

    # famílias agregadas na competência
    fam_map: dict = {}
    for e in eventos:
        fam_map[e["familia"]] = fam_map.get(e["familia"], 0.0) + e["tot"]
    familias = [{"familia": f, "cod": _HE_FAM_COD[f], "tot": round(fam_map.get(f, 0.0), 2)}
                for f in _HE_FAM_ORDEM if fam_map.get(f)]

    # horas extras "puras" (referência = horas dos eventos H.E) no mês
    horas = _q(f"""SELECT ROUND(SUM(ff.referencia),1) h {_HE_J}
                   WHERE {_HE_WHERE} AND TO_CHAR(ff.competficha,'YYYY-MM')=:comp
                     AND (UPPER(fe.desceven) LIKE 'H.E%' OR UPPER(fe.desceven) LIKE 'HORAS EXTRA%')""", p)
    horas_mes = (horas[0]["h"] or 0.0) if horas else 0.0

    # proventos totais da competência (para % da folha)
    prov = _q("""SELECT ROUND(SUM(valorficha),2) tot FROM vw_fichafinaneventos
                 WHERE codigoempresa=:emp AND tipoeven='P' AND TO_CHAR(competficha,'YYYY-MM')=:comp""", p)
    prov_mes = (prov[0]["tot"] or 0.0) if prov else 0.0

    # série 12m por competência × evento → agrega família (código) no Python
    serie_rows = _q(f"""SELECT TO_CHAR(ff.competficha,'YYYY-MM') comp, fe.desceven ev,
                            ROUND(SUM(ff.valorficha),2) tot
                        {_HE_J}
                        WHERE {_HE_WHERE} AND ff.competficha >= ADD_MONTHS(TRUNC(SYSDATE,'MM'),-12)
                        GROUP BY TO_CHAR(ff.competficha,'YYYY-MM'), fe.desceven""", {"emp": EMPRESA})
    serie_map: dict = {}
    for r in serie_rows:
        d = serie_map.setdefault(r["comp"], {"comp": r["comp"], "he50": 0.0, "he100": 0.0,
                                             "noturna": 0.0, "adic": 0.0, "dsr": 0.0, "total": 0.0})
        cod = _HE_FAM_COD[_he_familia(r["ev"])]
        d[cod] += (r["tot"] or 0.0)
        d["total"] += (r["tot"] or 0.0)
    serie = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()}
             for s in sorted(serie_map.values(), key=lambda x: x["comp"])]
    total_12m = round(sum(s["total"] for s in serie), 2)

    # por área na competência
    area_rows = _q(f"""SELECT COALESCE(fu.descarea,'(sem area)') area,
                          ROUND(SUM(ff.valorficha),2) tot, COUNT(DISTINCT ff.codintfunc) funcs
                       {_HE_J}
                       WHERE {_HE_WHERE} AND TO_CHAR(ff.competficha,'YYYY-MM')=:comp
                       GROUP BY COALESCE(fu.descarea,'(sem area)') ORDER BY 2 DESC NULLS LAST
                       FETCH FIRST 14 ROWS ONLY""", p)
    por_area = [{"area": r["area"], "tot": r["tot"] or 0.0, "funcs": r["funcs"]} for r in area_rows]

    return {
        "competencia": comp,
        "competencias": comps_l,
        "kpis": {
            "total_mes": total_mes, "total_12m": total_12m, "funcs_mes": funcs_mes,
            "media_func": round(total_mes / funcs_mes, 2) if funcs_mes else 0.0,
            "pct_proventos": round(100 * total_mes / prov_mes, 1) if prov_mes else 0.0,
            "horas_mes": horas_mes,
        },
        "eventos": eventos,
        "familias": familias,
        "serie": serie,
        "por_area": por_area,
        "fonte": "ERP GLOBUS - folha (agregado, sem PII)",
    }
