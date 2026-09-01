# -*- coding: utf-8 -*-
"""Ciclos da programação: quanto tempo CADA COISA leva, medido do histórico.

A tela de programação casava chegada×saída por cidade e data sem saber
quanto tempo nada leva. Este módulo mede os três componentes do ciclo nos
últimos 6 meses e responde "quando o veículo LIBERA":

    carregamento  = evento SAC 394→395, por cidade de ORIGEM   (~53%)
    deslocamento  = programacaoembarque dtsaida→dtchegada       (99,5%)
    descarga      = evento SAC 396→397, por DESTINATÁRIO        (51,7%)

SEM DUPLA CONTAGEM, e isso foi provado antes de somar: dtchegada coincide
com o evento 396 (chegada para descarga) com mediana de +0,02h — 49% dos
pares dentro de ±15 min. O deslocamento porta a porta INCLUI fila e
pernoite (Joinville→Curitiba: 12h medianas para 128 km) — não é defeito,
é o tempo que o veículo fica preso, que é o que decide alocação; o ⓘ diz.

TRÊS FONTES DE TEMPO convivem no CÓRTEX e NUNCA se fundem num número só:
o ETA do ERP (o que o programador digitou — erra >2h em metade dos casos,
medido), o ETA da TomTom (trânsito de agora, só viagem ativa, tela Torre)
e o histórico próprio (mediana 6m, este módulo). Cada um rotulado.

O TIMEOUT DE 60s DO AVA desenhou este módulo: a agregação de
coleta_ocorrencia com join estourou o statement_timeout DUAS vezes na
medição (com join e com parâmetro no lugar do literal). O que cabe é
single-table + casamento em Python + cache de 1h em endpoint SEPARADO do
radar de 120s — não é otimização, é o que cabe.
"""
from __future__ import annotations

import statistics
from datetime import datetime

from . import db
from .queries import cached

# Régua física (mesma família do _CTA_KM_SANO): fora dela vira n/d, contado.
# 2,3% das descargas >24h são min(396)→max(397) atravessando dias — artefato
# de pareamento já documentado no SAC, não descarga real.
CAP_CARGA_H = 24.0
CAP_DESCARGA_H = 24.0
CAP_TRANSITO_H = 96.0
# Rota/destino com menos de 10 amostras mostra n/d, nunca número.
N_MIN = 10

# Chave = as 6 colunas do documento de origem, como texto. Os códigos de
# ocorrência vão como LITERAIS de propósito (parametrizado estourou o
# timeout do 9.3 na medição).
CICLOS_VIAGENS_SQL = """
SELECT grupo||'|'||empresa||'|'||filialdocumentoorigem||'|'||unidadedocumentoorigem
       ||'|'||diferenciadornumerodocumentoorigem||'|'||numerodocumentoorigem AS k,
       upper(trim(cidadeorigem))||'/'||coalesce(uforigem,'?')  AS ori,
       upper(trim(cidadedestino))||'/'||coalesce(ufdestino,'?') AS dst,
       to_char(dtsaida,'YYYY-MM-DD HH24:MI:SS')   AS dtsaida,
       to_char(dtchegada,'YYYY-MM-DD HH24:MI:SS') AS dtchegada,
       coalesce(kmfretecompra,0)::float8 AS km
FROM programacaoembarque
WHERE dtcancelamento IS NULL AND semaforo = 1 AND tipo <> 3
  AND dtsaida >= current_date - 180 AND dtchegada IS NOT NULL
  AND nullif(trim(cidadeorigem),'') IS NOT NULL
  AND nullif(trim(cidadedestino),'') IS NOT NULL
"""

CICLOS_EVENTOS_SQL = """
SELECT grupo||'|'||empresa||'|'||filial||'|'||unidade
       ||'|'||diferenciadornumero||'|'||numero AS k,
       to_char(min(CASE WHEN ocorrencia=394 THEN dtocorrencia END),'YYYY-MM-DD HH24:MI:SS') AS cc,
       to_char(max(CASE WHEN ocorrencia=395 THEN dtocorrencia END),'YYYY-MM-DD HH24:MI:SS') AS sc,
       to_char(min(CASE WHEN ocorrencia=396 THEN dtocorrencia END),'YYYY-MM-DD HH24:MI:SS') AS cd,
       to_char(max(CASE WHEN ocorrencia=397 THEN dtocorrencia END),'YYYY-MM-DD HH24:MI:SS') AS fd
FROM coleta_ocorrencia
WHERE ocorrencia IN (394,395,396,397) AND dtocorrencia >= current_date - 200
GROUP BY 1
"""

