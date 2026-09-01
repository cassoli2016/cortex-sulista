# -*- coding: utf-8 -*-
"""Faturamento Detalhado (tela `fat`): as emissões do dia a dia que viram
faturamento, contra a meta, por modalidade, cliente, filial e emissor.

AS TRÊS FONTES OFICIAIS são as MESMAS da Visão Geral (VG_DIARIO_SQL):
CT-e (`conhecimento`), NFS-e (`notafiscalservico`) e KMM
(`sulista.faturamentokmm`) — com os filtros fiscais copiados VERBATIM.
Este é o recorte "régua da meta"; não confundir com faturas emitidas
(`faturamento_mes`) nem com a receita das viagens.

O QUE FOI MEDIDO ANTES DE DESENHAR (01/09/2026):
- KMM é fonte MORTA: 19.442 linhas, todas entre 01/01/2023 e 31/05/2023.
  A tela DIZ "fonte encerrada em 31/05/2023" quando a janela alcança — zero
  mudo pareceria queda.
- Modalidade via veículo do CT-e FECHA: 99,97% do valor de ago/26 com
  modalidade, e o join NÃO multiplica (5.511 docs → 5.511 linhas). NFS-e não
  tem veículo: é categoria própria, nunca "(sem modalidade)".
- A meta diária por cliente (metafaturamento_agrupamentoclientedia, tipo=1)
  tem histórico E futuro: 01/01/2024 → 31/12/2026.
- O vínculo cliente (acc.vinculo=1) cobre ~99% do valor; o resíduo vira a
  linha "(sem vínculo)" — sensor de vínculo furado E de dupla contagem.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from . import db
from .queries import (COM_REAL_MES_SQL, VG_DIARIO_SQL, VG_SAZONAL_SQL,
                      _meta_diaria_sazonal, cached)

# A data em que a última linha do KMM foi emitida (medido: nada depois).
KMM_ENCERRADO = "2023-05-31"

# Filtros fiscais canônicos — copiados de VG_DIARIO_SQL/COM_REAL_MES_SQL.
_CTE_W = """c.grupo = 1 AND c.empresa = 1 AND c.unidade = 1 AND c.numero < 1000000
  AND c.dtcancelamento IS NULL AND c.situacaocte = 3 AND c.tipo IN (1, 4)"""
_NFS_W = """n.grupo = 1 AND n.empresa = 1 AND n.numero < 1000000
  AND n.dtcancelamento IS NULL
  AND (n.emissaoeletronica = 2 OR (n.emissaoeletronica = 1 AND n.situacaonfse = 3))"""

FAT_FONTES_SQL = f"""
SELECT 'CT-e' AS fonte, count(*)::int AS docs,
       coalesce(sum(c.valortotalprestacao), 0)::float8 AS valor
FROM conhecimento c
WHERE {_CTE_W} AND c.dtemissao >= %(de)s::date AND c.dtemissao < %(ate)s::date
UNION ALL
SELECT 'KMM', count(*)::int, coalesce(sum(k.valor_cte), 0)::float8
FROM sulista.faturamentokmm k
WHERE k.dtemissao >= %(de)s::date AND k.dtemissao < %(ate)s::date
UNION ALL
SELECT 'NFS-e', count(*)::int, coalesce(sum(n.valortotalbruto), 0)::float8
FROM notafiscalservico n
WHERE {_NFS_W} AND n.dtemissao >= %(de)s::date AND n.dtemissao < %(ate)s::date
"""

# O diário realizado × meta — a VG_DIARIO_SQL deslocável para qualquer mês.
# Derivada por substituição (mesma técnica de VG_DIARIO_ANT_SQL): escrita à
# parte, as duas divergiriam de fonte no primeiro ajuste.
FAT_DIARIO_SQL = (
    VG_DIARIO_SQL
    .replace("dtemissao >= date_trunc('month', current_date)",
             "dtemissao >= %(de)s::date AND dtemissao < %(ate)s::date")
    .replace("dt >= date_trunc('month', current_date)",
             "dt >= %(de)s::date")
    .replace("dt < date_trunc('month', current_date) + interval '1 month'",
             "dt < %(ate)s::date")
)

# Modalidade do CT-e via veículo do documento, nas TRÊS janelas numa passada
# (m0, mês anterior equivalente, ano anterior). O LEFT JOIN não multiplica
# (placa é chave de veiculo; medido: 5.511 docs → 5.511 linhas).
FAT_MODAL_SQL = f"""
SELECT coalesce(nullif(trim(u.descricao), ''), '(sem veículo)') AS modalidade,
  sum(CASE WHEN c.dtemissao >= %(de)s::date  AND c.dtemissao < %(ate)s::date  THEN 1 ELSE 0 END)::int AS docs,
  sum(CASE WHEN c.dtemissao >= %(de)s::date  AND c.dtemissao < %(ate)s::date  THEN c.valortotalprestacao ELSE 0 END)::float8 AS valor,
  sum(CASE WHEN c.dtemissao >= %(de1)s::date AND c.dtemissao < %(ate1)s::date THEN c.valortotalprestacao ELSE 0 END)::float8 AS valor_m1,
  sum(CASE WHEN c.dtemissao >= %(dea)s::date AND c.dtemissao < %(atea)s::date THEN c.valortotalprestacao ELSE 0 END)::float8 AS valor_a1
