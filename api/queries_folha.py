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
    dem_m = _q("""SELECT TO_CHAR(dataterminocontrato,'YYYY-MM') m, COUNT(*) n FROM vw_funcionarios
                  WHERE codigoempresa = :emp AND situacaofunc = 'D'
                    AND dataterminocontrato >= ADD_MONTHS(TRUNC(SYSDATE),-12)
                    AND dataterminocontrato < TRUNC(SYSDATE)
                  GROUP BY TO_CHAR(dataterminocontrato,'YYYY-MM')""", p)
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
