"""Consultas do módulo Financeiro sobre o ERP AVA (validadas na varredura).

Mapeamento de negócio:
  - contaapagar : contas a pagar (valorpendente = saldo em aberto)
  - fatura      : contas a receber / frete (valortitulo = valor; valorsaldoreceber = saldo)
  - contacorrente_saldo / caixa_saldo : posição diária de bancos e caixa
Filtros: filial (None = todas) · data_ref (None = current_date) · horizonte (meses do fluxo).
Tudo compatível com PostgreSQL 9.3 (sem FILTER/RLS).
"""
from __future__ import annotations

from datetime import date

from . import db

# ============================================================================
# Cache de respostas (TTL) — o banco é remoto com link lento; consultas
# idênticas em sequência (navegação entre telas) saem da memória.
# ============================================================================
import time as _time

_RESP_CACHE: dict = {}


def cached(ttl: int = 90):
    def deco(fn):
        def wrapper(*args, **kwargs):
            key = (fn.__name__, repr(args), repr(sorted(kwargs.items())))
            hit = _RESP_CACHE.get(key)
            if hit and _time.time() - hit[0] < ttl:
                return hit[1]
            result = fn(*args, **kwargs)
            _RESP_CACHE[key] = (_time.time(), result)
            if len(_RESP_CACHE) > 200:
                _RESP_CACHE.clear()
            return result
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


# Expressões reutilizadas (params nomeados podem repetir com psycopg3).
DREF = "coalesce(%(data_ref)s::date, current_date)"
FIL = "AND (filial = %(filial)s OR %(filial)s::int IS NULL)"
# Filtro "entre datas" de vencimento — só para contas a receber/pagar (KPIs,
# aging e drill-down). O fluxo de caixa tem horizonte próprio e ignora o range.
RNG = ("AND (dtvencimento >= %(venc_de)s::date OR %(venc_de)s::date IS NULL) "
       "AND (dtvencimento <= %(venc_ate)s::date OR %(venc_ate)s::date IS NULL)")

_FAIXA = f"""CASE
    WHEN dtvencimento >= {DREF}       THEN '1_a_vencer'
    WHEN dtvencimento >= {DREF} - 30  THEN '2_vencido_ate_30'
    WHEN dtvencimento >= {DREF} - 90  THEN '3_vencido_31_90'
    WHEN dtvencimento >= {DREF} - 365 THEN '4_vencido_91_365'
    ELSE '5_vencido_mais_365' END"""

KPI_SQL = f"""
SELECT
  (SELECT coalesce(sum(valorsaldoreceber),0)::float8 FROM fatura
     WHERE valorsaldoreceber > 0 AND dtcancelamento IS NULL {FIL} {RNG})            AS receber_aberto,
  (SELECT count(*)::int FROM fatura
     WHERE valorsaldoreceber > 0 AND dtcancelamento IS NULL {FIL} {RNG})            AS receber_qtd,
  (SELECT coalesce(sum(fc.valorpendentecnpjcliente),0)::float8
     FROM fatura f JOIN fatura_composicao fc USING (grupo,empresa,filial,unidade,sequencia)
     LEFT JOIN conhecimento co ON co.grupo=fc.grupodocumentoorigem AND co.empresa=fc.empresadocumentoorigem
       AND co.filial=fc.filialdocumentoorigem AND co.unidade=fc.unidadedocumentoorigem
       AND co.diferenciadornumero=fc.diferenciadornumerodocumentoorigem AND co.serie=fc.seriedocumentoorigem
       AND co.numero=fc.numerosequenciadocumentoorigem AND fc.tipodocumentoorigem=6
     WHERE f.grupo=1 AND fc.valorpendentecnpjcliente>0 AND f.dtcancelamento IS NULL AND f.composicao=1
       AND coalesce(f.dtprevisaopagamento,f.dtvencimento) < {DREF} AND f.dtpagamento IS NULL
       AND fc.tipodocumentoorigem = ANY(string_to_array('6,8,10,11',',')::int[])
       AND (fc.tipodocumentoorigem<>6 OR co.situacaocte=3)
       AND (f.filial = %(filial)s OR %(filial)s::int IS NULL))                     AS receber_vencido,
  (SELECT coalesce(sum(fc.valorpendentecnpjcliente),0)::float8
     FROM fatura f JOIN fatura_composicao fc USING (grupo,empresa,filial,unidade,sequencia)
     WHERE f.grupo=1 AND fc.valorpendentecnpjcliente>0 AND f.dtcancelamento IS NULL AND f.composicao=2
       AND coalesce(f.dtprevisaopagamento,f.dtvencimento) < {DREF} AND f.dtpagamento IS NULL
       AND (f.filial = %(filial)s OR %(filial)s::int IS NULL))                     AS receber_pendente_fatur,
  (SELECT coalesce(sum(valorpendente),0)::float8 FROM contaapagar
     WHERE valorpendente > 0 {FIL} {RNG})                                          AS pagar_aberto,
  (SELECT count(*)::int FROM contaapagar WHERE valorpendente > 0 {FIL} {RNG})      AS pagar_qtd,
  (SELECT coalesce(sum(valorpendente),0)::float8 FROM contaapagar
     WHERE valorpendente > 0 AND dtvencimento < {DREF} {FIL} {RNG})                AS pagar_vencido,
  (SELECT coalesce(sum(valortitulo),0)::float8 FROM fatura
     WHERE dtcancelamento IS NULL
       AND date_trunc('month', dtemissao) = date_trunc('month', {DREF}) {FIL})     AS faturamento_mes,
  (SELECT coalesce(sum(valorsaldoreceber),0)::float8 FROM fatura
     WHERE valorsaldoreceber > 0 AND dtcancelamento IS NULL
       AND dtvencimento >= {DREF} AND dtvencimento <= {DREF} + 30 {FIL})           AS receber_prox30,
  (SELECT coalesce(sum(valorpendente),0)::float8 FROM contaapagar
     WHERE valorpendente > 0
       AND dtvencimento >= {DREF} AND dtvencimento <= {DREF} + 30 {FIL})           AS pagar_prox30
"""

AGING_AR_SQL = f"""
SELECT faixa, count(*)::int AS qtd, sum(valor)::float8 AS valor FROM (
  SELECT {_FAIXA} AS faixa, valorsaldoreceber AS valor
  FROM fatura WHERE valorsaldoreceber > 0 AND dtcancelamento IS NULL {FIL} {RNG}
) t GROUP BY faixa ORDER BY faixa
"""

AGING_AP_SQL = f"""
SELECT faixa, count(*)::int AS qtd, sum(valor)::float8 AS valor FROM (
  SELECT {_FAIXA} AS faixa, valorpendente AS valor
  FROM contaapagar WHERE valorpendente > 0 {FIL} {RNG}
) t GROUP BY faixa ORDER BY faixa
"""

# Saldo bancário + caixa consolidados da empresa (posição mais recente por conta).
# NÃO filtra por filial (contas bancárias são da empresa, não da filial).
SALDO_SQL = f"""
SELECT
  (SELECT sum(valorsaldo)::float8 FROM (
     SELECT DISTINCT ON (grupo,empresa,banco,agencia,conta) valorsaldo
     FROM contacorrente_saldo WHERE dtmovimento <= {DREF}
     ORDER BY grupo,empresa,banco,agencia,conta, dtmovimento DESC) x)              AS bancos,
  (SELECT max(dtmovimento) FROM contacorrente_saldo WHERE dtmovimento <= {DREF})   AS bancos_data,
  (SELECT sum(valorsaldo)::float8 FROM (
     SELECT DISTINCT ON (grupo,empresa,filial,unidade,caixa) valorsaldo
     FROM caixa_saldo WHERE dtmovimento <= {DREF}
     ORDER BY grupo,empresa,filial,unidade,caixa, dtmovimento DESC) x)             AS caixa
"""

# Faturamento médio dos últimos 6 meses completos (run-rate p/ previsão).
RUNRATE_SQL = f"""
SELECT coalesce(avg(mv),0)::float8 AS runrate FROM (
  SELECT sum(valortitulo) AS mv FROM fatura
  WHERE dtcancelamento IS NULL {FIL}
    AND dtemissao >= date_trunc('month', {DREF}) - interval '6 months'
    AND dtemissao <  date_trunc('month', {DREF})
  GROUP BY date_trunc('month', dtemissao)
) t
"""


# Ciclo de caixa: DSO (emissão->pagamento das faturas, ponderado por valor) e
# DPO (idem contas a pagar). Ciclo = DSO - DPO: dias de operação financiados
# pelo caixa próprio.
DSO_SQL = """
SELECT to_char(dtpagamento,'YYYY-MM') AS mes,
       (sum((dtpagamento::date - dtemissao::date) * valortitulo)
        / nullif(sum(valortitulo),0))::float8 AS dias
FROM fatura
WHERE dtcancelamento IS NULL AND dtpagamento IS NOT NULL AND valortitulo > 0
  AND dtpagamento >= date_trunc('month', current_date) - interval '11 months'
GROUP BY 1 ORDER BY 1
"""

DPO_SQL = """
SELECT to_char(dtpagamento,'YYYY-MM') AS mes,
       (sum((dtpagamento::date - dtemissaotitulo::date) * valorpago)
        / nullif(sum(valorpago),0))::float8 AS dias
FROM contaapagar
WHERE dtpagamento IS NOT NULL AND valorpago > 0
  AND dtpagamento >= date_trunc('month', current_date) - interval '11 months'
GROUP BY 1 ORDER BY 1
"""

# Histórico mensal de faturamento desde 2023 (meses fechados) — base do
# índice sazonal que substitui o run-rate constante na linha "realista".
SAZONAL_SQL = f"""
SELECT to_char(date_trunc('month', dtemissao),'YYYY-MM') AS mes,
       extract(month FROM dtemissao)::int AS mnum,
       sum(valortitulo)::float8 AS valor
FROM fatura
WHERE dtcancelamento IS NULL {FIL}
  AND dtemissao >= date '2023-01-01'
  AND dtemissao < date_trunc('month', {DREF})
GROUP BY 1, 2 ORDER BY 1
"""


def _previsao_sazonal(hist: list[dict], fallback: float):
    """Índice sazonal por mês-calendário (média do mês ÷ média geral) e nível
    recente dessazonalizado (últimos 6 meses ÷ índice). Previsão do mês m =
    nivel × índice[m]. Com menos de 15 meses de história, cai no run-rate."""
    if len(hist) < 15:
        return (lambda mnum: fallback), "runrate"
    media_geral = sum(r["valor"] for r in hist) / len(hist)
    por_mes: dict[int, list[float]] = {}
    for r in hist:
        por_mes.setdefault(r["mnum"], []).append(r["valor"])
    indice = {m: (sum(v) / len(v)) / media_geral if media_geral else 1.0
              for m, v in por_mes.items()}
    niveis = [r["valor"] / indice[r["mnum"]]
              for r in hist[-6:] if indice.get(r["mnum"])]
    nivel = sum(niveis) / len(niveis) if niveis else fallback
    return (lambda mnum: nivel * indice.get(mnum, 1.0)), "sazonal"


# O fluxo respeita o range de vencimento (filtro de período) quando informado.
# O corte por horizonte é feito em Python para não consumir o bucket 'atrasado'.
FLUXO_SQL = f"""
WITH mov AS (
  SELECT CASE WHEN dtvencimento < date_trunc('month',{DREF})::date THEN 'atrasado'
              ELSE to_char(dtvencimento,'YYYY-MM') END AS mes,
         CASE WHEN dtvencimento < date_trunc('month',{DREF})::date THEN '0000-00'
              ELSE to_char(dtvencimento,'YYYY-MM') END AS ord,
         valorsaldoreceber AS receber, 0::numeric AS pagar
  FROM fatura WHERE coalesce(valorsaldoreceber,0) > 0 AND dtcancelamento IS NULL
    AND dtvencimento IS NOT NULL {FIL} {RNG}
  UNION ALL
  SELECT CASE WHEN dtvencimento < date_trunc('month',{DREF})::date THEN 'atrasado'
              ELSE to_char(dtvencimento,'YYYY-MM') END,
         CASE WHEN dtvencimento < date_trunc('month',{DREF})::date THEN '0000-00'
              ELSE to_char(dtvencimento,'YYYY-MM') END,
         0::numeric, valorpendente
  FROM contaapagar WHERE coalesce(valorpendente,0) > 0
    AND dtvencimento IS NOT NULL {FIL} {RNG}
)
SELECT mes AS periodo,
       sum(receber)::float8 AS receber,
       sum(pagar)::float8   AS pagar,
       (sum(receber)-sum(pagar))::float8 AS liquido
FROM mov GROUP BY mes, ord ORDER BY ord
"""

# Distribuição de vencimentos por mês (gráficos de Contas a Receber / a Pagar).
# Buckets de borda: '0:ant' (mais de 6 meses antes da ref.) e '2:pos' (12+ meses depois).
def _venc_sql(tabela: str, cond: str, valor: str) -> str:
    return f"""
SELECT bucket,
       sum(CASE WHEN dtvencimento <  {DREF} THEN valor ELSE 0 END)::float8 AS vencido,
       sum(CASE WHEN dtvencimento >= {DREF} THEN valor ELSE 0 END)::float8 AS a_vencer,
       count(*)::int AS titulos
FROM (
  SELECT CASE
      WHEN date_trunc('month',dtvencimento) <  date_trunc('month',{DREF}) - interval '6 months'  THEN '0:ant'
      WHEN date_trunc('month',dtvencimento) >= date_trunc('month',{DREF}) + interval '12 months' THEN '2:pos'
      ELSE '1:'||to_char(dtvencimento,'YYYY-MM') END AS bucket,
    dtvencimento, {valor} AS valor
  FROM {tabela} WHERE {cond} AND dtvencimento IS NOT NULL {FIL} {RNG}
) t GROUP BY bucket ORDER BY bucket
"""

VENC_AR_SQL = _venc_sql("fatura", "valorsaldoreceber > 0 AND dtcancelamento IS NULL", "valorsaldoreceber")
VENC_AP_SQL = _venc_sql("contaapagar", "valorpendente > 0", "valorpendente")

# Drill-down: maiores devedores (a receber) e credores (a pagar).
# Nome resolvido em `cadastro`; o documento é mascarado antes de sair do backend.
DRILL_AR_SQL = f"""
SELECT f.cliente AS codigo,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), '(sem cadastro)') AS nome,
       count(*)::int AS titulos,
       sum(f.valorsaldoreceber)::float8 AS valor,
       sum(CASE WHEN f.dtvencimento < {DREF} THEN f.valorsaldoreceber ELSE 0 END)::float8 AS vencido
FROM fatura f LEFT JOIN cadastro c ON c.codigo = f.cliente
WHERE f.valorsaldoreceber > 0 AND f.dtcancelamento IS NULL {FIL} {RNG}
GROUP BY f.cliente, c.nomefantasia, c.razaosocial
ORDER BY valor DESC LIMIT 15
"""

DRILL_AP_SQL = f"""
SELECT a.cnpjcpfcodigo AS codigo,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), '(sem cadastro)') AS nome,
       count(*)::int AS titulos,
       sum(a.valorpendente)::float8 AS valor,
       sum(CASE WHEN a.dtvencimento < {DREF} THEN a.valorpendente ELSE 0 END)::float8 AS vencido
FROM contaapagar a LEFT JOIN cadastro c ON c.codigo = a.cnpjcpfcodigo
WHERE a.valorpendente > 0 {FIL} {RNG}
GROUP BY a.cnpjcpfcodigo, c.nomefantasia, c.razaosocial
ORDER BY valor DESC LIMIT 15
"""

FILTROS_SQL = """
SELECT f.codigo, coalesce(nullif(trim(f.apelido),''), f.cidade, 'Filial '||f.codigo) AS nome, f.uf
FROM filial f
WHERE f.empresa = 1
  AND f.codigo IN (SELECT filial FROM fatura UNION SELECT filial FROM contaapagar)
ORDER BY f.codigo
"""


def _mask_doc(doc: str | None) -> str:
    """Mascara CNPJ/CPF/código, deixando só 2 primeiros e 2 últimos dígitos (PII)."""
    if not doc:
        return ""
    d = "".join(ch for ch in str(doc) if ch.isalnum())
    if len(d) <= 4:
        return "•" * len(d)
    return f"{d[:2]}{'•' * (len(d) - 4)}{d[-2:]}"


def get_filtros() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT nome FROM empresa WHERE codigo = 1")
        emp = cur.fetchone()
        cur.execute(FILTROS_SQL)
        filiais = cur.fetchall()
    return {"empresa": (emp or {}).get("nome", "—"), "filiais": filiais}


@cached(ttl=90)
def get_overview(filial: int | None = None, data_ref: str | None = None,
                 horizonte: int = 12, venc_de: str | None = None,
                 venc_ate: str | None = None) -> dict:
    params = {"filial": filial, "data_ref": data_ref, "horizonte": horizonte,
              "venc_de": venc_de, "venc_ate": venc_ate}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(AGING_AR_SQL, params)
        aging_receber = cur.fetchall()
        cur.execute(AGING_AP_SQL, params)
        aging_pagar = cur.fetchall()
        cur.execute(SALDO_SQL, params)
        saldo = cur.fetchone()
        cur.execute(RUNRATE_SQL, params)
        runrate = (cur.fetchone() or {}).get("runrate") or 0.0
        cur.execute(SAZONAL_SQL, params)
        hist_sazonal = cur.fetchall()
        cur.execute(DSO_SQL)
        dso_rows = cur.fetchall()
        cur.execute(DPO_SQL)
        dpo_rows = cur.fetchall()
        from datetime import timedelta as _td
        _mes1 = date.today().replace(day=1)
        cur.execute(FIN_MENSAL_SQL, {"de": (_mes1 - _td(days=365)).replace(day=1).isoformat(),
                                     "ate": _mes1.isoformat()})
        custo_fin = cur.fetchall()
        cur.execute(FLUXO_SQL, params)
        fluxo = cur.fetchall()
        cur.execute(DRILL_AR_SQL, params)
        top_receber = cur.fetchall()
        cur.execute(DRILL_AP_SQL, params)
        top_pagar = cur.fetchall()
        cur.execute(VENC_AR_SQL, params)
        venc_receber = cur.fetchall()
        cur.execute(VENC_AP_SQL, params)
        venc_pagar = cur.fetchall()
        cur.execute(f"SELECT {DREF} AS dref, current_timestamp AS ts", params)
        meta = cur.fetchone()

    # Corte por horizonte sem consumir o bucket 'atrasado' (ele é estoque, não mês).
    if fluxo and fluxo[0]["periodo"] == "atrasado":
        fluxo = fluxo[:1] + fluxo[1:horizonte + 1]
    else:
        fluxo = fluxo[:horizonte]

    # Mascara o documento antes de qualquer coisa sair do backend.
    for r in top_receber + top_pagar:
        r["doc"] = _mask_doc(r.pop("codigo"))

    bancos = saldo.get("bancos") or 0.0
    cx = saldo.get("caixa") or 0.0
    saldo_inicial = bancos + cx
    dref: date = meta["dref"]
    cur_ym = f"{dref.year:04d}-{dref.month:02d}"

    # Enriquecer o fluxo: saldo projetado (ancorado no saldo atual) e linha
    # "realista" que usa a previsão de faturamento (run-rate) nos meses futuros
    # ainda sem recebíveis lançados.
    prever, metodo_prev = _previsao_sazonal(hist_sazonal, runrate)
    acc_book = acc_real = acc_stress = 0.0
    for row in fluxo:
        rec, pag = row["receber"], row["pagar"]
        if row["periodo"] and row["periodo"] not in ("atrasado", cur_ym) and row["periodo"] > cur_ym:
            rec_prev = max(rec, prever(int(row["periodo"][5:7])))
        else:
            rec_prev = rec
        acc_book += rec - pag
        acc_real += rec_prev - pag
        futuro = row["periodo"] and row["periodo"] not in ("atrasado",) and row["periodo"] > cur_ym
        acc_stress += (rec_prev * (0.9 if futuro else 1.0)) - pag
        row["receber_previsto"] = rec_prev
        row["saldo_projetado"] = saldo_inicial + acc_book
        row["saldo_realista"] = saldo_inicial + acc_real
        row["saldo_estresse"] = saldo_inicial + acc_stress

    kpis["saldo_bancos"] = bancos
    kpis["saldo_caixa"] = cx
    kpis["saldo_atual"] = saldo_inicial
    kpis["saldo_data"] = saldo["bancos_data"].isoformat() if saldo.get("bancos_data") else None
    kpis["faturamento_medio_6m"] = runrate
    dpo_map = {r["mes"]: r["dias"] for r in dpo_rows}
    ciclo = [{"mes": r["mes"], "dso": r["dias"], "dpo": dpo_map.get(r["mes"]),
              "ciclo": (r["dias"] - dpo_map[r["mes"]]) if dpo_map.get(r["mes"]) is not None else None}
             for r in dso_rows]
    ult3 = [c for c in ciclo if c["ciclo"] is not None][-3:]
    stress_neg = next((r["periodo"] for r in fluxo
                       if r["periodo"] and r["periodo"] != "atrasado"
                       and r.get("saldo_estresse", 0) < 0), None)
    kpis["estresse_gap_mes"] = stress_neg
    kpis["custo_financeiro_12m"] = sum(r["valor"] for r in custo_fin)
    kpis["dso_3m"] = (sum(c["dso"] for c in ult3) / len(ult3)) if ult3 else None
    kpis["dpo_3m"] = (sum(c["dpo"] for c in ult3) / len(ult3)) if ult3 else None
    kpis["ciclo_3m"] = (kpis["dso_3m"] - kpis["dpo_3m"]) if ult3 else None
    kpis["previsao_metodo"] = metodo_prev
    kpis["previsao_proximo_mes"] = prever(dref.month + 1 if dref.month < 12 else 1)
    kpis["posicao_liquida_aberto"] = kpis["receber_aberto"] - kpis["pagar_aberto"]

    return {
        "kpis": kpis,
        "aging_receber": aging_receber,
        "aging_pagar": aging_pagar,
        "fluxo_caixa": fluxo,
        "ciclo_caixa": ciclo,
        "custo_financeiro": custo_fin,
        "top_receber": top_receber,
        "top_pagar": top_pagar,
        "venc_receber": venc_receber,
        "venc_pagar": venc_pagar,
        "filial": filial,
        "venc_de": venc_de,
        "venc_ate": venc_ate,
        "data_ref": dref.isoformat(),
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA (banco sulista) · leitura",
    }


# ============================================================================
# DRE gerencial — razão do AVA (lancamento × planoconta)
# Movimento real = crédito − débito, EXCLUINDO historico=18 (encerramento
# mensal "APURACAO DO RESULTADO"). Sinal credor-positivo: receita > 0, custo < 0.
# v1 consolidada: lancamento não tem filial (lancamento_filial não tem historico,
# então não dá para excluir o encerramento por filial com segurança).
# ============================================================================
_DRE_GRUPO = r"""CASE
    WHEN p.estrutural LIKE '3.1.1%%' THEN 'receita_bruta'
    WHEN p.estrutural LIKE '3.1.2%%' THEN 'deducoes'
    WHEN p.estrutural LIKE '4.1.1.12%%' THEN 'depreciacao'
    WHEN p.estrutural ~ '^4\.1\.1\.(05|06|10|11)' THEN 'fixo'
    WHEN p.estrutural LIKE '4.1.1%%' THEN 'custo_var'
    WHEN p.estrutural LIKE '4.1.2%%' THEN 'custo_motorista'
    WHEN p.estrutural LIKE '4.1.3%%' THEN 'fixo'
    WHEN p.estrutural ~ '^4\.2\.(1|2|3)' THEN 'adm'
    WHEN p.estrutural LIKE '4.2.4%%' THEN 'fin'
    WHEN p.estrutural LIKE '4.2.5%%' THEN 'outras'
    ELSE NULL END"""

_DRE_BASE = """
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND p.estrutural ~ '^[34]' AND p.estrutural NOT LIKE '4.9%%'
  AND coalesce(l.historico, 0) <> 18
"""

DRE_MES_SQL = f"""
SELECT mes, grupo, sum(valor)::float8 AS valor FROM (
  SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
         {_DRE_GRUPO} AS grupo,
         (coalesce(l.valorcredito,0) - coalesce(l.valordebito,0)) AS valor
  {_DRE_BASE}
) t WHERE grupo IS NOT NULL
GROUP BY mes, grupo ORDER BY mes, grupo
"""

DRE_CONTA_SQL = f"""
SELECT t.grupo, t.conta, min(pd.descricao) AS descricao, sum(t.valor)::float8 AS valor FROM (
  SELECT {_DRE_GRUPO} AS grupo,
         substring(p.estrutural,1,8) AS conta,
         (coalesce(l.valorcredito,0) - coalesce(l.valordebito,0)) AS valor
  {_DRE_BASE}
) t
LEFT JOIN planoconta pd ON pd.estrutural = t.conta || '.0000'
WHERE t.grupo IS NOT NULL
GROUP BY t.grupo, t.conta ORDER BY abs(sum(t.valor)) DESC
LIMIT 30
"""


def _comp_bounds(comp_de: str, comp_ate: str) -> tuple[str, str]:
    """[comp_de, comp_ate] inclusivos (YYYY-MM) → [de, ate) em datas."""
    de = f"{comp_de}-01"
    ano, mes = int(comp_ate[:4]), int(comp_ate[5:7])
    ate = f"{ano + 1}-01-01" if mes == 12 else f"{ano}-{mes + 1:02d}-01"
    return de, ate


# DRE gerencial no MODELO DA EMPRESA (docs/dre_ia_analise.xlsx): linhas =
# agrupadores de sulista.agrupadorgerencial, organizados na hierarquia da
# planilha. Ajustes locais (data/ajustes_contabeis.json) sobrepõem o
# mapeamento — o banco acessível é uma RÉPLICA (sem escrita); o export SQL
# gera o script para aplicar no primário.
import json as _jsonmod
from pathlib import Path as _Path

_AJUSTES_PATH = _Path(__file__).resolve().parent.parent / "data" / "ajustes_contabeis.json"


