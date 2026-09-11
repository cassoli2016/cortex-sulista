# -*- coding: utf-8 -*-
"""O que a página inicial lê, o cartão da Saúde e o resumo do Copiloto.

TUDO AQUI LÊ O BANCO LOCAL, NUNCA A REDE. A tela é a primeira de todo mundo e
não pode esperar quatro sites de terceiro; quem fala com a rede é o relógio
(`agendador.py`). E é isso que deixa o Copiloto usar esta mesma leitura — fonte
de snapshot não dispara coleta externa.

AS COMPARAÇÕES SÃO POR DATA, NUNCA POR POSIÇÃO. "A semana anterior" é a que
fechou sete dias antes; se a ANP não pesquisou naquela semana (já pulou: ago/
2015, ago–out/2020), não há semana anterior, e o chip de tendência some — a
posição anterior na lista seria uma semana de um mês atrás apresentada como
"a semana passada".
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import pglocal
from . import coleta, fontes, rodovias

log = logging.getLogger("cortex.radar.painel")

ESQUEMA: str | None = None

NOME_CARTAO = "Radar do Transporte (mercado, notícias e rodovias)"

ROTULO_FONTE: dict[str, str] = {
    "anp": "Diesel (ANP)",
    "brent": "Brent (Yahoo)",
    "dolar": "Dólar (Yahoo)",
    "ptax": "PTAX (Banco Central)",
    "rodovias": "Rodovias (TomTom)",
    "frota": "Rodovias (nossa frota)",
    **{f"noticias_{t}": "Notícias · " + c["rotulo"] for t, c in fontes.TEMAS.items()},
}

#: Idade do último SUCESSO a partir da qual a fonte é "alerta"; o triplo é
#: "erro". Mede a EXECUÇÃO da coleta, não a novidade do dado: a ANP não publica
#: todo dia, mas a coleta dela precisa ter RODADO — senão a tela mostraria a
#: semana passada no dia em que a nova já saiu, sem ninguém saber.
LIMITE_ALERTA_S: dict[str, int] = {
    "anp": 26 * 3600,
    "ptax": 26 * 3600,
    "brent": 40 * 60,
    "dolar": 40 * 60,
    # a cadência das ocorrências é de 90 min (a franquia da TomTom é mensal)
    "rodovias": 100 * 60,
    "frota": 40 * 60,
    **{f"noticias_{t}": 2 * 3600 for t in fontes.TEMAS},
    "noticias_reforma": 3 * 3600,
    "noticias_antt": 3 * 3600,
}

#: Janela de cada aba de notícias: rodovia é o agora (3 dias); reforma e ANTT
#: andam em semanas.
DIAS_NOTICIA = {"trc": 14, "diesel": 14, "reforma": 30, "antt": 30, "rodovias": 3}
LIMITE_NOTICIAS = 15

def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def _f(v) -> float | None:
    return None if v is None else float(v)


def _d(v) -> str | None:
    return v.isoformat() if v is not None else None


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _ate(pontos: list[tuple[date, float]], alvo: date, folga: int = 10):
    """O último ponto em `alvo` ou antes — mas não mais velho que `folga`
    dias: sem ponto perto da data pedida, a comparação não existe."""
    for d, v in reversed(pontos):
        if d <= alvo:
            return {"dia": d.isoformat(), "valor": v} if d >= alvo - timedelta(days=folga) else None
    return None


# ------------------------------------------------------------------ blocos

def _diesel(esq) -> dict:
    linhas = pglocal.query(
        """SELECT produto, semana_inicio, semana_fim, postos, preco_revenda,
                  preco_min, preco_max, preco_distribuicao
             FROM rad_combustivel
            WHERE semana_fim >= (SELECT max(semana_fim) FROM rad_combustivel) - 735
            ORDER BY produto, semana_fim""", esquema=esq)
    saida = {}
    for produto in fontes.PRODUTOS_ANP.values():
        serie = [l for l in linhas if l["produto"] == produto and l["preco_revenda"] is not None]
        pontos = [{"semana_inicio": _d(l["semana_inicio"]), "semana_fim": _d(l["semana_fim"]),
                   "revenda": _f(l["preco_revenda"]), "min": _f(l["preco_min"]),
                   "max": _f(l["preco_max"]), "postos": l["postos"],
                   "distribuicao": _f(l["preco_distribuicao"])} for l in serie]
        if not pontos:
            saida[produto] = {"serie": [], "ultimo": None, "anterior": None,
                              "ref_4s": None, "ref_52s": None}
            continue
        pares = [(l["semana_fim"], float(l["preco_revenda"])) for l in serie]
        ult = pares[-1][0]
        por_fim = {l["semana_fim"]: p for l, p in zip(serie, pontos)}
        saida[produto] = {
            "serie": pontos,
            "ultimo": pontos[-1],
            "anterior": por_fim.get(ult - timedelta(days=7)),
            "ref_4s": _ate(pares, ult - timedelta(days=28), folga=6),
            "ref_52s": _ate(pares, ult - timedelta(days=364), folga=6),
        }
    return saida


def _mercado(esq, serie: str, dias_serie: int) -> dict:
    cot = pglocal.um(
        "SELECT valor, momento, moeda, fuso, coletado_em FROM rad_cotacao WHERE serie = %s",
        (serie,), esquema=esq)
    linhas = pglocal.query(
        "SELECT dia, valor FROM rad_serie WHERE serie = %s AND dia >= %s ORDER BY dia",
        (serie, _agora().date() - timedelta(days=max(dias_serie, 45) + 10)), esquema=esq)
    pontos = [(l["dia"], float(l["valor"])) for l in linhas]
    agora = None
    base = pontos[-1][0] if pontos else None
    if cot:
        fuso = timezone.utc
        try:
            fuso = ZoneInfo(cot["fuso"]) if cot["fuso"] else timezone.utc
        except Exception:  # noqa: BLE001
            pass
        base = cot["momento"].astimezone(fuso).date()
        agora = {"valor": float(cot["valor"]), "momento": cot["momento"].isoformat(),
                 "dia": base.isoformat(), "moeda": cot["moeda"],
                 "coletado_em": cot["coletado_em"].isoformat()}
    if base is None:
        return {"agora": None, "fechamento_anterior": None, "ref_30d": None,
                "max_12m": None, "min_12m": None, "serie": []}
    # O FECHAMENTO ANTERIOR É O DO PREGÃO ANTES DO ÚLTIMO NEGÓCIO. No sábado o
    # último negócio é de sexta, e a variação do dia é sexta contra quinta —
    # que é o que o mercado chama de variação do dia naquele momento.
    antes = [(d, v) for d, v in pontos if d < base]
    ano = [v for d, v in pontos if d > base - timedelta(days=365)]
    return {
        "agora": agora,
        "fechamento_anterior": ({"dia": antes[-1][0].isoformat(), "valor": antes[-1][1]}
                                if antes else None),
        "ref_30d": _ate(pontos, base - timedelta(days=30), folga=7),
        "max_12m": max(ano) if ano and dias_serie >= 365 else None,
        "min_12m": min(ano) if ano and dias_serie >= 365 else None,
        "serie": ([{"dia": d.isoformat(), "valor": v} for d, v in pontos
                   if d > base - timedelta(days=dias_serie)] if dias_serie >= 365 else []),
    }


def _ptax(esq) -> dict | None:
    l = pglocal.um("SELECT dia, valor FROM rad_serie WHERE serie = 'ptax' "
                   "ORDER BY dia DESC LIMIT 1", esquema=esq)
    return {"dia": l["dia"].isoformat(), "valor": float(l["valor"])} if l else None


def _rodovias(esq) -> dict:
    # DESLIGADO POR DECISÃO, o retrato gravado é o da última leitura ANTES da
    # decisão: publicá-lo seria mostrar ocorrência velha como se fosse de agora.
    desligado = rodovias.desligado()
    linhas = [] if desligado else pglocal.query(
        """SELECT regiao, rodovias, categoria, bloqueia, descricao, de, para,
                  atraso_s, magnitude, coletado_em
             FROM rad_rodovia
            ORDER BY bloqueia DESC, atraso_s DESC NULLS LAST, regiao, ordem""", esquema=esq)
    rotulos = {c[0]: c[1] for c in rodovias.CORREDORES}
    por_regiao = {c[0]: 0 for c in rodovias.CORREDORES}
    itens = []
    for l in linhas:
        por_regiao[l["regiao"]] = por_regiao.get(l["regiao"], 0) + 1
        itens.append({"regiao": l["regiao"], "regiao_rotulo": rotulos.get(l["regiao"], l["regiao"]),
                      "rodovias": l["rodovias"], "categoria": l["categoria"],
                      "bloqueia": bool(l["bloqueia"]), "descricao": l["descricao"],
                      "de": l["de"], "para": l["para"],
                      "atraso_min": (round(l["atraso_s"] / 60) if l["atraso_s"] is not None else None),
                      "magnitude": l["magnitude"]})
    return {"configurado": rodovias.ativo(), "desligado": desligado,
            "itens": itens, "bloqueios": sum(1 for i in itens if i["bloqueia"]),
            "corredores": [{"regiao": k, "rotulo": rotulos[k], "itens": por_regiao.get(k, 0)}
                           for k in rotulos]}


def _frota(esq) -> dict:
    """A nossa frota nos corredores — só contagem, nunca placa (`frota.py`)."""
    linhas = pglocal.query(
        """SELECT regiao, caminhoes, andando, lentos, parados, indefinidos,
                  lento_max_min, vel_lentos, coletado_em
             FROM rad_frota""", esquema=esq)
    if not linhas:
        return {"corredores": [], "coletado_em": None, "caminhoes": 0, "lentos": 0}
    por = {l["regiao"]: l for l in linhas}
    corredores = []
    for chave, rotulo, *_caixa in rodovias.CORREDORES:
        l = por.get(chave) or {}
        corredores.append({
            "regiao": chave, "rotulo": rotulo,
            **{k: int(l.get(k) or 0)
               for k in ("caminhoes", "andando", "lentos", "parados", "indefinidos")},
            "lento_max_min": l.get("lento_max_min"), "vel_lentos": l.get("vel_lentos")})
    return {"corredores": corredores,
            "coletado_em": _d(max(l["coletado_em"] for l in linhas)),
            "caminhoes": sum(c["caminhoes"] for c in corredores),
            "lentos": sum(c["lentos"] for c in corredores)}


def _chave_titulo(t: str) -> str:
    n = unicodedata.normalize("NFD", t or "")
    return " ".join("".join(c for c in n if unicodedata.category(c) != "Mn").lower().split())


def _noticias(esq) -> dict:
    agora = _agora()
    linhas = pglocal.query(
        """SELECT tema, titulo, fonte, link, publicada_em FROM rad_noticia
            WHERE publicada_em >= %s ORDER BY tema, publicada_em DESC""",
        (agora - timedelta(days=31),), esquema=esq)
    saida = {}
    for tema, cfg in fontes.TEMAS.items():
        corte = agora - timedelta(days=DIAS_NOTICIA.get(tema, 14))
        vistos, itens = set(), []
        for l in linhas:
            if l["tema"] != tema or l["publicada_em"] < corte:
                continue
            if not str(l["link"]).startswith("https://"):
                continue
            # A MESMA MATÉRIA EM DOIS VEÍCULOS é comum (agência replicada), e
            # duas linhas iguais na aba empurram a terceira notícia para fora.
            chave = _chave_titulo(l["titulo"])
            if chave in vistos:
                continue
            vistos.add(chave)
            itens.append({"titulo": l["titulo"], "fonte": l["fonte"], "link": l["link"],
                          "publicada_em": l["publicada_em"].isoformat()})
        saida[tema] = {"rotulo": cfg["rotulo"], "dias": DIAS_NOTICIA.get(tema, 14),
                       "total": len(itens), "itens": itens[:LIMITE_NOTICIAS]}
    return saida


def _coleta(esq) -> dict:
    est = coleta.estado(esq)
    agora = _agora()
    saida = {}
    desligado = rodovias.desligado()
    for fonte, rotulo in ROTULO_FONTE.items():
        # DESLIGADA POR DECISÃO, a fonte sai do estado: a última tentativa
        # (a da falta de crédito) continua gravada em `rad_coleta`, e a Saúde
        # e a tarja da tela a leriam como falha de agora, para sempre.
        if fonte == "rodovias" and desligado:
            continue
        e = est.get(fonte)
        if not e:
            saida[fonte] = {"rotulo": rotulo, "estado": "nunca"}
            continue
        idade = (agora - e["sucesso_em"]).total_seconds() if e["sucesso_em"] else None
        lim = LIMITE_ALERTA_S[fonte]
        if idade is None:
            st = "erro"
        else:
            st = "ok" if idade <= lim else ("alerta" if idade <= 3 * lim else "erro")
        saida[fonte] = {"rotulo": rotulo, "estado": st, "ok": bool(e["ok"]),
                        "sucesso_em": _d(e["sucesso_em"]), "tentativa_em": _d(e["tentativa_em"]),
                        "idade_s": int(idade) if idade is not None else None,
                        "erro": None if e["ok"] else e["erro"],
                        "itens": e["itens"], "dado_ate": _d(e["dado_ate"])}
    return saida


def painel(esquema: str | None = None) -> dict:
    """O payload da tela. Tudo já convertido para JSON (float, isoformat)."""
    esq = _esq(esquema)
    try:
        estado = _coleta(esq)
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"pronto": False, "gerado_em": _agora().isoformat(),
                    "mensagem": "As tabelas do Radar ainda não existem — elas "
                                "nascem com a API (migration 0079)."}
        raise
    return {
        "pronto": True,
        "gerado_em": _agora().isoformat(),
        "diesel": _diesel(esq),
        "brent": _mercado(esq, "brent", 365),
        "dolar": _mercado(esq, "dolar", 0),
        "ptax": _ptax(esq),
        "rodovias": _rodovias(esq),
        "frota": _frota(esq),
        "noticias": _noticias(esq),
        "coleta": estado,
    }


# --------------------------------------------------------------- a Saúde

def _ha(seg: int | None) -> str:
    if seg is None:
        return "nunca"
    if seg < 90:
        return "agora"
    if seg < 5400:
        return f"há {round(seg / 60)} min"
    if seg < 172800:
        return f"há {round(seg / 3600)} h"
    return f"há {round(seg / 86400)} dias"


def _br(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m") if iso else "—"


_PESO = {"erro": 0, "alerta": 1, "ok": 2}


def cartao_saude(esquema: str | None = None) -> dict:
    """O cartão da Saúde do Servidor: a coleta de cada fonte está RODANDO?"""
    try:
        est = _coleta(_esq(esquema))
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"nome": NOME_CARTAO, "status": "info",
                    "detalhe": "tabelas ainda não criadas (migration 0079 sobe com a API)"}
        return {"nome": NOME_CARTAO, "status": "erro",
                "detalhe": f"leitura do banco local falhou ({type(exc).__name__})"}
    medidas = {f: e for f, e in est.items() if e["estado"] != "nunca"}
    if not medidas:
        return {"nome": NOME_CARTAO, "status": "info",
                "detalhe": "aguardando a primeira coleta — o relógio sobe com a API, "
                           "só no processo líder, um minuto depois do arranque"}
    pior = min((e["estado"] for e in medidas.values()), key=lambda s: _PESO.get(s, 2))
    partes = []
    for f, rot in (("anp", "diesel até"), ("brent", "Brent"), ("dolar", "dólar"),
                   ("ptax", "PTAX até"), ("rodovias", "rodovias"),
                   ("frota", "frota nos corredores")):
        e = medidas.get(f)
        if not e:
            continue
        if f in ("anp", "ptax"):
            partes.append(f"{rot} {_br(e['dado_ate'])}")
        else:
            partes.append(f"{rot} {_ha(e['idade_s'])}")
    noticias = [e for f, e in medidas.items() if f.startswith("noticias_")]
    if noticias:
        ruins = [e for e in noticias if e["estado"] != "ok"]
        partes.append("notícias em dia" if not ruins
                      else f"notícias: {len(ruins)} de {len(noticias)} temas atrasados")
    falhas = [f"{e['rotulo']}: {e['erro'] or 'sem sucesso'} (último sucesso {_ha(e['idade_s'])})"
              for e in medidas.values() if e["estado"] != "ok"]
    desligado = rodovias.desligado()
    if desligado:
        partes.append(f"rodovias ao vivo desligadas por decisão desde "
                      f"{desligado['desde_br']} (só notícias)")
    elif not rodovias.ativo():
        partes.append("rodovias sem TomTom (só notícias)")
    detalhe = " · ".join(partes + falhas)
    return {"nome": NOME_CARTAO, "status": pior, "detalhe": detalhe[:500]}


# ------------------------------------------------------------ o Copiloto

def _var(a, b) -> float | None:
    return round(100 * (a / b - 1), 2) if a is not None and b else None


def resumo_copiloto(esquema: str | None = None) -> dict:
    """SÓ ESCALARES, e todos públicos: preço de bomba, Brent, dólar,
    contagem de ocorrências e manchetes. Nada da Sulista entra aqui."""
    p = painel(esquema)
    if not p.get("pronto"):
        return {"indisponivel": p.get("mensagem")}
    r: dict = {"fonte": "ANP (diesel, semanal) · Yahoo Finance (Brent futuro BZ=F e dólar "
                        "comercial, ~15 min de atraso) · Banco Central (PTAX) · "
                        "TomTom (rodovias) · Google Notícias"}
    for produto, nome in (("diesel_s10", "diesel_s10"), ("diesel_s500", "diesel_s500")):
        d = p["diesel"].get(produto) or {}
        u, a = d.get("ultimo"), d.get("anterior")
        if u:
            r[f"{nome}_bomba_rs_litro"] = u["revenda"]
            r[f"{nome}_semana"] = f"{u['semana_inicio']} a {u['semana_fim']}"
            r[f"{nome}_var_semana_pct"] = _var(u["revenda"], a["revenda"]) if a else None
    for serie in ("brent", "dolar"):
        m = p[serie]
        if m.get("agora"):
            r[f"{serie}_agora"] = m["agora"]["valor"]
            r[f"{serie}_momento"] = m["agora"]["momento"]
            fa, r30 = m.get("fechamento_anterior"), m.get("ref_30d")
            r[f"{serie}_var_dia_pct"] = _var(m["agora"]["valor"], fa["valor"]) if fa else None
            r[f"{serie}_var_30d_pct"] = _var(m["agora"]["valor"], r30["valor"]) if r30 else None
    if p.get("ptax"):
        r["ptax_venda"] = p["ptax"]["valor"]
        r["ptax_dia"] = p["ptax"]["dia"]
    rod = p["rodovias"]
    r["rodovias_ocorrencias_agora"] = len(rod["itens"]) if rod["configurado"] else None
    r["rodovias_bloqueios_agora"] = rod["bloqueios"] if rod["configurado"] else None
    # A NOSSA FROTA NOS CORREDORES, só em contagem: nenhuma placa sai daqui.
    fr = p["frota"]
    r["rodovias_frota_caminhoes_agora"] = fr["caminhoes"] if fr["coletado_em"] else None
    r["rodovias_frota_lentos_agora"] = fr["lentos"] if fr["coletado_em"] else None
    for tema, n in p["noticias"].items():
        r[f"manchetes_{tema}"] = " | ".join(i["titulo"] for i in n["itens"][:3]) or None
    return r
