# api/poligonos/servico.py
"""Onde se perde tempo dentro da planta do cliente.

A pergunta da tela: das horas que o veiculo passa dentro da Tupy Joinville,
quanto e atendimento (parado num ponto mapeado) e quanto e fila/manobra.

MEDIDO em agosto/26: mediana de 410 min dentro da planta por visita com
servico, dos quais 93 min em pontos e 306 min fora de qualquer ponto - 75% do
tempo. E esse numero que a tela existe para mostrar.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta

from api import db
from api.poligonos.sql import (BBOX, CNPJ_TUPY_JOINVILLE, EXTENSAO_MAX,
                               FROTA_SQL, GAP_VISITA, POLIGONOS_SQL,
                               VISITAS_SQL)

log = logging.getLogger("cortex.poligonos")

# A media nao serve para NENHUM dos dois escopos, por motivos diferentes:
#   planta - 12,7% das visitas passam de 24 h (caminhao estacionado, nao
#            atendimento) e uma chega a 145 h; a media fica 2,4x a mediana;
#   ponto  - a cauda e curta mas existe (p99 = 151 min contra mediana de 9).
# Toda estatistica desta tela e MEDIANA, e a contagem vai junto para quem le
# saber sobre quantas visitas ela foi tirada.
JANELA_MAX_DIAS = 120

# Visita a planta SEM passar por ponto nenhum: 158 das 481 em agosto, mediana
# de 31 min. Nao entram no calculo de "tempo de atendimento" - o veiculo nao
# foi atendido - mas sao contadas e mostradas, porque um volume alto delas
# significa area de servico nao mapeada.
MIN_LEITURAS_CONFIAVEL = 2

# limiar do aviso de fila: acima disto o tempo fora de ponto domina a visita
FILA_ALERTA_PCT = 60.0


def _min(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def _med(vals: list[float]) -> float | None:
    return round(statistics.median(vals), 1) if vals else None


def _p90(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[max(0, int(len(s) * 0.9) - 1)], 1)


def _janela(de: str | None, ate: str | None) -> tuple[str, str]:
    """Datas em horario LOCAL. `date.today()` e nao `utcnow()`: em UTC-3 o
    toISOString volta um dia e o periodo perderia o dia corrente."""
    hoje = date.today()
    d_ate = date.fromisoformat(ate) if ate else hoje
    d_de = date.fromisoformat(de) if de else (d_ate - timedelta(days=29))
    if d_de > d_ate:
        d_de, d_ate = d_ate, d_de
    # teto de janela: o teste de contencao roda por posicao (~67 mil/mes) e
    # nao ha indice espacial; 120 dias ja leva ~20 s.
    if (d_ate - d_de).days > JANELA_MAX_DIAS:
        d_de = d_ate - timedelta(days=JANELA_MAX_DIAS)
    # `ate` exclusivo no SQL: o dia final inteiro tem de entrar
    return d_de.isoformat(), (d_ate + timedelta(days=1)).isoformat()


def _casar(planta: list[dict], pontos: list[dict]) -> dict[int, list[dict]]:
    """Quais visitas a ponto acontecem DENTRO de cada passagem pela planta.

    Casamento por placa + intervalo contido. O perimetro contem os pontos
    geometricamente, entao toda visita a ponto deveria cair dentro de uma
    passagem; as que nao caem (leitura de borda, extensao estourando o limite
    da passagem) sao contadas no aviso em vez de somem caladas.
    """
    por_placa: dict[str, list[dict]] = {}
    for v in planta:
        por_placa.setdefault(v["veiculo"], []).append(v)
    dentro: dict[int, list[dict]] = {}
    orfas = 0
    for p in pontos:
        achou = None
        for v in por_placa.get(p["veiculo"], ()):
            if v["entrada"] <= p["entrada"] and p["saida"] <= v["saida"]:
                achou = v
                break
        if achou is None:
            orfas += 1
            continue
        dentro.setdefault(id(achou), []).append(p)
    dentro["_orfas"] = orfas  # type: ignore[index]
    return dentro


def _coords(geometria: str) -> list[list[float]]:
    """Texto do `polygon` do Postgres -> [[lat, lon], ...].

    Os vértices de cadastro_poligono estão gravados como (LATITUDE, LONGITUDE)
    — a ordem que o Leaflet consome direto, e a MESMA armadilha documentada no
    sql.py: não inverter para o (x=lon, y=lat) habitual de GIS."""
    import re as _re
    return [[float(a), float(b)]
            for a, b in _re.findall(r"\(([-\d.]+),([-\d.]+)\)", geometria or "")]


def _mapa(inventario: list[dict], ranking: list[dict]) -> dict:
    """As geometrias para o mapa de calor da planta (pedido de 01/09/2026).

    Cada polígono interno vai com os números do PRÓPRIO recorte filtrado
    (mediana, visitas, total de horas) — é o total de horas que pinta a
    intensidade no mapa. Ponto cadastrado SEM visita no período vai junto,
    zerado: sumir do mapa esconderia justamente o ponto morto, que é
    informação (a tela já lista os "sem movimento")."""
    por_id = {r["poligono_id"]: r for r in ranking}
    perimetro = next((_coords(r["geometria"]) for r in inventario
                      if r["tipo"] == 1 and r.get("geometria")), None)
    pontos = []
    for r in inventario:
        if r["tipo"] != 4:
            continue
        c = _coords(r.get("geometria") or "")
        if len(c) < 3:
            continue
        stats = por_id.get(r["id"], {})
        pontos.append({
            "id": r["id"],
            "nome": (r["nome"] or f"poligono {r['id']}").strip(),
            "coords": c,
            "mediana_min": stats.get("mediana_min"),
            "p90_min": stats.get("p90_min"),
            "visitas": stats.get("visitas", 0),
            "total_h": stats.get("total_h", 0.0),
            "placas": stats.get("placas", 0),
        })
    return {"perimetro": perimetro, "pontos": pontos}


def get_poligonos(de: str | None = None, ate: str | None = None,
                  uso: str | None = None) -> dict:
    d_de, d_ate = _janela(de, ate)
    par = dict(BBOX)
    par.update({"cnpj": CNPJ_TUPY_JOINVILLE, "de": d_de, "ate": d_ate,
                "gap": GAP_VISITA, "ext": EXTENSAO_MAX})
    linhas = db.query(VISITAS_SQL, par)
    inventario = db.query(POLIGONOS_SQL, {"cnpj": CNPJ_TUPY_JOINVILLE})
    frota = {r["placa"]: (r["uso"] or "").strip()
             for r in db.query(FROTA_SQL) if r["placa"]}

    nomes = {r["id"]: (r["nome"] or f"poligono {r['id']}").strip()
             for r in inventario}
    perimetro = [r for r in inventario if r["tipo"] == 1]

    pontos = [x for x in linhas if x["escopo"] == "ponto"]
    planta = [x for x in linhas if x["escopo"] == "planta"]
    if uso:
        alvo = {u.strip().upper() for u in uso.split(",") if u.strip()}
        pontos = [x for x in pontos if frota.get(x["veiculo"], "") in alvo]
        planta = [x for x in planta if frota.get(x["veiculo"], "") in alvo]

    dentro = _casar(planta, pontos)
    orfas = dentro.pop("_orfas", 0)  # type: ignore[arg-type]

    com = [v for v in planta if dentro.get(id(v))]
    sem = [v for v in planta if not dentro.get(id(v))]

    tot = [_min(v["entrada"], v["saida"]) for v in com]
    em_ponto = [sum(_min(p["entrada"], p["saida"]) for p in dentro[id(v)])
                for v in com]
    fila = [max(0.0, a - b) for a, b in zip(tot, em_ponto)]
    pct_fila = _med([100 * f / t for f, t in zip(fila, tot) if t > 0])

    # ranking por ponto
    por_pol: dict[int, list[float]] = {}
    placas_pol: dict[int, set] = {}
    for p in pontos:
        por_pol.setdefault(p["poligono_id"], []).append(
            _min(p["entrada"], p["saida"]))
        placas_pol.setdefault(p["poligono_id"], set()).add(p["veiculo"])
    ranking = sorted(
        ({"poligono_id": k, "nome": nomes.get(k, f"poligono {k}"),
          "visitas": len(v), "mediana_min": _med(v), "p90_min": _p90(v),
          "total_h": round(sum(v) / 60, 1), "placas": len(placas_pol[k])}
         for k, v in por_pol.items()),
        key=lambda x: -(x["mediana_min"] or 0))

    # serie mensal (mediana do mes, nao media - mesma regra)
    por_mes: dict[str, dict[str, list[float]]] = {}
    for v, t, ep, f in zip(com, tot, em_ponto, fila):
        m = v["entrada"].strftime("%Y-%m")
        alvo = por_mes.setdefault(m, {"tot": [], "ponto": [], "fila": []})
        alvo["tot"].append(t)
        alvo["ponto"].append(ep)
        alvo["fila"].append(f)
    mensal = [{"mes": m, "visitas": len(v["tot"]),
               "mediana_min": _med(v["tot"]), "ponto_min": _med(v["ponto"]),
               "fila_min": _med(v["fila"])}
              for m, v in sorted(por_mes.items())]

    # visitas a ponto mais longas, com a placa e a modalidade
    longas = sorted(pontos, key=lambda p: -_min(p["entrada"], p["saida"]))[:40]
    tabela = [{"veiculo": p["veiculo"], "uso": frota.get(p["veiculo"], ""),
               "poligono": nomes.get(p["poligono_id"], ""),
               "entrada": p["entrada"].strftime("%Y-%m-%d %H:%M"),
               "saida": p["saida"].strftime("%Y-%m-%d %H:%M"),
               "minutos": round(_min(p["entrada"], p["saida"]), 1),
               "leituras": p["leituras"],
               "estimado": p["leituras"] < MIN_LEITURAS_CONFIAVEL}
              for p in longas]

    sem_mov = [nomes[r["id"]] for r in inventario
               if r["tipo"] == 4 and r["id"] not in por_pol]
    uma_leitura = sum(1 for p in pontos
                      if p["leituras"] < MIN_LEITURAS_CONFIAVEL)

    return {
        "periodo": {"de": d_de, "ate": d_ate, "uso": uso or ""},
        "kpis": {
            "visitas_com_servico": len(com),
            "visitas_sem_servico": len(sem),
            "mediana_sem_servico": _med([_min(v["entrada"], v["saida"])
                                         for v in sem]),
            "mediana_planta_min": _med(tot),
            "mediana_ponto_min": _med(em_ponto),
            "mediana_fila_min": _med(fila),
            "pct_fila": pct_fila,
            "placas": len({v["veiculo"] for v in planta}),
            "pontos_ativos": len(por_pol),
            "pontos_cadastrados": sum(1 for r in inventario if r["tipo"] == 4),
            "tem_perimetro": bool(perimetro),
        },
        "ranking": ranking,
        "mapa": _mapa(inventario, ranking),
        "mensal": mensal,
        "tabela": tabela,
        "sem_movimento": sem_mov,
        "avisos": _avisos(pct_fila, uma_leitura, len(pontos), orfas, sem_mov,
                          perimetro),
        "fonte": {
            "tabela": "veiculo_posicao x cadastro_poligono (@>)",
            "cliente": CNPJ_TUPY_JOINVILLE,
            "gap_visita": GAP_VISITA, "extensao_max": EXTENSAO_MAX,
            "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }


def _avisos(pct_fila, uma_leitura, n_pontos, orfas, sem_mov, perimetro) -> list[str]:
    av: list[str] = []
    if not perimetro:
        av.append(
            "Perimetro da planta nao cadastrado para este cliente: sem ele nao "
            "da para separar tempo de atendimento de tempo de fila, e a tela "
            "mostra so a permanencia ponto a ponto.")
    if pct_fila is not None and pct_fila >= FILA_ALERTA_PCT:
        av.append(
            f"{pct_fila:.0f}% do tempo dentro da planta e passado FORA de "
            "qualquer ponto mapeado. Parte disso e fila e manobra, mas parte "
            "pode ser area de servico ainda nao mapeada - vale conferir com o "
            "cliente antes de tratar tudo como espera.")
    if uma_leitura and n_pontos:
        av.append(
            f"{uma_leitura} de {n_pontos} visitas tem uma unica leitura de "
            f"GPS ({100*uma_leitura/n_pontos:.0f}%): nelas a permanencia e "
            "ESTIMADA a partir da cadencia do rastreador (3 a 5 min), nao "
            "medida. Aparecem marcadas na tabela.")
    if orfas:
        av.append(
            f"{orfas} visitas a ponto nao couberam em nenhuma passagem pelo "
            "perimetro (leitura de borda). Elas contam no ranking por ponto e "
            "ficam de fora da decomposicao.")
    if sem_mov:
        av.append(
            f"Sem movimento no periodo: {', '.join(sem_mov[:6])}"
            f"{'...' if len(sem_mov) > 6 else ''}. Ou o ponto deixou de ser "
            "usado, ou o cadastro do poligono esta sobrando.")
    return av