def ler_ajustes() -> dict:
    try:
        return _jsonmod.loads(_AJUSTES_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def salvar_ajuste(grupo: int, reduzido: int, agrupador: str,
                  conta: str = "") -> dict:
    ajustes = ler_ajustes()
    ajustes[f"{grupo}|{reduzido}"] = {
        "agrupador": agrupador.strip(), "conta": conta,
        "em": date.today().isoformat(),
    }
    _AJUSTES_PATH.parent.mkdir(exist_ok=True)
    _AJUSTES_PATH.write_text(_jsonmod.dumps(ajustes, ensure_ascii=False, indent=1))
    _RESP_CACHE.clear()
    return ajustes


def remover_ajuste(grupo: int, reduzido: int) -> dict:
    ajustes = ler_ajustes()
    ajustes.pop(f"{grupo}|{reduzido}", None)
    _AJUSTES_PATH.write_text(_jsonmod.dumps(ajustes, ensure_ascii=False, indent=1))
    _RESP_CACHE.clear()
    return ajustes


def export_sql_ajustes() -> str:
    """Script p/ aplicar os ajustes locais no banco PRIMARIO (via DBeaver)."""
    ajustes = ler_ajustes()
    if not ajustes:
        return "-- nenhum ajuste local pendente\n"
    linhas = ["-- Ajustes do agrupador gerencial gerados pelo Cortex Sulista",
              f"-- {date.today().isoformat()} - aplicar no banco PRIMARIO", "BEGIN;"]
    for chave, aj in sorted(ajustes.items()):
        grupo, reduzido = chave.split("|")
        ag = aj["agrupador"].replace("'", "''")
        linhas.append(
            f"UPDATE sulista.agrupadorgerencial SET descricao = '{ag}' "
            f"WHERE grupo = {int(grupo)} AND reduzido = {int(reduzido)};")
        linhas.append(
            f"INSERT INTO sulista.agrupadorgerencial (grupo, reduzido, descricao) "
            f"SELECT {int(grupo)}, {int(reduzido)}, '{ag}' WHERE NOT EXISTS "
            f"(SELECT 1 FROM sulista.agrupadorgerencial WHERE grupo = {int(grupo)} "
            f"AND reduzido = {int(reduzido)});")
    linhas.append("COMMIT;")
    return "\n".join(linhas) + "\n"


DRE_AG_SQL = """
SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
       coalesce(ag.descricao, 'CLASSIFICAR') AS agrupador,
       sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS valor
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
GROUP BY 1, 2
"""

# lançamentos das contas com ajuste local: migram de agrupador em memória
DRE_AJUSTADAS_SQL = """
SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
       l.grupo::text || '|' || l.reduzido::text AS chave,
       coalesce(ag.descricao, 'CLASSIFICAR') AS agrupador_orig,
       sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS valor
FROM lancamento l
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (l.grupo::text || '|' || l.reduzido::text) = ANY(%(chaves)s)
GROUP BY 1, 2, 3
"""

# Hierarquia da planilha: (rotulo, nivel, tipo, seletor)
#   tipo 'pref' = soma agrupadores pelo(s) prefixo(s); 'nome' = nomes exatos;
#   'formula' = soma de outras linhas (por rotulo)
DRE_MODELO = [
    ("RECEITA BRUTA", 0, "pref", ["RECEITA OPERACIONAL BRUTA", "RECEITA DE PEDAGIO", "RECEITA OUTROS", "RECEITA DE SERVICO"]),
    ("DEDUCOES DA RECEITA", 0, "formula", ["IMPOSTOS FEDERAIS", "IMPOSTOS ESTADUAIS", "IMPOSTOS MUNICIPAIS", "CONTRIBUICAO PREVIDENCIARIA", "ANULACOES", "DESCONTOS"]),
    ("IMPOSTOS FEDERAIS", 1, "nome", ["IMPOSTOS FEDERAIS"]),
    ("IMPOSTOS ESTADUAIS", 1, "nome", ["IMPOSTOS ESTADUAIS"]),
    ("IMPOSTOS MUNICIPAIS", 1, "nome", ["IMPOSTOS MUNICIPAIS"]),
    ("CONTRIBUICAO PREVIDENCIARIA", 1, "pref", ["CONTRIBUI"]),
    ("ANULACOES", 1, "pref", ["ANULA"]),
    ("DESCONTOS", 1, "nome", ["DESCONTOS"]),
    ("RECEITA LIQUIDA", 0, "formula", ["RECEITA BRUTA", "DEDUCOES DA RECEITA"]),
    ("CSP", 0, "formula", ["CUSTO FIXO", "CUSTO VARIAVEL", "CREDITOS TRIBUTARIOS"]),
    ("CUSTO FIXO", 1, "pref", ["CF - "]),
    ("CUSTO VARIAVEL", 1, "pref", ["CV - "]),
    ("CREDITOS TRIBUTARIOS", 1, "pref", ["CR - "]),
    ("LUCRO BRUTO", 0, "formula", ["RECEITA LIQUIDA", "CSP"]),
    ("DESPESAS", 0, "formula", ["OVERHEAD", "INDENIZACOES", "OUTRAS DESPESAS/RECEITAS OPERACIONAIS"]),
    ("OVERHEAD", 1, "pref", ["OVERHEAD - "]),
    ("INDENIZACOES", 1, "pref", ["INDENIZA"]),
    ("OUTRAS DESPESAS/RECEITAS OPERACIONAIS", 1, "pref", ["OUTRAS DESPESAS - ", "OUTRAS RECEITAS - ", "(1, -/+)"]),
    ("RESULTADO OPERACIONAL (LOP 1)", 0, "formula", ["LUCRO BRUTO", "DESPESAS"]),
    ("RESULTADO FINANCEIRO", 0, "pref", ["FINANC - "]),
    ("RESULTADO NAO OPERACIONAL", 0, "pref", ["DESPESAS N", "RECEITA - VENDA"]),
    ("RESULTADO DO EXERCICIO", 0, "formula", ["RESULTADO OPERACIONAL (LOP 1)", "RESULTADO FINANCEIRO", "RESULTADO NAO OPERACIONAL"]),
]


def _dre_aloca(agrupador: str) -> str | None:
    """Em qual linha-mãe da DRE o agrupador cai (para o detalhe expansível)."""
    a = agrupador.upper()
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            continue
        for s in sel:
            if (tipo == "nome" and a == s) or (tipo == "pref" and a.startswith(s.upper())):
                return rotulo
    return None


@cached(ttl=300)
def get_dre(comp_de: str, comp_ate: str) -> dict:
    de, ate = _comp_bounds(comp_de, comp_ate)
    # mesmo intervalo, um ano antes (comparativo a/a)
    comp_de_aa = f"{int(comp_de[:4]) - 1}{comp_de[4:]}"
    comp_ate_aa = f"{int(comp_ate[:4]) - 1}{comp_ate[4:]}"
    de_aa, ate_aa = _comp_bounds(comp_de_aa, comp_ate_aa)
    ajustes = ler_ajustes()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(DRE_AG_SQL, {"de": de, "ate": ate})
        rows = cur.fetchall()
        cur.execute(DRE_AG_SQL, {"de": de_aa, "ate": ate_aa})
        rows_aa = cur.fetchall()
        mudancas = []
        mudancas_aa = []
        if ajustes:
            cur.execute(DRE_AJUSTADAS_SQL,
                        {"de": de, "ate": ate, "chaves": list(ajustes.keys())})
            mudancas = cur.fetchall()
            cur.execute(DRE_AJUSTADAS_SQL,
                        {"de": de_aa, "ate": ate_aa, "chaves": list(ajustes.keys())})
            mudancas_aa = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    # valores por (mes, agrupador), aplicando os ajustes locais
    val: dict = {}
    for r in rows:
        val[(r["mes"], r["agrupador"])] = val.get((r["mes"], r["agrupador"]), 0.0) + r["valor"]
    for mrow in mudancas:
        novo = ajustes[mrow["chave"]]["agrupador"]
        if novo == mrow["agrupador_orig"]:
            continue
        val[(mrow["mes"], mrow["agrupador_orig"])] = val.get((mrow["mes"], mrow["agrupador_orig"]), 0.0) - mrow["valor"]
        val[(mrow["mes"], novo)] = val.get((mrow["mes"], novo), 0.0) + mrow["valor"]

    val_aa: dict = {}
    for r in rows_aa:
        val_aa[r["agrupador"]] = val_aa.get(r["agrupador"], 0.0) + r["valor"]
    for mrow in mudancas_aa:
        novo = ajustes[mrow["chave"]]["agrupador"]
        if novo == mrow["agrupador_orig"]:
            continue
        val_aa[mrow["agrupador_orig"]] = val_aa.get(mrow["agrupador_orig"], 0.0) - mrow["valor"]
        val_aa[novo] = val_aa.get(novo, 0.0) + mrow["valor"]

    meses = sorted({m for m, _ in val})
    agrupadores = sorted({a for _, a in val} | set(val_aa))

    import unicodedata
    def _norm(s):
        return unicodedata.normalize("NFKD", s.upper()).encode("ascii", "ignore").decode()

    # soma por linha do modelo
    def soma_sel(tipo, sel, mes):
        total = 0.0
        for a in agrupadores:
            na = _norm(a)
            for s in sel:
                ns = _norm(s)
                if (tipo == "nome" and na == ns) or (tipo == "pref" and na.startswith(ns)):
                    total += val.get((mes, a), 0.0)
                    break
        return total

    def soma_sel_aa(tipo, sel):
        total = 0.0
        for a, v in val_aa.items():
            na = _norm(a)
            for s in sel:
                ns = _norm(s)
                if (tipo == "nome" and na == ns) or (tipo == "pref" and na.startswith(ns)):
                    total += v
                    break
        return total

    # 1ª passada: linhas diretas (nome/prefixo); 2ª: fórmulas em ordem
    por_rotulo: dict = {}
    aa_rotulo: dict = {}
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo != "formula":
            por_rotulo[rotulo] = {mes: soma_sel(tipo, sel, mes) for mes in meses}
            aa_rotulo[rotulo] = soma_sel_aa(tipo, sel)
    for rotulo, _nivel, tipo, sel in DRE_MODELO:
        if tipo == "formula":
            por_rotulo[rotulo] = {mes: sum(por_rotulo.get(r, {}).get(mes, 0.0) for r in sel)
                                  for mes in meses}
            aa_rotulo[rotulo] = sum(aa_rotulo.get(r, 0.0) for r in sel)

    linhas = []
    usados: set = set()
    for rotulo, nivel, tipo, sel in DRE_MODELO:
        vals = por_rotulo[rotulo]
        # detalhe: agrupadores que caem nesta linha
        detalhe = []
        if tipo != "formula":
            for a in agrupadores:
                na = _norm(a)
                if any((tipo == "nome" and na == _norm(s)) or (tipo == "pref" and na.startswith(_norm(s))) for s in sel):
                    usados.add(a)
                    dvals = {m: val.get((m, a), 0.0) for m in meses}
                    if any(abs(v) > 0.005 for v in dvals.values()) or abs(val_aa.get(a, 0.0)) > 0.005:
                        detalhe.append({"agrupador": a, "meses": dvals,
                                        "total": sum(dvals.values()),
                                        "total_aa": val_aa.get(a, 0.0)})
            detalhe.sort(key=lambda d: -abs(d["total"]))
        linhas.append({"rotulo": rotulo, "nivel": nivel, "tipo": tipo,
                       "meses": vals, "total": sum(vals.values()),
                       "total_aa": aa_rotulo.get(rotulo, 0.0),
                       "detalhe": detalhe if len(detalhe) > 1 else []})

    # transparência: o que não entrou em nenhuma linha (inclui CLASSIFICAR)
    sobras = []
    for a in agrupadores:
        if a in usados:
            continue
        dvals = {m: val.get((m, a), 0.0) for m in meses}
        if any(abs(v) > 0.005 for v in dvals.values()):
            sobras.append({"agrupador": a, "meses": dvals, "total": sum(dvals.values())})
    if sobras:
        vals = {m: sum(s["meses"][m] for s in sobras) for m in meses}
        linhas.append({"rotulo": "NAO ALOCADO / CLASSIFICAR", "nivel": 0,
                       "tipo": "sobra", "meses": vals, "total": sum(vals.values()),
                       "total_aa": sum(val_aa.get(s["agrupador"], 0.0) for s in sobras),
                       "detalhe": sobras})

    return {
        "linhas": linhas, "meses": meses,
        "comp_de": comp_de, "comp_ate": comp_ate,
        "comp_de_aa": comp_de_aa, "comp_ate_aa": comp_ate_aa,
        "ajustes_locais": len(ajustes),
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · razão × agrupador gerencial (sulista.agrupadorgerencial) · leitura",
    }


# Uma ÚNICA execução da cadeia pesada (o join de recebimento não tem índice
# no 9.3 e custa ~12s): busca as linhas do período+filial e deriva KPIs,
# fornecedores, listas aninhadas e opções facetadas de filtros em Python.
OC_ROWS_SQL = """
WITH oc AS (
  SELECT o.grupo, o.empresa, o.filial, o.diferenciadornumero, o.numero,
         o.dtemissao, o.dtprevisaoentrega, o.dtaprovador,
         o.cnpjcpffornecedor, o.codigousuario, o.usuarioaprovador,
         coalesce(o.valortotal,0) AS valortotal,
         coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), '(sem cadastro)') AS fornecedor
  FROM ordemcompra o
  LEFT JOIN cadastro c ON c.codigo = o.cnpjcpffornecedor
  WHERE o.dtemissao >= %(dt_de)s::date AND o.dtemissao < %(dt_ate)s::date + 1
    AND (o.filial = %(filial)s OR %(filial)s::int IS NULL)
),
rec AS (
  SELECT r.grupo, r.empresa, r.filialordemcompra AS filial,
         r.diferenciadornumeroordemcompra AS diferenciadornumero,
         r.numeroordemcompra AS numero,
         sum(coalesce(r.valortotal,0)) AS valor_recebido
  FROM notafiscalentrada_item_ordemcomprarecebida r
  JOIN oc ON oc.grupo=r.grupo AND oc.empresa=r.empresa AND oc.filial=r.filialordemcompra
         AND oc.diferenciadornumero=r.diferenciadornumeroordemcompra AND oc.numero=r.numeroordemcompra
  GROUP BY 1,2,3,4,5
)
SELECT oc.numero, oc.filial,
       to_char(oc.dtemissao,'YYYY-MM-DD') AS emissao,
       to_char(oc.dtprevisaoentrega,'YYYY-MM-DD') AS previsao_entrega,
       oc.dtprevisaoentrega < current_date AS previsao_vencida,
       oc.fornecedor, oc.cnpjcpffornecedor AS codigo_forn,
       oc.codigousuario AS criador_cod, oc.usuarioaprovador AS aprovador_cod,
       (oc.dtaprovador IS NULL) AS sem_aprovacao,
       oc.valortotal::float8 AS valor,
       greatest(oc.valortotal - coalesce(rec.valor_recebido,0), 0)::float8 AS valor_pendente
FROM oc LEFT JOIN rec ON rec.grupo=oc.grupo AND rec.empresa=oc.empresa AND rec.filial=oc.filial
     AND rec.diferenciadornumero=oc.diferenciadornumero AND rec.numero=oc.numero
"""

OC_USUARIOS_SQL = "SELECT codigo, coalesce(nullif(trim(nomecompleto),''), 'usuário '||codigo) AS nome FROM usuario"

# Série mensal de emissões (últimos 12 meses): leve, sem o join de recebimento.
OC_MENSAL_SQL = """
SELECT to_char(o.dtemissao,'YYYY-MM') AS mes, count(*)::int AS ocs,
       sum(coalesce(o.valortotal,0))::float8 AS valor
FROM ordemcompra o
LEFT JOIN cadastro c ON c.codigo = o.cnpjcpffornecedor
WHERE o.dtemissao >= date_trunc('month', current_date) - interval '11 months'
  AND (o.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (o.codigousuario = %(criador)s OR %(criador)s::int IS NULL)
  AND (o.usuarioaprovador = %(aprovador)s OR %(aprovador)s::int IS NULL)
  AND (%(fornecedor)s::text IS NULL OR c.nomefantasia ILIKE '%%'||%(fornecedor)s||'%%'
       OR c.razaosocial ILIKE '%%'||%(fornecedor)s||'%%')
GROUP BY 1 ORDER BY 1
"""


def _oc_status(r: dict) -> str:
    if r["sem_aprovacao"]:
        return "aprovacao"
    if r["valor_pendente"] > 1 and r["previsao_vencida"]:
        return "atrasada"
    if r["valor_pendente"] > 1:
        return "aguardando"
    return "recebida"


_USUARIOS_CACHE: dict = {"ts": 0.0, "nomes": {}}


def _usuarios_cache(cur) -> dict:
    """Nomes de usuários com cache de 1h (tabela pequena e estável; o túnel
    tem throughput baixo, então evitar re-transferir a cada load)."""
    import time
    if time.time() - _USUARIOS_CACHE["ts"] > 3600 or not _USUARIOS_CACHE["nomes"]:
        cur.execute(OC_USUARIOS_SQL)
        _USUARIOS_CACHE["nomes"] = {u["codigo"]: u["nome"] for u in cur.fetchall()}
        _USUARIOS_CACHE["ts"] = time.time()
    return _USUARIOS_CACHE["nomes"]


@cached(ttl=90)
def get_ordens_compra(filial: int | None, dt_de: str, dt_ate: str,
                      status: str | None = None, fornecedor: str | None = None,
                      criador: int | None = None, aprovador: int | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate,
              "status": status, "fornecedor": fornecedor,
              "criador": criador, "aprovador": aprovador}
    MAX_OCS_POR_FORN = 50
    with db.get_conn() as conn, conn.cursor() as cur:
        # o planner do 9.3 escolhe merge join por (grupo,empresa) — quase
        # constantes — e o join OC×recebimentos vira O(n×m) (~50s); com hash
        # join a mesma consulta sai em <1s
        cur.execute("SET LOCAL enable_mergejoin = off")
        cur.execute(OC_ROWS_SQL, params)
        rows = cur.fetchall()
        nomes = _usuarios_cache(cur)
        cur.execute(OC_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    forn_lower = fornecedor.lower() if fornecedor else None
    for r in rows:
        r["status"] = _oc_status(r)

    def match(r: dict, skip: str = "") -> bool:
        if skip != "status" and status and r["status"] != status:
            return False
        if skip != "fornecedor" and forn_lower and forn_lower not in r["fornecedor"].lower():
            return False
        if skip != "criador" and criador is not None and r["criador_cod"] != criador:
            return False
        if skip != "aprovador" and aprovador is not None and r["aprovador_cod"] != aprovador:
            return False
        return True

    sel = [r for r in rows if match(r)]

    kpis = {
        "ocs": len(sel),
        "valor": sum(r["valor"] for r in sel),
        "aprovacao_qtd": sum(1 for r in sel if r["status"] == "aprovacao"),
        "aprovacao_valor": sum(r["valor"] for r in sel if r["status"] == "aprovacao"),
        "pend_qtd": sum(1 for r in sel if r["valor_pendente"] > 1),
        "pend_valor": sum(r["valor_pendente"] for r in sel if r["valor_pendente"] > 1),
        "atraso_qtd": sum(1 for r in sel if r["status"] == "atrasada"),
        "atraso_valor": sum(r["valor_pendente"] for r in sel if r["status"] == "atrasada"),
    }

    # fornecedores agregados (top 30 por valor) com ordens aninhadas
    grupos: dict[str, dict] = {}
    for r in sel:
        g = grupos.setdefault(r["codigo_forn"], {
            "fornecedor": r["fornecedor"], "ocs": 0, "valor": 0.0,
            "valor_pendente": 0.0, "atrasadas": 0, "em_aprovacao": 0, "_rows": []})
        g["ocs"] += 1
        g["valor"] += r["valor"]
        g["valor_pendente"] += r["valor_pendente"] if r["valor_pendente"] > 1 else 0
        g["atrasadas"] += 1 if r["status"] == "atrasada" else 0
        g["em_aprovacao"] += 1 if r["status"] == "aprovacao" else 0
        g["_rows"].append(r)
    fornecedores = []
    for codigo, g in sorted(grupos.items(), key=lambda kv: -kv[1]["valor"])[:30]:
        ordens = sorted(g.pop("_rows"), key=lambda r: (-r["valor_pendente"], r["emissao"]), reverse=False)
        ordens.sort(key=lambda r: -r["valor_pendente"])
        g["doc"] = _mask_doc(codigo)
        g["ocultas"] = max(0, len(ordens) - MAX_OCS_POR_FORN)
        g["ordens"] = [{
            "numero": r["numero"], "filial": r["filial"], "emissao": r["emissao"],
            "previsao_entrega": r["previsao_entrega"],
            "criador": nomes.get(r["criador_cod"], f"usuário {r['criador_cod']}"),
            "aprovador": (nomes.get(r["aprovador_cod"], f"usuário {r['aprovador_cod']}")
                          if r["aprovador_cod"] is not None else None),
            "valor": r["valor"],
            "valor_pendente": r["valor_pendente"] if r["valor_pendente"] > 1 else 0,
            "status": r["status"],
        } for r in ordens[:MAX_OCS_POR_FORN]]
        fornecedores.append(g)

    # opções facetadas (todos os filtros exceto o próprio)
    def facet(campo: str, skip: str) -> list:
        cont: dict = {}
        for r in rows:
            if r[campo] is None or not match(r, skip=skip):
                continue
            cont[r[campo]] = cont.get(r[campo], 0) + 1
        return [{"codigo": c, "nome": nomes.get(c, f"usuário {c}"), "ocs": n}
                for c, n in sorted(cont.items(), key=lambda kv: -kv[1])]

    return {
        "kpis": kpis,
        "fornecedores": fornecedores,
        "mensal": mensal,
        "criadores": facet("criador_cod", "criador"),
        "aprovadores": facet("aprovador_cod", "aprovador"),
        "dt_de": dt_de, "dt_ate": dt_ate,
        "filial": filial, "status": status, "fornecedor": fornecedor,
        "criador": criador, "aprovador": aprovador,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · ordemcompra × NF de entrada · leitura",
    }


# ============================================================================
# Agregados e Terceiros — manifesto (viagens) × veiculo.tipofrota × conhecimento
# (km) × acertoviagemagregado (acertos/contratos).
# tipofrota: 1 = frota própria, 2 = TERCEIRO, 3 = AGREGADO (confirmado pelo negócio:
# o custo de compra de frete concentra em 2 e 3; a própria tem custo ~0).
# km da viagem = max(kmfrete) dos CT-es da composição (mesma rota; somar
# superconta). R$/km agregado = soma(custo das viagens com km) / soma(km).
# ============================================================================
def _agr_base(where_data: str) -> str:
    """Viagens de agregados/terceiros: fonte canonica = programacaoembarque
    (semaforo=1, nao cancelada). km = kmfretecompra (cobertura ~100%);
    custo = valorfretecompra; tipo=3 = deslocamento vazio."""
    return f"""
WITH mx AS (
  SELECT p.numero, p.filial, p.dtemissao,
         p.cnpjcpfcodigoveiculo AS codigo, p.veiculo AS placa,
         coalesce(u.descricao,'?') AS utilizacao,
         coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
         coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
         coalesce(p.valorfretecompra,0) AS custo,
         coalesce(p.valorfrete,0) AS receita,
         coalesce(p.kmfretecompra,0) AS km,
         (p.tipo = 3) AS vazio,
         coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), '(sem cadastro)') AS transportador
  FROM programacaoembarque p
  JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
  LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
  LEFT JOIN cadastro c ON c.codigo = p.cnpjcpfcodigoveiculo
  WHERE {where_data}
    AND p.dtcancelamento IS NULL AND p.semaforo = 1
    AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
    AND (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
    AND (%(transportador)s::text IS NULL OR c.nomefantasia ILIKE '%%'||%(transportador)s||'%%'
         OR c.razaosocial ILIKE '%%'||%(transportador)s||'%%')
)
"""


_AGR_DATA = "p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1"
_AGR_12M = "p.dtemissao >= date_trunc('month', current_date) - interval '11 months'"

AGR_KPI_SQL = _agr_base(_AGR_DATA) + """
SELECT count(*)::int AS viagens,
       coalesce(sum(custo),0)::float8 AS valor,
       coalesce(sum(receita),0)::float8 AS receita,
       count(DISTINCT codigo)::int AS transportadores,
       coalesce(sum(CASE WHEN km>0 THEN km ELSE 0 END),0)::float8 AS km_total,
       coalesce(sum(CASE WHEN km>0 THEN custo ELSE 0 END),0)::float8 AS valor_com_km,
       sum(CASE WHEN km>0 THEN 1 ELSE 0 END)::int AS viagens_com_km
FROM mx
"""

AGR_TRANSP_SQL = _agr_base(_AGR_DATA) + """
SELECT codigo, min(transportador) AS transportador, min(utilizacao) AS utilizacao,
       count(*)::int AS viagens,
       sum(custo)::float8 AS valor,
       sum(receita)::float8 AS receita,
       sum(CASE WHEN km>0 THEN km ELSE 0 END)::float8 AS km,
       sum(CASE WHEN km>0 THEN custo ELSE 0 END)::float8 AS valor_com_km
FROM mx GROUP BY codigo
ORDER BY sum(custo) DESC LIMIT 30
"""

AGR_VIAGENS_SQL = _agr_base(_AGR_DATA) + """
SELECT codigo AS codigo_t, numero, filial,
       to_char(dtemissao,'YYYY-MM-DD') AS emissao,
       placa, origem, destino,
       custo::float8 AS valor, receita::float8 AS receita, km::float8 AS km
FROM mx WHERE codigo = ANY(%(codigos)s)
ORDER BY codigo, custo DESC
"""

AGR_MENSAL_SQL = _agr_base(_AGR_DATA) + """
SELECT to_char(dtemissao,'YYYY-MM') AS mes, count(*)::int AS viagens,
       sum(custo)::float8 AS valor,
       sum(receita)::float8 AS receita,
       sum(CASE WHEN km>0 THEN km ELSE 0 END)::float8 AS km,
       sum(CASE WHEN km>0 THEN custo ELSE 0 END)::float8 AS valor_com_km
FROM mx GROUP BY 1 ORDER BY 1
"""

# Acertos (fechamentos) por transportador no período.
AGR_ACERTOS_SQL = """
SELECT a.cnpjcpfcodigo AS codigo, count(*)::int AS acertos,
       coalesce(sum(a.valortotalfaturamento),0)::float8 AS valor_acertos,
       coalesce(sum(a.valortotaladiantamento),0)::float8 AS adiantamentos
FROM acertoviagemagregado a
WHERE a.dtemissao >= %(dt_de)s::date AND a.dtemissao < %(dt_ate)s::date + 1
  AND (a.filial = %(filial)s OR %(filial)s::int IS NULL)
GROUP BY 1
"""


@cached(ttl=90)
def get_agregados(filial: int | None, dt_de: str, dt_ate: str,
                  modalidade: str | None = None, transportador: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate,
              "modalidade": modalidade, "transportador": transportador}
    MAX_VIAGENS = 30
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(AGR_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(AGR_TRANSP_SQL, params)
        transportadores = cur.fetchall()
        viagens: dict[str, list] = {}
        codigos = [t["codigo"] for t in transportadores if t["codigo"]]
        if codigos:
            cur.execute(AGR_VIAGENS_SQL, {**params, "codigos": codigos})
            for r in cur.fetchall():
                viagens.setdefault(r.pop("codigo_t"), []).append(r)
        cur.execute(AGR_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute(AGR_ACERTOS_SQL, params)
        acertos = {r["codigo"]: r for r in cur.fetchall()}
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    kpis["rs_km"] = (kpis["valor_com_km"] / kpis["km_total"]) if kpis["km_total"] else None
    kpis["pct_pago"] = (100.0 * kpis["valor"] / kpis["receita"]) if kpis["receita"] else None
    kpis["acertos"] = sum(a["acertos"] for a in acertos.values())
    kpis["valor_acertos"] = sum(a["valor_acertos"] for a in acertos.values())

    for t in transportadores:
        t["pct_pago"] = (100.0 * t["valor"] / t["receita"]) if t.get("receita") else None
        codigo = t.pop("codigo")
        t["doc"] = _mask_doc(codigo)
        t["rs_km"] = (t["valor_com_km"] / t["km"]) if t["km"] else None
        a = acertos.get(codigo, {})
        t["acertos"] = a.get("acertos", 0)
        t["valor_acertos"] = a.get("valor_acertos", 0.0)
        vs = viagens.get(codigo, [])
        for v in vs:
            v["rs_km"] = (v["valor"] / v["km"]) if v["km"] else None
        t["ocultas"] = max(0, len(vs) - MAX_VIAGENS)
        t["viagens_lista"] = vs[:MAX_VIAGENS]

    for r in mensal:
        r["rs_km"] = (r["valor_com_km"] / r["km"]) if r["km"] else None

    return {
        "kpis": kpis,
        "transportadores": transportadores,
        "mensal": mensal,
        "dt_de": dt_de, "dt_ate": dt_ate,
        "filial": filial, "modalidade": modalidade, "transportador": transportador,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · manifesto × conhecimento (km) × acertoviagemagregado · leitura",
    }


# ============================================================================
# Make vs Buy — CKM da frota própria (custos do razão ÷ km carregado dos
# manifestos próprios) contra o R$/km pago a agregados e terceiros.
# Mesma régua nos dois lados: km carregado = max(kmfrete) dos CT-es da viagem.
# km estimado = km medido × (viagens ÷ viagens com km) — cobertura declarada.
# Créditos tributários (4.1.1.15) ficam FORA do cálculo por km (são mistos
# entre frota própria e afretamento) e são reportados à parte.
# ============================================================================
MVB_CUSTO_SQL = """
SELECT mes, comp, sum(valor)::float8 AS valor FROM (
  SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
    CASE
      WHEN p.estrutural LIKE '4.1.1.01%%' THEN 'combustivel'
      WHEN p.estrutural LIKE '4.1.1.02%%' THEN 'manutencao'
      WHEN p.estrutural LIKE '4.1.1.04%%' THEN 'pneus'
      WHEN p.estrutural ~ '^4\\.1\\.1\\.(03|07|09|13)' THEN 'outros_var'
      WHEN p.estrutural LIKE '4.1.1.15%%' THEN 'creditos'
      WHEN p.estrutural ~ '^4\\.1\\.2\\.(01|02|03)' THEN 'motoristas'
      WHEN p.estrutural ~ '^4\\.1\\.2\\.(04|05|06)' THEN 'fixo'
      WHEN p.estrutural LIKE '4.1.1.12%%' THEN 'depreciacao'
      WHEN p.estrutural ~ '^4\\.1\\.1\\.(05|06|10|11)' THEN 'fixo'
      WHEN p.estrutural LIKE '4.1.3%%' THEN 'fixo'
      ELSE NULL END AS comp,
    (coalesce(l.valordebito,0) - coalesce(l.valorcredito,0)) AS valor
  FROM lancamento l
  JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
    AND p.estrutural LIKE '4.1%%' AND coalesce(l.historico,0) <> 18
) t WHERE comp IS NOT NULL
GROUP BY mes, comp ORDER BY mes, comp
"""


def _mvb_km_sql(tipofrota_cond: str, extra_cols: str = "") -> str:
    """km por mes da programacaoembarque (semaforo=1), separando carregado
    (tipo<>3) de vazio (tipo=3). Fonte canonica de km e custo de compra."""
    return f"""
SELECT to_char(p.dtemissao,'YYYY-MM') AS mes{extra_cols},
       count(*)::int AS viagens,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_carregado,
       sum(CASE WHEN p.tipo = 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_vazio,
       sum(coalesce(p.valorfretecompra,0))::float8 AS custo_compra
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo AND {tipofrota_cond}
WHERE p.dtemissao >= %(de)s::date AND p.dtemissao < %(ate)s::date
  AND p.dtcancelamento IS NULL AND p.semaforo = 1
GROUP BY 1{extra_cols} ORDER BY 1
"""


MVB_PROPRIA_SQL = _mvb_km_sql("v.utilizacaoveiculo IN ('TRA','LOC')")
MVB_BUY_SQL = _mvb_km_sql("v.utilizacaoveiculo IN ('AGR','TER')", ", v.utilizacaoveiculo")



# Rotas contratadas (AGR/TER) no período — para comparar R$/km da rota com o
# CKM próprio: onde a contratação está cara, vale posicionar frota própria.
MVB_ROTA_SQL = """
SELECT coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       count(*)::int AS viagens,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km,
       sum(coalesce(p.valorfretecompra,0))::float8 AS custo,
       sum(coalesce(p.valorfrete,0))::float8 AS receita
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
WHERE p.dtemissao >= %(de)s::date AND p.dtemissao < %(ate)s::date
  AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
GROUP BY 1, 2
HAVING sum(coalesce(p.kmfretecompra,0)) >= 5000
ORDER BY 5 DESC LIMIT 25
"""


@cached(ttl=300)
def get_make_vs_buy(comp_de: str, comp_ate: str) -> dict:
    de, ate = _comp_bounds(comp_de, comp_ate)
    params = {"de": de, "ate": ate}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(MVB_CUSTO_SQL, params)
        custos_rows = cur.fetchall()
        cur.execute(MVB_PROPRIA_SQL, params)
        propria_rows = cur.fetchall()
        cur.execute(MVB_BUY_SQL, params)
        buy_rows = cur.fetchall()
        cur.execute(MVB_ROTA_SQL, params)
        rota_rows = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    custos: dict[str, dict] = {}
    for r in custos_rows:
        custos.setdefault(r["mes"], {})[r["comp"]] = r["valor"]
    propria = {r["mes"]: r for r in propria_rows}
    buy: dict[str, dict] = {}
    for r in buy_rows:
        buy.setdefault(r["mes"], {})[r["utilizacaoveiculo"]] = r

    meses = sorted(set(custos) | set(propria) | set(buy))
    VAR = ("combustivel", "manutencao", "pneus", "outros_var")
    mensal = []
    tot = {"var": 0.0, "motoristas": 0.0, "fixo": 0.0, "depreciacao": 0.0,
           "creditos": 0.0, "km_carregado": 0.0, "km_vazio": 0.0,
           "viagens_proprias": 0, "comp": {}}
    tot_buy = {"TER": {"km": 0.0, "custo": 0.0}, "AGR": {"km": 0.0, "custo": 0.0}}
    for mes in meses:
        c = custos.get(mes, {})
        var = sum(c.get(k, 0.0) for k in VAR)
        mot = c.get("motoristas", 0.0)
        fixo = c.get("fixo", 0.0)
        dep = c.get("depreciacao", 0.0)
        p = propria.get(mes) or {"km_carregado": 0.0, "km_vazio": 0.0, "viagens": 0}
        kmc = p["km_carregado"]
        b2, b3 = buy.get(mes, {}).get('TER'), buy.get(mes, {}).get('AGR')

        def rs(b):
            return (b["custo_compra"] / b["km_carregado"]) if b and b["km_carregado"] else None

        mensal.append({
            "mes": mes,
            "km_proprio": kmc + p["km_vazio"],
            "retorno_vazio": (p["km_vazio"] / (kmc + p["km_vazio"])) if (kmc + p["km_vazio"]) else None,
            "ckm_marginal": ((var + mot) / kmc) if kmc else None,
            "ckm_cheio": ((var + mot + fixo + dep) / kmc) if kmc else None,
            "rs_km_agregado": rs(b3),
            "rs_km_terceiro": rs(b2),
        })
        tot["var"] += var; tot["motoristas"] += mot; tot["fixo"] += fixo
        tot["depreciacao"] += dep; tot["creditos"] += c.get("creditos", 0.0)
        tot["km_carregado"] += kmc; tot["km_vazio"] += p["km_vazio"]
        tot["viagens_proprias"] += p["viagens"]
        for k in list(VAR) + ["motoristas", "fixo", "depreciacao"]:
            tot["comp"][k] = tot["comp"].get(k, 0.0) + c.get(k, 0.0)
        for tf, b in (('TER', b2), ('AGR', b3)):
            if b:
                tot_buy[tf]["km"] += b["km_carregado"]
                tot_buy[tf]["custo"] += b["custo_compra"]

    kmc = tot["km_carregado"]
    km_total = kmc + tot["km_vazio"]
    resumo = {
        "km_proprio_estimado": km_total,       # nomes mantidos p/ compat do front
        "km_proprio_medido": km_total,          # agora é medido de verdade
        "km_carregado": kmc,
        "km_vazio": tot["km_vazio"],
        "retorno_vazio": (tot["km_vazio"] / km_total) if km_total else None,
        "cobertura_km": 1.0,                    # kmfretecompra ~100% preenchido
        "viagens_proprias": tot["viagens_proprias"],
        "custo_var": tot["var"], "custo_motoristas": tot["motoristas"],
        "custo_fixo": tot["fixo"], "depreciacao": tot["depreciacao"],
        "creditos_tributarios": tot["creditos"],
        # CKM por km CARREGADO (produtivo) — comparável ao R$/km contratado
        "ckm_marginal": ((tot["var"] + tot["motoristas"]) / kmc) if kmc else None,
        "ckm_cheio": ((tot["var"] + tot["motoristas"] + tot["fixo"] + tot["depreciacao"]) / kmc) if kmc else None,
        # CKM bruto (por km total, carregado+vazio) — referência
        "ckm_bruto_marginal": ((tot["var"] + tot["motoristas"]) / km_total) if km_total else None,
        "rs_km_agregado": (tot_buy["AGR"]["custo"] / tot_buy["AGR"]["km"]) if tot_buy["AGR"]["km"] else None,
        "rs_km_terceiro": (tot_buy["TER"]["custo"] / tot_buy["TER"]["km"]) if tot_buy["TER"]["km"] else None,
        "componentes_km": {k: (v / kmc if kmc else None) for k, v in tot["comp"].items()},
    }
    ckm_marg = resumo["ckm_marginal"]
    rotas = []
    for r in rota_rows:
        rs = (r["custo"] / r["km"]) if r["km"] else None
        spread = (ckm_marg - rs) if (rs is not None and ckm_marg) else None
        rotas.append({
            **r, "rs_km": rs, "spread": spread,
            "margem_compra": ((r["receita"] - r["custo"]) / r["receita"]) if r["receita"] else None,
            # spread negativo = contratar sai MAIS CARO que o custo marginal
            # próprio -> candidata a rodar frota própria
            "recomendacao": None if spread is None else ("propria" if spread < 0 else "contratar"),
        })
    rotas.sort(key=lambda x: (x["spread"] if x["spread"] is not None else 999))

    return {
        "comp_de": comp_de, "comp_ate": comp_ate,
        "resumo": resumo, "mensal": mensal, "rotas": rotas,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · programação de embarque (km/custo) × razão (custos próprios) · consolidado",
    }


# ============================================================================
# Comercial — clientes (AGRUPAMENTO/grupo economico), receita e RKM a partir
# da programacao de embarque (viagem carregada, semaforo=1, nao cancelada).
# km = kmfretecompra; receita = valorfrete; RKM = receita / km carregado.
# ============================================================================
_COM_BASE = """
FROM programacaoembarque p
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (%(cliente)s::text IS NULL OR ag.descricao ILIKE '%%'||%(cliente)s||'%%'
       OR cp.nomefantasia ILIKE '%%'||%(cliente)s||'%%' OR cp.razaosocial ILIKE '%%'||%(cliente)s||'%%')
"""

_COM_KEY = "coalesce('AG'||ag.codigo::text, co.cnpjcpfcodigopagadorfrete, '(sem)')"
_COM_NOME = ("coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''), "
             "nullif(trim(cp.razaosocial),''), '(sem cliente)')")
_COM_PERIODO = "AND p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1"

CLI_KPI_SQL = f"""
SELECT count(*)::int AS ctes,
       coalesce(sum(p.valorfrete),0)::float8 AS receita,
       count(DISTINCT {_COM_KEY})::int AS clientes,
       coalesce(sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN p.kmfretecompra ELSE 0 END),0)::float8 AS km,
       coalesce(sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN coalesce(p.valorfrete,0) ELSE 0 END),0)::float8 AS receita_com_km,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN 1 ELSE 0 END)::int AS ctes_com_km
{_COM_BASE} {_COM_PERIODO}
"""

CLI_MENSAL_SQL = f"""
SELECT to_char(p.dtemissao,'YYYY-MM') AS mes, count(*)::int AS ctes,
       sum(coalesce(p.valorfrete,0))::float8 AS receita,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN p.kmfretecompra ELSE 0 END)::float8 AS km,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN coalesce(p.valorfrete,0) ELSE 0 END)::float8 AS receita_com_km
{_COM_BASE} {_COM_PERIODO}
GROUP BY 1 ORDER BY 1
"""

CLI_TOP_SQL = f"""
SELECT {_COM_KEY} AS codigo,
       min({_COM_NOME}) AS cliente,
       count(*)::int AS ctes,
       sum(coalesce(p.valorfrete,0))::float8 AS receita,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN p.kmfretecompra ELSE 0 END)::float8 AS km,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN coalesce(p.valorfrete,0) ELSE 0 END)::float8 AS receita_com_km
{_COM_BASE} {_COM_PERIODO}
GROUP BY {_COM_KEY}
ORDER BY 4 DESC LIMIT 30
"""

CLI_ANT_SQL = f"""
SELECT {_COM_KEY} AS codigo,
       min({_COM_NOME}) AS cliente,
       sum(coalesce(p.valorfrete,0))::float8 AS receita
{_COM_BASE}
  AND p.dtemissao >= %(dt_de)s::date - interval '1 year'
  AND p.dtemissao < %(dt_ate)s::date + 1 - interval '1 year'
GROUP BY {_COM_KEY}
"""

CLI_ROTAS_SQL = f"""
SELECT {_COM_KEY} AS codigo_c,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       count(*)::int AS ctes,
       sum(coalesce(p.valorfrete,0))::float8 AS receita,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN p.kmfretecompra ELSE 0 END)::float8 AS km,
       sum(CASE WHEN coalesce(p.kmfretecompra,0)>0 THEN coalesce(p.valorfrete,0) ELSE 0 END)::float8 AS receita_com_km
{_COM_BASE} {_COM_PERIODO} AND {_COM_KEY} = ANY(%(codigos)s)
GROUP BY 1, 2, 3
ORDER BY 1, 5 DESC
"""




# ============================================================================
# Heurística de recuperação dos "(sem cliente)": programações sem coleta
# vinculada (operação de Piraquara programa direto). Cliente = pagador do
# CT-e autorizado do MESMO veículo emitido entre saída-1d e saída+2d (o mais
# próximo). Recupera ~91% do valor; o resto segue como "(sem cliente)".
# ============================================================================
HEUR_SEMCLI_SQL = """
SELECT coalesce('AG'||ag.codigo::text, s.pagador, '(sem)') AS codigo,
       min(coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''),
                    nullif(trim(cp.razaosocial),''), '(sem cliente)')) AS cliente,
       count(*)::int AS ctes,
       sum(s.valorfrete)::float8 AS receita,
       sum(CASE WHEN s.km > 0 THEN s.km ELSE 0 END)::float8 AS km,
       sum(CASE WHEN s.km > 0 THEN s.valorfrete ELSE 0 END)::float8 AS receita_com_km,
       sum(CASE WHEN s.utilizacao IN ('AGR','TER') THEN s.custocompra ELSE 0 END)::float8 AS custo_comprado,
       sum(CASE WHEN s.utilizacao IN ('AGR','TER') AND s.km > 0 THEN s.km ELSE 0 END)::float8 AS km_comprado,
       sum(CASE WHEN s.utilizacao IN ('TRA','LOC') AND s.km > 0 THEN s.km ELSE 0 END)::float8 AS km_proprio
FROM (
  SELECT DISTINCT ON (p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero)
         coalesce(p.valorfrete,0) AS valorfrete,
         coalesce(p.valorfretecompra,0) AS custocompra,
         coalesce(p.kmfretecompra,0) AS km,
         v.utilizacaoveiculo AS utilizacao,
         c.cnpjcpfcodigopagadorfrete AS pagador
  FROM programacaoembarque p
  LEFT JOIN veiculo v ON v.placa = p.veiculo
  LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
    AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
    AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
    AND co.numero=p.numerodocumentoorigem
  LEFT JOIN conhecimento c ON c.veiculo = p.veiculo
    AND c.situacaocte = 3 AND c.tipo IN (1,4)
    AND c.dtemissao >= %(dt_de)s::date - 4
    AND c.dtemissao BETWEEN coalesce(p.dtsaida, p.dtemissao) - interval '1 day'
                        AND coalesce(p.dtsaida, p.dtemissao) + interval '2 days'
  WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
    AND p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
    AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
    AND co.numero IS NULL
  ORDER BY p.grupo, p.empresa, p.filial, p.diferenciadornumero, p.numero,
           abs(extract(epoch FROM (c.dtemissao - coalesce(p.dtsaida, p.dtemissao))))
) s
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = s.pagador
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = s.pagador
GROUP BY 1
"""


def _merge_heuristica(clientes: list[dict], heur: list[dict],
                      campos: tuple[str, ...]) -> list[dict]:
    """Redistribui os recuperados: soma nos clientes certos e abate do
    "(sem)". Linhas de clientes que só existem via heurística entram novas."""
    por_codigo = {c["codigo"]: c for c in clientes}
    sem = por_codigo.get("(sem)")
    for h in heur:
        if h["codigo"] == "(sem)":
            continue                      # nem o CT-e achou: fica no bucket
        if sem:
            sem["ctes"] = max(0, sem["ctes"] - h["ctes"])
            for f in campos:
                sem[f] = max(0.0, sem[f] - h[f])
        alvo = por_codigo.get(h["codigo"])
        if alvo:
            alvo["ctes"] += h["ctes"]
            for f in campos:
                alvo[f] += h[f]
        else:
            novo = {k: h[k] for k in ("codigo", "cliente", "ctes", *campos)}
            clientes.append(novo)
            por_codigo[h["codigo"]] = novo
    if sem and sem.get("receita", 0) <= 0:
        clientes.remove(sem)
    return clientes


# Re-preço cirúrgico: RKM que o cliente paga vs RKM dos DEMAIS clientes na
# mesma rota. Onde o delta é negativo, há dinheiro na mesa com evidência.
RKM_ROTA_SQL = f"""
SELECT coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       sum(coalesce(p.valorfrete,0))::float8 AS receita,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km
{_COM_BASE} {_COM_PERIODO} AND coalesce(p.kmfretecompra,0) > 0
GROUP BY 1, 2
HAVING sum(coalesce(p.kmfretecompra,0)) >= 3000
"""

RKM_CLI_ROTA_SQL = f"""
SELECT {_COM_KEY} AS codigo, min({_COM_NOME}) AS cliente,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       count(*)::int AS viagens,
       sum(coalesce(p.valorfrete,0))::float8 AS receita,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km
{_COM_BASE} {_COM_PERIODO} AND coalesce(p.kmfretecompra,0) > 0
GROUP BY {_COM_KEY}, 3, 4
HAVING sum(coalesce(p.kmfretecompra,0)) >= 3000
"""

# Meta x realizado do MÊS CORRENTE por agrupamento (metas são globais:
# sem filtro de filial/cliente aqui).
COM_META_SQL = """
SELECT 'AG'||m.agrupamentocliente::text AS codigo,
       min(coalesce(nullif(trim(ag.descricao),''),'(sem nome)')) AS cliente,
       sum(CASE WHEN m.dt <= current_date THEN m.valor ELSE 0 END)::float8 AS meta_mtd,
       sum(m.valor)::float8 AS meta_mes
FROM sulista.metafaturamento_agrupamentoclientedia m
LEFT JOIN agrupamentocliente ag ON ag.codigo = m.agrupamentocliente
WHERE m.tipo = 1
  AND m.dt >= date_trunc('month', current_date)
  AND m.dt < date_trunc('month', current_date) + interval '1 month'
GROUP BY 1
HAVING sum(m.valor) > 0
"""

# Realizado do mês por cliente = faturamento OFICIAL (3 fontes por dtemissao:
# conhecimento + notafiscalservico + sulista.faturamentokmm), agrupado por
# agrupamentocliente — chave 'AG'||codigo, casando com COM_META_SQL. Antes
# usava p.valorfrete (viagens), que diverge do faturamento oficial da empresa.
COM_REAL_MES_SQL = """
SELECT codigo, sum(realizado)::float8 AS realizado FROM (
  SELECT 'AG'||ac.codigo::text AS codigo, sum(c.valortotalprestacao) AS realizado
  FROM conhecimento c
  JOIN agrupamentocliente_cnpjcpfcodigo acc ON acc.grupo=c.grupo AND acc.empresa=c.empresa
     AND acc.cnpjcpfcodigo=c.cnpjcpfcodigopagadorfrete AND acc.vinculo=1
  JOIN agrupamentocliente ac ON ac.grupo=acc.grupo AND ac.empresa=acc.empresa AND ac.codigo=acc.codigo
  WHERE c.grupo=1 AND c.empresa=1 AND c.unidade=1 AND c.numero<1000000
    AND c.dtcancelamento IS NULL AND c.situacaocte=3 AND c.tipo IN (1,4)
    AND c.dtemissao::date BETWEEN %(dt_de)s AND %(dt_ate)s
  GROUP BY 1
  UNION ALL
  SELECT 'AG'||ac.codigo::text, sum(n.valortotalbruto)
  FROM notafiscalservico n
  JOIN agrupamentocliente_cnpjcpfcodigo acc ON acc.grupo=n.grupo AND acc.empresa=n.empresa
     AND acc.cnpjcpfcodigo=n.cnpjcpfcodigo AND acc.vinculo=1
  JOIN agrupamentocliente ac ON ac.grupo=acc.grupo AND ac.empresa=acc.empresa AND ac.codigo=acc.codigo
  WHERE n.grupo=1 AND n.empresa=1 AND n.numero<1000000 AND n.dtcancelamento IS NULL
    AND (n.emissaoeletronica=2 OR (n.emissaoeletronica=1 AND n.situacaonfse=3))
    AND n.dtemissao::date BETWEEN %(dt_de)s AND %(dt_ate)s
  GROUP BY 1
  UNION ALL
  SELECT 'AG'||ac.codigo::text, sum(k.valor_cte)
  FROM sulista.faturamentokmm k
  JOIN agrupamentocliente_cnpjcpfcodigo acc ON acc.grupo=k.grupo AND acc.empresa=k.empresa
     AND acc.cnpjcpfcodigo=k.pagadorfrete_cnpj AND acc.vinculo=1
  JOIN agrupamentocliente ac ON ac.grupo=acc.grupo AND ac.empresa=acc.empresa AND ac.codigo=acc.codigo
  WHERE k.dtemissao::date BETWEEN %(dt_de)s AND %(dt_ate)s
  GROUP BY 1
) t GROUP BY codigo
"""


@cached(ttl=90)
def get_comercial(filial: int | None, dt_de: str, dt_ate: str,
                  cliente: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate, "cliente": cliente}
    MAX_ROTAS = 20
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CLI_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(CLI_TOP_SQL, params)
        clientes = cur.fetchall()
        cur.execute(HEUR_SEMCLI_SQL, params)
        heur = cur.fetchall()
        clientes = _merge_heuristica(
            clientes, heur, ("receita", "km", "receita_com_km"))
        clientes.sort(key=lambda c: -c["receita"])
        clientes = clientes[:30]
        rotas: dict[str, list] = {}
        codigos = [r["codigo"] for r in clientes if r["codigo"]]
        if codigos:
            cur.execute(CLI_ROTAS_SQL, {**params, "codigos": codigos})
            for r in cur.fetchall():
                rotas.setdefault(r.pop("codigo_c"), []).append(r)
        cur.execute(CLI_ANT_SQL, params)
        anteriores = {r["codigo"]: r for r in cur.fetchall()}
        cur.execute(CLI_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute(RKM_ROTA_SQL, params)
        rkm_rotas = cur.fetchall()
        cur.execute(RKM_CLI_ROTA_SQL, params)
        rkm_cli_rotas = cur.fetchall()
        cur.execute(COM_META_SQL)
        metas_rows = cur.fetchall()
        mes_ini = date.today().replace(day=1).isoformat()
        mes_params = {"filial": None, "cliente": None,
                      "dt_de": mes_ini, "dt_ate": date.today().isoformat()}
        cur.execute(COM_REAL_MES_SQL, mes_params)
        real_mes = {r["codigo"]: r["realizado"] for r in cur.fetchall()}
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    kpis["rkm"] = (kpis["receita_com_km"] / kpis["km"]) if kpis["km"] else None
    receita_total = kpis["receita"] or 0.0
    top10 = sum(r["receita"] for r in clientes[:10])
    kpis["concentracao_top10"] = (top10 / receita_total) if receita_total else None

    vistos = set()
    for cl in clientes:
        codigo = cl.pop("codigo")
        vistos.add(codigo)
        cl["doc"] = "grupo econômico" if str(codigo).startswith("AG") else _mask_doc(codigo)
        cl["rkm"] = (cl["receita_com_km"] / cl["km"]) if cl["km"] else None
        cl["share"] = (cl["receita"] / receita_total) if receita_total else None
        ant = anteriores.get(codigo)
        cl["receita_anterior"] = ant["receita"] if ant else 0.0
        rs = rotas.get(codigo, [])
        for r in rs:
            r["rkm"] = (r["receita_com_km"] / r["km"]) if r["km"] else None
        cl["ocultas"] = max(0, len(rs) - MAX_ROTAS)
        cl["rotas"] = rs[:MAX_ROTAS]

    acum = 0.0
    abc = {"top1": None, "top5": None, "top10": None, "top20": None, "n80": None}
    if receita_total > 0:
        for i, cl in enumerate(clientes, start=1):
            acum += cl["receita"]
            if i == 1: abc["top1"] = acum / receita_total
            if i == 5: abc["top5"] = acum / receita_total
            if i == 10: abc["top10"] = acum / receita_total
            if i == 20: abc["top20"] = acum / receita_total
            if abc["n80"] is None and acum >= 0.8 * receita_total:
                abc["n80"] = i

    em_queda = []
    for cl in clientes:
        ant = cl.get("receita_anterior") or 0.0
        if cl["cliente"] == "(sem cliente)":
            continue                      # heuristica distorce o YoY do bucket
        if ant > 100000 and cl["receita"] < 0.7 * ant:
            em_queda.append({
                "cliente": cl["cliente"], "receita": cl["receita"],
                "receita_anterior": ant,
                "queda_pct": 100.0 * (cl["receita"] / ant - 1.0),
                "perda": ant - cl["receita"],
            })
    em_queda.sort(key=lambda x: -x["perda"])
    em_queda = em_queda[:12]

    perdidos = sorted(
        ({"cliente": a["cliente"], "receita_anterior": a["receita"]}
         for cod, a in anteriores.items()
         if cod not in vistos and a["receita"] > 50000),
        key=lambda x: -x["receita_anterior"])[:10]

    # --- re-preço: RKM do cliente vs RKM dos demais na mesma rota ---
    rota_tot = {(r["origem"], r["destino"]): r for r in rkm_rotas}
    reprecio = []
    for r in rkm_cli_rotas:
        t = rota_tot.get((r["origem"], r["destino"]))
        if not t:
            continue
        km_outros = t["km"] - r["km"]
        rec_outros = t["receita"] - r["receita"]
        if km_outros < 2000 or rec_outros <= 0:
            continue                      # rota sem base de comparação
        rkm_cli = r["receita"] / r["km"]
        rkm_outros = rec_outros / km_outros
        if rkm_cli < 1.0:
            continue                      # frete ~zero = operacao interna/CIF, nao subpreco
        delta = (rkm_cli / rkm_outros - 1.0) * 100.0
        if delta <= -5.0:
            reprecio.append({
                "cliente": r["cliente"], "origem": r["origem"], "destino": r["destino"],
                "viagens": r["viagens"], "km": r["km"],
                "rkm_cliente": rkm_cli, "rkm_outros": rkm_outros, "delta_pct": delta,
                "potencial": (rkm_outros - rkm_cli) * r["km"],
            })
    reprecio.sort(key=lambda x: -x["potencial"])
    reprecio = reprecio[:20]

    # --- meta x realizado do mês corrente por agrupamento ---
    metas = []
    for m in metas_rows:
        realizado = real_mes.get(m["codigo"], 0.0)
        metas.append({
            "cliente": m["cliente"], "meta_mtd": m["meta_mtd"], "meta_mes": m["meta_mes"],
            "realizado": realizado,
            "atingimento": (realizado / m["meta_mtd"]) if m["meta_mtd"] else None,
            "gap": m["meta_mtd"] - realizado,
        })
    metas.sort(key=lambda x: -x["gap"])
    metas = metas[:20]

    return {
        "kpis": kpis, "clientes": clientes, "mensal": mensal,
        "reprecio": reprecio, "metas_mes": metas, "em_queda": em_queda, "abc": abc,
        "clientes_perdidos": perdidos,
        "dt_de": dt_de, "dt_ate": dt_ate, "filial": filial, "cliente": cliente,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · programação de embarque × agrupamento de clientes · leitura",
    }


# ============================================================================
# Visão Geral — resumo executivo de todas as áreas em uma conexão.
# ============================================================================

# Ponto de equilíbrio: fixos totais (fixo op + adm + depreciação) sobre a
# margem de contribuição dos últimos 12 meses fechados do razão.
BREAKEVEN_SQL = f"""
SELECT grupo, sum(valor)::float8 AS valor FROM (
  SELECT {_DRE_GRUPO} AS grupo,
         (coalesce(l.valorcredito,0) - coalesce(l.valordebito,0)) AS valor
  {_DRE_BASE}
) t WHERE grupo IS NOT NULL GROUP BY grupo
"""

FIN_MENSAL_SQL = f"""
SELECT mes, sum(valor)::float8 AS valor FROM (
  SELECT to_char(l.dtlancamento,'YYYY-MM') AS mes,
         (coalesce(l.valordebito,0) - coalesce(l.valorcredito,0)) AS valor
  {_DRE_BASE} AND p.estrutural LIKE '4.2.4%%'
) t GROUP BY mes ORDER BY mes
"""

VG_MES_SQL = """
SELECT
  (SELECT coalesce(sum(valorfrete),0)::float8 FROM programacaoembarque
     WHERE dtcancelamento IS NULL AND semaforo = 1 AND tipo <> 3
       AND dtemissao >= date_trunc('month', current_date))                       AS receita_mes,
  (SELECT coalesce(sum(p.valorfretecompra),0)::float8 FROM programacaoembarque p
     JOIN veiculo v ON v.placa = p.veiculo AND v.utilizacaoveiculo IN ('AGR','TER')
     WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
       AND p.dtemissao >= date_trunc('month', current_date))                     AS frete_contratado_mes,
  (SELECT coalesce(sum(a.custo),0)::float8 FROM sulista.ctaplus_abastecimentos a
     JOIN veiculo v ON v.placa = a.veiculo_placa AND coalesce(v.utilizacaoveiculo,'') NOT IN ('AGR','TER')
     WHERE a.data_inicio_abastecimento >= date_trunc('month', current_date))     AS combustivel_proprio_mes,
  (SELECT coalesce(sum(valortotal),0)::float8 FROM ordemservico
     WHERE dtemissao >= date_trunc('month', current_date))                       AS manutencao_mes,
  (SELECT count(*)::int FROM ordemservico WHERE dtfechamento IS NULL)            AS os_abertas
"""


# Séries da Visão Geral: faturamento diário × meta (mês corrente, com os
# filtros fiscais do negócio: situacaocte=3, tipo IN (1,4) + KMM + NFS-e),
# km por modalidade (30 dias) e receita mensal (12 meses).
VG_DIARIO_SQL = """
SELECT dia, sum(realizado)::float8 AS realizado, sum(meta)::float8 AS meta FROM (
  SELECT extract(day from dtemissao)::int AS dia,
         coalesce(valortotalprestacao,0) AS realizado, 0::numeric AS meta
  FROM conhecimento
  WHERE dtemissao >= date_trunc('month', current_date)
    AND grupo = 1 AND empresa = 1 AND unidade = 1 AND numero < 1000000
    AND dtcancelamento IS NULL AND situacaocte = 3 AND tipo IN (1,4)
  UNION ALL
  SELECT extract(day from dtemissao)::int, coalesce(valor_cte,0), 0
  FROM sulista.faturamentokmm
  WHERE dtemissao >= date_trunc('month', current_date)
  UNION ALL
  SELECT extract(day from dtemissao)::int, coalesce(valortotalbruto,0), 0
  FROM notafiscalservico
  WHERE dtemissao >= date_trunc('month', current_date)
    AND grupo = 1 AND empresa = 1 AND numero < 1000000
    AND dtcancelamento IS NULL
    AND (emissaoeletronica = 2 OR (emissaoeletronica = 1 AND situacaonfse = 3))
  UNION ALL
  SELECT extract(day from dt)::int, 0, coalesce(valor,0)
  FROM sulista.metafaturamento_agrupamentoclientedia
  WHERE dt >= date_trunc('month', current_date)
    AND dt < date_trunc('month', current_date) + interval '1 month'
    AND tipo = 1
) t GROUP BY 1 ORDER BY 1
"""

VG_MODAL_KM_SQL = """
SELECT coalesce(u.descricao,'(sem)') AS utilizacao,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND p.dtemissao >= current_date - 30
GROUP BY 1 ORDER BY 2 DESC
"""

VG_REC12_SQL = """
SELECT to_char(p.dtemissao,'YYYY-MM') AS mes,
       sum(coalesce(p.valorfrete,0))::float8 AS receita
FROM programacaoembarque p
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND p.dtemissao >= date_trunc('month', current_date) - interval '11 months'
GROUP BY 1 ORDER BY 1
"""

# Contadores de OC agregados no banco (mesma regra de _oc_status): a Visão
# Geral só precisa de 3 números — trazer as linhas de 12 meses pelo túnel
# era o item mais caro da tela.
VG_OC_SQL = """
WITH oc AS (
  SELECT o.grupo, o.empresa, o.filial, o.diferenciadornumero, o.numero,
         o.dtprevisaoentrega, o.dtaprovador, coalesce(o.valortotal,0) AS valortotal
  FROM ordemcompra o
  WHERE o.dtemissao >= current_date - 365 AND o.dtemissao < current_date + 1
),
rec AS (
  SELECT r.grupo, r.empresa, r.filialordemcompra AS filial,
         r.diferenciadornumeroordemcompra AS diferenciadornumero,
         r.numeroordemcompra AS numero,
         sum(coalesce(r.valortotal,0)) AS valor_recebido
  FROM notafiscalentrada_item_ordemcomprarecebida r
  JOIN oc ON oc.grupo=r.grupo AND oc.empresa=r.empresa AND oc.filial=r.filialordemcompra
         AND oc.diferenciadornumero=r.diferenciadornumeroordemcompra AND oc.numero=r.numeroordemcompra
  GROUP BY 1,2,3,4,5
),
base AS (
  SELECT (oc.dtaprovador IS NULL) AS sem_aprovacao,
         coalesce(oc.dtprevisaoentrega < current_date, false) AS previsao_vencida,
         greatest(oc.valortotal - coalesce(rec.valor_recebido,0), 0) AS valor_pendente
  FROM oc LEFT JOIN rec ON rec.grupo=oc.grupo AND rec.empresa=oc.empresa AND rec.filial=oc.filial
       AND rec.diferenciadornumero=oc.diferenciadornumero AND rec.numero=oc.numero
)
SELECT
  coalesce(sum(CASE WHEN NOT sem_aprovacao AND valor_pendente > 1 AND previsao_vencida
                    THEN 1 ELSE 0 END),0)::int                                        AS oc_atrasadas,
  coalesce(sum(CASE WHEN NOT sem_aprovacao AND valor_pendente > 1 AND previsao_vencida
                    THEN valor_pendente ELSE 0 END),0)::float8                        AS oc_atraso_valor,
  coalesce(sum(CASE WHEN sem_aprovacao THEN 1 ELSE 0 END),0)::int                    AS oc_aprovacao
FROM base
"""


def _ponto_equilibrio(g: dict) -> dict | None:
    """Faturamento bruto mensal mínimo para resultado zero (média 12m)."""
    rb = g.get("receita_bruta", 0.0)
    rl = rb + g.get("deducoes", 0.0)              # deduções vêm negativas
    if rl <= 0:
        return None
    var = -(g.get("custo_var", 0.0) + g.get("custo_motorista", 0.0))
    fixos = -(g.get("fixo", 0.0) + g.get("adm", 0.0) + g.get("depreciacao", 0.0))
    mc_pct = (rl - var) / rl
    if mc_pct <= 0:
        return None
    be_rl = fixos / mc_pct
    return {
        "faturamento_minimo_mes": (be_rl * (rb / rl)) / 12.0,
        "mc_pct": mc_pct * 100.0,
        "fixos_mes": fixos / 12.0,
    }


@cached(ttl=60)
def get_visao_geral() -> dict:
    from concurrent.futures import ThreadPoolExecutor

    fin_params = {"filial": None, "data_ref": None, "venc_de": None, "venc_ate": None}
    de_be = (date.today().replace(day=1) - __import__("datetime").timedelta(days=365)).replace(day=1).isoformat()
    ate_be = date.today().replace(day=1).isoformat()

    # A tela consolida ~12 consultas num banco atrás de túnel SSH: rodar em
    # série soma todas as latências. Grupos independentes em conexões
    # próprias (o pool do db.py reusa) derrubam o tempo para o pior grupo.
    def _roda(lote):
        out = []
        with db.get_conn() as conn, conn.cursor() as cur:
            for sql, params, um in lote:
                cur.execute(sql, params)
                if um is not None:
                    out.append(cur.fetchone() if um else cur.fetchall())
        return out

    grupos = [
        [(KPI_SQL, fin_params, True), (SALDO_SQL, fin_params, True),
         (RUNRATE_SQL, fin_params, True)],
        [(FLUXO_SQL, fin_params, False), (BREAKEVEN_SQL, {"de": de_be, "ate": ate_be}, False)],
        [(VG_MES_SQL, None, True), (VG_DIARIO_SQL, None, False)],
        # o SET LOCAL evita o merge join degenerado do 9.3 no join OC×recebimentos
        [("SET LOCAL enable_mergejoin = off", None, None),
         (VG_MODAL_KM_SQL, None, False), (VG_REC12_SQL, None, False),
         (VG_OC_SQL, None, True), ("SELECT current_timestamp AS ts", None, True)],
    ]
    with ThreadPoolExecutor(max_workers=len(grupos)) as ex:
        g_fin, g_fluxo, g_mes, g_series = list(ex.map(_roda, grupos))

    fin, saldo, rr = g_fin
    runrate = (rr or {}).get("runrate") or 0.0
    fluxo = g_fluxo[0][:13]
    be_rows = {r["grupo"]: r["valor"] for r in g_fluxo[1]}
    mes, diario = g_mes
    modal_km, receita_12m, oc, meta = g_series

    bancos = (saldo.get("bancos") or 0.0) + (saldo.get("caixa") or 0.0)
    acc = bancos
    gap_mes = None
    fluxo_serie = []
    for row in fluxo:
        acc += row["receber"] - row["pagar"]
        if acc < 0 and gap_mes is None:
            gap_mes = row["periodo"]
        fluxo_serie.append({"periodo": row["periodo"], "saldo_projetado": acc})
    hoje_dia = date.today().day
    meta_acum = sum(r["meta"] for r in diario if r["dia"] <= hoje_dia)
    real_acum = sum(r["realizado"] for r in diario)
    atingimento = (real_acum / meta_acum) if meta_acum else None

    return {
        "saldo_atual": bancos,
        "saldo_data": saldo["bancos_data"].isoformat() if saldo.get("bancos_data") else None,
        "gap_mes": gap_mes if bancos >= 0 else "agora",
        "receber_aberto": fin["receber_aberto"],
        "receber_vencido": fin["receber_vencido"],
        "receber_pendente_fatur": fin.get("receber_pendente_fatur", 0.0),
        "pagar_aberto": fin["pagar_aberto"],
        "pagar_vencido": fin["pagar_vencido"],
        "receber_prox30": fin["receber_prox30"],
        "pagar_prox30": fin["pagar_prox30"],
        "faturamento_mes": fin["faturamento_mes"],
        "faturamento_medio_6m": runrate,
        "receita_mes_cte": mes["receita_mes"],
        "frete_contratado_mes": mes["frete_contratado_mes"],
        "combustivel_proprio_mes": mes["combustivel_proprio_mes"],
        "manutencao_mes": mes["manutencao_mes"],
        "os_abertas": mes["os_abertas"],
        "oc_atrasadas": oc["oc_atrasadas"],
        "oc_atraso_valor": oc["oc_atraso_valor"],
        "oc_aprovacao": oc["oc_aprovacao"],
        "diario": diario,
        "atingimento_mes": atingimento,
        "ponto_equilibrio": _ponto_equilibrio(be_rows),
        "meta_acumulada": meta_acum,
        "realizado_acumulado": real_acum,
        "fluxo_serie": fluxo_serie[:7],
        "modal_km": modal_km,
        "receita_12m": receita_12m,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA + CTA Plus · resumo de todas as áreas · leitura",
    }


# ============================================================================
# Combustível — sulista.ctaplus_abastecimentos (gestora CTA Plus, vivo).
# A maior parte do diesel é de veículos de agregados/terceiros (repassado no
# acerto): o painel separa por modalidade via join com veiculo.tipofrota.
# km/l usa apenas distancias sas (1..3000 km) e EXCLUI ARLA.
# PII: motorista_nome/cpf existem na fonte e NAO saem da API.
# ============================================================================
_CTA_BASE = """
FROM sulista.ctaplus_abastecimentos a
LEFT JOIN veiculo v ON v.placa = a.veiculo_placa
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE a.data_inicio_abastecimento >= %(dt_de)s::date
  AND a.data_inicio_abastecimento <= %(dt_ate)s::date
  AND (%(modalidade)s::text IS NULL
       OR (%(modalidade)s = 'proprio' AND coalesce(v.utilizacaoveiculo,'') NOT IN ('AGR','TER') AND v.placa IS NOT NULL)
       OR (%(modalidade)s = 'terceiros' AND (v.utilizacaoveiculo IN ('AGR','TER') OR v.placa IS NULL)))
  AND (%(placa)s::text IS NULL OR a.veiculo_placa ILIKE '%%'||%(placa)s||'%%')
  AND (%(posto)s::text IS NULL
       OR (%(posto)s = 'comercial' AND a.posto_comercial)
       OR (%(posto)s = 'interno' AND NOT a.posto_comercial))
  AND (%(combustivel)s::text IS NULL OR a.combustivel_descricao = %(combustivel)s)
"""

_CTA_KM_SANO = ("(coalesce(a.distancia,0) > 0 AND a.distancia < 3000 "
                "AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%arla%%')")

COMB_KPI_SQL = f"""
SELECT count(*)::int AS abastecimentos,
       coalesce(sum(a.volume),0)::float8 AS litros,
       coalesce(sum(a.custo),0)::float8 AS custo,
       coalesce(sum(CASE WHEN coalesce(v.utilizacaoveiculo,'') NOT IN ('AGR','TER') AND v.placa IS NOT NULL THEN a.custo ELSE 0 END),0)::float8 AS custo_proprio,
       coalesce(sum(CASE WHEN v.utilizacaoveiculo IN ('AGR','TER') OR v.placa IS NULL THEN a.custo ELSE 0 END),0)::float8 AS custo_terceiros,
       coalesce(sum(CASE WHEN {_CTA_KM_SANO} THEN a.distancia ELSE 0 END),0)::float8 AS km_sano,
       coalesce(sum(CASE WHEN {_CTA_KM_SANO} THEN a.volume ELSE 0 END),0)::float8 AS litros_km_sano,
       count(DISTINCT a.veiculo_placa)::int AS veiculos
{_CTA_BASE}
"""

COMB_MENSAL_SQL = f"""
SELECT to_char(a.data_inicio_abastecimento,'YYYY-MM') AS mes,
       count(*)::int AS abastecimentos,
       sum(a.volume)::float8 AS litros,
       sum(a.custo)::float8 AS custo,
       sum(CASE WHEN coalesce(v.utilizacaoveiculo,'') NOT IN ('AGR','TER') AND v.placa IS NOT NULL THEN a.custo ELSE 0 END)::float8 AS custo_proprio,
       sum(CASE WHEN v.utilizacaoveiculo IN ('AGR','TER') OR v.placa IS NULL THEN a.custo ELSE 0 END)::float8 AS custo_terceiros,
       sum(CASE WHEN {_CTA_KM_SANO} THEN a.distancia ELSE 0 END)::float8 AS km_sano,
       sum(CASE WHEN {_CTA_KM_SANO} THEN a.volume ELSE 0 END)::float8 AS litros_km_sano
FROM sulista.ctaplus_abastecimentos a
LEFT JOIN veiculo v ON v.placa = a.veiculo_placa
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE a.data_inicio_abastecimento >= %(dt_de)s::date
  AND a.data_inicio_abastecimento <= %(dt_ate)s::date
  AND (%(modalidade)s::text IS NULL
       OR (%(modalidade)s = 'proprio' AND coalesce(v.utilizacaoveiculo,'') NOT IN ('AGR','TER') AND v.placa IS NOT NULL)
       OR (%(modalidade)s = 'terceiros' AND (v.utilizacaoveiculo IN ('AGR','TER') OR v.placa IS NULL)))
  AND (%(placa)s::text IS NULL OR a.veiculo_placa ILIKE '%%'||%(placa)s||'%%')
  AND (%(posto)s::text IS NULL
       OR (%(posto)s = 'comercial' AND a.posto_comercial)
       OR (%(posto)s = 'interno' AND NOT a.posto_comercial))
  AND (%(combustivel)s::text IS NULL OR a.combustivel_descricao = %(combustivel)s)
GROUP BY 1 ORDER BY 1
"""

# Consumo (litros) por dia e por semana ISO, mesmos filtros da serie mensal.
_COMB_PERIODO_FILTROS = """
FROM sulista.ctaplus_abastecimentos a
LEFT JOIN veiculo v ON v.placa = a.veiculo_placa
WHERE a.data_inicio_abastecimento >= %(dt_de)s::date
  AND a.data_inicio_abastecimento <= %(dt_ate)s::date
  AND (%(modalidade)s::text IS NULL
       OR (%(modalidade)s = 'proprio' AND coalesce(v.utilizacaoveiculo,'') NOT IN ('AGR','TER') AND v.placa IS NOT NULL)
       OR (%(modalidade)s = 'terceiros' AND (v.utilizacaoveiculo IN ('AGR','TER') OR v.placa IS NULL)))
  AND (%(placa)s::text IS NULL OR a.veiculo_placa ILIKE '%%'||%(placa)s||'%%')
  AND (%(posto)s::text IS NULL
       OR (%(posto)s = 'comercial' AND a.posto_comercial)
       OR (%(posto)s = 'interno' AND NOT a.posto_comercial))
  AND (%(combustivel)s::text IS NULL OR a.combustivel_descricao = %(combustivel)s)
"""

COMB_DIARIO_SQL = f"""
SELECT to_char(a.data_inicio_abastecimento,'YYYY-MM-DD') AS dia,
       sum(a.volume)::float8 AS litros,
       sum(a.custo)::float8 AS custo
{_COMB_PERIODO_FILTROS}
GROUP BY 1 ORDER BY 1
"""

COMB_SEMANAL_SQL = f"""
SELECT to_char(a.data_inicio_abastecimento,'IYYY-IW') AS semana,
       min(a.data_inicio_abastecimento)::date AS inicio,
       sum(a.volume)::float8 AS litros,
       sum(a.custo)::float8 AS custo
{_COMB_PERIODO_FILTROS}
GROUP BY 1 ORDER BY 1
"""

COMB_VEIC_SQL = f"""
SELECT a.veiculo_placa AS placa,
       min(coalesce(a.veiculo_categoria,'')) AS categoria,
       min(coalesce(u.descricao,'(sem)')) AS utilizacao,
       count(*)::int AS abastecimentos,
       sum(a.volume)::float8 AS litros,
       sum(a.custo)::float8 AS custo,
       sum(CASE WHEN {_CTA_KM_SANO} THEN a.distancia ELSE 0 END)::float8 AS km,
       sum(CASE WHEN {_CTA_KM_SANO} THEN a.volume ELSE 0 END)::float8 AS litros_km
{_CTA_BASE}
GROUP BY a.veiculo_placa ORDER BY sum(a.custo) DESC LIMIT 30
"""

COMB_DET_SQL = f"""
SELECT a.veiculo_placa AS placa_t,
       to_char(a.data_inicio_abastecimento,'YYYY-MM-DD') AS data,
       coalesce(a.posto_nome,'?') AS posto,
       a.posto_comercial,
       coalesce(a.combustivel_descricao,'?') AS combustivel,
       a.volume::float8 AS litros,
       a.custo::float8 AS custo,
       a.custo_unitario::float8 AS rs_litro,
       a.odometro,
       (CASE WHEN {_CTA_KM_SANO} THEN a.distancia END)::float8 AS distancia,
       (CASE WHEN {_CTA_KM_SANO} AND a.volume > 0 THEN a.distancia / a.volume END)::float8 AS km_l
{_CTA_BASE} AND a.veiculo_placa = ANY(%(placas)s)
ORDER BY a.veiculo_placa, a.data_inicio_abastecimento DESC
"""

COMB_POSTO_SQL = f"""
SELECT coalesce(a.posto_nome,'?') AS posto, bool_or(a.posto_comercial) AS comercial,
       min(coalesce(a.posto_uf,'')) AS uf,
       count(*)::int AS abastecimentos,
       sum(a.volume)::float8 AS litros,
       sum(a.custo)::float8 AS custo
{_CTA_BASE}
GROUP BY coalesce(a.posto_nome,'?') ORDER BY sum(a.custo) DESC LIMIT 12
"""

COMB_TIPO_SQL = f"""
SELECT coalesce(a.combustivel_descricao,'(sem)') AS combustivel,
       count(*)::int AS abastecimentos,
       sum(a.volume)::float8 AS litros,
       sum(a.custo)::float8 AS custo
{_CTA_BASE}
GROUP BY 1 ORDER BY 4 DESC
"""


@cached(ttl=90)
def get_combustivel(dt_de: str, dt_ate: str, modalidade: str | None = None,
                    placa: str | None = None, posto: str | None = None,
                    combustivel: str | None = None) -> dict:
    params = {"dt_de": dt_de, "dt_ate": dt_ate, "modalidade": modalidade,
              "placa": placa, "posto": posto, "combustivel": combustivel}
    MAX_DET = 30
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(COMB_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(COMB_VEIC_SQL, params)
        veiculos = cur.fetchall()
        det: dict[str, list] = {}
        placas = [r["placa"] for r in veiculos if r["placa"]]
        if placas:
            cur.execute(COMB_DET_SQL, {**params, "placas": placas})
            for r in cur.fetchall():
                det.setdefault(r.pop("placa_t"), []).append(r)
        cur.execute(COMB_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute(COMB_DIARIO_SQL, params)
        diario = cur.fetchall()
        cur.execute(COMB_SEMANAL_SQL, params)
        semanal = cur.fetchall()
        cur.execute(COMB_POSTO_SQL, params)
        postos = cur.fetchall()
        cur.execute(COMB_TIPO_SQL, params)
        combustiveis = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    kpis["rs_litro"] = (kpis["custo"] / kpis["litros"]) if kpis["litros"] else None
    kpis["km_l"] = (kpis["km_sano"] / kpis["litros_km_sano"]) if kpis["litros_km_sano"] else None
    for r in mensal:
        r["rs_litro"] = (r["custo"] / r["litros"]) if r["litros"] else None
        r["km_l"] = (r["km_sano"] / r["litros_km_sano"]) if r["litros_km_sano"] else None
    for vv in veiculos:
        vv["rs_litro"] = (vv["custo"] / vv["litros"]) if vv["litros"] else None
        vv["km_l"] = (vv["km"] / vv["litros_km"]) if vv["litros_km"] else None
        ds = det.get(vv["placa"], [])
        vv["ocultos"] = max(0, len(ds) - MAX_DET)
        vv["abastecimentos_lista"] = ds[:MAX_DET]
    for p in postos:
        p["rs_litro"] = (p["custo"] / p["litros"]) if p["litros"] else None
    for c in combustiveis:
        c["rs_litro"] = (c["custo"] / c["litros"]) if c["litros"] else None

    return {
        "kpis": kpis, "veiculos": veiculos, "postos": postos, "mensal": mensal,
        "diario": diario, "semanal": semanal,
        "combustiveis": combustiveis,
        "dt_de": dt_de, "dt_ate": dt_ate,
        "modalidade": modalidade, "placa": placa, "posto": posto, "combustivel": combustivel,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "CTA Plus (sulista.ctaplus_abastecimentos) × frota AVA · leitura",
    }


# ============================================================================
# Manutenção — ordemservico (OSs de manutenção, com peças + mão de obra).
# `tipo` (1/2) exibido bruto (significado não confirmado pelo negócio).
# ============================================================================
_OS_BASE = """
FROM ordemservico o
LEFT JOIN veiculo v ON v.placa = o.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE o.dtemissao >= %(dt_de)s::date AND o.dtemissao < %(dt_ate)s::date + 1
  AND (o.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (%(placa)s::text IS NULL OR o.veiculo ILIKE '%%'||%(placa)s||'%%')
"""

MAN_KPI_SQL = f"""
SELECT count(*)::int AS ordens,
       coalesce(sum(o.valortotal),0)::float8 AS custo,
       coalesce(sum(o.valortotalpecas),0)::float8 AS pecas,
       coalesce(sum(o.valortotalmaoobra),0)::float8 AS maoobra,
       sum(CASE WHEN o.dtfechamento IS NULL THEN 1 ELSE 0 END)::int AS abertas,
       coalesce(sum(CASE WHEN o.dtfechamento IS NULL THEN o.valortotal ELSE 0 END),0)::float8 AS abertas_valor,
       count(DISTINCT o.veiculo)::int AS veiculos
{_OS_BASE}
"""

MAN_MENSAL_SQL = """
SELECT to_char(o.dtemissao,'YYYY-MM') AS mes, count(*)::int AS ordens,
       sum(coalesce(o.valortotal,0))::float8 AS custo,
       sum(coalesce(o.valortotalpecas,0))::float8 AS pecas,
       sum(coalesce(o.valortotalmaoobra,0))::float8 AS maoobra
FROM ordemservico o
WHERE o.dtemissao >= %(dt_de)s::date AND o.dtemissao < %(dt_ate)s::date + 1
  AND (o.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (%(placa)s::text IS NULL OR o.veiculo ILIKE '%%'||%(placa)s||'%%')
GROUP BY 1 ORDER BY 1
"""

MAN_VEIC_SQL = f"""
SELECT o.veiculo AS placa, min(coalesce(u.descricao,'(sem)')) AS utilizacao,
       count(*)::int AS ordens,
       sum(coalesce(o.valortotal,0))::float8 AS custo,
       sum(coalesce(o.valortotalpecas,0))::float8 AS pecas,
       sum(coalesce(o.valortotalmaoobra,0))::float8 AS maoobra,
       sum(CASE WHEN o.dtfechamento IS NULL THEN 1 ELSE 0 END)::int AS abertas
{_OS_BASE}
GROUP BY o.veiculo ORDER BY sum(coalesce(o.valortotal,0)) DESC LIMIT 30
"""

MAN_DET_SQL = f"""
SELECT o.veiculo AS placa_t, o.numero, o.filial, o.tipo,
       to_char(o.dtemissao,'YYYY-MM-DD') AS emissao,
       to_char(o.dtfechamento,'YYYY-MM-DD') AS fechamento,
       coalesce(o.valortotalpecas,0)::float8 AS pecas,
       coalesce(o.valortotalmaoobra,0)::float8 AS maoobra,
       coalesce(o.valortotal,0)::float8 AS custo
{_OS_BASE} AND o.veiculo = ANY(%(placas)s)
ORDER BY o.veiculo, o.dtemissao DESC
"""


@cached(ttl=90)
def get_manutencao(filial: int | None, dt_de: str, dt_ate: str,
                   placa: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate, "placa": placa}
    MAX_DET = 30
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(MAN_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(MAN_VEIC_SQL, params)
        veiculos = cur.fetchall()
        det: dict[str, list] = {}
        placas = [r["placa"] for r in veiculos if r["placa"]]
        if placas:
            cur.execute(MAN_DET_SQL, {**params, "placas": placas})
            for r in cur.fetchall():
                det.setdefault(r.pop("placa_t"), []).append(r)
        cur.execute(MAN_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    for vv in veiculos:
        ds = det.get(vv["placa"], [])
        vv["ocultas"] = max(0, len(ds) - MAX_DET)
        vv["ordens_lista"] = ds[:MAX_DET]

    return {
        "kpis": kpis, "veiculos": veiculos, "mensal": mensal,
        "dt_de": dt_de, "dt_ate": dt_ate, "filial": filial, "placa": placa,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · ordemservico · leitura",
    }


# ============================================================================
# Análise de KM — vazio × carregado por modalidade, cliente e rota.
# Fonte canônica: programacaoembarque (semaforo=1, não cancelada).
# Oportunidade de venda = rota com km vazio recorrente (vender frete de volta).
# ============================================================================
_KM_BASE = """
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
"""

KM_KPI_SQL = f"""
SELECT count(*)::int AS viagens,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_carregado,
       sum(CASE WHEN p.tipo = 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_vazio,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.valorfrete,0) ELSE 0 END)::float8 AS receita
{_KM_BASE}
"""

KM_MENSAL_SQL = f"""
SELECT to_char(p.dtemissao,'YYYY-MM') AS mes,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_carregado,
       sum(CASE WHEN p.tipo = 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_vazio,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.valorfrete,0) ELSE 0 END)::float8 AS receita
{_KM_BASE}
GROUP BY 1 ORDER BY 1
"""

KM_MODAL_SQL = f"""
SELECT coalesce(u.descricao,'(sem)') AS utilizacao, count(*)::int AS viagens,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_carregado,
       sum(CASE WHEN p.tipo = 3 THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_vazio,
       sum(CASE WHEN p.tipo <> 3 THEN coalesce(p.valorfrete,0) ELSE 0 END)::float8 AS receita
{_KM_BASE}
GROUP BY 1 ORDER BY 3 DESC
"""

KM_CLI_SQL = f"""
SELECT coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''),
       nullif(trim(cp.razaosocial),''), '(sem cliente)') AS cliente,
       count(*)::int AS viagens,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km_carregado,
       sum(coalesce(p.valorfrete,0))::float8 AS receita
FROM programacaoembarque p
JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND p.dtemissao >= %(dt_de)s::date AND p.dtemissao < %(dt_ate)s::date + 1
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
GROUP BY 1 ORDER BY 3 DESC LIMIT 15
"""

KM_ROTA_VAZIO_SQL = f"""
SELECT coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       count(*)::int AS viagens,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km_vazio
{_KM_BASE} AND p.tipo = 3
GROUP BY 1, 2 ORDER BY 4 DESC LIMIT 15
"""


@cached(ttl=90)
def get_analise_km(filial: int | None, dt_de: str, dt_ate: str,
                   modalidade: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate, "modalidade": modalidade}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(KM_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(KM_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute(KM_MODAL_SQL, params)
        modalidades = cur.fetchall()
        cur.execute(KM_CLI_SQL, params)
        clientes = cur.fetchall()
        cur.execute(KM_ROTA_VAZIO_SQL, params)
        rotas_vazio = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    def enrich(d):
        total = d["km_carregado"] + d["km_vazio"]
        d["km_total"] = total
        d["retorno_vazio"] = (d["km_vazio"] / total) if total else None
        d["rkm"] = (d["receita"] / d["km_carregado"]) if d["km_carregado"] else None
        return d

    enrich(kpis)
    for m in mensal:
        enrich(m)
    for md in modalidades:
        enrich(md)
    km_cli_total = sum(c["km_carregado"] for c in clientes) or None
    for c in clientes:
        c["rkm"] = (c["receita"] / c["km_carregado"]) if c["km_carregado"] else None
        c["share_km"] = (c["km_carregado"] / kpis["km_carregado"]) if kpis["km_carregado"] else None

    return {
        "kpis": kpis, "mensal": mensal, "modalidades": modalidades,
        "clientes": clientes, "rotas_vazio": rotas_vazio,
        "dt_de": dt_de, "dt_ate": dt_ate, "filial": filial, "modalidade": modalidade,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · programação de embarque · leitura",
    }


# ============================================================================
# Torre de Controle — posição ao vivo (veiculo_ultimaposicaomacro →
# veiculo_posicao.latituderastreadora, atualizada em minutos) + viagens em
# trânsito (programação com saída e sem chegada, últimos 15 dias).
# ============================================================================
TORRE_POS_SQL = """
SELECT um.veiculo AS placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       coalesce(nullif(trim(v.numerofrota),''), um.veiculo) AS frota,
       vp.latituderastreadora::float8 AS lat,
       vp.longituderastreadora::float8 AS lng,
       to_char(vp.dt,'YYYY-MM-DD HH24:MI') AS posicao_em,
       greatest(vp.velocidade,0)::int AS velocidade,
       (vp.dt >= current_timestamp - interval '24 hours') AS recente
FROM rastreamento.veiculo_ultimaposicaomacro um
JOIN veiculo_posicao vp ON vp.veiculo = um.veiculo
  AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
LEFT JOIN veiculo v ON v.placa = um.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE vp.latituderastreadora IS NOT NULL AND vp.longituderastreadora IS NOT NULL
"""

TORRE_TRANSITO_SQL = """
SELECT p.numero, p.filial, p.veiculo AS placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       coalesce(nullif(trim(m.nomefantasia),''), nullif(trim(m.razaosocial),'')) AS motorista,
       coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''), '(sem cliente)') AS cliente,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       to_char(p.dtsaida,'YYYY-MM-DD HH24:MI') AS saida,
       to_char(co.dtprevisaochegadaviagem,'YYYY-MM-DD HH24:MI') AS previsao_chegada,
       (co.dtprevisaochegadaviagem IS NOT NULL AND co.dtprevisaochegadaviagem < current_timestamp) AS atrasada,
       (p.tipo = 3) AS vazio,
       coalesce(p.kmfretecompra,0)::float8 AS km,
       coalesce(p.valorfrete,0)::float8 AS valorfrete
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
LEFT JOIN cadastro m ON m.codigo = p.motorista
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND p.dtsaida IS NOT NULL AND p.dtchegada IS NULL
  AND p.dtsaida >= current_date - 15
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
ORDER BY atrasada DESC, co.dtprevisaochegadaviagem NULLS LAST
"""


@cached(ttl=25)
def get_torre(filial: int | None = None) -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(TORRE_POS_SQL)
        posicoes = cur.fetchall()
        cur.execute(TORRE_TRANSITO_SQL, {"filial": filial})
        transito = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    pos_por_placa = {p["placa"]: p for p in posicoes}
    em_viagem = set()
    for t in transito:
        em_viagem.add(t["placa"])
        p = pos_por_placa.get(t["placa"])
        t["lat"] = p["lat"] if p else None
        t["lng"] = p["lng"] if p else None
        t["posicao_em"] = p["posicao_em"] if p else None
        t["velocidade"] = p["velocidade"] if p else None
    for p in posicoes:
        p["em_viagem"] = p["placa"] in em_viagem

    hoje = str(date.today())
    kpis = {
        "em_transito": len(transito),
        "atrasadas": sum(1 for t in transito if t["atrasada"]),
        "com_posicao_24h": sum(1 for p in posicoes if p["recente"]),
        "veiculos_monitorados": len(posicoes),
        "saidas_hoje": sum(1 for t in transito if (t["saida"] or "").startswith(hoje)),
        "chegadas_previstas_hoje": sum(
            1 for t in transito if (t["previsao_chegada"] or "").startswith(hoje)),
    }
    return {
        "kpis": kpis, "posicoes": posicoes, "transito": transito,
        "filial": filial,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · veiculo_posicao (rastreamento ao vivo) × programação de embarque",
    }


# ============================================================================
# Veículos — composição da frota: utilização, tipo, característica, marca,
# modelo e ano. situacao: ativos (ativoinativo=1) ou todos.
# ============================================================================
_VEIC_BASE = """
FROM veiculo v
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
LEFT JOIN tipoveiculo tv ON tv.codigo = v.tipoveiculo
LEFT JOIN caracteristicaveiculo cv ON cv.codigo = v.caracteristicaveiculo
LEFT JOIN marcaveiculo mv ON mv.codigo = v.marcaveiculo
WHERE (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
  AND (%(situacao)s = 'todos' OR v.ativoinativo = 1)
"""

VEIC_KPI_SQL = f"""
SELECT count(*)::int AS total,
       sum(CASE WHEN v.ativoinativo = 1 THEN 1 ELSE 0 END)::int AS ativos,
       sum(CASE WHEN v.ativoinativo <> 1 THEN 1 ELSE 0 END)::int AS inativos,
       sum(CASE WHEN v.utilizacaoveiculo IN ('TRA','LOC') AND v.ativoinativo = 1 THEN 1 ELSE 0 END)::int AS proprios_ativos,
       round(avg(CASE WHEN v.ativoinativo = 1 AND v.anofabricacao BETWEEN 1980 AND extract(year from current_date)
                 THEN extract(year from current_date) - v.anofabricacao END)::numeric, 1)::float8 AS idade_media
FROM veiculo v
WHERE (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
"""

VEIC_UTIL_SQL = """
SELECT coalesce(u.descricao,'(sem)') AS utilizacao,
       sum(CASE WHEN v.ativoinativo = 1 THEN 1 ELSE 0 END)::int AS ativos,
       sum(CASE WHEN v.ativoinativo <> 1 THEN 1 ELSE 0 END)::int AS inativos
FROM veiculo v
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE (v.utilizacaoveiculo = %(modalidade)s OR %(modalidade)s::text IS NULL)
GROUP BY 1 ORDER BY 2 DESC
"""

VEIC_TIPO_SQL = _VEIC_BASE.replace("FROM veiculo v", "SELECT coalesce(tv.descricao,'(sem tipo)') AS tipo, count(*)::int AS qtd FROM veiculo v", 1) + """
GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""

VEIC_CARAC_SQL = _VEIC_BASE.replace("FROM veiculo v", "SELECT coalesce(cv.descricao,'(sem)') AS caracteristica, count(*)::int AS qtd FROM veiculo v", 1) + """
GROUP BY 1 ORDER BY 2 DESC LIMIT 15
"""

VEIC_MARCA_SQL = _VEIC_BASE.replace("FROM veiculo v", "SELECT coalesce(mv.descricao,'(sem marca)') AS marca, count(*)::int AS qtd, round(avg(CASE WHEN v.anofabricacao BETWEEN 1980 AND extract(year from current_date) THEN v.anofabricacao END)::numeric,0)::int AS ano_medio FROM veiculo v", 1) + """
GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""

VEIC_MODELO_SQL = _VEIC_BASE.replace("FROM veiculo v", "SELECT coalesce(mv.descricao,'(sem marca)') AS marca_t, coalesce(nullif(trim(v.modeloveiculo),''),'(sem modelo)') AS modelo, count(*)::int AS qtd, min(CASE WHEN v.anofabricacao BETWEEN 1980 AND extract(year from current_date) THEN v.anofabricacao END) AS ano_min, max(CASE WHEN v.anofabricacao BETWEEN 1980 AND extract(year from current_date) THEN v.anofabricacao END) AS ano_max FROM veiculo v", 1) + """
GROUP BY 1, 2 ORDER BY 1, 3 DESC
"""


@cached(ttl=300)
def get_veiculos(modalidade: str | None = None, situacao: str = "ativos") -> dict:
    params = {"modalidade": modalidade, "situacao": situacao}
    MAX_MODELOS = 25
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(VEIC_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(VEIC_UTIL_SQL, params)
        utilizacoes = cur.fetchall()
        cur.execute(VEIC_TIPO_SQL, params)
        tipos = cur.fetchall()
        cur.execute(VEIC_CARAC_SQL, params)
        caracteristicas = cur.fetchall()
        cur.execute(VEIC_MARCA_SQL, params)
        marcas = cur.fetchall()
        cur.execute(VEIC_MODELO_SQL, params)
        modelos_rows = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    modelos: dict[str, list] = {}
    for r in modelos_rows:
        modelos.setdefault(r.pop("marca_t"), []).append(r)
    for m in marcas:
        ms = modelos.get(m["marca"], [])
        m["ocultos"] = max(0, len(ms) - MAX_MODELOS)
        m["modelos"] = ms[:MAX_MODELOS]

    return {
        "kpis": kpis, "utilizacoes": utilizacoes, "tipos": tipos,
        "caracteristicas": caracteristicas, "marcas": marcas,
        "modalidade": modalidade, "situacao": situacao,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · cadastro de veículos · leitura",
    }


# ============================================================================
# Torre de Segurança — violações de cerca (rastreamentoevento, vivo),
# velocidade atual da frota (veiculo_posicao), sinistros (boletimocorrencia).
# A rastreadora atual só emite macros operacionais; eventos de risco vêm
# das cercas + velocidade + BOs.
# ============================================================================
SEG_KPI_SQL = """
SELECT
  (SELECT count(*)::int FROM rastreamentoevento
     WHERE tipoevento = 1 AND dtencerramento IS NULL
       AND dtinc >= current_date - 7)                                        AS cercas_abertas_7d,
  (SELECT count(*)::int FROM rastreamentoevento
     WHERE tipoevento = 1 AND dtinc >= current_date - 1)                     AS cercas_24h,
  (SELECT count(*)::int FROM (
     SELECT vp.velocidade
     FROM rastreamento.veiculo_ultimaposicaomacro um
     JOIN veiculo_posicao vp ON vp.veiculo = um.veiculo
       AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
     WHERE vp.dt >= current_timestamp - interval '2 hours'
       AND vp.velocidade > 90) t)                                            AS excesso_agora,
  (SELECT count(*)::int FROM boletimocorrencia
     WHERE dtocorrencia >= current_date - 365 AND dtcancelamento IS NULL)    AS bos_12m,
  (SELECT coalesce(sum(valorsinistro),0)::float8 FROM boletimocorrencia
     WHERE dtocorrencia >= current_date - 365 AND dtcancelamento IS NULL)    AS valor_sinistro_12m,
  (SELECT coalesce(sum(valorrecebidoseguro),0)::float8 FROM boletimocorrencia
     WHERE dtocorrencia >= current_date - 365 AND dtcancelamento IS NULL)    AS recebido_seguro_12m
"""

SEG_CERCAS_SQL = """
SELECT re.veiculo AS placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       to_char(re.dtinc,'YYYY-MM-DD HH24:MI') AS inicio,
       round(extract(epoch from (current_timestamp - re.dtinc))/3600.0)::int AS horas_aberta
FROM rastreamentoevento re
LEFT JOIN veiculo v ON v.placa = re.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE re.tipoevento = 1 AND re.dtencerramento IS NULL
  AND re.dtinc >= current_date - 7
ORDER BY re.dtinc DESC LIMIT 40
"""

SEG_VELOCIDADE_SQL = """
SELECT um.veiculo AS placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       vp.velocidade::int AS velocidade,
       vp.latituderastreadora::float8 AS lat,
       vp.longituderastreadora::float8 AS lng,
       to_char(vp.dt,'HH24:MI') AS posicao_em
FROM rastreamento.veiculo_ultimaposicaomacro um
JOIN veiculo_posicao vp ON vp.veiculo = um.veiculo
  AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
LEFT JOIN veiculo v ON v.placa = um.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE vp.dt >= current_timestamp - interval '2 hours'
  AND vp.velocidade > 80
  AND vp.latituderastreadora IS NOT NULL
ORDER BY vp.velocidade DESC LIMIT 40
"""

SEG_BO_MENSAL_SQL = """
SELECT to_char(dtocorrencia,'YYYY-MM') AS mes, count(*)::int AS bos,
       sum(coalesce(valorsinistro,0))::float8 AS valor_sinistro
FROM boletimocorrencia
WHERE dtocorrencia >= date_trunc('month', current_date) - interval '11 months'
  AND dtcancelamento IS NULL
GROUP BY 1 ORDER BY 1
"""

SEG_BO_RECENTES_SQL = """
SELECT b.numero, b.filial,
       to_char(b.dtocorrencia,'YYYY-MM-DD') AS ocorrencia,
       coalesce(nullif(trim(b.descricao),''),'(sem descrição)') AS descricao,
       b.veiculo AS placa,
       coalesce(b.valorsinistro,0)::float8 AS valor_sinistro,
       coalesce(b.valorrecebidoseguro,0)::float8 AS recebido_seguro,
       (b.dtencerramento IS NULL) AS aberto
FROM boletimocorrencia b
WHERE b.dtcancelamento IS NULL
ORDER BY b.dtocorrencia DESC LIMIT 25
"""


@cached(ttl=45)
def get_seguranca() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(SEG_KPI_SQL)
        kpis = cur.fetchone()
        cur.execute(SEG_CERCAS_SQL)
        cercas = cur.fetchall()
        cur.execute(SEG_VELOCIDADE_SQL)
        velocidade = cur.fetchall()
        cur.execute(SEG_BO_MENSAL_SQL)
        bo_mensal = cur.fetchall()
        cur.execute(SEG_BO_RECENTES_SQL)
        bo_recentes = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()
    return {
        "kpis": kpis, "cercas": cercas, "velocidade": velocidade,
        "bo_mensal": bo_mensal, "bo_recentes": bo_recentes,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · cercas + posição ao vivo + boletins de ocorrência",
    }


# ============================================================================
# Consulta de Veículo — ficha por placa: cadastro, viagem atual, posição ao
# vivo, KPIs 30d (faturamento/km/vazio), top clientes, últimas viagens,
# combustível, manutenção e multas. Reusa as fontes já validadas.
# ============================================================================
VEICF_CAD_SQL = """
SELECT v.placa, nullif(trim(v.numerofrota),'') AS frota,
       coalesce(mv.descricao,'') AS marca, nullif(trim(v.modeloveiculo),'') AS modelo,
       coalesce(tv.descricao,'') AS tipo, coalesce(cv.descricao,'') AS caracteristica,
       coalesce(u.descricao,'') AS modalidade, v.utilizacaoveiculo AS modalidade_cod,
       (CASE WHEN v.anofabricacao BETWEEN 1980 AND extract(year from current_date)
             THEN v.anofabricacao END)::int AS ano,
       (v.ativoinativo = 1) AS ativo
FROM veiculo v
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
LEFT JOIN tipoveiculo tv ON tv.codigo = v.tipoveiculo
LEFT JOIN caracteristicaveiculo cv ON cv.codigo = v.caracteristicaveiculo
LEFT JOIN marcaveiculo mv ON mv.codigo = v.marcaveiculo
WHERE v.placa = %(placa)s
"""

VEICF_POS_SQL = """
SELECT vp.latituderastreadora::float8 AS lat, vp.longituderastreadora::float8 AS lng,
       to_char(vp.dt,'YYYY-MM-DD HH24:MI') AS posicao_em,
       greatest(vp.velocidade,0)::int AS velocidade,
       (vp.dt >= current_timestamp - interval '24 hours') AS recente
FROM rastreamento.veiculo_ultimaposicaomacro um
JOIN veiculo_posicao vp ON vp.veiculo = um.veiculo
  AND vp.sequenciaposicaoveiculo = um.sequenciaposicaoveiculo
WHERE um.veiculo = %(placa)s
  AND vp.latituderastreadora IS NOT NULL AND vp.longituderastreadora IS NOT NULL
"""

VEICF_VIAGEM_SQL = """
SELECT coalesce(nullif(trim(m.nomefantasia),''), nullif(trim(m.razaosocial),'')) AS motorista,
       coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''), '(sem cliente)') AS cliente,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       to_char(p.dtsaida,'YYYY-MM-DD HH24:MI') AS saida,
       to_char(co.dtprevisaochegadaviagem,'YYYY-MM-DD HH24:MI') AS previsao_chegada,
       (co.dtprevisaochegadaviagem IS NOT NULL AND co.dtprevisaochegadaviagem < current_timestamp) AS atrasada,
       (p.tipo = 3) AS vazio,
       coalesce(p.kmfretecompra,0)::float8 AS km, coalesce(p.valorfrete,0)::float8 AS valorfrete
FROM programacaoembarque p
LEFT JOIN cadastro m ON m.codigo = p.motorista
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.veiculo = %(placa)s AND p.dtcancelamento IS NULL AND p.semaforo = 1
  AND p.dtsaida IS NOT NULL AND p.dtchegada IS NULL
ORDER BY p.dtsaida DESC LIMIT 1
"""

VEICF_VIAGENS_SQL = """
SELECT DISTINCT ON (p.grupo,p.empresa,p.filial,p.diferenciadornumero,p.numero)
       to_char(coalesce(p.dtchegada,p.dtsaida,p.dtemissao),'YYYY-MM-DD') AS data,
       p.tipo, coalesce(p.kmfretecompra,0)::float8 AS km,
       coalesce(p.valorfrete,0)::float8 AS valorfrete,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       coalesce(nullif(trim(ag.descricao),''), nullif(trim(cp.nomefantasia),''),
                nullif(trim(cp.razaosocial),'')) AS cliente
FROM programacaoembarque p
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.veiculo = %(placa)s AND p.dtcancelamento IS NULL AND p.semaforo = 1
  AND coalesce(p.dtchegada,p.dtsaida,p.dtemissao) >= %(de)s::date
  AND coalesce(p.dtchegada,p.dtsaida,p.dtemissao) < %(ate)s::date
ORDER BY p.grupo,p.empresa,p.filial,p.diferenciadornumero,p.numero,
         coalesce(p.dtchegada,p.dtsaida,p.dtemissao) DESC
"""

VEICF_COMB_SQL = """
SELECT count(*)::int AS abastecimentos,
       coalesce(sum(a.volume),0)::float8 AS litros, coalesce(sum(a.custo),0)::float8 AS custo,
       coalesce(sum(CASE WHEN a.distancia BETWEEN 1 AND 3000 AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%ARLA%%' THEN a.distancia ELSE 0 END),0)::float8 AS km_sano,
       coalesce(sum(CASE WHEN a.distancia BETWEEN 1 AND 3000 AND coalesce(a.combustivel_descricao,'') NOT ILIKE '%%ARLA%%' THEN a.volume ELSE 0 END),0)::float8 AS litros_sano
FROM sulista.ctaplus_abastecimentos a
WHERE a.veiculo_placa = %(placa)s
  AND a.data_inicio_abastecimento >= %(de)s::date AND a.data_inicio_abastecimento < %(ate)s::date
"""

VEICF_MAN_SQL = """
SELECT count(*)::int AS ordens_30d, coalesce(sum(o.valortotal),0)::float8 AS custo_30d
FROM ordemservico o
WHERE o.veiculo = %(placa)s AND o.dtemissao >= %(de)s::date AND o.dtemissao < %(ate)s::date
"""

VEICF_MAN_ABERTAS_SQL = """
SELECT count(*)::int AS abertas, coalesce(sum(o.valortotal),0)::float8 AS abertas_valor
FROM ordemservico o WHERE o.veiculo = %(placa)s AND o.dtfechamento IS NULL
"""

VEICF_MULTA_SQL = """
SELECT count(*)::int AS multas, coalesce(sum(r.valoratevencimento),0)::float8 AS valor,
       coalesce(sum(r.pontuacao),0)::int AS pontos,
       coalesce(sum(CASE WHEN r.dtliquidacao IS NULL AND r.dtbaixa IS NULL THEN r.valoratevencimento ELSE 0 END),0)::float8 AS pendente
FROM infracaotransito_registro r
WHERE r.veiculo = %(placa)s AND r.dtinfracao >= current_date - interval '12 months'
"""


@cached(ttl=60)
def get_veiculo_ficha(placa: str) -> dict:
    placa = (placa or "").strip().upper()
    if not placa:
        return {"encontrado": False, "placa": ""}
    from collections import defaultdict as _dd
    from datetime import timedelta as _td
    hoje = date.today()
    de = (hoje - _td(days=30)).isoformat()
    ate = (hoje + _td(days=1)).isoformat()
    par = {"placa": placa, "de": de, "ate": ate}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(VEICF_CAD_SQL, par); cad = cur.fetchone()
        cur.execute(VEICF_POS_SQL, par); pos = cur.fetchone()
        cur.execute(VEICF_VIAGEM_SQL, par); viagem = cur.fetchone()
        cur.execute(VEICF_VIAGENS_SQL, par); vgs = cur.fetchall()
        cur.execute(VEICF_COMB_SQL, par); comb = cur.fetchone()
        cur.execute(VEICF_MAN_SQL, par); man = cur.fetchone()
        cur.execute(VEICF_MAN_ABERTAS_SQL, {"placa": placa}); manab = cur.fetchone()
        cur.execute(VEICF_MULTA_SQL, {"placa": placa}); multa = cur.fetchone()
        cur.execute("SELECT current_timestamp AS ts"); meta = cur.fetchone()

    carregadas = [v for v in vgs if v["tipo"] != 3]
    fat = sum(v["valorfrete"] for v in carregadas)
    km_rodado = sum(v["km"] for v in vgs)
    km_carregado = sum(v["km"] for v in carregadas)
    km_vazio = sum(v["km"] for v in vgs if v["tipo"] == 3)

    cli: dict = _dd(lambda: {"receita": 0.0, "km": 0.0, "viagens": 0})
    for v in carregadas:
        c = v["cliente"] or "(sem cliente)"
        cli[c]["receita"] += v["valorfrete"]; cli[c]["km"] += v["km"]; cli[c]["viagens"] += 1
    top_clientes = sorted(({"cliente": k, **val} for k, val in cli.items()),
                          key=lambda x: -x["receita"])[:10]
    ultimas = sorted(vgs, key=lambda v: v["data"] or "", reverse=True)[:15]
    km_l = (comb["km_sano"] / comb["litros_sano"]) if comb and comb["litros_sano"] else None

    return {
        "encontrado": bool(cad or pos or vgs or viagem),
        "placa": placa, "cadastro": cad, "posicao": pos, "viagem_atual": viagem,
        "kpis": {"faturamento": fat, "km_rodado": km_rodado, "km_carregado": km_carregado,
                 "km_vazio": km_vazio, "pct_vazio": (100 * km_vazio / km_rodado) if km_rodado else 0.0,
                 "viagens": len(carregadas)},
        "top_clientes": top_clientes, "ultimas_viagens": ultimas,
        "combustivel": {"custo": (comb["custo"] if comb else 0.0),
                        "litros": (comb["litros"] if comb else 0.0),
                        "abastecimentos": (comb["abastecimentos"] if comb else 0), "km_l": km_l},
        "manutencao": {"custo_30d": (man["custo_30d"] if man else 0.0),
                       "ordens_30d": (man["ordens_30d"] if man else 0),
                       "abertas": (manab["abertas"] if manab else 0),
                       "abertas_valor": (manab["abertas_valor"] if manab else 0.0)},
        "multas": dict(multa) if multa else {},
        "periodo": {"de": de, "ate": hoje.isoformat()},
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA - programacaoembarque + rastreamento (posicao) + CTA Plus + ordemservico + infracaotransito",
    }


# ============================================================================
# Consulta de Cliente — ficha 360 por cliente (agrupamento): margem/km da DRE
# por Cliente (reuso, sem 3o numero divergente) + rotas, veiculos, ultimas
# viagens e recebiveis (aging). Cliente = agrupamentocliente (grupo economico).
# ============================================================================
CLIF_RESOLVE_SQL = """
SELECT codigo, descricao FROM agrupamentocliente
WHERE descricao ILIKE '%%'||%(q)s||'%%'
ORDER BY (upper(descricao)=upper(%(q)s)) DESC, length(descricao) LIMIT 1
"""

CLIF_CNPJS_SQL = "SELECT cnpjcpfcodigo FROM agrupamentocliente_cnpjcpfcodigo WHERE codigo = %(ag)s"

CLIF_VIAGENS_SQL = """
SELECT DISTINCT ON (p.grupo,p.empresa,p.filial,p.diferenciadornumero,p.numero)
       to_char(coalesce(p.dtchegada,p.dtsaida,p.dtemissao),'YYYY-MM-DD') AS data,
       coalesce(p.kmfretecompra,0)::float8 AS km, coalesce(p.valorfrete,0)::float8 AS valorfrete,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS origem,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       p.veiculo AS placa, coalesce(u.descricao,'(sem)') AS modalidade
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
WHERE av.codigo = %(ag)s AND p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND coalesce(p.dtchegada,p.dtsaida,p.dtemissao) >= %(de)s::date
  AND coalesce(p.dtchegada,p.dtsaida,p.dtemissao) < %(ate)s::date
ORDER BY p.grupo,p.empresa,p.filial,p.diferenciadornumero,p.numero,
         coalesce(p.dtchegada,p.dtsaida,p.dtemissao) DESC
"""

CLIF_RECEB_SQL = """
SELECT coalesce(sum(f.valorsaldoreceber),0)::float8 AS aberto,
       coalesce(sum(CASE WHEN f.dtvencimento < current_date THEN f.valorsaldoreceber ELSE 0 END),0)::float8 AS vencido,
       coalesce(sum(CASE WHEN f.dtvencimento >= current_date THEN f.valorsaldoreceber ELSE 0 END),0)::float8 AS a_vencer,
       coalesce(sum(CASE WHEN f.dtvencimento < current_date-90 THEN f.valorsaldoreceber ELSE 0 END),0)::float8 AS vencido_mais_90,
       count(*)::int AS titulos, min(f.dtvencimento)::text AS venc_mais_antigo
FROM fatura f
WHERE f.valorsaldoreceber > 0 AND f.dtcancelamento IS NULL AND f.cliente = ANY(%(cnpjs)s)
"""


@cached(ttl=120)
def get_cliente_ficha(cliente: str, comp_de: str, comp_ate: str) -> dict:
    from collections import defaultdict as _dd
    import unicodedata as _ud
    q = (cliente or "").strip()
    if not q:
        return {"encontrado": False, "busca": ""}
    de, ate = _comp_bounds(comp_de, comp_ate)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CLIF_RESOLVE_SQL, {"q": q})
        ag = cur.fetchone()
        if not ag:
            return {"encontrado": False, "busca": q}
        cur.execute(CLIF_CNPJS_SQL, {"ag": ag["codigo"]})
        cnpjs = [r["cnpjcpfcodigo"] for r in cur.fetchall()]
        cur.execute(CLIF_VIAGENS_SQL, {"ag": ag["codigo"], "de": de, "ate": ate})
        vgs = cur.fetchall()
        receb = {}
        if cnpjs:
            cur.execute(CLIF_RECEB_SQL, {"cnpjs": cnpjs})
            receb = cur.fetchone() or {}
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    nome = ag["descricao"]

    # margem/km/%vazio da DRE por Cliente (reuso, sem 3o numero)
    def _norm(s):
        return _ud.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode().strip()
    from . import dre_cliente as _dc  # lazy: evita import circular (dre_cliente importa queries)
    dre = _dc.get_dre_cliente(comp_de, comp_ate)
    cli_dre = next((c for c in dre.get("clientes", []) if _norm(c.get("cliente")) == _norm(nome)), None)
    linhas = (cli_dre or {}).get("linhas", {})
    ind = (cli_dre or {}).get("indicadores", {})

    # rotas, veiculos, ultimas — do foco (carregadas do periodo)
    rotas: dict = _dd(lambda: {"viagens": 0, "km": 0.0, "receita": 0.0})
    veic: dict = _dd(lambda: {"viagens": 0, "km": 0.0, "receita": 0.0, "modalidade": ""})
    for v in vgs:
        rk = f'{v["origem"]} → {v["destino"]}'
        rotas[rk]["viagens"] += 1; rotas[rk]["km"] += v["km"]; rotas[rk]["receita"] += v["valorfrete"]
        vp = v["placa"] or "(sem placa)"
        veic[vp]["viagens"] += 1; veic[vp]["km"] += v["km"]; veic[vp]["receita"] += v["valorfrete"]
        veic[vp]["modalidade"] = v["modalidade"]
    top_rotas = sorted(({"rota": k, **val} for k, val in rotas.items()), key=lambda x: -x["receita"])[:10]
    top_veic = sorted(({"placa": k, **val} for k, val in veic.items()), key=lambda x: -x["receita"])[:10]
    ultimas = sorted(vgs, key=lambda v: v["data"] or "", reverse=True)[:15]
    receita_bruta_viagens = sum(v["valorfrete"] for v in vgs)

    return {
        "encontrado": True, "cliente": nome, "codigo": ag["codigo"], "cnpjs": len(cnpjs),
        "kpis": {
            "receita_liquida": linhas.get("RECEITA LIQUIDA", 0.0),
            "receita_bruta": linhas.get("RECEITA BRUTA", receita_bruta_viagens),
            "mc": ind.get("mc", 0.0), "mc_pct": ind.get("mc_pct"),
            "margem_direta": linhas.get("MARGEM DIRETA DO CLIENTE", 0.0),
            "km_carregado": ind.get("km_carregado", 0.0), "km_vazio": ind.get("km_vazio", 0.0),
            "pct_vazio": ind.get("pct_km_vazio", 0.0), "viagens": ind.get("viagens", len(vgs)),
            "mix": ind.get("mix", {}),
        },
        "recebiveis": {
            "aberto": receb.get("aberto", 0.0), "vencido": receb.get("vencido", 0.0),
            "a_vencer": receb.get("a_vencer", 0.0), "vencido_mais_90": receb.get("vencido_mais_90", 0.0),
            "titulos": receb.get("titulos", 0), "venc_mais_antigo": receb.get("venc_mais_antigo"),
        },
        "top_rotas": top_rotas, "top_veiculos": top_veic, "ultimas_viagens": ultimas,
        "comp_de": comp_de, "comp_ate": comp_ate,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA - DRE por Cliente (margem) + programacaoembarque (rotas/veiculos) + fatura (recebiveis)",
    }


# ============================================================================
# Multas — infracaotransito_registro × infracaotransito (tipo/gravidade).
# Paga = dtliquidacao ou dtbaixa preenchida.
# ============================================================================
_MULTA_BASE = """
FROM infracaotransito_registro r
LEFT JOIN infracaotransito i ON i.codigo = r.infracaotransito
LEFT JOIN veiculo v ON v.placa = r.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE r.dtinfracao >= %(dt_de)s::date AND r.dtinfracao < %(dt_ate)s::date + 1
  AND (%(placa)s::text IS NULL OR r.veiculo ILIKE '%%'||%(placa)s||'%%')
"""

MULTA_KPI_SQL = f"""
SELECT count(*)::int AS multas,
       coalesce(sum(r.valoratevencimento),0)::float8 AS valor,
       coalesce(sum(r.pontuacao),0)::int AS pontos,
       sum(CASE WHEN r.dtliquidacao IS NOT NULL OR r.dtbaixa IS NOT NULL THEN 1 ELSE 0 END)::int AS pagas,
       coalesce(sum(CASE WHEN r.dtliquidacao IS NULL AND r.dtbaixa IS NULL
                    THEN r.valoratevencimento ELSE 0 END),0)::float8 AS pendente_valor,
       count(DISTINCT r.veiculo)::int AS veiculos
{_MULTA_BASE}
"""

MULTA_MENSAL_SQL = f"""
SELECT to_char(r.dtinfracao,'YYYY-MM') AS mes, count(*)::int AS multas,
       sum(coalesce(r.valoratevencimento,0))::float8 AS valor
{_MULTA_BASE}
GROUP BY 1 ORDER BY 1
"""

MULTA_TIPO_SQL = f"""
SELECT coalesce(nullif(trim(i.descricao),''),'(sem tipo)') AS infracao,
       coalesce(i.gravidade::text,'-') AS gravidade,
       count(*)::int AS multas,
       sum(coalesce(r.valoratevencimento,0))::float8 AS valor,
       sum(coalesce(r.pontuacao,0))::int AS pontos
{_MULTA_BASE}
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15
"""

MULTA_VEIC_SQL = f"""
SELECT r.veiculo AS placa, min(coalesce(u.descricao,'(sem)')) AS utilizacao,
       count(*)::int AS multas,
       sum(coalesce(r.valoratevencimento,0))::float8 AS valor,
       sum(coalesce(r.pontuacao,0))::int AS pontos
{_MULTA_BASE}
GROUP BY r.veiculo ORDER BY 3 DESC LIMIT 20
"""

MULTA_DET_SQL = f"""
SELECT r.veiculo AS placa_t,
       to_char(r.dtinfracao,'YYYY-MM-DD') AS data,
       coalesce(nullif(trim(i.descricao),''),'(sem tipo)') AS infracao,
       coalesce(nullif(trim(r.nomemotorista),''),'-') AS motorista,
       coalesce(nullif(trim(r.cidade),''),'?')||'/'||coalesce(r.uf,'?') AS local,
       coalesce(r.pontuacao,0)::int AS pontos,
       coalesce(r.valoratevencimento,0)::float8 AS valor,
       (r.dtliquidacao IS NOT NULL OR r.dtbaixa IS NOT NULL) AS paga
{_MULTA_BASE} AND r.veiculo = ANY(%(placas)s)
ORDER BY r.veiculo, r.dtinfracao DESC
"""

MULTA_MOTORISTA_SQL = f"""
SELECT coalesce(nullif(trim(r.nomemotorista),''),'(sem motorista)') AS motorista,
       count(*)::int AS multas,
       sum(coalesce(r.pontuacao,0))::int AS pontos,
       sum(coalesce(r.valoratevencimento,0))::float8 AS valor
{_MULTA_BASE}
GROUP BY 1 ORDER BY 3 DESC LIMIT 12
"""


@cached(ttl=90)
def get_multas(dt_de: str, dt_ate: str, placa: str | None = None) -> dict:
    params = {"dt_de": dt_de, "dt_ate": dt_ate, "placa": placa}
    MAX_DET = 25
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(MULTA_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(MULTA_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute(MULTA_TIPO_SQL, params)
        tipos = cur.fetchall()
        cur.execute(MULTA_VEIC_SQL, params)
        veiculos = cur.fetchall()
        det: dict[str, list] = {}
        placas = [r["placa"] for r in veiculos if r["placa"]]
        if placas:
            cur.execute(MULTA_DET_SQL, {**params, "placas": placas})
            for r in cur.fetchall():
                det.setdefault(r.pop("placa_t"), []).append(r)
        cur.execute(MULTA_MOTORISTA_SQL, params)
        motoristas = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    for vv in veiculos:
        ds = det.get(vv["placa"], [])
        vv["ocultas"] = max(0, len(ds) - MAX_DET)
        vv["multas_lista"] = ds[:MAX_DET]

    return {
        "kpis": kpis, "mensal": mensal, "tipos": tipos,
        "veiculos": veiculos, "motoristas": motoristas,
        "dt_de": dt_de, "dt_ate": dt_ate, "placa": placa,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · registro de infrações de trânsito · leitura",
    }


# ============================================================================
# Programação Inteligente — casar descargas com coletas para minimizar km
# vazio. Radar 72h (chegadas x saídas por cidade) + balanço estrutural de
# malha 90d + km vazio evitável (dias em que rodou vazio saindo de cidade
# que tinha carga saindo no mesmo dia).
# ============================================================================
_PROG_VIVO = """
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
"""

PROG_CHEGADAS_SQL = f"""
SELECT p.veiculo AS placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       coalesce(nullif(trim(p.cidadedestino),''),'?') AS cidade,
       coalesce(p.ufdestino,'?') AS uf,
       to_char(p.dtprevisaochegadaviagem,'YYYY-MM-DD HH24:MI') AS eta,
       coalesce(nullif(trim(p.cidadeorigem),''),'?')||'/'||coalesce(p.uforigem,'?') AS vindo_de
{_PROG_VIVO}
  AND p.dtsaida IS NOT NULL AND p.dtchegada IS NULL
  AND p.veiculo IS NOT NULL
  AND p.dtprevisaochegadaviagem BETWEEN current_timestamp - interval '12 hours'
                                    AND current_timestamp + interval '72 hours'
ORDER BY p.dtprevisaochegadaviagem
"""

PROG_SAIDAS_SQL = f"""
SELECT coalesce(nullif(trim(p.cidadeorigem),''),'?') AS cidade,
       coalesce(p.uforigem,'?') AS uf,
       coalesce(nullif(trim(p.cidadedestino),''),'?')||'/'||coalesce(p.ufdestino,'?') AS destino,
       to_char(p.dtprevisaosaidaviagem,'YYYY-MM-DD HH24:MI') AS saida,
       p.veiculo AS placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       coalesce(p.kmfretecompra,0)::float8 AS km
{_PROG_VIVO}
  AND p.dtsaida IS NULL
  AND p.dtprevisaosaidaviagem BETWEEN current_timestamp - interval '12 hours'
                                  AND current_timestamp + interval '96 hours'
ORDER BY p.dtprevisaosaidaviagem
"""

PROG_VAZIO_DIA_SQL = f"""
SELECT coalesce(nullif(trim(p.cidadeorigem),''),'?') AS cidade,
       coalesce(p.uforigem,'?') AS uf, p.dtsaida::date AS dia,
       count(*)::int AS viagens, sum(coalesce(p.kmfretecompra,0))::float8 AS km
{_PROG_VIVO}
  AND p.tipo = 3 AND p.dtsaida >= current_date - 90
GROUP BY 1, 2, 3
"""

PROG_CARGA_DIA_SQL = f"""
SELECT coalesce(nullif(trim(p.cidadeorigem),''),'?') AS cidade,
       coalesce(p.uforigem,'?') AS uf, p.dtsaida::date AS dia,
       count(*)::int AS cargas
{_PROG_VIVO}
  AND p.tipo <> 3 AND p.dtsaida >= current_date - 90
GROUP BY 1, 2, 3
"""

PROG_CHEGADA_90D_SQL = f"""
SELECT coalesce(nullif(trim(p.cidadedestino),''),'?') AS cidade,
       coalesce(p.ufdestino,'?') AS uf, count(*)::int AS chegadas
{_PROG_VIVO}
  AND p.tipo <> 3 AND p.dtsaida >= current_date - 90
GROUP BY 1, 2
"""

PROG_DIESEL_SQL = """
SELECT coalesce(sum(a.custo),0)::float8 AS custo
FROM sulista.ctaplus_abastecimentos a
JOIN veiculo v ON v.placa = a.veiculo_placa
WHERE a.data_inicio_abastecimento >= current_date - 90
  AND coalesce(v.utilizacaoveiculo,'') IN ('TRA','LOC')
  AND upper(coalesce(a.combustivel_descricao,'')) NOT LIKE '%%ARLA%%'
"""

PROG_KM_PROPRIO_SQL = f"""
SELECT coalesce(sum(coalesce(p.kmfretecompra,0)),0)::float8 AS km
{_PROG_VIVO}
  AND p.dtsaida >= current_date - 90
  AND v.utilizacaoveiculo IN ('TRA','LOC')
"""



PROG_VEIC_DISP_SQL = """
SELECT v.placa, coalesce(u.descricao,'(sem)') AS utilizacao,
       t.ult_saida::date AS ult_saida,
       coalesce(t.em_viagem,0)::int AS em_viagem,
       coalesce(os.abertas,0)::int AS os_abertas
FROM veiculo v
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
LEFT JOIN (SELECT veiculo, max(dtsaida) AS ult_saida,
                  sum(CASE WHEN dtchegada IS NULL THEN 1 ELSE 0 END) AS em_viagem
           FROM programacaoembarque
           WHERE dtcancelamento IS NULL AND semaforo = 1
             AND dtsaida >= current_date - 120
           GROUP BY veiculo) t ON t.veiculo = v.placa
LEFT JOIN (SELECT veiculo, count(*) AS abertas
           FROM ordemservico
           WHERE dtfechamento IS NULL AND dtemissao >= current_date - 180
           GROUP BY veiculo) os ON os.veiculo = v.placa
WHERE v.utilizacaoveiculo IN ('TRA','LOC') AND v.dtinativo IS NULL
"""

PROG_MOT_DISP_SQL = """
SELECT coalesce(nullif(trim(c.razaosocial),''),'(sem nome)') AS motorista,
       max(p.dtsaida)::date AS ult_saida,
       sum(CASE WHEN p.dtchegada IS NULL THEN 1 ELSE 0 END)::int AS em_viagem,
       min(cc.dtvencimentocarteirahabilitacao)::date AS venc_cnh
FROM programacaoembarque p
LEFT JOIN cadastro c ON c.codigo = p.motorista
LEFT JOIN cadastro_continua cc ON cc.cnpjcpfcodigo = p.motorista
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1
  AND p.motorista IS NOT NULL AND p.dtsaida >= current_date - 30
GROUP BY p.motorista, c.razaosocial
"""


@cached(ttl=120)
def get_programacao() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(PROG_CHEGADAS_SQL)
        chegadas = cur.fetchall()
        cur.execute(PROG_SAIDAS_SQL)
        saidas = cur.fetchall()
        cur.execute(PROG_VAZIO_DIA_SQL)
        vazio_dia = cur.fetchall()
        cur.execute(PROG_CARGA_DIA_SQL)
        carga_dia = cur.fetchall()
        cur.execute(PROG_CHEGADA_90D_SQL)
        chegadas_90d = cur.fetchall()
        cur.execute(PROG_DIESEL_SQL)
        diesel = cur.fetchone()["custo"]
        cur.execute(PROG_KM_PROPRIO_SQL)
        km_proprio = cur.fetchone()["km"]
        cur.execute(PROG_VEIC_DISP_SQL)
        veic_disp = cur.fetchall()
        cur.execute(PROG_MOT_DISP_SQL)
        mot_disp = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    custo_km_diesel = (diesel / km_proprio) if km_proprio else 0.0

    # ---- radar 72h: casa chegadas x saídas pela cidade/UF ----
    key = lambda c, u: (c.upper().strip(), (u or "?").upper())
    saidas_por_cid: dict = {}
    for s in saidas:
        saidas_por_cid.setdefault(key(s["cidade"], s["uf"]), []).append(s)

    casamentos, sem_retorno = [], []
    cid_com_chegada = set()
    for c in chegadas:
        k = key(c["cidade"], c["uf"])
        cid_com_chegada.add(k)
        # carga compatível: sai depois da chegada prevista (com 12h de folga p/ descarga)
        compat = [s for s in saidas_por_cid.get(k, []) if s["saida"] >= c["eta"]]
        if compat:
            casamentos.append({**c, "cargas": compat[:3], "n_cargas": len(compat)})
        else:
            sem_retorno.append(c)

    sem_veiculo = [s for s in saidas
                   if key(s["cidade"], s["uf"]) not in cid_com_chegada]

    # ---- vazio evitável 90d: rodou vazio de uma cidade num dia em que
    #      também saiu carga da mesma cidade ----
    cargas_no_dia = {}
    for r in carga_dia:
        cargas_no_dia[(key(r["cidade"], r["uf"]), str(r["dia"]))] = r["cargas"]

    km_vazio_total = 0.0
    km_evitavel = 0.0
    evitavel_por_cid: dict = {}
    for r in vazio_dia:
        km_vazio_total += r["km"]
        k = (key(r["cidade"], r["uf"]), str(r["dia"]))
        if cargas_no_dia.get(k):
            km_evitavel += r["km"]
            ck = key(r["cidade"], r["uf"])
            agg = evitavel_por_cid.setdefault(ck, {
                "cidade": r["cidade"], "uf": r["uf"],
                "km_evitavel": 0.0, "viagens_vazias": 0, "dias": 0})
            agg["km_evitavel"] += r["km"]
            agg["viagens_vazias"] += r["viagens"]
            agg["dias"] += 1
    evitaveis = sorted(evitavel_por_cid.values(),
                       key=lambda x: -x["km_evitavel"])[:15]

    # ---- balanço de malha 90d por cidade ----
    malha: dict = {}
    for r in carga_dia:
        k = key(r["cidade"], r["uf"])
        m = malha.setdefault(k, {"cidade": r["cidade"], "uf": r["uf"],
                                 "saidas": 0, "chegadas": 0, "km_vazio": 0.0})
        m["saidas"] += r["cargas"]
    for r in chegadas_90d:
        k = key(r["cidade"], r["uf"])
        m = malha.setdefault(k, {"cidade": r["cidade"], "uf": r["uf"],
                                 "saidas": 0, "chegadas": 0, "km_vazio": 0.0})
        m["chegadas"] += r["chegadas"]
    for r in vazio_dia:
        k = key(r["cidade"], r["uf"])
        if k in malha:
            malha[k]["km_vazio"] += r["km"]
    balanco = [m for m in malha.values() if m["chegadas"] + m["saidas"] >= 10]
    for m in balanco:
        m["saldo"] = m["saidas"] - m["chegadas"]
    balanco.sort(key=lambda x: x["saldo"])
    deficit = balanco[:12]                      # chega muito, sai pouco
    superavit = sorted(balanco, key=lambda x: -x["saldo"])[:12]


    # ---- disponibilidade de frota própria (TRA+LOC ativos) ----
    from datetime import date as _date
    hoje = _date.today()
    dias = lambda d: (hoje - d).days if d else None
    frota_total = len(veic_disp)
    frota_viagem = sum(1 for v in veic_disp if v["em_viagem"] > 0)
    frota_os = sum(1 for v in veic_disp if v["em_viagem"] == 0 and v["os_abertas"] > 0)
    frota_disp = frota_total - frota_viagem - frota_os
    ociosos = sorted(
        ({**v, "dias_parado": dias(v["ult_saida"])}
         for v in veic_disp if v["em_viagem"] == 0 and v["os_abertas"] == 0),
        key=lambda x: -(x["dias_parado"] if x["dias_parado"] is not None else 999))
    for o in ociosos:
        o["ult_saida"] = o["ult_saida"].isoformat() if o["ult_saida"] else None
        o.pop("em_viagem"), o.pop("os_abertas")

    # ---- disponibilidade de motoristas (rodaram nos últimos 30 dias) ----
    mot_total = len(mot_disp)
    mot_viagem = sum(1 for m in mot_disp if m["em_viagem"] > 0)
    cnh_vencida = [m for m in mot_disp if m["venc_cnh"] and m["venc_cnh"] < hoje]
    cnh_vencendo = sum(1 for m in mot_disp
                       if m["venc_cnh"] and 0 <= (m["venc_cnh"] - hoje).days <= 30)
    cnh_vencida_rodando = sum(1 for m in cnh_vencida if m["em_viagem"] > 0)
    mot_parados = sorted(
        ({**m, "dias_parado": dias(m["ult_saida"])}
         for m in mot_disp if m["em_viagem"] == 0),
        key=lambda x: -(x["dias_parado"] or 0))
    def _mot_out(rows):
        out = []
        for m in rows:
            out.append({
                "motorista": m["motorista"],
                "dias_parado": m.get("dias_parado"),
                "ult_saida": m["ult_saida"].isoformat() if m["ult_saida"] else None,
                "em_viagem": m["em_viagem"] > 0,
                "venc_cnh": m["venc_cnh"].isoformat() if m["venc_cnh"] else None,
                "cnh_vencida": bool(m["venc_cnh"] and m["venc_cnh"] < hoje),
            })
        return out

    return {
        "kpis": {
            "chegando_72h": len(chegadas),
            "com_retorno": len(casamentos),
            "sem_retorno": len(sem_retorno),
            "cargas_72h": len(saidas),
            "cargas_sem_chegada": len(sem_veiculo),
            "km_vazio_90d": km_vazio_total,
            "km_evitavel_90d": km_evitavel,
            "custo_km_diesel": custo_km_diesel,
            "economia_potencial": km_evitavel * custo_km_diesel,
            "frota_total": frota_total, "frota_viagem": frota_viagem,
            "frota_os": frota_os, "frota_disp": frota_disp,
            "mot_total": mot_total, "mot_viagem": mot_viagem,
            "mot_parados": mot_total - mot_viagem,
            "cnh_vencida": len(cnh_vencida), "cnh_vencendo": cnh_vencendo,
            "cnh_vencida_rodando": cnh_vencida_rodando,
        },
        "ociosos": ociosos[:20],
        "motoristas_parados": _mot_out(mot_parados[:20]),
        "cnh_alertas": _mot_out(sorted(cnh_vencida, key=lambda m: m["venc_cnh"])[:20]),
        "casamentos": casamentos[:25],
        "sem_retorno": sem_retorno[:25],
        "sem_veiculo": sem_veiculo[:25],
        "evitaveis": evitaveis,
        "deficit": deficit,
        "superavit": superavit,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · programacaoembarque (janela 72h + histórico 90 dias)",
    }


# ============================================================================
# Rentabilidade por cliente — quanto SOBRA de cada grupo econômico.
# Receita = valorfrete. Custo de servir: viagens contratadas (AGR/TER) usam o
# custo real (valorfretecompra); viagens próprias (TRA/LOC) usam km carregado
# vezes o CKM marginal do período (custos do razão ÷ km carregado próprio).
# ============================================================================
RENT_CLI_SQL = f"""
SELECT {_COM_KEY} AS codigo,
       min({_COM_NOME}) AS cliente,
       count(*)::int AS viagens,
       sum(coalesce(p.kmfretecompra,0))::float8 AS km,
       sum(coalesce(p.valorfrete,0))::float8 AS receita,
       sum(CASE WHEN v.utilizacaoveiculo IN ('AGR','TER')
                THEN coalesce(p.valorfretecompra,0) ELSE 0 END)::float8 AS custo_comprado,
       sum(CASE WHEN v.utilizacaoveiculo IN ('AGR','TER')
                THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_comprado,
       sum(CASE WHEN v.utilizacaoveiculo IN ('TRA','LOC')
                THEN coalesce(p.kmfretecompra,0) ELSE 0 END)::float8 AS km_proprio
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN coleta co ON co.grupo=p.grupo AND co.empresa=p.empresa
  AND co.filial=p.filialdocumentoorigem AND co.unidade=p.unidadedocumentoorigem
  AND co.diferenciadornumero=p.diferenciadornumerodocumentoorigem
  AND co.numero=p.numerodocumentoorigem
LEFT JOIN agrupamentocliente_cnpjcpfcodigo av ON av.cnpjcpfcodigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente ag ON ag.codigo = av.codigo
LEFT JOIN cadastro cp ON cp.codigo = co.cnpjcpfcodigopagadorfrete
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND (p.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (%(cliente)s::text IS NULL OR ag.descricao ILIKE '%%'||%(cliente)s||'%%'
       OR cp.nomefantasia ILIKE '%%'||%(cliente)s||'%%' OR cp.razaosocial ILIKE '%%'||%(cliente)s||'%%')
  {_COM_PERIODO}
GROUP BY {_COM_KEY}
ORDER BY 5 DESC LIMIT 30
"""


@cached(ttl=300)
def get_rentabilidade(filial: int | None, dt_de: str, dt_ate: str,
                      cliente: str | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate, "cliente": cliente}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(RENT_CLI_SQL, params)
        clientes = cur.fetchall()
        for c in clientes:
            c["ctes"] = c.pop("viagens")
        cur.execute(HEUR_SEMCLI_SQL, params)
        heur = cur.fetchall()
        clientes = _merge_heuristica(
            clientes, heur,
            ("receita", "km", "custo_comprado", "km_comprado", "km_proprio"))
        clientes.sort(key=lambda c: -c["receita"])
        clientes = clientes[:30]
        for c in clientes:
            c["viagens"] = c.pop("ctes")
        # CKM marginal do MESMO período (custos do razão / km carregado próprio)
        mvb_params = {"de": dt_de, "ate": dt_ate}
        cur.execute(MVB_CUSTO_SQL, mvb_params)
        custo_rows = cur.fetchall()
        cur.execute(MVB_PROPRIA_SQL, mvb_params)
        prop_rows = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    var_mot = sum(r["valor"] for r in custo_rows
                  if r["comp"] in ("combustivel", "manutencao", "pneus",
                                   "outros_var", "motoristas"))
    km_prop_total = sum(r["km_carregado"] for r in prop_rows)
    ckm_marginal = (var_mot / km_prop_total) if km_prop_total else 0.0

    tot = {"receita": 0.0, "custo": 0.0, "negativos": 0}
    for c in clientes:
        c.pop("codigo")
        c["custo_proprio"] = c["km_proprio"] * ckm_marginal
        c["custo_total"] = c["custo_comprado"] + c["custo_proprio"]
        c["margem"] = c["receita"] - c["custo_total"]
        c["margem_pct"] = (100.0 * c["margem"] / c["receita"]) if c["receita"] else None
        c["rkm"] = (c["receita"] / c["km"]) if c["km"] else None
        c["pct_proprio"] = (100.0 * c["km_proprio"] / c["km"]) if c["km"] else None
        tot["receita"] += c["receita"]
        tot["custo"] += c["custo_total"]
        if c["margem"] < 0:
            tot["negativos"] += 1

    margem_total = tot["receita"] - tot["custo"]
    return {
        "clientes": clientes,
        "kpis": {
            "receita": tot["receita"], "custo": tot["custo"],
            "margem": margem_total,
            "margem_pct": (100.0 * margem_total / tot["receita"]) if tot["receita"] else None,
            "ckm_marginal": ckm_marginal,
            "clientes_negativos": tot["negativos"],
        },
        "dt_de": dt_de, "dt_ate": dt_ate,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · viagens (receita/custo comprado) + razão (CKM próprio marginal) · leitura",
    }



# ============================================================================
# Contabilidade — contas x agrupador (painel de ajuste) e análises (centro
# de custo). Réplica é somente leitura: ajustes ficam locais + export SQL.
# ============================================================================
CONTAB_CONTAS_SQL = """
SELECT l.grupo, l.reduzido, min(p.estrutural) AS estrutural,
       min(upper(p.descricao)) AS conta,
       coalesce(min(ag.descricao), 'CLASSIFICAR') AS agrupador,
       count(*)::int AS lancamentos,
       sum(coalesce(l.valordebito,0))::float8 AS debito,
       sum(coalesce(l.valorcredito,0))::float8 AS credito,
       sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))::float8 AS saldo
FROM lancamento l
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1
LEFT JOIN sulista.agrupadorgerencial ag ON ag.reduzido = l.reduzido
  AND ag.grupo = l.grupo
WHERE l.dtlancamento >= %(de)s::date AND l.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
  AND (ag.descricao IS NOT NULL OR p.estrutural ~ '^[34]')
  AND (%(busca)s::text IS NULL OR upper(p.descricao) LIKE upper('%%'||%(busca)s||'%%')
       OR p.estrutural LIKE %(busca)s||'%%'
       OR upper(coalesce(ag.descricao,'CLASSIFICAR')) LIKE upper('%%'||%(busca)s||'%%'))
GROUP BY l.grupo, l.reduzido
ORDER BY (coalesce(min(ag.descricao),'CLASSIFICAR')='CLASSIFICAR') DESC,
         abs(sum(coalesce(l.valorcredito,0)-coalesce(l.valordebito,0))) DESC
LIMIT 120
"""

CONTAB_AGRUPADORES_SQL = """
SELECT descricao, count(*)::int AS contas
FROM sulista.agrupadorgerencial GROUP BY 1 ORDER BY 1
"""

CONTAB_CC_SQL = """
SELECT coalesce(nullif(trim(cc.descricao),''),'SEM CENTRO DE CUSTO') AS centro_custo,
       sum(coalesce(lc.valordebito,0))::float8 AS debito,
       sum(coalesce(lc.valorcredito,0))::float8 AS credito,
       sum(coalesce(lc.valordebito,0)-coalesce(lc.valorcredito,0))::float8 AS custo_liquido
FROM lancamento_filial_unidade_centrocusto lc
LEFT JOIN centrocusto cc ON cc.codigo = lc.centrocusto
JOIN lancamento l ON l.sequencia = lc.sequencia AND l.reduzido = lc.reduzido
  AND l.dtlancamento = lc.dtlancamento
JOIN planoconta p ON p.reduzido = l.reduzido AND p.grupo = l.grupo
  AND p.ativoinativo = 1 AND p.estrutural LIKE '4%%'
WHERE lc.dtlancamento >= %(de)s::date AND lc.dtlancamento < %(ate)s::date
  AND coalesce(l.historico, 0) <> 18
GROUP BY 1 ORDER BY 4 DESC LIMIT 20
"""


@cached(ttl=120)
def get_contabil(comp_de: str, comp_ate: str, busca: str | None = None) -> dict:
    de, ate = _comp_bounds(comp_de, comp_ate)
    params = {"de": de, "ate": ate, "busca": busca}
    ajustes = ler_ajustes()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CONTAB_CONTAS_SQL, params)
        contas = cur.fetchall()
        cur.execute(CONTAB_AGRUPADORES_SQL)
        agrupadores = cur.fetchall()
        cur.execute(CONTAB_CC_SQL, {"de": de, "ate": ate})
        centros = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    a_classificar_valor = 0.0
    a_classificar_n = 0
    for c in contas:
        aj = ajustes.get(f"{c['grupo']}|{c['reduzido']}")
        c["ajuste_local"] = aj["agrupador"] if aj else None
        c["agrupador_efetivo"] = c["ajuste_local"] or c["agrupador"]
        if c["agrupador_efetivo"] == "CLASSIFICAR":
            a_classificar_n += 1
            a_classificar_valor += abs(c["saldo"])

    return {
        "contas": contas,
        "agrupadores": [a["descricao"] for a in agrupadores],
        "centros_custo": centros,
        "kpis": {
            "a_classificar": a_classificar_n,
            "a_classificar_valor": a_classificar_valor,
            "ajustes_locais": len(ajustes),
        },
        "comp_de": comp_de, "comp_ate": comp_ate, "busca": busca,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA (réplica, leitura) · ajustes locais até aplicar no primário",
    }


# ============================================================================
# Régua de cobrança — clientes com recebíveis vencidos, priorizados por valor,
# com faixas de idade e detalhe dos títulos.
# ============================================================================
# Inadimplência pelo MÉTODO OFICIAL do ERP (Querys Sulista/INADIMPLENCIA):
# fatura + fatura_composicao, só "Faturado" (composicao=1), valor =
# valorpendentecnpjcliente, vencido por COALESCE(dtprevisaopagamento,
# dtvencimento) com dtpagamento IS NULL, docs 6/8/10/11 e CT-e válido
# (situacaocte=3). Antes usávamos fatura.valorsaldoreceber, que inflava ~12x
# por incluir pendentes de faturamento (composicao=2) — agora à parte.
_COB_FROM = """
FROM fatura f
JOIN fatura_composicao fc USING (grupo, empresa, filial, unidade, sequencia)
LEFT JOIN conhecimento co ON co.grupo=fc.grupodocumentoorigem AND co.empresa=fc.empresadocumentoorigem
   AND co.filial=fc.filialdocumentoorigem AND co.unidade=fc.unidadedocumentoorigem
   AND co.diferenciadornumero=fc.diferenciadornumerodocumentoorigem AND co.serie=fc.seriedocumentoorigem
   AND co.numero=fc.numerosequenciadocumentoorigem AND fc.tipodocumentoorigem=6
"""
_COB_WHERE = """
WHERE f.grupo=1 AND fc.valorpendentecnpjcliente > 0 AND f.dtcancelamento IS NULL
  AND f.composicao = 1
  AND coalesce(f.dtprevisaopagamento, f.dtvencimento) < current_date AND f.dtpagamento IS NULL
  AND fc.tipodocumentoorigem = ANY(string_to_array('6,8,10,11',',')::int[])
  AND (fc.tipodocumentoorigem <> 6 OR co.situacaocte = 3)
  AND (f.filial = %(filial)s OR %(filial)s::int IS NULL)
"""
_COB_DV = "(current_date - coalesce(f.dtprevisaopagamento, f.dtvencimento))"

COB_CLI_SQL = f"""
SELECT f.cliente AS codigo,
       coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), '(sem cadastro)') AS cliente,
       count(*)::int AS titulos,
       sum(fc.valorpendentecnpjcliente)::float8 AS vencido,
       sum(CASE WHEN {_COB_DV} <= 30 THEN fc.valorpendentecnpjcliente ELSE 0 END)::float8 AS ate_30,
       sum(CASE WHEN {_COB_DV} BETWEEN 31 AND 90 THEN fc.valorpendentecnpjcliente ELSE 0 END)::float8 AS de_31_90,
       sum(CASE WHEN {_COB_DV} BETWEEN 91 AND 365 THEN fc.valorpendentecnpjcliente ELSE 0 END)::float8 AS de_91_365,
       sum(CASE WHEN {_COB_DV} > 365 THEN fc.valorpendentecnpjcliente ELSE 0 END)::float8 AS mais_365,
       min(coalesce(f.dtprevisaopagamento, f.dtvencimento))::text AS vencimento_mais_antigo
{_COB_FROM}
LEFT JOIN cadastro c ON c.codigo = f.cliente
{_COB_WHERE}
  AND (%(cliente)s::text IS NULL OR c.nomefantasia ILIKE '%%'||%(cliente)s||'%%'
       OR c.razaosocial ILIKE '%%'||%(cliente)s||'%%')
GROUP BY f.cliente, c.nomefantasia, c.razaosocial
ORDER BY 4 DESC LIMIT 30
"""

COB_DSO_SQL = """
SELECT cliente AS codigo,
       (sum((dtpagamento::date - dtemissao::date) * valortitulo)
        / nullif(sum(valortitulo),0))::float8 AS dso
FROM fatura
WHERE dtcancelamento IS NULL AND dtpagamento IS NOT NULL AND valortitulo > 0
  AND dtpagamento >= current_date - 180
  AND cliente = ANY(%(codigos)s)
GROUP BY cliente
"""

COB_TIT_SQL = f"""
SELECT f.cliente AS codigo_c, fc.numerosequenciadocumentoorigem AS numero, f.filial,
       to_char(f.dtemissao,'YYYY-MM-DD') AS emissao,
       to_char(coalesce(f.dtprevisaopagamento, f.dtvencimento),'YYYY-MM-DD') AS vencimento,
       {_COB_DV}::int AS dias_vencido,
       fc.valorpendentecnpjcliente::float8 AS saldo
{_COB_FROM}
{_COB_WHERE}
  AND f.cliente = ANY(%(codigos)s)
ORDER BY f.cliente, fc.valorpendentecnpjcliente DESC
"""

# Pendente de faturamento vencido (composicao=2) — mostrado à parte; NÃO entra
# no "vencido oficial".
COB_PENDENTE_SQL = """
SELECT coalesce(sum(fc.valorpendentecnpjcliente),0)::float8 AS valor, count(*)::int AS docs
FROM fatura f
JOIN fatura_composicao fc USING (grupo, empresa, filial, unidade, sequencia)
WHERE f.grupo=1 AND fc.valorpendentecnpjcliente > 0 AND f.dtcancelamento IS NULL
  AND f.composicao = 2
  AND coalesce(f.dtprevisaopagamento, f.dtvencimento) < current_date AND f.dtpagamento IS NULL
  AND (f.filial = %(filial)s OR %(filial)s::int IS NULL)
"""


@cached(ttl=90)
def get_cobranca(filial: int | None, cliente: str | None = None) -> dict:
    params = {"filial": filial, "cliente": cliente}
    MAX_TIT = 30
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(COB_CLI_SQL, params)
        clientes = cur.fetchall()
        titulos: dict[str, list] = {}
        dso_cli: dict[str, float] = {}
        codigos = [r["codigo"] for r in clientes if r["codigo"]]
        if codigos:
            cur.execute(COB_TIT_SQL, {**params, "codigos": codigos})
            for r in cur.fetchall():
                titulos.setdefault(r.pop("codigo_c"), []).append(r)
            cur.execute(COB_DSO_SQL, {"codigos": codigos})
            dso_cli = {r["codigo"]: r["dso"] for r in cur.fetchall()}
        cur.execute(COB_PENDENTE_SQL, params)
        pend = cur.fetchone()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    total = sum(c["vencido"] for c in clientes)
    for c in clientes:
        codigo = c.pop("codigo")
        c["doc"] = _mask_doc(codigo)
        c["dso"] = dso_cli.get(codigo)
        ts = titulos.get(codigo, [])
        c["ocultos"] = max(0, len(ts) - MAX_TIT)
        c["titulos_lista"] = ts[:MAX_TIT]

    return {
        "clientes": clientes,
        "total_vencido_top": total,
        "pendente_faturamento": (pend or {}).get("valor", 0.0),
        "pendente_faturamento_docs": (pend or {}).get("docs", 0),
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · inadimplência oficial (fatura_composicao, só Faturado) · "
                  "pendente de faturamento à parte · leitura"),
    }


# ============================================================================
# Jornada do Motorista (Lei 13.103/2015)
# ----------------------------------------------------------------------------
# Bottom-up sobre o módulo de jornada que o próprio AVA já apura. A tabela
# `jornada` (cabeçalho diário por motorista) traz as flags de compliance
# prontas: tempodirecaocontinuaultrapassado / tempointervaloinsuficiente
# (1-Sim; 2-Não). Não recalculamos violação sobre contadores brutos (que
# acumulam e não são confiáveis) — surgimos a apuração oficial do ERP.
# PII: `cnpjcpfcodigo` é o CPF do motorista; NUNCA sai no payload. O nome é
# resolvido (cadastro.codigo) e a ficha é endereçada por um token opaco (HMAC).
# ============================================================================
import hmac as _hmac
import hashlib as _hashlib
import os as _os
from datetime import timedelta as _timedelta

# Segredo do token da ficha: estável no processo (painel e ficha rodam no
# mesmo processo). Tokens antigos de um processo anterior falham de forma
# graciosa — o front recarrega o painel a cada navegação.
_JOR_SECRET = (_os.environ.get("JORNADA_TOKEN_SECRET") or "").encode() or _os.urandom(16)
_JOR_TOKEN_MAP: dict[str, str] = {}   # token -> cpf (preenchido pelo painel)

CNH_ALERTA_DIAS = 30                  # CNH vencendo dentro desta janela = atenção


def _jor_token(cpf: str) -> str:
    """Token opaco e determinístico (no processo) para endereçar a ficha sem
    expor o CPF em URL/log."""
    return _hmac.new(_JOR_SECRET, str(cpf).encode(), _hashlib.sha256).hexdigest()[:16]


def _jor_cnh_status(venc, hoje: date) -> str | None:
    """'vencida' | 'vencendo' (<=30d) | 'ok' | None (sem data)."""
    if not venc:
        return None
    if venc < hoje:
        return "vencida"
    if venc <= hoje + _timedelta(days=CNH_ALERTA_DIAS):
        return "vencendo"
    return "ok"


def _jor_risco(v_direcao: int, v_intervalo: int, cnh_status: str | None) -> str:
    """Semáforo do motorista: 'critico' | 'atencao' | 'ok'."""
    if (v_direcao or 0) > 0 or cnh_status == "vencida":
        return "critico"
    if (v_intervalo or 0) > 0 or cnh_status == "vencendo":
        return "atencao"
    return "ok"


def _iv_horas(td) -> float:
    """interval (timedelta) -> horas decimais; None/negativo -> 0.0."""
    if not td:
        return 0.0
    h = td.total_seconds() / 3600.0
    return round(h, 1) if h > 0 else 0.0


# Painel: um registro por motorista no período, com flags agregadas do ERP.
JOR_PAINEL_SQL = """
SELECT j.cnpjcpfcodigo AS cpf,
       coalesce(nullif(trim(c.razaosocial),''),'(sem nome)') AS nome,
       count(*)::int AS jornadas,
       sum(j.tempodirecao) AS h_direcao,
       sum(j.tempojornada) AS h_jornada,
       sum(coalesce(j.hora50,interval '0') + coalesce(j.hora100,interval '0')) AS h_extra,
       sum(CASE WHEN j.tempodirecaocontinuaultrapassado = 1 THEN 1 ELSE 0 END)::int AS v_direcao,
       sum(CASE WHEN j.tempointervaloinsuficiente = 1 THEN 1 ELSE 0 END)::int AS v_intervalo,
       min(cc.dtvencimentocarteirahabilitacao)::date AS cnh_venc,
       max(cc.categoriacarteirahabilitacao) AS cnh_cat
FROM jornada j
LEFT JOIN cadastro c ON c.codigo = j.cnpjcpfcodigo
LEFT JOIN cadastro_continua cc ON cc.cnpjcpfcodigo = j.cnpjcpfcodigo
WHERE j.dtinicio >= %(de)s AND j.dtinicio < %(ate)s
  AND (%(busca)s::text IS NULL OR c.razaosocial ILIKE '%%'||%(busca)s||'%%')
GROUP BY j.cnpjcpfcodigo, c.razaosocial
"""


@cached(ttl=120)
def get_jornada(comp_de: str, comp_ate: str, busca: str | None = None) -> dict:
    """Painel de compliance de jornada por motorista no período (competência)."""
    de, ate = _comp_bounds(comp_de, comp_ate)
    hoje = date.today()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(JOR_PAINEL_SQL, {"de": de, "ate": ate, "busca": busca})
        linhas = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    motoristas = []
    _JOR_TOKEN_MAP.clear()
    for r in linhas:
        cpf = r["cpf"]
        tok = _jor_token(cpf)
        _JOR_TOKEN_MAP[tok] = cpf
        cnh = _jor_cnh_status(r["cnh_venc"], hoje)
        motoristas.append({
            "id": tok,
            "nome": r["nome"],
            "doc": _mask_doc(cpf),
            "jornadas": r["jornadas"],
            "h_direcao": _iv_horas(r["h_direcao"]),
            "h_jornada": _iv_horas(r["h_jornada"]),
            "h_extra": _iv_horas(r["h_extra"]),
            "v_direcao": r["v_direcao"],
            "v_intervalo": r["v_intervalo"],
            "cnh_venc": r["cnh_venc"].isoformat() if r["cnh_venc"] else None,
            "cnh_cat": (r["cnh_cat"] or "").strip() or None,
            "cnh_status": cnh,
            "risco": _jor_risco(r["v_direcao"], r["v_intervalo"], cnh),
        })

    # ordena por risco (critico->atencao->ok) e depois por violações de direção
    ordem = {"critico": 0, "atencao": 1, "ok": 2}
    motoristas.sort(key=lambda m: (ordem.get(m["risco"], 3), -m["v_direcao"], -m["h_direcao"]))

    n = len(motoristas)
    em_compliance = sum(1 for m in motoristas if m["risco"] == "ok")
    kpis = {
        "motoristas": n,
        "pct_compliance": round(100 * em_compliance / n, 1) if n else 0.0,
        "viol_direcao": sum(m["v_direcao"] for m in motoristas),
        "viol_intervalo": sum(m["v_intervalo"] for m in motoristas),
        "cnh_vencida": sum(1 for m in motoristas if m["cnh_status"] == "vencida"),
        "cnh_vencendo": sum(1 for m in motoristas if m["cnh_status"] == "vencendo"),
        "h_extra": round(sum(m["h_extra"] for m in motoristas), 1),
    }
    violacoes_tipo = [
        {"tipo": "Direção contínua > 5h30", "n": kpis["viol_direcao"]},
        {"tipo": "Intervalo insuficiente", "n": kpis["viol_intervalo"]},
    ]
    alertas = [m for m in motoristas
               if m["cnh_status"] in ("vencida", "vencendo") or m["v_direcao"] > 0][:20]

    return {
        "kpis": kpis,
        "violacoes_tipo": violacoes_tipo,
        "motoristas": motoristas,
        "alertas": alertas,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · tabela jornada (apuração oficial do ERP) · "
                  "só motoristas com controle de jornada · leitura"),
    }


# Ficha: jornadas do motorista no período (para timeline + detalhe).
JOR_FICHA_SQL = """
SELECT j.dtinicio, j.dtfim,
       j.tempodirecao, j.tempojornada, j.tempodescanso, j.temporepouso,
       j.tempointervalorefeicao, j.tempoespera,
       coalesce(j.hora30,interval '0') AS hora30,
       coalesce(j.hora50,interval '0') AS hora50,
       coalesce(j.hora100,interval '0') AS hora100,
       j.tempodirecaocontinuaultrapassado AS v_direcao,
       j.tempointervaloinsuficiente AS v_intervalo
FROM jornada j
WHERE j.cnpjcpfcodigo = %(cpf)s
  AND j.dtinicio >= %(de)s AND j.dtinicio < %(ate)s
ORDER BY j.dtinicio DESC
LIMIT 90
"""

JOR_FICHA_CAB_SQL = """
SELECT coalesce(nullif(trim(c.razaosocial),''),'(sem nome)') AS nome,
       cc.dtvencimentocarteirahabilitacao::date AS cnh_venc,
       cc.categoriacarteirahabilitacao AS cnh_cat,
       cc.ufcarteirahabilitacao AS cnh_uf
FROM cadastro c
LEFT JOIN cadastro_continua cc ON cc.cnpjcpfcodigo = c.codigo
WHERE c.codigo = %(cpf)s
"""


def _jor_resolve_token(token: str) -> str | None:
    """token -> cpf. Usa o mapa do último painel; se faltar (ex.: ficha aberta
    direto), varre os motoristas com jornada nos últimos 400 dias e casa o
    token recomputado. Nunca devolve o CPF ao chamador externo."""
    cpf = _JOR_TOKEN_MAP.get(token)
    if cpf:
        return cpf
    rows = db.query("SELECT DISTINCT cnpjcpfcodigo AS cpf FROM jornada "
                    "WHERE dtinicio >= current_date - 400")
    for r in rows:
        c = r["cpf"]
        t = _jor_token(c)
        _JOR_TOKEN_MAP[t] = c
        if t == token:
            cpf = c
    return cpf


@cached(ttl=120)
def get_motorista_jornada(token: str, comp_de: str, comp_ate: str) -> dict:
    """Ficha de jornada de um motorista (endereçado por token opaco)."""
    cpf = _jor_resolve_token(token)
    if not cpf:
        return {"erro": "motorista não encontrado (recarregue o painel)"}
    de, ate = _comp_bounds(comp_de, comp_ate)
    hoje = date.today()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(JOR_FICHA_CAB_SQL, {"cpf": cpf})
        cab = cur.fetchone() or {}
        cur.execute(JOR_FICHA_SQL, {"cpf": cpf, "de": de, "ate": ate})
        js = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    jornadas = []
    for r in js:
        jornadas.append({
            "inicio": r["dtinicio"].isoformat() if r["dtinicio"] else None,
            "fim": r["dtfim"].isoformat() if r["dtfim"] else None,
            "h_direcao": _iv_horas(r["tempodirecao"]),
            "h_jornada": _iv_horas(r["tempojornada"]),
            "h_descanso": _iv_horas(r["tempodescanso"]),
            "h_repouso": _iv_horas(r["temporepouso"]),
            "h_refeicao": _iv_horas(r["tempointervalorefeicao"]),
            "v_direcao": r["v_direcao"] == 1,
            "v_intervalo": r["v_intervalo"] == 1,
        })

    cnh = _jor_cnh_status(cab.get("cnh_venc"), hoje)
    kpis = {
        "jornadas": len(jornadas),
        "h_direcao": round(sum(j["h_direcao"] for j in jornadas), 1),
        "h_jornada": round(sum(j["h_jornada"] for j in jornadas), 1),
        "h_descanso": round(sum(j["h_descanso"] for j in jornadas), 1),
        "h_extra": round(sum(_iv_horas(r["hora50"]) + _iv_horas(r["hora100"]) for r in js), 1),
        "h_noturno": round(sum(_iv_horas(r["hora30"]) for r in js), 1),
        "v_direcao": sum(1 for j in jornadas if j["v_direcao"]),
        "v_intervalo": sum(1 for j in jornadas if j["v_intervalo"]),
    }
    return {
        "nome": cab.get("nome", "(sem nome)"),
        "doc": _mask_doc(cpf),
        "cnh": {
            "venc": cab["cnh_venc"].isoformat() if cab.get("cnh_venc") else None,
            "cat": (cab.get("cnh_cat") or "").strip() or None,
            "uf": (cab.get("cnh_uf") or "").strip() or None,
            "status": cnh,
        },
        "kpis": kpis,
        "risco": _jor_risco(kpis["v_direcao"], kpis["v_intervalo"], cnh),
        "jornadas": jornadas,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · tabela jornada (apuração oficial do ERP) · leitura",
    }


# ============================================================================
# Custos Extras (sulista.custoextra) — cobrança de acessórios por CT-e
# ----------------------------------------------------------------------------
# Descarga, diária, estadia, ajudante, escolta, carga crítica etc. lançados
# por CT-e, com status de cobrança. Fonte: Querys Sulista/OPERACAO - Custos
# Extras.sql. Ângulo de gestão: o que ainda NÃO foi cobrado = receita a
# recuperar.
# ============================================================================
CEX_TIPO = {8: "Descarga", 104: "Diária", 105: "Estadia", 106: "Coleta Frustrada",
            107: "Frete Compra", 108: "Movimentação Balança", 109: "Ajudante",
            110: "Carga Crítica", 111: "Escolta"}
CEX_STATUS = {1: "Emitido", 2: "Não Cobrado", 3: "Aguardando Cobrança"}
CEX_JUSTIF = {1: "Devido", 2: "Acordo comercial", 3: "Erro operacional", 4: "Já Contemplado"}

CEX_AGG_SQL = """
SELECT ce.tipocusto, ce.statuscobranca, count(*)::int AS n,
       sum(coalesce(ce.valorcusto,0))::float8 AS custo,
       sum(coalesce(ce.valorcobrado,0))::float8 AS cobrado
FROM sulista.custoextra ce
WHERE ce.dtinclusao::date BETWEEN %(dt_de)s AND %(dt_ate)s
GROUP BY ce.tipocusto, ce.statuscobranca
"""

CEX_LIST_SQL = """
SELECT ce.id, ce.tipocusto, ce.statuscobranca, ce.justificativa,
       coalesce(ce.valorcusto,0)::float8 AS custo,
       coalesce(ce.valorcobrado,0)::float8 AS cobrado,
       to_char(ce.dtinclusao,'YYYY-MM-DD') AS data,
       co.numero AS cte,
       coalesce(nullif(trim(ac.descricao),''), nullif(trim(cad.razaosocial),''), '(sem cliente)') AS cliente,
       u.nomecompleto AS usuario
FROM sulista.custoextra ce
LEFT JOIN conhecimento co ON co.grupo=ce.grupo AND co.empresa=ce.empresa
   AND co.filial=ce.filialdocumento AND co.unidade=ce.unidadedocumento
   AND co.diferenciadornumero=ce.diferenciadornumerodocumento AND co.serie=ce.seriedocumento
   AND co.numero=ce.numerodocumento
LEFT JOIN cadastro cad ON cad.codigo = co.cnpjcpfcodigopagadorfrete
LEFT JOIN agrupamentocliente_cnpjcpfcodigo acc ON acc.grupo=co.grupo AND acc.empresa=co.empresa
   AND acc.cnpjcpfcodigo=co.cnpjcpfcodigopagadorfrete AND acc.vinculo=1
LEFT JOIN agrupamentocliente ac ON ac.grupo=acc.grupo AND ac.empresa=acc.empresa AND ac.codigo=acc.codigo
LEFT JOIN usuario u ON u.codigo = ce.userinclusao
WHERE ce.dtinclusao::date BETWEEN %(dt_de)s AND %(dt_ate)s
ORDER BY ce.dtinclusao DESC
LIMIT 200
"""


@cached(ttl=120)
def get_custos_extras(dt_de: str, dt_ate: str) -> dict:
    """Custos extras (acessórios) por CT-e no período, com status de cobrança."""
    params = {"dt_de": dt_de, "dt_ate": dt_ate}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CEX_AGG_SQL, params)
        agg = cur.fetchall()
        cur.execute(CEX_LIST_SQL, params)
        lst = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    total_custo = sum(a["custo"] for a in agg)
    total_cobrado = sum(a["cobrado"] for a in agg)
    # a cobrar = custo dos lançamentos ainda não emitidos (status 2/3) não coberto
    a_cobrar = sum(max(a["custo"] - a["cobrado"], 0.0) for a in agg if a["statuscobranca"] in (2, 3))
    n_total = sum(a["n"] for a in agg)

    por_tipo: dict[str, dict] = {}
    for a in agg:
        t = CEX_TIPO.get(a["tipocusto"], f"Tipo {a['tipocusto']}")
        d = por_tipo.setdefault(t, {"tipo": t, "n": 0, "custo": 0.0, "cobrado": 0.0})
        d["n"] += a["n"]; d["custo"] += a["custo"]; d["cobrado"] += a["cobrado"]
    por_tipo_l = sorted(por_tipo.values(), key=lambda x: -x["custo"])

    por_status: dict[str, dict] = {}
    for a in agg:
        s = CEX_STATUS.get(a["statuscobranca"], "Sem status")
        d = por_status.setdefault(s, {"status": s, "n": 0, "custo": 0.0, "cobrado": 0.0})
        d["n"] += a["n"]; d["custo"] += a["custo"]; d["cobrado"] += a["cobrado"]

    lancamentos = [{
        "id": r["id"], "data": r["data"], "cte": r["cte"], "cliente": r["cliente"],
        "tipo": CEX_TIPO.get(r["tipocusto"], f"Tipo {r['tipocusto']}"),
        "status": CEX_STATUS.get(r["statuscobranca"], "—"),
        "justificativa": CEX_JUSTIF.get(r["justificativa"]),
        "custo": r["custo"], "cobrado": r["cobrado"], "usuario": r["usuario"],
    } for r in lst]

    return {
        "kpis": {
            "n": n_total, "total_custo": total_custo, "total_cobrado": total_cobrado,
            "a_cobrar": a_cobrar,
            "pct_cobrado": round(100 * total_cobrado / total_custo, 1) if total_custo else 0.0,
        },
        "por_tipo": por_tipo_l,
        "por_status": list(por_status.values()),
        "lancamentos": lancamentos,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · sulista.custoextra (custos extras por CT-e) · leitura",
    }


# ============================================================================
# SAC / Freetime & Estadia (detention)
# ----------------------------------------------------------------------------
# Freetime contratado por cliente (sulista.sac_freetimecliente) + ESTIMATIVA de
# estadia excedente: permanência no carregamento (ocorrências SAC 394->395) e
# na descarga (396->397) além do freetime do cliente, × valor/hora contratado.
# É ESTIMATIVA (usa o freetime vigente do cliente, SEM as exceções por
# mercadoria/operação da apuração oficial); a estadia efetivamente cobrada
# aparece em Custos Extras (Estadia/Diária). Não reproduz o CNPJ de parceiro
# embutido na regra oficial. Fonte: Querys Sulista/OPERACAO - Monitoramento SAC.
# ============================================================================
# Freetime representativo por cliente (contrato vigente mais recente).
SAC_FT_REP = """
ft AS (
  SELECT DISTINCT ON (agrupamentocliente) agrupamentocliente,
         freetimecarga, freetimedescarga, valor_coleta, valor_entrega
  FROM sulista.sac_freetimecliente WHERE ativoinativo = 1
  ORDER BY agrupamentocliente, dtinicio DESC NULLS LAST
)"""

# Estadia estimada por coleta (só as que excederam o freetime no período).
# Cada janela (carga/descarga) é capada em 24h: acima disso é quase sempre
# artefato de pareamento (min(chegada)->max(saída) atravessando paradas/dias),
# não detention real — a estimativa fica conservadora.
SAC_DET_SQL = f"""
WITH ev AS (
  SELECT grupo,empresa,filial,unidade,diferenciadornumero,serie,numero,
    min(CASE WHEN ocorrencia=394 THEN dtocorrencia END) AS cc,
    max(CASE WHEN ocorrencia=395 THEN dtocorrencia END) AS sc,
    min(CASE WHEN ocorrencia=396 THEN dtocorrencia END) AS cd,
    max(CASE WHEN ocorrencia=397 THEN dtocorrencia END) AS fd
  FROM coleta_ocorrencia
  WHERE ocorrencia IN (394,395,396,397)
    AND dtocorrencia::date BETWEEN %(dt_de)s AND %(dt_ate)s
  GROUP BY 1,2,3,4,5,6,7),
{SAC_FT_REP},
perm AS (
  SELECT c.numero AS coleta, c.filial,
         coalesce(nullif(trim(ac.descricao),''),'(sem cliente)') AS cliente,
         to_char(coalesce(ev.fd, ev.sc, ev.cd, ev.cc),'YYYY-MM-DD') AS data,
         CASE WHEN ev.sc > ev.cc AND ev.sc <= ev.cc + interval '24 hours'
              THEN extract(epoch from (ev.sc-ev.cc))/3600 ELSE 0 END AS win_carga,
         CASE WHEN ev.fd > ev.cd AND ev.fd <= ev.cd + interval '24 hours'
              THEN extract(epoch from (ev.fd-ev.cd))/3600 ELSE 0 END AS win_desc,
         extract(epoch from ft.freetimecarga)/3600 AS ft_carga,
         extract(epoch from ft.freetimedescarga)/3600 AS ft_desc,
         coalesce(ft.valor_coleta,0) AS vc, coalesce(ft.valor_entrega,0) AS ve
  FROM ev
  JOIN coleta c ON c.grupo=ev.grupo AND c.empresa=ev.empresa AND c.filial=ev.filial
    AND c.unidade=ev.unidade AND c.diferenciadornumero=ev.diferenciadornumero
    AND c.serie=ev.serie AND c.numero=ev.numero
  LEFT JOIN agrupamentocliente_cnpjcpfcodigo acc ON acc.grupo=c.grupo AND acc.empresa=c.empresa
    AND acc.cnpjcpfcodigo=c.cnpjcpfcodigopagadorfrete AND acc.vinculo=1
  LEFT JOIN agrupamentocliente ac ON ac.grupo=acc.grupo AND ac.empresa=acc.empresa AND ac.codigo=acc.codigo
  JOIN ft ON ft.agrupamentocliente = ac.codigo)
SELECT coleta, filial, cliente, data,
       round(win_carga::numeric,1)::float8 AS h_carga,
       round(win_desc::numeric,1)::float8 AS h_descarga,
       round(GREATEST(win_carga - ft_carga, 0)::numeric,1)::float8 AS exc_carga,
       round(GREATEST(win_desc - ft_desc, 0)::numeric,1)::float8 AS exc_descarga,
       round((GREATEST(win_carga - ft_carga, 0)*vc + GREATEST(win_desc - ft_desc, 0)*ve)::numeric,2)::float8 AS valor_est
FROM perm
WHERE GREATEST(win_carga - ft_carga, 0) + GREATEST(win_desc - ft_desc, 0) > 0
ORDER BY valor_est DESC NULLS LAST
"""

# Freetime contratado por cliente (referência).
SAC_FT_SQL = """
SELECT coalesce(nullif(trim(ac.descricao),''),'(sem cliente)') AS cliente,
       ft.filial,
       round((extract(epoch from ft.freetimecarga)/3600)::numeric,1)::float8 AS ft_carga_h,
       round((extract(epoch from ft.freetimedescarga)/3600)::numeric,1)::float8 AS ft_descarga_h,
       ft.valor_coleta::float8 AS valor_coleta, ft.valor_entrega::float8 AS valor_entrega,
       ft.observacao
FROM sulista.sac_freetimecliente ft
LEFT JOIN agrupamentocliente ac ON ac.codigo = ft.agrupamentocliente
WHERE ft.ativoinativo = 1
ORDER BY ac.descricao, ft.filial
"""


@cached(ttl=180)
def get_sac_freetime(dt_de: str, dt_ate: str) -> dict:
    """SAC/Freetime: estadia estimada excedente por cliente + freetime de
    referência. Valores são ESTIMATIVA (regra padrão de freetime)."""
    params = {"dt_de": dt_de, "dt_ate": dt_ate}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(SAC_DET_SQL, params)
        det = cur.fetchall()
        cur.execute(SAC_FT_SQL)
        ft = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    com_exc = [d for d in det if (d["valor_est"] or 0) > 0 or (d["exc_carga"] or 0) > 0 or (d["exc_descarga"] or 0) > 0]
    por_cli: dict[str, dict] = {}
    for d in com_exc:
        k = d["cliente"]
        p = por_cli.setdefault(k, {"cliente": k, "coletas": 0, "exc_carga": 0.0,
                                   "exc_descarga": 0.0, "valor_est": 0.0})
        p["coletas"] += 1
        p["exc_carga"] += d["exc_carga"] or 0.0
        p["exc_descarga"] += d["exc_descarga"] or 0.0
        p["valor_est"] += d["valor_est"] or 0.0
    por_cliente = sorted(por_cli.values(), key=lambda x: -x["valor_est"])
    for p in por_cliente:
        p["exc_carga"] = round(p["exc_carga"], 1)
        p["exc_descarga"] = round(p["exc_descarga"], 1)
        p["valor_est"] = round(p["valor_est"], 2)

    valor_total = round(sum(d["valor_est"] or 0.0 for d in com_exc), 2)
    horas_exc = round(sum((d["exc_carga"] or 0.0) + (d["exc_descarga"] or 0.0) for d in com_exc), 1)

    freetime_cli = [{
        "cliente": r["cliente"], "filial": r["filial"],
        "ft_carga_h": r["ft_carga_h"], "ft_descarga_h": r["ft_descarga_h"],
        "valor_coleta": r["valor_coleta"], "valor_entrega": r["valor_entrega"],
        "obs": (r["observacao"] or "").strip() or None,
    } for r in ft]

    return {
        "kpis": {
            "valor_estimado": valor_total,
            "coletas_excedidas": len(com_exc),
            "horas_excedentes": horas_exc,
            "clientes_freetime": len({r["cliente"] for r in ft}),
        },
        "por_cliente": por_cliente[:30],
        "coletas": com_exc[:100],
        "freetime_cliente": freetime_cli,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · SAC (coleta_ocorrencia 394-397) + sulista.sac_freetimecliente · "
                  "ESTIMATIVA (freetime padrão, sem exceções por mercadoria) · leitura"),
    }


# ============================================================================
# Manutenção Preventiva — revisões próximas/vencidas
# ----------------------------------------------------------------------------
# Fonte: função avacorpi.fnc_manutencaopreventiva_gridview + regras oficiais
# (Querys Sulista/MANUTENCAO - Revisoes Proximas). Duas lógicas distintas:
#   - Trações (com motor): por KM. km_faltante = marcadorproximatroca −
#     odômetro atual (último ctaplus, fallback marcadoratual). VENCIDA <0;
#     PRÓXIMA se km_faltante/marcadortroca < 10%.
#   - Carretas/semi-reboque: por DATA. dias = dtultimatroca + 180 (ou 240 se
#     CARROCERIA BAU) − hoje. VENCIDA <0; PRÓXIMA ≤30 dias.
# ============================================================================
_MPREV_FN = "avacorpi.fnc_manutencaopreventiva_gridview(2,1,1,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,3,NULL,1,1)"

MPREV_TRACAO_SQL = f"""
SELECT retorno.frota, retorno.veiculo,
  NULLIF(REGEXP_REPLACE(retorno.marcadorproximatroca::text,'\\D','','g'),'')::int AS prox,
  NULLIF(REGEXP_REPLACE(retorno.marcadortroca::text,'\\D','','g'),'')::int AS intervalo,
  coalesce(NULLIF(REGEXP_REPLACE(cta.odometro::text,'\\D','','g'),'')::int,
           NULLIF(REGEXP_REPLACE(retorno.marcadoratual::text,'\\D','','g'),'')::int) AS odometro
FROM {_MPREV_FN} retorno
LEFT JOIN veiculo v ON retorno.veiculo=v.placa
LEFT JOIN (SELECT veiculo_nome, odometro,
             ROW_NUMBER() OVER (PARTITION BY veiculo_nome ORDER BY data_inicio_abastecimento DESC) rn
           FROM sulista.ctaplus_abastecimentos) cta ON retorno.veiculo=cta.veiculo_nome AND cta.rn=1
WHERE retorno.ds_grupoproduto='MANUTENCAO PREVENTIVA' AND v.possuimotor=1 AND v.ativoinativo=1
  AND v.atividadeveiculo NOT IN ('ENC','ADM') AND retorno.frota<>'GERADOR'
"""

MPREV_CARRETA_SQL = f"""
SELECT retorno.frota, retorno.veiculo, retorno.dtultimatroca::date AS ult, c.descricao AS carroceria
FROM {_MPREV_FN} retorno
LEFT JOIN veiculo v ON retorno.veiculo=v.placa
LEFT JOIN carroceriaveiculo c ON v.carroceriaveiculo=c.codigo
WHERE retorno.ds_grupoproduto='MANUTENCAO PREVENTIVA' AND retorno.modeloveiculo LIKE '%SEMI REBOQUE%'
  AND v.modeloveiculo<>'GERAR' AND v.ativoinativo=1 AND v.atividadeveiculo<>'ENC'
"""


@cached(ttl=300)
def get_manutencao_preventiva() -> dict:
    """Revisões preventivas próximas/vencidas — trações por km, carretas por data."""
    hoje = date.today()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(MPREV_TRACAO_SQL)
        tra = cur.fetchall()
        cur.execute(MPREV_CARRETA_SQL)
        car = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    tracoes = []
    for t in tra:
        prox, odo, itv = t["prox"], t["odometro"], t["intervalo"]
        if prox is None or odo is None:
            continue
        falta = prox - odo
        if falta < 0:
            status = "vencida"
        elif itv and (falta / itv) < 0.1:
            status = "proxima"
        else:
            continue
        tracoes.append({"frota": t["frota"], "veiculo": t["veiculo"],
                        "km_faltante": falta, "intervalo": itv, "status": status})
    tracoes.sort(key=lambda x: x["km_faltante"])

    carretas = []
    for c in car:
        if not c["ult"]:
            continue
        limite = 240 if (c["carroceria"] or "") == "CARROCERIA BAU" else 180
        dias = (c["ult"] + _timedelta(days=limite) - hoje).days
        if dias < 0:
            status = "vencida"
        elif dias <= 30:
            status = "proxima"
        else:
            continue
        carretas.append({"frota": c["frota"], "veiculo": c["veiculo"], "dias": dias,
                         "status": status, "bau": (c["carroceria"] or "") == "CARROCERIA BAU"})
    carretas.sort(key=lambda x: x["dias"])

    kpis = {
        "tracoes_vencidas": sum(1 for t in tracoes if t["status"] == "vencida"),
        "tracoes_proximas": sum(1 for t in tracoes if t["status"] == "proxima"),
        "carretas_vencidas": sum(1 for c in carretas if c["status"] == "vencida"),
        "carretas_proximas": sum(1 for c in carretas if c["status"] == "proxima"),
    }
    kpis["total"] = len(tracoes) + len(carretas)
    kpis["vencidas"] = kpis["tracoes_vencidas"] + kpis["carretas_vencidas"]

    return {
        "kpis": kpis,
        "tracoes": tracoes,
        "carretas": carretas,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · fnc_manutencaopreventiva_gridview + ctaplus (odômetro) · "
                  "trações por km, carretas por data · leitura"),
    }


# ============================================================================
# Comunicação veículo × rastreadora — saúde da telemetria
# ----------------------------------------------------------------------------
# Compara a última posição (veiculo_posicao.ultimaposicao=1) com hoje, em
# faixas de atraso. Foco nos veículos COM rastreador que pararam de comunicar.
# Fonte: Querys Sulista/MANUTENCAO - Comunicação veic x rastreadora.
# ============================================================================
COMRAST_SQL = """
SELECT v.placa, v.numerofrota,
       CASE v.tipofrota WHEN 1 THEN 'Próprio' WHEN 2 THEN 'Terceiro' WHEN 3 THEN 'Agregado' ELSE '-' END AS tipofrota,
       vp.dt AS ultima, vp.situacao AS ignicao, vp.descricaoposicao AS posicao,
       (v.cnpjcpfcodigorastreador IS NOT NULL) AS tem_rastreador
FROM veiculo v
LEFT JOIN veiculo_posicao vp ON vp.veiculo = v.placa AND vp.ultimaposicao = 1
WHERE v.ativoinativo = 1
"""


def _comrast_faixa(dias) -> tuple[int, str]:
    if dias is None:
        return 99, "sem posição registrada"
    if dias <= 0:
        return 1, "comunicando hoje"
    if dias <= 2:
        return 2, "até 2 dias"
    if dias <= 5:
        return 3, "até 5 dias"
    if dias <= 15:
        return 4, "até 15 dias"
    if dias <= 30:
        return 6, "até 30 dias"
    if dias <= 60:
        return 7, "até 60 dias"
    return 8, "mais de 60 dias"


@cached(ttl=120)
def get_comunicacao_rastreadora() -> dict:
    """Saúde de comunicação da frota com a rastreadora (última posição)."""
    hoje = date.today()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(COMRAST_SQL)
        veic = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    faixas: dict[int, dict] = {}
    parados = []           # com rastreador, com posição, mas não comunicaram hoje
    com_rast = comunicando = sem_posicao = 0
    for v in veic:
        dias = (hoje - v["ultima"].date()).days if v["ultima"] else None
        cod, lbl = _comrast_faixa(dias)
        f = faixas.setdefault(cod, {"faixa": lbl, "codigo": cod, "n": 0})
        f["n"] += 1
        if v["tem_rastreador"]:
            com_rast += 1
        if cod == 1:
            comunicando += 1
        elif cod == 99:
            sem_posicao += 1
        elif v["tem_rastreador"]:      # tinha posição e parou
            parados.append({
                "placa": v["placa"], "frota": v["numerofrota"], "tipofrota": v["tipofrota"],
                "ultima": v["ultima"].isoformat() if v["ultima"] else None,
                "dias": dias, "faixa": lbl,
                "ignicao": {0: "desligada", 1: "ligada", 2: "?"}.get(v["ignicao"], "—"),
                "posicao": v["posicao"],
            })
    parados.sort(key=lambda x: -(x["dias"] or 0))

    return {
        "kpis": {
            "com_rastreador": com_rast,
            "comunicando_hoje": comunicando,
            "parados": len(parados),
            "sem_posicao": sem_posicao,
        },
        "faixas": [faixas[k] for k in sorted(faixas)],
        "parados": parados[:100],
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · veiculo_posicao (última posição) · frota ativa · leitura"),
    }


# ============================================================================
# Qualidade — Certidões & Licenças (semáforo de vencimento) + Auditoria Interna
# ----------------------------------------------------------------------------
# Fonte: Querys Sulista/QUALIDADE. Certidões/licenças/alvarás/apólices com
# semáforo por dias até vencer; auditorias internas com NCs.
# ============================================================================
QUAL_TIPO = {1: "Certidão", 2: "Licença", 3: "Alvará", 4: "Societário", 5: "Apólice de Seguro"}
QUAL_STATUS_ACAO = {1: "Não iniciado", 2: "Em andamento", 3: "Concluída", 4: "Cancelado"}

QUAL_CERT_SQL = """
SELECT ce.tipoarquivo, ce.filial,
       coalesce(nullif(trim(cad.razaosocial),''), ce.emissor) AS emissor,
       ce.dtemissao::date AS emissao, ce.dtvencimento::date AS venc,
       (ce.dtvencimento::date - current_date) AS dias,
       ce.observacao
FROM sulista.certidoes ce
LEFT JOIN cadastro cad ON avacorpi.fnc_formata_cnpjcpf(cad.codigo) = ce.emissor
WHERE ce.ativoinativo = 1
ORDER BY ce.dtvencimento NULLS LAST
"""

QUAL_AUD_SQL = """
SELECT ca.dt_auditoria::date AS dt, ca.area_setor, ca.processo_auditado,
       ca.tipo_auditoria, ca.resultado, ca.qtde_ncs, ca.qtde_observacoes,
       ca.principal_problema, ca.status_acao, ca.prazo_acao::date AS prazo,
       ca.dt_encerramento::date AS encerramento
FROM sulista.controle_auditoria ca
ORDER BY ca.id DESC
LIMIT 50
"""


def _qual_cert_status(dias) -> str:
    if dias is None:
        return "sem_data"
    if dias < 0:
        return "vencida"
    if dias <= 15:
        return "vence_15"
    if dias <= 30:
        return "vence_30"
    return "ok"


@cached(ttl=300)
def get_qualidade() -> dict:
    """Certidões/licenças com semáforo de vencimento + auditorias internas."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(QUAL_CERT_SQL)
        cert = cur.fetchall()
        cur.execute(QUAL_AUD_SQL)
        aud = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    certidoes = []
    for c in cert:
        st = _qual_cert_status(c["dias"])
        certidoes.append({
            "tipo": QUAL_TIPO.get(c["tipoarquivo"], "Documento"),
            "emissor": (c["emissor"] or "").strip() or "—",
            "filial": c["filial"],
            "emissao": c["emissao"].isoformat() if c["emissao"] else None,
            "venc": c["venc"].isoformat() if c["venc"] else None,
            "dias": c["dias"], "status": st,
            "obs": (c["observacao"] or "").strip() or None,
        })

    auditorias = [{
        "dt": a["dt"].isoformat() if a["dt"] else None,
        "area": (a["area_setor"] or "").strip() or "—",
        "processo": (a["processo_auditado"] or "").strip() or None,
        "tipo": {1: "Interna", 2: "Externa"}.get(a["tipo_auditoria"], "—"),
        "resultado": "Aprovado" if a["resultado"] == 1 else "Reprovado",
        "ncs": a["qtde_ncs"] or 0, "obs": a["qtde_observacoes"] or 0,
        "problema": (a["principal_problema"] or "").strip() or None,
        "status_acao": QUAL_STATUS_ACAO.get(a["status_acao"]),
        "prazo": a["prazo"].isoformat() if a["prazo"] else None,
        "encerrada": a["encerramento"].isoformat() if a["encerramento"] else None,
    } for a in aud]

    kpis = {
        "certidoes": len(certidoes),
        "vencidas": sum(1 for c in certidoes if c["status"] == "vencida"),
        "vencendo": sum(1 for c in certidoes if c["status"] in ("vence_15", "vence_30")),
        "auditorias": len(auditorias),
        "ncs_abertas": sum(a["ncs"] for a in auditorias if a["status_acao"] not in ("Concluída", "Cancelado")),
    }

    return {
        "kpis": kpis,
        "certidoes": certidoes,
        "auditorias": auditorias,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": "ERP AVA · sulista.certidoes + sulista.controle_auditoria · leitura",
    }