CICLOS_DESTINATARIO_SQL = """
SELECT co.grupo||'|'||co.empresa||'|'||co.filial||'|'||co.unidade
       ||'|'||co.diferenciadornumero||'|'||co.numero AS k,
       coalesce(nullif(trim(cd.nomefantasia),''), nullif(trim(cd.razaosocial),''),'(sem)') AS destinatario
FROM coleta co
LEFT JOIN cadastro cd ON cd.codigo = co.destinatario
WHERE co.dtinc >= current_date - 210
"""

# Freetime contratado por cliente — tabela de VIGÊNCIA: DISTINCT ON, nunca
# join direto (regra da casa; padrão do SAC_FT em api/queries.py).
CICLOS_FREETIME_SQL = """
SELECT DISTINCT ON (upper(trim(coalesce(nullif(trim(cd.nomefantasia),''), cd.razaosocial))))
       upper(trim(coalesce(nullif(trim(cd.nomefantasia),''), cd.razaosocial))) AS cliente,
       f.horasfreetime::float8 AS freetime_h
FROM sulista.sac_freetimecliente f
JOIN cadastro cd ON cd.codigo = f.cliente
ORDER BY 1, f.dtvigencia DESC NULLS LAST
"""


def _dt(txt: str | None) -> datetime | None:
    if not txt:
        return None
    try:
        return datetime.strptime(txt[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _horas(a: datetime | None, b: datetime | None, cap: float) -> float | None:
    """b − a em horas, None fora da régua física (negativo ou acima do cap)."""
    if not a or not b:
        return None
    h = (b - a).total_seconds() / 3600.0
    return h if 0 <= h <= cap else None


def _p90(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(0.9 * len(s)))]


def _med(vals: list[float]) -> float | None:
    return statistics.median(vals) if vals else None


def montar_ciclos(viagens: list[dict], eventos: dict[str, dict],
                  destinatarios: dict[str, str],
                  freetimes: dict[str, float] | None = None) -> dict:
    """Compositor puro — testável sem banco.

    `viagens` = linhas de CICLOS_VIAGENS_SQL; `eventos` = k → linha de
    CICLOS_EVENTOS_SQL; `destinatarios` = k → nome.
    """
    rotas: dict[tuple[str, str], dict] = {}
    carreg_por_ori: dict[str, list[float]] = {}
    desc_por_dest: dict[str, list[float]] = {}
    desc_por_cid: dict[str, list[float]] = {}
    desc_todas: list[float] = []
    fora_regua = 0

    for v in viagens:
        ori, dst = v["ori"], v["dst"]
        saida, cheg = _dt(v["dtsaida"]), _dt(v["dtchegada"])
        desloc = _horas(saida, cheg, CAP_TRANSITO_H)
        if desloc is None and saida and cheg:
            fora_regua += 1
        r = rotas.setdefault((ori, dst), {"desloc": [], "km": [], "n": 0})
        r["n"] += 1
        if desloc is not None:
            r["desloc"].append(desloc)
        if v.get("km"):
            r["km"].append(float(v["km"]))

        ev = eventos.get(v["k"])
        if ev:
            carga = _horas(_dt(ev.get("cc")), _dt(ev.get("sc")), CAP_CARGA_H)
            if carga is not None:
                carreg_por_ori.setdefault(ori, []).append(carga)
            desc = _horas(_dt(ev.get("cd")), _dt(ev.get("fd")), CAP_DESCARGA_H)
            if desc is not None:
                desc_todas.append(desc)
                desc_por_cid.setdefault(dst, []).append(desc)
                nome = destinatarios.get(v["k"])
                if nome and nome != "(sem)":
                    desc_por_dest.setdefault(f"{nome} — {dst}", []).append(desc)

    descarga_global = _med(desc_todas)

    def _descarga(dst: str, destinatario: str | None) -> tuple[float | None, str, int]:
        """destinatário (n≥10) → cidade (n≥10) → global, SEMPRE com a fonte —
        número que muda de fonte sem avisar é número em que ninguém confia."""
        if destinatario:
            vs = desc_por_dest.get(destinatario) or []
            if len(vs) >= N_MIN:
                return _med(vs), "destinatario", len(vs)
        vs = desc_por_cid.get(dst) or []
        if len(vs) >= N_MIN:
            return _med(vs), "cidade", len(vs)
        return descarga_global, "global", len(desc_todas)

    saida_rotas = []
    total_viagens = sum(r["n"] for r in rotas.values())
    cobertas = 0
    for (ori, dst), r in sorted(rotas.items(), key=lambda x: -x[1]["n"]):
        if r["n"] < N_MIN:
            continue
        cobertas += r["n"]
        carreg = carreg_por_ori.get(ori) or []
        dmed, dfonte, dn = _descarga(dst, None)
        desloc_med = _med(r["desloc"])
        carreg_med = _med(carreg) if len(carreg) >= N_MIN else None
        ciclo = (sum(x for x in (carreg_med, desloc_med, dmed) if x is not None)
                 if desloc_med is not None else None)
        saida_rotas.append({
            "ori": ori, "dst": dst, "n": r["n"],
            "desloc_med_h": desloc_med, "desloc_p90_h": _p90(r["desloc"]),
            "km_med": _med(r["km"]),
            "carreg_med_h": carreg_med,
            "carreg_n": len(carreg),
            "descarga_med_h": dmed, "descarga_p90_h": _p90(
                desc_por_cid.get(dst) or []),
            "descarga_fonte": dfonte, "descarga_n": dn,
            # p90 NÃO soma (p90+p90 ≠ p90 da soma): só a mediana compõe o
            # ciclo; o p90 fica por componente
            "ciclo_med_h": ciclo,
        })

    lentos = []
    for nome, vs in desc_por_dest.items():
        if len(vs) < N_MIN:
            continue
        med = _med(vs)
        if descarga_global and (med > 2 * descarga_global or (_p90(vs) or 0) > 12):
            cliente_key = nome.split(" — ")[0].upper().strip()
            lentos.append({"destinatario": nome, "n": len(vs),
                           "descarga_med_h": med, "descarga_p90_h": _p90(vs),
                           "freetime_h": (freetimes or {}).get(cliente_key)})
    lentos.sort(key=lambda x: -(x["descarga_med_h"] or 0))

    return {
        "rotas": saida_rotas,
        "destinos_lentos": lentos[:20],
        "descarga_por_cidade": {c: _med(v) for c, v in desc_por_cid.items()
                                if len(v) >= N_MIN},
        "kpis": {
            "rotas_com_historico": len(saida_rotas),
            "cobertura_viagens_pct": (100.0 * cobertas / total_viagens)
            if total_viagens else None,
            "descarga_mediana_h": descarga_global,
            "viagens_com_descarga_pct": (100.0 * len(desc_todas) / total_viagens)
            if total_viagens else None,
            "fora_da_regua": fora_regua,
        },
        "janela": "últimos 6 meses",
        "fonte": ("ERP AVA · programacaoembarque (dtsaida→dtchegada, porta a "
                  "porta — inclui fila e pernoite) + eventos SAC 394-397 · "
                  "mediana e p90 sobre 6 meses; menos de 10 amostras = n/d"),
    }


@cached(ttl=3600)
def get_ciclos() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(CICLOS_VIAGENS_SQL)
        viagens = [dict(r) for r in cur.fetchall()]
        cur.execute(CICLOS_EVENTOS_SQL)
        eventos = {r["k"]: dict(r) for r in cur.fetchall()}
        cur.execute(CICLOS_DESTINATARIO_SQL)
        dests = {r["k"]: r["destinatario"] for r in cur.fetchall()}
        try:
            cur.execute(CICLOS_FREETIME_SQL)
            fts = {r["cliente"]: float(r["freetime_h"] or 0) for r in cur.fetchall()}
        except Exception:  # noqa: BLE001 - freetime é enfeite, não estrutura
            fts = {}
    out = montar_ciclos(viagens, eventos, dests, fts)
    out["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    return out