FROM conhecimento c
LEFT JOIN veiculo v ON v.placa = c.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE {_CTE_W} AND ((c.dtemissao >= %(de)s::date AND c.dtemissao < %(ate)s::date)
   OR (c.dtemissao >= %(de1)s::date AND c.dtemissao < %(ate1)s::date)
   OR (c.dtemissao >= %(dea)s::date AND c.dtemissao < %(atea)s::date))
GROUP BY 1
"""

# 13 meses de realizado (3 fontes) × meta × docs. O eixo de meses é GERADO em
# Python — GROUP BY não devolve o mês sem linha, e abril emendaria em agosto.
FAT_MENSAL_SQL = f"""
SELECT mes, sum(realizado)::float8 AS realizado, sum(meta)::float8 AS meta,
       sum(docs)::int AS docs
FROM (
  SELECT to_char(c.dtemissao, 'YYYY-MM') AS mes,
         sum(c.valortotalprestacao) AS realizado, 0::numeric AS meta,
         count(*) AS docs
  FROM conhecimento c
  WHERE {_CTE_W} AND c.dtemissao >= %(de13)s::date AND c.dtemissao < %(ate)s::date
  GROUP BY 1
  UNION ALL
  SELECT to_char(k.dtemissao, 'YYYY-MM'), sum(k.valor_cte), 0, count(*)
  FROM sulista.faturamentokmm k
  WHERE k.dtemissao >= %(de13)s::date AND k.dtemissao < %(ate)s::date
  GROUP BY 1
  UNION ALL
  SELECT to_char(n.dtemissao, 'YYYY-MM'), sum(n.valortotalbruto), 0, count(*)
  FROM notafiscalservico n
  WHERE {_NFS_W} AND n.dtemissao >= %(de13)s::date AND n.dtemissao < %(ate)s::date
  GROUP BY 1
  UNION ALL
  SELECT to_char(m.dt, 'YYYY-MM'), 0, sum(m.valor), 0
  FROM sulista.metafaturamento_agrupamentoclientedia m
  WHERE m.tipo = 1 AND m.dt >= %(de13)s::date AND m.dt < %(ate)s::date
  GROUP BY 1
) t GROUP BY 1
"""

FAT_MODAL_MENSAL_SQL = f"""
SELECT to_char(c.dtemissao, 'YYYY-MM') AS mes,
       coalesce(nullif(trim(u.descricao), ''), '(sem veículo)') AS modalidade,
       sum(c.valortotalprestacao)::float8 AS valor
FROM conhecimento c
LEFT JOIN veiculo v ON v.placa = c.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE {_CTE_W} AND c.dtemissao >= %(de13)s::date AND c.dtemissao < %(ate)s::date
GROUP BY 1, 2
"""

# COM_META_SQL parametrizada — a original está presa em current_date.
FAT_META_CLI_SQL = """
SELECT 'AG'||m.agrupamentocliente::text AS codigo,
       min(coalesce(nullif(trim(ag.descricao), ''), '(sem nome)')) AS cliente,
       sum(CASE WHEN m.dt <= %(corte)s::date THEN m.valor ELSE 0 END)::float8 AS meta_mtd,
       sum(m.valor)::float8 AS meta_mes
