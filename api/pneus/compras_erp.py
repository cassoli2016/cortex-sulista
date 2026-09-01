# -*- coding: utf-8 -*-
"""O histórico de COMPRA de pneus — que está no ERP, não na Prolog.

A Prolog não tem data de compra (recap_data vazia em 8.572/8.572 pneus).
Mas o ERP tem a série inteira: `notafiscalentrada_item × produto` distingue
PNEU NOVO × RECAPAGEM × PNEU USADO × VULCANIZAÇÃO, com quantidade e R$,
mês a mês. É o mesmo padrão da lição do pedágio: a fonte já estava no banco.

MEDIDO (01/09/2026, query de 25 meses em 1,1 s):
- últimos 12m: 458 pneus novos (R$ 783 mil) · 1.174 recapagens (R$ 699 mil,
  ~R$ 579/un — bate com a mediana R$ 560 do recap_custo da Prolog) ·
  204 usados (R$ 242 mil);
- NOVOS compram-se em LOTE (abr/25: 210 · out/25: 184 · nov/25–jan/26: ZERO
  — a frota viveu do lote); RECAPAGEM é fluxo estável (58–147/mês);
- `descricaoproduto` do item é NULL em 100% — o join com `produto` é
  OBRIGATÓRIO, não enfeite.

O AVA é PG 9.3 (CASE WHEN, sem FILTER) e a falha daqui NUNCA derruba a tela
de pneus: ela abre sem banco nenhum (lê o snapshot da Prolog em arquivo) e o
bloco de compras degrada com `erro` dito no payload.
"""
from __future__ import annotations

import logging
import time
from datetime import date

from api import db

log = logging.getLogger("cortex.pneus.compras")

# Classificação por texto do PRODUTO (o domínio real do cadastro; a evidência
# é a própria descrição — ex.: "PNEU 295/80R22,5 LISO - NOVO", "RECAPAGEM
# PNEU 275/80R22,5"). "novo" exige a descrição COMEÇANDO com PNEU: sem isso,
# "SERVICO DE DESMONTAGEM E MONTAGEM DE PNEU" (196 un/90d a R$ 56) entrava
# como compra de pneu e o ritmo saía 4x o real — medido na primeira prova.
COMPRAS_SQL = """
SELECT to_char(i.dtemissao, 'YYYY-MM') AS mes,
       CASE
         WHEN upper(p.descricao) LIKE '%%RECAP%%'  THEN 'recapagem'
         WHEN upper(p.descricao) LIKE '%%VULCAN%%'
           OR upper(p.descricao) LIKE '%%CONSERTO%%' THEN 'vulcanizacao'
         WHEN upper(p.descricao) LIKE '%%USADO%%'  THEN 'usado'
         WHEN upper(p.descricao) LIKE '%%SERVICO%%'
           OR upper(p.descricao) LIKE '%%MONTAGEM%%'
           OR upper(p.descricao) LIKE '%%RODIZIO%%' THEN 'servico'
         WHEN upper(p.descricao) LIKE 'PNEU %%'     THEN 'novo'
         ELSE 'outros'
       END AS tipo,
       sum(coalesce(i.quantidade, 0))::float8 AS qt,
       sum(coalesce(i.valortotal, 0))::float8 AS valor
FROM notafiscalentrada_item i
JOIN produto p ON p.codigo = i.produto
WHERE (upper(p.descricao) LIKE '%%PNEU%%'
   OR upper(p.descricao) LIKE '%%RECAPAGEM%%'
   OR upper(p.descricao) LIKE '%%VULCANIZA%%')
  AND i.dtemissao IS NOT NULL
GROUP BY 1, 2
"""

# Preço unitário vigente por item (últimos 90 dias): o número que a compra
# usa como referência de negociação.
PRECOS_SQL = """
SELECT trim(p.descricao) AS item,
       sum(coalesce(i.quantidade, 0))::float8 AS qt,
       (sum(coalesce(i.valortotal, 0)) / nullif(sum(coalesce(i.quantidade, 0)), 0))::float8 AS unit
FROM notafiscalentrada_item i
JOIN produto p ON p.codigo = i.produto
WHERE upper(p.descricao) LIKE '%%PNEU%%'
  AND upper(p.descricao) NOT LIKE '%%SERVICO%%'
  AND upper(p.descricao) NOT LIKE '%%MONTAGEM%%'
  AND upper(p.descricao) NOT LIKE '%%CONSERTO%%'
  AND i.dtemissao >= current_date - 90
GROUP BY 1
HAVING sum(coalesce(i.quantidade, 0)) >= 2
ORDER BY 2 DESC
LIMIT 10
"""

# cache TTL em memória (padrão _custos_rows da casa): a série muda uma vez
# por dia, e a tela não pode pagar a consulta do AVA a cada F5
_CACHE: dict = {}
_TTL = 3600.0


def _serie_meses(n: int, hoje: date) -> list[str]:
    """Eixo GERADO (GROUP BY não devolve mês sem compra — e 'nov/25–jan/26
    zero' é exatamente a informação que não pode sumir do gráfico)."""
    out, a, m = [], hoje.year, hoje.month
    for _ in range(n):
        out.append(f"{a}-{m:02d}")
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return list(reversed(out))


def compras(force: bool = False) -> dict:
    """Série mensal de compras + preços vigentes. Nunca levanta: falha do
    AVA vira `{"erro": ...}` com o resto da tela vivo."""
    agora = time.time()
    hit = _CACHE.get("compras")
    if hit and not force and agora - hit[0] < _TTL:
        return hit[1]
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(COMPRAS_SQL)
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(PRECOS_SQL)
            precos = [{"item": r["item"], "qt": float(r["qt"] or 0),
                       "unit": float(r["unit"] or 0)} for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        log.warning("compras de pneus indisponiveis: %s", type(exc).__name__)
        out = {"serie": [], "precos": [], "ritmo_12m": None,
               "erro": ("O ERP não respondeu — o histórico de compras fica "
                        "indisponível; o restante da tela segue valendo.")}
        return out

    eixo = _serie_meses(24, date.today())
    por_mes: dict[str, dict] = {m: {"mes": m, "novos_qt": 0.0, "novos_vl": 0.0,
                                    "recap_qt": 0.0, "recap_vl": 0.0,
                                    "usados_qt": 0.0, "usados_vl": 0.0}
                                for m in eixo}
    for r in rows:
        m0 = por_mes.get(r["mes"])
        if not m0:
            continue
        t = r["tipo"]
        if t == "novo":
            m0["novos_qt"] += float(r["qt"] or 0)
            m0["novos_vl"] += float(r["valor"] or 0)
        elif t == "recapagem":
            m0["recap_qt"] += float(r["qt"] or 0)
            m0["recap_vl"] += float(r["valor"] or 0)
        elif t == "usado":
            m0["usados_qt"] += float(r["qt"] or 0)
            m0["usados_vl"] += float(r["valor"] or 0)
    serie = [por_mes[m] for m in eixo]

    ult12 = serie[-12:]
    ritmo = {"novos_mes": sum(r["novos_qt"] for r in ult12) / 12.0,
             "recap_mes": sum(r["recap_qt"] for r in ult12) / 12.0,
             "usados_mes": sum(r["usados_qt"] for r in ult12) / 12.0,
             "total_12m_vl": sum(r["novos_vl"] + r["recap_vl"] + r["usados_vl"]
                                 for r in ult12)}
    out = {"serie": serie, "precos": precos, "ritmo_12m": ritmo, "erro": None}
    _CACHE["compras"] = (agora, out)
    return out
