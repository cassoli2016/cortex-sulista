# -*- coding: utf-8 -*-
"""Tela de Gerenciamento de Risco (`gr`) — Fase 1: o que o ERP já recebe.

MEDIDO EM 01/09/2026 antes de desenhar:
- `ocorrenciarastreamento` viva ao minuto (1,0 mi de linhas; ~60,8 mil
  eventos/90d), com macro em TEXTO no `parametrorecebimento` — o catálogo
  `ocorrencia_rastreadora` não cobre tudo, e código sem tabela de domínio
  não vira rótulo inventado: o texto do próprio hub é a fonte.
- Cobertura de GR nas viagens: 771 de 776 nos últimos 7 dias (99,4%) — o
  que interessa é a EXCEÇÃO, e ela é listada nominalmente.
- `rastreadora_retorno`: Raster + OnixSat + Tecnologia 3S entregando a
  cada minuto. O frescor por fonte é o alarme "não está chegando AGORA" —
  nunca contagem de tropeços.
- As tabelas são GRANDES e o AVA é 9.3 com statement_timeout de 60s:
  janela estreita + coluna indexada (dtinc/dtsaida), nunca LIKE no XML.

O vínculo viagem×GR usa EXISTS, não JOIN: a tabela de vínculo tem
`sequencia` (pode haver mais de uma linha por viagem) e o join inflaria a
contagem — a lição do join com vigência.
"""
from __future__ import annotations

from api import db
from api.queries import cached

EVENTOS_MACRO_SQL = """
SELECT coalesce(nullif(trim(o.parametrorecebimento), ''),
                '(macro '||coalesce(o.ocorrenciarastreadora::text, '?')||')') AS macro,
       sum(CASE WHEN o.dtinc >= current_timestamp - interval '24 hours'
                THEN 1 ELSE 0 END)::int AS n_24h,
       count(*)::int AS n_7d
FROM ocorrenciarastreamento o
WHERE o.dtinc >= current_timestamp - interval '7 days' AND o.sentido = 2
GROUP BY 1 ORDER BY 2 DESC, 3 DESC LIMIT 20
"""

EVENTOS_ULTIMOS_SQL = """
SELECT o.veiculo AS placa,
       coalesce(nullif(trim(o.parametrorecebimento), ''),
                '(macro '||coalesce(o.ocorrenciarastreadora::text, '?')||')') AS macro,
       to_char(o.dtrecebimento, 'YYYY-MM-DD HH24:MI') AS quando,
       coalesce(nullif(trim(o.cidadeposicaoveiculo), ''), '?') AS cidade,
       coalesce(o.ufposicaoveiculo, '') AS uf,
       o.velocidade::float8 AS velocidade,
       coalesce(nullif(trim(o.observacao), ''), '') AS obs
FROM ocorrenciarastreamento o
WHERE o.dtinc >= current_timestamp - interval '24 hours' AND o.sentido = 2
ORDER BY o.dtrecebimento DESC LIMIT 60
"""

COBERTURA_SQL = """
SELECT coalesce(u.descricao, '(sem cadastro)') AS modalidade,
       count(*)::int AS viagens,
       sum(CASE WHEN EXISTS (
             SELECT 1 FROM programacaoembarque_gerenciadorarisco gr
             WHERE gr.grupo = p.grupo AND gr.empresa = p.empresa
               AND gr.diferenciadornumero = p.diferenciadornumero
               AND gr.numero = p.numero)
           THEN 1 ELSE 0 END)::int AS com_gr
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND p.dtsaida >= current_date - 30
GROUP BY 1 ORDER BY 2 DESC
"""

SEM_GR_SQL = """
SELECT p.veiculo AS placa,
       to_char(p.dtsaida, 'YYYY-MM-DD HH24:MI') AS saida,
       upper(trim(coalesce(p.cidadeorigem,'?')))||'/'||coalesce(p.uforigem,'?') AS origem,
       upper(trim(coalesce(p.cidadedestino,'?')))||'/'||coalesce(p.ufdestino,'?') AS destino,
       coalesce(u.descricao, '(sem cadastro)') AS modalidade,
       coalesce(p.valorfrete, 0)::float8 AS frete
FROM programacaoembarque p
LEFT JOIN veiculo v ON v.placa = p.veiculo
LEFT JOIN utilizacaoveiculo u ON u.codigo = v.utilizacaoveiculo
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.tipo <> 3
  AND p.dtsaida >= current_date - 30
  AND NOT EXISTS (
        SELECT 1 FROM programacaoembarque_gerenciadorarisco gr
        WHERE gr.grupo = p.grupo AND gr.empresa = p.empresa
          AND gr.diferenciadornumero = p.diferenciadornumero
          AND gr.numero = p.numero)
ORDER BY p.dtsaida DESC LIMIT 40
"""

FLUXO_SQL = """
SELECT coalesce(nullif(trim(ra.descricao), ''), 'fonte '||r.idrastreadora) AS fonte,
       count(*)::int AS n_6h,
       sum(CASE WHEN r.dtinc >= current_timestamp - interval '1 hour'
                THEN 1 ELSE 0 END)::int AS n_1h,
       to_char(max(r.dtinc), 'YYYY-MM-DD HH24:MI') AS ultima,
       (extract(epoch from (current_timestamp - max(r.dtinc))) / 60.0)::float8
         AS minutos_atras
FROM rastreadora_retorno r
LEFT JOIN rastreadora ra ON ra.id = r.idrastreadora
WHERE r.dtinc >= current_timestamp - interval '6 hours'
GROUP BY 1, r.idrastreadora ORDER BY 2 DESC
"""

# fonte que entrega a cada minuto e some por mais de 60 min NÃO está chegando
# AGORA — cadências diferentes teriam limiares separados; hoje as três
# entregam no mesmo ritmo (medido: máx 2 min entre retornos)
LIMIAR_MUDO_MIN = 60.0


@cached(ttl=120)
def get_gr() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(EVENTOS_MACRO_SQL)
        macros = [dict(r) for r in cur.fetchall()]
        cur.execute(EVENTOS_ULTIMOS_SQL)
        ultimos = [dict(r) for r in cur.fetchall()]
        cur.execute(COBERTURA_SQL)
        cobertura = [dict(r) for r in cur.fetchall()]
        cur.execute(SEM_GR_SQL)
        sem_gr = [dict(r) for r in cur.fetchall()]
        cur.execute(FLUXO_SQL)
        fontes = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    for f in fontes:
        f["mudo"] = (f["minutos_atras"] or 0) > LIMIAR_MUDO_MIN
    tot_v = sum(c["viagens"] for c in cobertura)
    tot_gr = sum(c["com_gr"] for c in cobertura)
    return {
        "macros": macros,
        "ultimos": ultimos,
        "cobertura": {"modalidades": cobertura, "viagens": tot_v,
                      "com_gr": tot_gr, "sem_gr_n": tot_v - tot_gr,
                      "janela": "últimos 30 dias"},
        "sem_gr": sem_gr,
        "fluxo": {"fontes": fontes,
                  "alarme": any(f["mudo"] for f in fontes),
                  "janela": "últimas 6 horas"},
        "eventos_24h": sum(m["n_24h"] for m in macros),
        "eventos_7d": sum(m["n_7d"] for m in macros),
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · ocorrenciarastreamento (eventos do hub Raster/"
                  "OnixSat/3S) + programacaoembarque_gerenciadorarisco "
                  "(vínculo viagem×GR) + rastreadora_retorno (frescor por "
                  "fonte) · leitura"),
    }
