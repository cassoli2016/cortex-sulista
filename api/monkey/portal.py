# -*- coding: utf-8 -*-
"""Tela "Portal Tupy" (`tupy`) — a validação do que a Monkey entrega.

Lê o ESPELHO local (mky_recebiveis), nunca a API: a tela abre em
milissegundos e não cai junto com o fornecedor. O espelho é a varredura
completa do convênio (48,6 mil títulos desde jun/2024 na primeira carga) e
o frescor vem de mky_carga — dado velho é DITO, não disfarçado.

TRÊS DECISÕES DE LEITURA:
- A janela mensal é ancorada no ÚLTIMO VENCIMENTO do espelho, nunca em
  current_date, e os meses são GERADOS — mês sem título aparece vazio em
  vez de emendar abril em agosto.
- Deságio e percentuais saem da unidade de ORIGEM (somas primeiro, razão
  depois) — arredondar antes de dividir move o número de lado.
- `purchased_tax`/`fee_*` são mostrados COMO O PORTAL PUBLICA, com o nome
  do fornecedor no ⓘ: a semântica exata (a.m.? a.a.?) ainda não veio da
  Monkey, e taxa com rótulo inventado é pior que taxa com rótulo cru.
"""
from __future__ import annotations

from api import pglocal
from api.queries import cached

# O teste redireciona isto para um schema próprio (fixture `esquema_pg`).
ESQUEMA: str | None = None

# fora da posição = já saiu do portal (mesma régua do api/monkey/normaliza)
_FORA = "('SOLD', 'PAID', 'REFUSED', 'CANCELLED')"

KPIS_SQL = f"""
SELECT count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor_total,
       sum(CASE WHEN status = 'SOLD' THEN 1 ELSE 0 END)::int AS vendidos,
       coalesce(sum(CASE WHEN status = 'SOLD' THEN payment_value END), 0)::float8
         AS valor_vendido,
       coalesce(sum(CASE WHEN status = 'SOLD'
                         THEN payment_value - coalesce(receipt_value,
                                                       payment_value) END),
                0)::float8 AS desagio_vendido,
       coalesce(sum(payment_value - coalesce(receipt_value, payment_value)),
                0)::float8 AS desagio_total,
       sum(CASE WHEN buyer_cnpj IS NOT NULL THEN 1 ELSE 0 END)::int
         AS com_investidor,
       sum(CASE WHEN status = 'PAID' THEN 1 ELSE 0 END)::int AS liquidados,
       coalesce(sum(CASE WHEN status = 'PAID' THEN payment_value END), 0)::float8
         AS valor_liquidado,
       sum(CASE WHEN status NOT IN {_FORA} THEN 1 ELSE 0 END)::int AS abertos,
       coalesce(sum(CASE WHEN status NOT IN {_FORA} THEN payment_value END),
                0)::float8 AS valor_aberto,
       to_char(min(CASE WHEN invoice_date >= DATE '2000-01-01'
                        THEN invoice_date END), 'YYYY-MM-DD') AS primeira_nf,
       to_char(max(payment_date), 'YYYY-MM-DD') AS ultimo_venc
FROM mky_recebiveis
"""

MENSAL_SQL = """
WITH ancora AS (
  SELECT date_trunc('month', max(payment_date))::date AS fim
  FROM mky_recebiveis WHERE payment_date IS NOT NULL
),
meses AS (
  SELECT generate_series((SELECT fim FROM ancora) - interval '12 months',
                         (SELECT fim FROM ancora),
                         interval '1 month')::date AS mes
)
SELECT to_char(m.mes, 'YYYY-MM') AS mes,
       count(r.external_id)::int AS titulos,
       coalesce(sum(r.payment_value), 0)::float8 AS valor,
       coalesce(sum(CASE WHEN r.status = 'SOLD' THEN r.payment_value END),
                0)::float8 AS vendido,
       coalesce(sum(CASE WHEN r.status = 'SOLD'
                         THEN r.payment_value - coalesce(r.receipt_value,
                                                         r.payment_value) END),
                0)::float8 AS desagio,
       coalesce(sum(CASE WHEN r.status = 'PAID' THEN r.payment_value END),
                0)::float8 AS liquidado,
       avg(CASE WHEN r.status = 'SOLD' THEN r.purchased_tax END)::float8
         AS taxa_media
FROM meses m
LEFT JOIN mky_recebiveis r
       ON date_trunc('month', r.payment_date)::date = m.mes
GROUP BY m.mes ORDER BY m.mes
"""