FROM sulista.metafaturamento_agrupamentoclientedia m
LEFT JOIN agrupamentocliente ag ON ag.codigo = m.agrupamentocliente
WHERE m.tipo = 1 AND m.dt >= %(de)s::date AND m.dt < %(ate)s::date
GROUP BY 1 HAVING sum(m.valor) > 0
"""

FAT_DIAS_SQL = f"""
SELECT dia, fonte, docs, valor, filiais, emissores FROM (
  SELECT c.dtemissao::date AS dia, 'CT-e' AS fonte, count(*)::int AS docs,
         sum(c.valortotalprestacao)::float8 AS valor,
         count(distinct c.filial)::int AS filiais,
         count(distinct c.usuarioemissor)::int AS emissores
  FROM conhecimento c
  WHERE {_CTE_W} AND c.dtemissao >= current_date - 14
  GROUP BY 1
  UNION ALL
  SELECT n.dtemissao::date, 'NFS-e', count(*)::int, sum(n.valortotalbruto)::float8,
         count(distinct n.filial)::int, count(distinct n.usuarioemissor)::int
  FROM notafiscalservico n
  WHERE {_NFS_W} AND n.dtemissao >= current_date - 14
  GROUP BY 1
) t ORDER BY dia, fonte
"""

# Cancelamentos: MESMOS filtros fiscais MENOS o dtcancelamento (é ele que se
# conta) e o situacaocte (cancelado não fica em 3).
FAT_CANCEL_SQL = """
SELECT c.dtemissao::date AS dia, count(*)::int AS n,
       coalesce(sum(c.valortotalprestacao), 0)::float8 AS valor
FROM conhecimento c
WHERE c.grupo = 1 AND c.empresa = 1 AND c.unidade = 1 AND c.numero < 1000000
  AND c.tipo IN (1, 4) AND c.dtcancelamento IS NOT NULL
  AND c.dtemissao >= %(de)s::date AND c.dtemissao < %(ate)s::date
GROUP BY 1
"""

FAT_FILIAL_SQL = f"""
SELECT c.filial AS codigo,
       coalesce(nullif(trim(f.apelido), ''), f.cidade, 'Filial '||c.filial) AS nome,
       count(*)::int AS docs, sum(c.valortotalprestacao)::float8 AS valor
FROM conhecimento c
LEFT JOIN filial f ON f.codigo = c.filial AND f.empresa = 1
WHERE {_CTE_W} AND c.dtemissao >= %(de)s::date AND c.dtemissao < %(ate)s::date
GROUP BY 1, 2 ORDER BY 4 DESC
"""

FAT_EMISSORES_SQL = f"""
SELECT coalesce(nullif(trim(u.nomecompleto), ''), 'usuário '||c.usuarioemissor) AS nome,
       count(*)::int AS docs, sum(c.valortotalprestacao)::float8 AS valor
