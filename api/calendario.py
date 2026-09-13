# -*- coding: utf-8 -*-
"""O calendário de feriados da casa — o que faz "dia útil" deixar de ser só
"segunda a sexta".

PEDIDO DE QUEM OPERA (12/09/2026): "crie no sistema essa parte do calendário,
e já popule buscando da web os feriados nacionais". Até aqui o e-mail da
inadimplência das 13h e a agenda do WhatsApp com "só dias úteis" sairiam num 7
de setembro, e a série de dias úteis contava o feriado como dia de trabalho.

TRÊS FONTES, UMA DECISÃO
========================
1. **A WEB POPULA.** BrasilAPI (`/api/feriados/v1/{ano}`), pública e sem chave:
   nome, data e as datas móveis.
2. **A LEI FEDERAL DECIDE O QUE É FOLGA.** Medido em 12/09/2026: a BrasilAPI
   marca como "national" 14 datas por ano, e três não são feriado pela lei —
   Carnaval (segunda e terça) e Corpus Christi são PONTO FACULTATIVO, e a
   Páscoa é domingo. Se a web decidisse a folga, o e-mail de dia útil pararia
   no Carnaval sem ninguém ter decidido isso. Eles entram como `facultativo`
   com a folga DESLIGADA, e quem opera liga na aba Feriados da Gestão se a
   casa não trabalha. (A Nager.Date, a outra fonte pública, erra do outro
   lado: acerta o Carnaval como opcional e chama Corpus Christi de feriado.)
3. **O QUE A WEB NÃO TEM** — estadual, municipal, da empresa — entra à mão, na
   mesma aba.

A WEB NUNCA CRIA FOLGA SOZINHA: data que ela chama de feriado e a lei não
confirma entra como `a_conferir`, sem folga, e a Saúde avisa. Um erro da fonte
não pode calar um e-mail. E A LEI COBRE A FALTA DA WEB: ano sem busca bem
sucedida (ou banco fora) usa a lista da lei, então "dia útil" nunca volta a
ignorar feriado nacional em silêncio.

O CALENDÁRIO SE MANTÉM SOZINHO: `garantir()` busca o ano corrente e o próximo
quando faltam, no máximo uma tentativa por dia, e é chamado pela rotina dos
relatórios por e-mail (que já roda de 15 em 15 minutos).
"""
from __future__ import annotations

import json
import logging
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta

from . import pglocal
from . import tls as _tls
from .sob_teste import sob_teste

log = logging.getLogger("cortex.calendario")

ESQUEMA: str | None = None

URL = "https://brasilapi.com.br/api/feriados/v1/{ano}"
FONTE_WEB = "brasilapi"
TIMEOUT = 20
_UA = "Mozilla/5.0 (compatible; CORTEX-Sulista/1.0; +painel interno)"

MANUAIS = ("estadual", "municipal", "empresa")
TIPOS = ("nacional", "facultativo", "comemorativa", "a_conferir") + MANUAIS
DIAS = {1: "segunda", 2: "terça", 3: "quarta", 4: "quinta", 5: "sexta",
        6: "sábado", 7: "domingo"}

#: Ponto facultativo federal que a web chama de feriado (nome normalizado).
FACULTATIVOS = ("carnaval", "corpus christi", "quarta-feira de cinzas")
#: Data da web que não é feriado nem ponto facultativo.
COMEMORATIVAS = ("pascoa", "domingo de pascoa")

#: Uma tentativa na web por dia, por ano que falta: a rotina que chama roda de
#: 15 em 15 minutos, e bater na fonte a cada passagem num dia ruim dela não
#: traz o calendário mais cedo.
RETENTAR_H = 24

_TTL = 300
_CACHE: dict[int, tuple[float, dict]] = {}


class FormatoInesperado(ValueError):
    """A web respondeu, mas não com a lista de feriados que se espera."""