# GROUP BY seller_id, nunca pelo nome: as 5 filiais da Sulista têm a MESMA
# razão social no portal (medido: agrupar por nome colapsava tudo numa linha)
SELLERS_SQL = """
SELECT seller_id,
       max(seller_cnpj) AS cnpj,
       max(seller_nome) AS seller,
       count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       sum(CASE WHEN status = 'SOLD' THEN 1 ELSE 0 END)::int AS vendidos,
       coalesce(sum(CASE WHEN status = 'SOLD' THEN payment_value END),
                0)::float8 AS valor_vendido,
       avg(CASE WHEN status = 'SOLD' THEN purchased_tax END)::float8
         AS taxa_media
FROM mky_recebiveis
GROUP BY 1 ORDER BY 5 DESC
"""

STATUS_SQL = """
SELECT status, count(*)::int AS n,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       to_char(min(payment_date), 'YYYY-MM-DD') AS venc_min,
       to_char(max(payment_date), 'YYYY-MM-DD') AS venc_max
FROM mky_recebiveis GROUP BY 1 ORDER BY 2 DESC
"""

INVESTIDORES_SQL = """
SELECT coalesce(buyer_nome, buyer_cnpj, '(sem comprador)') AS investidor,
       count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       avg(purchased_tax)::float8 AS taxa_media
FROM mky_recebiveis WHERE status IN ('SOLD', 'PAID')
GROUP BY 1 ORDER BY 3 DESC LIMIT 12
"""

# a VALIDAÇÃO propriamente: as perguntas que dizem se o dado merece confiança
QUALIDADE_SQL = f"""
SELECT count(*)::int AS total,
       sum(CASE WHEN coalesce(invoice_key, '') = '' THEN 1 ELSE 0 END)::int
         AS sem_chave_nfe,
       sum(CASE WHEN receipt_value > payment_value THEN 1 ELSE 0 END)::int
         AS recebe_mais_que_nominal,
       sum(CASE WHEN payment_date < invoice_date THEN 1 ELSE 0 END)::int
         AS vence_antes_de_emitir,
       sum(CASE WHEN coalesce(total_installment, 1) > 1 THEN 1 ELSE 0 END)::int
         AS parcelados,
       sum(CASE WHEN invoice_date < DATE '2000-01-01' THEN 1 ELSE 0 END)::int
         AS emissao_zerada,
       sum(CASE WHEN real_payment_date IS NOT NULL THEN 1 ELSE 0 END)::int
         AS com_data_real,
       sum(CASE WHEN effective_payment_date IS NOT NULL THEN 1 ELSE 0 END)::int
         AS com_data_efetiva,
       avg(CASE WHEN status = 'PAID' AND effective_payment_date IS NOT NULL
                THEN (effective_payment_date - payment_date) END)::float8
         AS atraso_medio_liq_dias,
       count(DISTINCT asset_type)::int AS tipos_de_ativo,
       count(DISTINCT sponsor_cnpj)::int AS sacados_distintos,
       to_char(max(alterado_fornecedor), 'YYYY-MM-DD HH24:MI') AS ultima_alteracao
FROM mky_recebiveis
"""

CARGA_SQL = """
SELECT to_char(terminado_em, 'YYYY-MM-DD HH24:MI') AS quando,
       recebidos, gravados, sem_chave, erro
FROM mky_carga ORDER BY id DESC LIMIT 1
"""