FROM conhecimento c
LEFT JOIN usuario u ON u.codigo = c.usuarioemissor
WHERE {_CTE_W} AND c.dtemissao >= %(de)s::date AND c.dtemissao < %(ate)s::date
GROUP BY 1 ORDER BY 3 DESC LIMIT 10
"""


def _mes_valido(mes: str | None) -> str | None:
    if mes and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise ValueError("mês inválido — use YYYY-MM")
    return mes


def _janelas(mes: str | None, hoje: date) -> dict:
    """As três janelas: m0, mês anterior EQUIVALENTE e ano anterior.

    Comparar agosto inteiro com setembro-até-dia-5 é a mentira clássica do
    MoM — a janela equivalente (regra do trendChip) corta os dois lados no
    mesmo dia. Mês FECHADO compara mês cheio × mês cheio.
    """
    if mes:
        ano, m = int(mes[:4]), int(mes[5:7])
    else:
        ano, m = hoje.year, hoje.month
    ini = date(ano, m, 1)
    dias_no_mes = calendar.monthrange(ano, m)[1]
    fim = ini + timedelta(days=dias_no_mes)          # exclusivo
    corrente = (ano, m) == (hoje.year, hoje.month)
    corte = hoje if corrente else fim - timedelta(days=1)

    def _equiv(base: date) -> tuple[date, date]:
        dias = calendar.monthrange(base.year, base.month)[1]
        d = dias if not corrente else min(corte.day, dias)
        return base, base + timedelta(days=d)        # exclusivo

    m1 = (ini - timedelta(days=1)).replace(day=1)
    a1 = ini.replace(year=ano - 1)
    de1, ate1 = _equiv(m1)
    dea, atea = _equiv(a1)
    de13 = (ini - timedelta(days=365)).replace(day=1)
    return {"mes": f"{ano}-{m:02d}", "ini": ini, "fim": fim, "corte": corte,
            "corrente": corrente, "dias_no_mes": dias_no_mes,
            "de1": de1, "ate1": ate1, "dea": dea, "atea": atea, "de13": de13}


def _meses_eixo(de13: date, ini: date) -> list[str]:
    """Os 13 meses do eixo, GERADOS — mês sem linha não some, vira zero."""
    out, a, m = [], de13.year, de13.month
    while (a, m) <= (ini.year, ini.month):
        out.append(f"{a}-{m:02d}")
        m += 1
        if m > 12:
            a, m = a + 1, 1
    return out


@cached(ttl=90)
def get_detalhado(mes: str | None = None) -> dict:
    hoje = date.today()
    j = _janelas(_mes_valido(mes), hoje)
    p0 = {"de": j["ini"].isoformat(), "ate": j["fim"].isoformat()}
    p1 = {"de": j["de1"].isoformat(), "ate": j["ate1"].isoformat()}
    pa = {"de": j["dea"].isoformat(), "ate": j["atea"].isoformat()}

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(FAT_FONTES_SQL, p0)
        fontes0 = {r["fonte"]: r for r in cur.fetchall()}
        cur.execute(FAT_FONTES_SQL, p1)
        fontes1 = {r["fonte"]: r for r in cur.fetchall()}
        cur.execute(FAT_FONTES_SQL, pa)
        fontesa = {r["fonte"]: r for r in cur.fetchall()}

        cur.execute(FAT_DIARIO_SQL, p0)
        diario = [dict(r) for r in cur.fetchall()]
        meta_fonte = "erp"
        if j["corrente"]:
            cur.execute(VG_SAZONAL_SQL)
            diario, meta_fonte = _meta_diaria_sazonal(
                diario, [dict(r) for r in cur.fetchall()],
                j["ini"].year, j["ini"].month)

        cur.execute(FAT_MODAL_SQL, {**p0, "de1": p1["de"], "ate1": p1["ate"],
                                    "dea": pa["de"], "atea": pa["ate"]})
        modal_rows = [dict(r) for r in cur.fetchall()]

        p13 = {"de13": j["de13"].isoformat(), "ate": j["fim"].isoformat()}
        cur.execute(FAT_MENSAL_SQL, p13)
        mensal_rows = {r["mes"]: dict(r) for r in cur.fetchall()}
        cur.execute(FAT_MODAL_MENSAL_SQL, p13)
        mm_rows = [dict(r) for r in cur.fetchall()]

        cur.execute(FAT_META_CLI_SQL, {**p0, "corte": j["corte"].isoformat()})
        metas_cli = {r["codigo"]: dict(r) for r in cur.fetchall()}
        cur.execute(COM_REAL_MES_SQL, {"dt_de": p0["de"],
                                       "dt_ate": j["corte"].isoformat()})
        real_cli = {r["codigo"]: float(r["realizado"] or 0) for r in cur.fetchall()}
        cur.execute(COM_REAL_MES_SQL, {"dt_de": pa["de"],
                                       "dt_ate": (j["atea"] - timedelta(days=1)).isoformat()})
        real_cli_a1 = {r["codigo"]: float(r["realizado"] or 0) for r in cur.fetchall()}

        cur.execute(FAT_DIAS_SQL)
        dias_rows = [dict(r) for r in cur.fetchall()]
        cur.execute(FAT_CANCEL_SQL, {"de": (hoje - timedelta(days=14)).isoformat(),
                                     "ate": (hoje + timedelta(days=1)).isoformat()})
        cancel_14 = {r["dia"]: dict(r) for r in cur.fetchall()}
        cur.execute(FAT_CANCEL_SQL, p0)
        cancel_mes = [dict(r) for r in cur.fetchall()]
        cur.execute(FAT_FILIAL_SQL, p0)
        filiais = [dict(r) for r in cur.fetchall()]
        cur.execute(FAT_EMISSORES_SQL, p0)
        emissores = [dict(r) for r in cur.fetchall()]

    # ---- KPIs (régua MTD do painel: até o corte, dia corrente incluso) ----
    realizado = sum(float(d["realizado"] or 0) for d in diario)
    meta_mes = sum(float(d["meta"] or 0) for d in diario)
    meta_mtd = sum(float(d["meta"] or 0) for d in diario
                   if int(d["dia"]) <= j["corte"].day) if j["corrente"] else meta_mes
    # atingimento por DIAS FECHADOS: às 08h o dia corrente tem meta cheia e
    # realizado de minutos — julgá-lo derrubaria o chip toda manhã (mesma
    # regra do resumo de WhatsApp e do norte do fechamento)
    if j["corrente"]:
        meta_fech = sum(float(d["meta"] or 0) for d in diario
                        if int(d["dia"]) < j["corte"].day)
        real_fech = sum(float(d["realizado"] or 0) for d in diario
                        if int(d["dia"]) < j["corte"].day)
    else:
        meta_fech, real_fech = meta_mes, realizado
    docs0 = sum(int(r["docs"] or 0) for r in fontes0.values())
    canc_n = sum(int(r["n"]) for r in cancel_mes)
    canc_v = sum(float(r["valor"]) for r in cancel_mes)

    # ---- fontes (KMM morto: nota, nunca zero mudo) ----
    fontes = []
    for nome in ("CT-e", "NFS-e", "KMM"):
        v0 = fontes0.get(nome) or {}
        v1 = fontes1.get(nome) or {}
        va = fontesa.get(nome) or {}
        tr = (float(v0.get("valor") or 0), float(v1.get("valor") or 0),
              float(va.get("valor") or 0))
        if nome == "KMM" and not any(tr):
            continue                     # fora da janela viva — some da lista
        fontes.append({"fonte": nome, "docs": int(v0.get("docs") or 0),
                       "valor": tr[0], "valor_m1": tr[1], "valor_a1": tr[2]})

    # ---- modalidades (NFS-e é categoria própria; <0,1% vira "outros") ----
    nfse = fontes0.get("NFS-e") or {}
    modal_rows.append({"modalidade": "NFS-e (serviço)",
                       "docs": int(nfse.get("docs") or 0),
                       "valor": float(nfse.get("valor") or 0),
                       "valor_m1": float((fontes1.get("NFS-e") or {}).get("valor") or 0),
                       "valor_a1": float((fontesa.get("NFS-e") or {}).get("valor") or 0)})
    total_modal = sum(float(r["valor"] or 0) for r in modal_rows) or 1.0
    principais, outros = [], {"modalidade": "outros", "docs": 0, "valor": 0.0,
                              "valor_m1": 0.0, "valor_a1": 0.0, "n_agrupadas": 0}
    for r in sorted(modal_rows, key=lambda x: -float(x["valor"] or 0)):
        v = float(r["valor"] or 0)
        if v / total_modal < 0.001 and r["modalidade"] != "NFS-e (serviço)":
            outros["docs"] += int(r["docs"] or 0)
            outros["valor"] += v
            outros["valor_m1"] += float(r["valor_m1"] or 0)
            outros["valor_a1"] += float(r["valor_a1"] or 0)
            outros["n_agrupadas"] += 1
            continue
        principais.append({**r, "share": v / total_modal})
    if outros["n_agrupadas"]:
        outros["share"] = outros["valor"] / total_modal
        principais.append(outros)

    # ---- séries mensais (eixo GERADO) ----
    eixo = _meses_eixo(j["de13"], j["ini"])
    mensal = [{"mes": m,
               "realizado": float((mensal_rows.get(m) or {}).get("realizado") or 0),
               "meta": float((mensal_rows.get(m) or {}).get("meta") or 0),
               "docs": int((mensal_rows.get(m) or {}).get("docs") or 0)}
              for m in eixo]
    mm_piv: dict[str, dict[str, float]] = {m: {} for m in eixo}
    for r in mm_rows:
        if r["mes"] in mm_piv:
            mm_piv[r["mes"]][r["modalidade"]] = float(r["valor"] or 0)
    modal_mensal = [{"mes": m, **mm_piv[m]} for m in eixo]

    # ---- clientes: meta × realizado × YoY, com o resíduo à mostra ----
    clientes = []
    for cod in set(metas_cli) | set(real_cli):
        mrow = metas_cli.get(cod) or {}
        r0 = real_cli.get(cod, 0.0)
        mm = float(mrow.get("meta_mtd") or 0)
        clientes.append({
            "codigo": cod,
            "cliente": mrow.get("cliente") or cod,
            "meta_mes": float(mrow.get("meta_mes") or 0),
            "meta_mtd": mm,
            "realizado": r0,
            # meta zerada não é 0% de atingimento: é cliente SEM meta (n/d)
            "ating": (r0 / mm) if mm > 0 else None,
            "share": (r0 / realizado) if realizado else 0.0,
            "realizado_a1": real_cli_a1.get(cod, 0.0),
        })
    clientes.sort(key=lambda c: -c["realizado"])
    soma_cli = sum(c["realizado"] for c in clientes)
    nas_duas = sum(1 for c in clientes if c["meta_mes"] > 0 and c["realizado"] > 0)
    com_meta_v = sum(c["realizado"] for c in clientes if c["meta_mes"] > 0)

    # ---- últimos 14 dias (pivô por dia) ----
    dias_piv: dict = {}
    for r in dias_rows:
        d0 = dias_piv.setdefault(str(r["dia"]), {"dia": str(r["dia"]), "cte": 0,
                                                 "nfse": 0, "valor": 0.0,
                                                 "filiais": 0, "emissores": 0,
                                                 "cancelados": 0,
                                                 "cancelados_valor": 0.0})
        if r["fonte"] == "CT-e":
            d0["cte"] = int(r["docs"])
            d0["filiais"] = int(r["filiais"])
            d0["emissores"] = int(r["emissores"])
        else:
            d0["nfse"] = int(r["docs"])
        d0["valor"] += float(r["valor"] or 0)
    for dia, c in cancel_14.items():
        k = str(dia)
        if k in dias_piv:
            dias_piv[k]["cancelados"] = int(c["n"])
            dias_piv[k]["cancelados_valor"] = float(c["valor"])
    dias = sorted(dias_piv.values(), key=lambda x: x["dia"], reverse=True)

    total_fil = sum(float(f["valor"] or 0) for f in filiais) or 1.0
    return {
        "mes": j["mes"], "mes_fechado": not j["corrente"],
        "dias_no_mes": j["dias_no_mes"], "dia_corte": j["corte"].day,
        "janela_m1": {"de": p1["de"], "ate": (j["ate1"] - timedelta(days=1)).isoformat()},
        "janela_a1": {"de": pa["de"], "ate": (j["atea"] - timedelta(days=1)).isoformat()},
        "kpis": {
            "realizado": realizado,
            "realizado_m1": sum(float(r.get("valor") or 0) for r in fontes1.values()),
            "realizado_a1": sum(float(r.get("valor") or 0) for r in fontesa.values()),
            "meta_mtd": meta_mtd, "meta_mes": meta_mes,
            "atingimento": (realizado / meta_mtd) if meta_mtd > 0 else None,
            "atingimento_fechado": (real_fech / meta_fech) if meta_fech > 0 else None,
            "docs": docs0,
            "cancelados": {"n": canc_n, "valor": canc_v},
        },
        "diario": [{"dia": int(d["dia"]),
                    "realizado": float(d["realizado"] or 0),
                    "meta": float(d["meta"] or 0)} for d in diario],
        "meta_fonte": meta_fonte,
        "fontes": fontes,
        "kmm_encerrado": KMM_ENCERRADO,
        "modalidades": principais,
        "modal_mensal": modal_mensal,
        "mensal": mensal,
        "clientes": clientes,
        "clientes_cobertura": {
            "grupos_real": sum(1 for c in clientes if c["realizado"] > 0),
            "grupos_meta": sum(1 for c in clientes if c["meta_mes"] > 0),
            "nas_duas": nas_duas,
            "pct_valor_com_meta": (com_meta_v / soma_cli) if soma_cli else None,
            "sem_vinculo": realizado - soma_cli,
        },
        "dias": dias,
        "filiais": [{**f, "valor": float(f["valor"] or 0),
                     "share": float(f["valor"] or 0) / total_fil} for f in filiais],
        "emissores": [{**e, "valor": float(e["valor"] or 0)} for e in emissores],
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": ("ERP AVA · conhecimento + notafiscalservico + faturamentokmm "
                  "(emissão) × metafaturamento_agrupamentoclientedia · leitura"),
    }