def _esq(esquema: str | None = None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


# ═══════════════════════════════════════════════════════ a lei ═══════════

def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anônimo, Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lz = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lz) // 451
    mes = (h + lz - 7 * m + 114) // 31
    dia = ((h + lz - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def nacionais_da_lei(ano: int) -> dict[date, str]:
    """Os feriados nacionais pela lei federal: Leis 662/1949, 6.802/1980 e
    10.607/2002 (as datas fixas), a Paixão de Cristo (que a portaria anual do
    governo federal lista como feriado nacional) e o 20 de novembro desde 2024
    (Lei 14.759/2023). Ponto facultativo não entra."""
    out = {date(ano, 1, 1): "Confraternização Universal",
           date(ano, 4, 21): "Tiradentes",
           date(ano, 5, 1): "Dia do Trabalho",
           date(ano, 9, 7): "Independência do Brasil",
           date(ano, 10, 12): "Nossa Senhora Aparecida",
           date(ano, 11, 2): "Finados",
           date(ano, 11, 15): "Proclamação da República",
           date(ano, 12, 25): "Natal"}
    out[pascoa(ano) - timedelta(days=2)] = "Sexta-feira da Paixão"
    if ano >= 2024:
        out[date(ano, 11, 20)] = "Dia Nacional de Zumbi e da Consciência Negra"
    return dict(sorted(out.items()))


# ═══════════════════════════════════════════════════════ a web ═══════════

def baixar(ano: int) -> list[dict]:
    """O corpo da BrasilAPI para o ano: `[{date, name, type, weekday}]`."""
    req = urllib.request.Request(URL.format(ano=int(ano)),
                                 headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_tls.contexto()) as r:
        corpo = r.read(1_000_001)
    if len(corpo) > 1_000_000:
        raise FormatoInesperado("resposta maior que 1 MB")
    dados = json.loads(corpo.decode("utf-8"))
    if not isinstance(dados, list) or not all(
            isinstance(x, dict) and x.get("date") and x.get("name") for x in dados):
        raise FormatoInesperado("a resposta não é a lista de feriados")
    return dados


def classificar(itens: list[dict], ano: int) -> tuple[list[dict], list[str]]:
    """Da lista da web, as linhas do calendário e as divergências com a lei."""
    lei = nacionais_da_lei(ano)
    linhas, divergencias, vistos, ja = [], [], set(), set()
    for it in itens:
        try:
            d = date.fromisoformat(str(it["date"])[:10])
        except ValueError:
            divergencias.append(f"data ilegível na web: {it.get('date')!r}")
            continue
        nome = " ".join(str(it["name"]).split())[:80]
        if d.year != ano:
            divergencias.append(f"{d:%d/%m/%Y} {nome}: veio no ano errado")
            continue
        chave = _norm(nome)
        if d in lei:
            tipo, folga = "nacional", True
            vistos.add(d)
        elif chave in FACULTATIVOS:
            tipo, folga = "facultativo", False
        elif chave in COMEMORATIVAS:
            tipo, folga = "comemorativa", False
        else:
            tipo, folga = "a_conferir", False
            divergencias.append(f"{d:%d/%m} {nome}: a web chama de feriado e a "
                                "lei federal não confirma")
        if (d, tipo) in ja:
            continue
        ja.add((d, tipo))
        linhas.append({"data": d, "nome": nome, "tipo": tipo, "folga": folga,
                       "fonte": FONTE_WEB})
    for d, nome in lei.items():
        if d not in vistos:
            linhas.append({"data": d, "nome": nome, "tipo": "nacional", "folga": True,
                           "fonte": "lei"})
            divergencias.append(f"{d:%d/%m} {nome}: feriado da lei que a web não "
                                "trouxe — entrou pela lei")
    return sorted(linhas, key=lambda x: (x["data"], x["tipo"])), divergencias


def _invalidar() -> None:
    _CACHE.clear()


def popular(ano: int, *, esquema: str | None = None, baixar_fn=None) -> dict:
    """Busca na web e grava. A folga que alguém DECIDIU (`folga_por`) não é
    desfeita pela busca seguinte. A falha fica registrada — sem apagar o
    último sucesso — e sobe para quem chamou."""
    esq = _esq(esquema)
    try:
        itens = (baixar_fn or baixar)(ano)
    except Exception as exc:
        pglocal.executar(
            """INSERT INTO cal_feriados_coleta(ano, fonte, erro, erro_em)
               VALUES (%s, %s, %s, now())
               ON CONFLICT (ano) DO UPDATE SET erro = excluded.erro, erro_em = now()""",
            (int(ano), FONTE_WEB, f"{type(exc).__name__}: {str(exc)[:160]}"), esq)
        raise
    linhas, divergencias = classificar(itens, ano)
    with pglocal.get_conn(esq) as cx:
        with cx.cursor() as cur:
            for l in linhas:
                cur.execute(
                    """INSERT INTO cal_feriados(data, nome, tipo, folga, fonte)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (data, tipo, uf, municipio) DO UPDATE SET
                         nome = excluded.nome, fonte = excluded.fonte,
                         coletado_em = now(),
                         folga = CASE WHEN cal_feriados.folga_por IS NULL
                                      THEN excluded.folga ELSE cal_feriados.folga END""",
                    (l["data"], l["nome"], l["tipo"], l["folga"], l["fonte"]))
            cur.execute(
                """INSERT INTO cal_feriados_coleta(ano, fonte, ok_em, itens, divergencias)
                   VALUES (%s, %s, now(), %s, %s)
                   ON CONFLICT (ano) DO UPDATE SET fonte = excluded.fonte,
                     ok_em = now(), itens = excluded.itens,
                     divergencias = excluded.divergencias, erro = NULL, erro_em = NULL""",
                (int(ano), FONTE_WEB, len(linhas), divergencias))
        cx.commit()
    _invalidar()
    return {"ano": int(ano), "itens": len(linhas),
            "folgas": sum(1 for l in linhas if l["folga"]),
            "divergencias": divergencias}


def garantir(hoje: date | None = None, *, esquema: str | None = None,
             baixar_fn=None) -> list[str]:
    """Busca o ano corrente e o próximo quando ainda não há busca boa, no
    máximo uma tentativa por dia. NUNCA levanta: quem chama é a rotina dos
    relatórios, e o calendário não pode derrubar o envio de e-mail."""
    hoje = hoje or date.today()
    esq = _esq(esquema)
    saida = []
    for ano in (hoje.year, hoje.year + 1):
        try:
            c = pglocal.um("SELECT ok_em, erro_em FROM cal_feriados_coleta WHERE ano = %s",
                           (ano,), esq) or {}
            if c.get("ok_em"):
                continue
            if c.get("erro_em") and (datetime.now(c["erro_em"].tzinfo) - c["erro_em"]
                                     < timedelta(hours=RETENTAR_H)):
                continue
            r = popular(ano, esquema=esq, baixar_fn=baixar_fn)
            saida.append(f"calendario {ano}: {r['itens']} datas, {r['folgas']} folgas"
                         + (f", {len(r['divergencias'])} a conferir" if r["divergencias"] else ""))
        except Exception as exc:  # noqa: BLE001
            saida.append(f"calendario {ano}: busca falhou ({type(exc).__name__}) — vale a lei")
    return saida


# ═══════════════════════════════════════════════════ o que é folga ═══════

def _carregar(ano: int, esq) -> dict[date, str]:
    ok = pglocal.um("SELECT ok_em FROM cal_feriados_coleta WHERE ano = %s", (ano,), esq)
    do_banco = {l["data"]: l["nome"] for l in pglocal.query(
        "SELECT data, nome FROM cal_feriados WHERE folga AND data >= %s AND data <= %s "
        "ORDER BY data", (date(ano, 1, 1), date(ano, 12, 31)), esq)}
    if not ok or not ok.get("ok_em"):
        # sem busca boa: a lei é o PISO, e o que alguém lançou à mão soma
        return {**nacionais_da_lei(ano), **do_banco}
    return do_banco


def folgas(ano: int) -> dict[date, str]:
    """As datas que NÃO são dia útil no ano, com o nome. Cache de 5 min.

    Numa rodada de testes sem esquema dublado, vale a lei e o banco NÃO é
    lido: o teste que dependesse do calendário de produção mudaria de
    resultado conforme alguém mexe na aba Feriados."""
    if ESQUEMA is None and sob_teste():
        return nacionais_da_lei(ano)
    agora = time.monotonic()
    c = _CACHE.get(ano)
    if c and agora - c[0] < _TTL:
        return c[1]
    try:
        res = _carregar(ano, _esq())
    except Exception as exc:  # noqa: BLE001
        log.info("calendario: banco indisponivel (%s) — vale a lei", type(exc).__name__)
        res = nacionais_da_lei(ano)
    _CACHE[ano] = (agora, res)
    return res


def feriado(d: date) -> str | None:
    """O nome da folga em `d`, ou None."""
    return folgas(d.year).get(d)


def dia_util(d: date) -> bool:
    """Segunda a sexta, fora das folgas do calendário."""
    return d.isoweekday() <= 5 and d not in folgas(d.year)


# ═══════════════════════════════════════════════════════ a aba ═══════════

def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def estado(ano: int, esquema: str | None = None) -> dict:
    esq = _esq(esquema)
    linhas = pglocal.query(
        """SELECT id, data, nome, tipo, uf, municipio, folga, fonte, criado_por,
                  folga_por, folga_em
             FROM cal_feriados WHERE data >= %s AND data <= %s
            ORDER BY data, tipo""", (date(ano, 1, 1), date(ano, 12, 31)), esq)
    c = pglocal.um("SELECT * FROM cal_feriados_coleta WHERE ano = %s", (ano,), esq)
    return {
        "ano": ano,
        "itens": [{**l, "data": l["data"].isoformat(),
                   "dia_semana": DIAS[l["data"].isoweekday()],
                   "folga_em": _iso(l.get("folga_em"))} for l in linhas],
        "coleta": ({"ok_em": _iso(c.get("ok_em")), "itens": c.get("itens"),
                    "divergencias": list(c.get("divergencias") or []),
                    "erro": c.get("erro"), "erro_em": _iso(c.get("erro_em"))}
                   if c else None),
        "fonte": URL.format(ano=ano),
    }


def _validar_manual(dados: dict) -> dict:
    try:
        d = date.fromisoformat(str(dados.get("data") or "")[:10])
    except ValueError:
        raise ValueError("Informe a data do feriado.") from None
    nome = " ".join(str(dados.get("nome") or "").split())[:80]
    if len(nome) < 3:
        raise ValueError("Dê um nome ao feriado.")
    tipo = str(dados.get("tipo") or "").strip().lower()
    if tipo not in MANUAIS:
        raise ValueError("Tipo deve ser estadual, municipal ou da empresa — os "
                         "nacionais vêm da busca na web.")
    uf = str(dados.get("uf") or "").strip().upper()
    municipio = " ".join(str(dados.get("municipio") or "").split())[:60]
    if tipo in ("estadual", "municipal") and (len(uf) != 2 or not uf.isalpha()):
        raise ValueError("Informe a UF com duas letras.")
    if tipo == "municipal" and len(municipio) < 2:
        raise ValueError("Informe o município.")
    if tipo == "estadual":
        municipio = ""
    if tipo == "empresa":
        uf = municipio = ""
    return {"data": d, "nome": nome, "tipo": tipo, "uf": uf, "municipio": municipio,
            "folga": bool(dados.get("folga", True))}


def gravar_manual(dados: dict, quem: str, esquema: str | None = None) -> dict:
    """Feriado que a web não traz. Nasce COM folga: quem lança um feriado da
    casa está dizendo que ninguém trabalha nele."""
    v = _validar_manual(dados)
    r = pglocal.um(
        """INSERT INTO cal_feriados(data, nome, tipo, uf, municipio, folga, fonte,
                                    criado_por, folga_por, folga_em)
           VALUES (%s, %s, %s, %s, %s, %s, 'manual', %s, %s, now())
           ON CONFLICT (data, tipo, uf, municipio) DO UPDATE SET nome = excluded.nome,
             folga = excluded.folga, folga_por = excluded.folga_por, folga_em = now()
           RETURNING id""",
        (v["data"], v["nome"], v["tipo"], v["uf"], v["municipio"], v["folga"],
         quem or None, quem or None), _esq(esquema))
    _invalidar()
    return {**v, "data": v["data"].isoformat(), "id": int(r["id"])}


def marcar_folga(ident: int, folga: bool, quem: str, esquema: str | None = None) -> dict:
    """Liga ou desliga a folga de uma data — e guarda quem decidiu, para a
    próxima busca na web não desfazer a decisão."""
    if not quem:
        raise ValueError("Informe quem está decidindo.")
    r = pglocal.um(
        """UPDATE cal_feriados SET folga = %s, folga_por = %s, folga_em = now()
            WHERE id = %s RETURNING id, data, nome, tipo, folga""",
        (bool(folga), quem, int(ident)), _esq(esquema))
    if not r:
        raise ValueError(f"Feriado {ident} não existe.")
    _invalidar()
    return {**r, "data": r["data"].isoformat()}


def remover_manual(ident: int, esquema: str | None = None) -> None:
    """Só o que foi lançado à mão sai. O que veio da web ou da lei voltaria na
    próxima busca — para ele, desliga-se a folga."""
    r = pglocal.um("SELECT tipo FROM cal_feriados WHERE id = %s", (int(ident),), _esq(esquema))
    if not r:
        raise ValueError(f"Feriado {ident} não existe.")
    if r["tipo"] not in MANUAIS:
        raise ValueError("Feriado que veio da web ou da lei não se remove — a "
                         "próxima busca o traria de volta. Desmarque a folga.")
    pglocal.executar("DELETE FROM cal_feriados WHERE id = %s", (int(ident),), _esq(esquema))
    _invalidar()


# ═══════════════════════════════════════════════════ Saúde e Copiloto ════

def situacao(hoje: date | None = None, esquema: str | None = None) -> dict:
    """A busca do ano corrente e do próximo, para a Saúde."""
    hoje = hoje or date.today()
    out = {}
    for ano in (hoje.year, hoje.year + 1):
        c = pglocal.um("SELECT * FROM cal_feriados_coleta WHERE ano = %s", (ano,), _esq(esquema))
        out[ano] = ({"ok_em": c.get("ok_em"), "itens": c.get("itens") or 0,
                     "divergencias": list(c.get("divergencias") or []),
                     "erro": c.get("erro")} if c else None)
    return out


def proxima_folga(hoje: date | None = None) -> tuple[date, str] | None:
    hoje = hoje or date.today()
    for ano in (hoje.year, hoje.year + 1):
        for d, nome in sorted(folgas(ano).items()):
            if d >= hoje:
                return d, nome
    return None


def resumo_copiloto(hoje: date | None = None) -> dict:
    """Escalares: o próximo feriado e os dias úteis que restam no mês."""
    hoje = hoje or date.today()
    prox = proxima_folga(hoje)
    fim = (hoje.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    mes = [hoje.replace(day=k) for k in range(1, fim.day + 1)]
    return {
        "proximo_feriado": prox[0].isoformat() if prox else None,
        "proximo_feriado_nome": prox[1] if prox else None,
        "dias_uteis_no_mes": sum(1 for d in mes if dia_util(d)),
        "dias_uteis_restantes_no_mes": sum(1 for d in mes if d >= hoje and dia_util(d)),
        "feriados_em_dia_de_semana_restantes_no_ano": sum(
            1 for d in folgas(hoje.year) if d >= hoje and d.isoweekday() <= 5),
    }