TITULOS_SQL = """
SELECT external_id, invoice_number, installment, total_installment,
       status, asset_type,
       to_char(invoice_date, 'YYYY-MM-DD') AS emissao,
       to_char(payment_date, 'YYYY-MM-DD') AS vencimento,
       to_char(effective_payment_date, 'YYYY-MM-DD') AS pago_em,
       payment_value, receipt_value, purchased_tax, fee_amount,
       coalesce(seller_nome, seller_cnpj) AS seller,
       coalesce(buyer_nome, '') AS investidor
FROM mky_recebiveis
WHERE (%(q)s = '' OR invoice_number ILIKE %(q_like)s
       OR external_id ILIKE %(q_like)s)
ORDER BY payment_date DESC NULLS LAST, external_id DESC
LIMIT 80
"""


def _posicao_painel() -> dict:
    """O que o painel de Antecipações tem gravado para a Tupy — a
    conferência de dois caminhos para o mesmo número."""
    try:
        from api.antecipacoes import registro
        ultimo = registro.ultimo_envio("tupy") or {}
        return {"titulos": int(ultimo.get("titulos") or 0),
                "valor_saldo": float(ultimo.get("valor_saldo") or 0.0),
                "quando": ultimo.get("ts") or None,
                "origem": ultimo.get("origem") or None}
    except Exception:  # noqa: BLE001 — painel indisponível não derruba a tela
        return {}


@cached(ttl=120)
def get_portal_tupy(q: str = "") -> dict:
    return montar(q)


def montar(q: str = "", esquema: str | None = None) -> dict:
    q = (q or "").strip()[:60]
    params = {"q": q, "q_like": f"%{q}%"}
    try:
        with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
            cur.execute(KPIS_SQL)
            kpis = dict(cur.fetchone() or {})
            if not kpis.get("titulos"):
                return {"disponivel": False,
                        "motivo": "espelho vazio — a coleta ainda não rodou "
                                  "(scripts/coletar_monkey.py)"}
            cur.execute(MENSAL_SQL)
            mensal = [dict(r) for r in cur.fetchall()]
            cur.execute(SELLERS_SQL)
            sellers = [dict(r) for r in cur.fetchall()]
            cur.execute(STATUS_SQL)
            por_status = [dict(r) for r in cur.fetchall()]
            cur.execute(INVESTIDORES_SQL)
            investidores = [dict(r) for r in cur.fetchall()]
            cur.execute(QUALIDADE_SQL)
            qualidade = dict(cur.fetchone() or {})
            cur.execute(CARGA_SQL)
            carga_row = cur.fetchone()
            carga = dict(carga_row) if carga_row else {}
            cur.execute(TITULOS_SQL, params)
            titulos = [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"disponivel": False, "motivo": "migration 0036 pendente"}
        raise

    # deságio percentual calculado das SOMAS (unidade de origem). MEDIDO em
    # 01/09/2026: 100% dos títulos (SOLD e PAID) têm deságio, taxa e
    # investidor — TODO título deste convênio passa pelo leilão; PAID é
    # "antecipado e já liquidado", nunca "liquidado sem antecipar". Por isso
    # o "antecipado histórico" é o TOTAL, e o corte por status diz só em que
    # fase do ciclo cada um está.
    vt = kpis.get("valor_total") or 0.0
    kpis["desagio_pct"] = (100.0 * (kpis.get("desagio_total") or 0.0) / vt
                           if vt else None)
    return {
        "disponivel": True,
        "kpis": kpis,
        "mensal": mensal,
        "sellers": sellers,
        "por_status": por_status,
        "investidores": investidores,
        "qualidade": qualidade,
        "carga": carga,
        "titulos": titulos,
        "busca": q,
        "conferencia": {
            "espelho_abertos": kpis.get("abertos") or 0,
            "espelho_valor_aberto": kpis.get("valor_aberto") or 0.0,
            "painel": _posicao_painel(),
        },
        "fonte": ("Monkey Exchange · espelho local mky_recebiveis (varredura "
                  "completa por seller, 2×/dia) + ant_envios (posição do "
                  "painel) · leitura"),
    }
