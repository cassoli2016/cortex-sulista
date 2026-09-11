# -*- coding: utf-8 -*-
"""As quatro portas públicas do Radar: baixar e LER. Nada aqui toca o banco.

CADA FONTE FOI ESCOLHIDA POR SER A ORIGINAL, NÃO A MAIS CÔMODA
===============================================================
Medido em 11/09/2026, desta máquina:

- **Diesel — ANP, Levantamento de Preços, planilha semanal Brasil.** É o
  número que a imprensa cita ("diesel sobe pela terceira semana") e que o
  cliente vai citar numa renegociação de frete. 464 KB, uma linha por semana
  e produto desde 2012; a semana fecha no sábado. "Óleo diesel" na planilha é
  o **S500 comum**, dito na própria nota do arquivo — o S10 é outra linha.
- **Brent — o CONTRATO FUTURO do mês cheio (`BZ=F`), pelo Yahoo Finance**,
  com ~15 min de atraso. É o Brent que a imprensa cita ("petróleo cai 3%"), e
  é o que a pessoa quer ver ao abrir a tela: a decisão de quem opera, em
  11/09/2026, foi "não posso ver uma informação de dois dias atrás".
  A primeira escolha foi a OFICIAL — o spot FOB Europa da EIA, pela Ipeadata
  (`EIA366_PBRENT366`, sem chave) — e ela foi trocada por isso: tem DOIS DIAS
  de atraso por construção (em 11/09 o último ponto era 09/09), e nenhuma
  cadência de coleta resolve atraso da origem.
  O preço de agora e o histórico diário vêm da MESMA fonte, de propósito: o
  futuro e o spot são medidas diferentes (US$ 101,21 × US$ 109,51 no mesmo
  09/09), e uma série que troca de fonte no meio deixa de ser série.
  O RISCO É CONHECIDO E ESTÁ DITO: o Yahoo não publica essa API como produto,
  não há contrato nem chave. Se ele mudar o formato, `ler_yahoo` recusa com
  `FormatoInesperado`, a Saúde fica vermelha e a tela mostra a última leitura
  boa com a hora dela — nunca um número inventado.
  Avaliados e recusados: o FRED (conexão recusada desta rede); a API da EIA
  (chave de demonstração tem teto por hora, e é spot, com o mesmo atraso).
- **Dólar — o comercial pelo mesmo Yahoo (`BRL=X`), e a PTAX de venda do
  Banco Central (SGS, série 1) ao lado.** O comercial é o de agora; a PTAX é a
  taxa de referência de contrato, publicada uma vez por dia útil. As duas
  aparecem, cada uma com a sua data, porque respondem perguntas diferentes.
- **Notícias — busca do Google Notícias em RSS.** Três buscas, uma por tema.
  O RSS não traz o texto, só manchete, veículo e horário, e o link passa pelo
  Google — o que é o certo: a matéria é do veículo, e a tela manda a pessoa
  até ele.

A FALHA É DITA PELO TIPO, e o motivo é outro que o de sempre: nenhuma destas
URLs carrega segredo, mas `str(exc)` de rede despeja a URL inteira, com a
busca, no log de quem só queria saber que a ANP estava fora do ar.
"""
from __future__ import annotations

import io
import json
import logging
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from .. import tls as _tls

log = logging.getLogger("cortex.radar.fontes")

URL_ANP = ("https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
           "precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/"
           "semanal-brasil-desde-2013.xlsx")
URL_YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
             "?range={janela}&interval=1d")
URL_PTAX = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados"
            "?formato=json&dataInicial={ini}&dataFinal={fim}")
URL_NOTICIAS = "https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"

#: Série da casa × símbolo no Yahoo. `BZ=F` é o Brent da NYMEX que acompanha o
#: ICE Brent do mês cheio; `BRL=X` é o dólar comercial em reais.
SIMBOLOS_YAHOO: dict[str, str] = {"brent": "BZ=F", "dolar": "BRL=X"}

#: Os temas das notícias. A BUSCA É A CURADORIA, então ela fica escrita aqui,
#: à vista, e não espalhada: quem achar que o tema "Transporte" traz notícia
#: demais de ônibus mexe numa linha só. `when:` é do próprio Google Notícias e
#: corta o que é velho na origem — sem ele a busca de reforma tributária
#: devolve matéria de 2023 misturada com a de ontem.
TEMAS: dict[str, dict] = {
    "trc": {
        "rotulo": "Transporte",
        "busca": ('"transporte rodoviário de cargas" OR "transporte de cargas" '
                  'OR caminhoneiros OR "frete rodoviário" when:14d'),
    },
    "diesel": {
        "rotulo": "Diesel e petróleo",
        "busca": ('"preço do diesel" OR "óleo diesel" OR "diesel Petrobras" '
                  'when:14d'),
    },
    "reforma": {
        "rotulo": "Reforma tributária",
        "busca": ('"reforma tributária" (transporte OR frete OR logística OR '
                  'transportadoras OR combustíveis) when:30d'),
    },
    # A ANTT não publica RSS: o `/RSS` do portal gov.br devolve a página HTML
    # (medido em 11/09/2026). A busca pega a própria ANTT (o gov.br aparece
    # como veículo) e quem repercute resolução, piso e fiscalização.
    "antt": {
        "rotulo": "ANTT",
        "busca": ('ANTT (frete OR "piso mínimo" OR RNTRC OR "transporte de cargas" '
                  'OR caminhoneiro OR resolução) when:30d'),
    },
    # A SITUAÇÃO DAS RODOVIAS POR NOTÍCIA é a que avisa ANTES: bloqueio
    # programado de sábado sai na quinta. O incidente de agora vem da TomTom
    # (`api/radar/rodovias.py`); as duas se completam, não se repetem.
    "rodovias": {
        "rotulo": "Rodovias",
        "busca": ('(rodovia OR "BR-116" OR "BR-101" OR "BR-376" OR "BR-277" OR '
                  '"BR-381" OR "BR-153") (interditada OR interdição OR bloqueio OR '
                  '"pare e siga" OR deslizamento OR "fila de caminhões") when:3d'),
    },
}

#: Os produtos da planilha da ANP que interessam a uma transportadora, pelo
#: nome NORMALIZADO (a planilha já vem sem acento, mas a normalização protege
#: do dia em que ela voltar a ter). O S500 é "OLEO DIESEL", sem sufixo.
PRODUTOS_ANP: dict[str, str] = {
    "OLEO DIESEL S10": "diesel_s10",
    "OLEO DIESEL": "diesel_s500",
}

#: Teto do que se aceita baixar. A série do Brent inteira tem 1,8 MB; dez
#: vezes isso já não é a resposta que se pediu.
LIMITE_BYTES = 20 * 1024 * 1024

_UA = "Mozilla/5.0 (compatible; CORTEX-Sulista/1.0; +painel interno)"


class FormatoInesperado(ValueError):
    """A fonte respondeu, mas não no formato que este módulo sabe ler.

    É ERRO, e alto: planilha que mudou de coluna lida "do jeito que der" vira
    preço de distribuição publicado como preço de bomba, calado."""


def descrever_falha(exc: Exception) -> str:
    """O que se grava e se mostra de uma falha: o TIPO, e o código HTTP quando
    houver. Nunca `str(exc)` de rede (ver o cabeçalho)."""
    # A exceção que já sabe se dizer em uma linha diz (a TomTom sem crédito:
    # "TomTom sem créditos no produto de trânsito", e não "TomTomIndisponivel").
    rotulo = getattr(exc, "rotulo_curto", None)
    if rotulo:
        return str(rotulo)[:200]
    codigo = getattr(exc, "code", None)
    if isinstance(exc, FormatoInesperado):
        return f"formato inesperado: {exc}"[:200]
    return f"{type(exc).__name__} {codigo}" if codigo else type(exc).__name__


def baixar(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=_tls.contexto()) as r:
        corpo = r.read(LIMITE_BYTES + 1)
    if len(corpo) > LIMITE_BYTES:
        raise FormatoInesperado("resposta maior que o teto de 20 MB")
    return corpo


def url_noticias(tema: str) -> str:
    return URL_NOTICIAS.format(q=urllib.parse.quote(TEMAS[tema]["busca"]))


def url_ptax(ini: date, fim: date) -> str:
    return URL_PTAX.format(ini=ini.strftime("%d/%m/%Y"), fim=fim.strftime("%d/%m/%Y"))


def url_yahoo(serie: str, janela: str = "2y") -> str:
    return URL_YAHOO.format(simbolo=urllib.parse.quote(SIMBOLOS_YAHOO[serie]),
                            janela=janela)


# ------------------------------------------------------------------ leitores

def _norm(txt) -> str:
    n = unicodedata.normalize("NFD", str(txt or ""))
    return " ".join("".join(c for c in n if unicodedata.category(c) != "Mn").upper().split())


def _data(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(v.strip()[:10], fmt).date()
            except ValueError:
                pass
    return None


def _num(v) -> float | None:
    """A planilha escreve '-' onde não há medição (o preço de distribuição
    deixou de ser coletado em ago/2020). Isso é AUSÊNCIA, e vira None — zero
    seria um preço."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


#: As colunas que se leem, pelo cabeçalho NORMALIZADO — nunca pela posição. Se
#: a ANP inserir uma coluna, a leitura por posição passaria a publicar o
#: desvio-padrão como preço médio, sem erro nenhum.
_COLUNAS_ANP = {
    "semana_inicio": "DATA INICIAL",
    "semana_fim": "DATA FINAL",
    "produto": "PRODUTO",
    "postos": "NUMERO DE POSTOS PESQUISADOS",
    "unidade": "UNIDADE DE MEDIDA",
    "preco_revenda": "PRECO MEDIO REVENDA",
    "preco_min": "PRECO MINIMO REVENDA",
    "preco_max": "PRECO MAXIMO REVENDA",
    "preco_distribuicao": "PRECO MEDIO DISTRIBUICAO",
}


def ler_anp(conteudo: bytes) -> list[dict]:
    """As linhas de diesel da planilha semanal da ANP."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise FormatoInesperado(f"a planilha não abriu ({type(exc).__name__})") from exc
    try:
        ws = wb[wb.sheetnames[0]]
        idx: dict[str, int] | None = None
        saida: list[dict] = []
        for linha in ws.iter_rows(values_only=True):
            if not linha:
                continue
            if idx is None:
                if _norm(linha[0]) == "DATA INICIAL":
                    cab = [_norm(c) for c in linha]
                    falta = [n for n in _COLUNAS_ANP.values() if n not in cab]
                    if falta:
                        raise FormatoInesperado("coluna ausente: " + ", ".join(falta))
                    idx = {k: cab.index(n) for k, n in _COLUNAS_ANP.items()}
                continue
            produto = PRODUTOS_ANP.get(_norm(linha[idx["produto"]]))
            if not produto:
                continue
            fim = _data(linha[idx["semana_fim"]])
            if fim is None:
                continue
            saida.append({
                "produto": produto,
                "semana_inicio": _data(linha[idx["semana_inicio"]]),
                "semana_fim": fim,
                "postos": int(_num(linha[idx["postos"]]) or 0) or None,
                "unidade": str(linha[idx["unidade"]] or "").strip(),
                "preco_revenda": _num(linha[idx["preco_revenda"]]),
                "preco_min": _num(linha[idx["preco_min"]]),
                "preco_max": _num(linha[idx["preco_max"]]),
                "preco_distribuicao": _num(linha[idx["preco_distribuicao"]]),
            })
        if idx is None:
            raise FormatoInesperado("o cabeçalho 'DATA INICIAL' não foi encontrado")
        return saida
    finally:
        wb.close()


def ler_yahoo(conteudo: bytes) -> dict:
    """`{"pontos": [(dia, fechamento)], "agora": {...}}` do gráfico do Yahoo.

    O DIA DE CADA BARRA SAI NO FUSO DA BOLSA (`exchangeTimezoneName`), não no
    nosso nem em UTC: a barra do pregão de Nova York começa à meia-noite de lá,
    que é 1h da manhã aqui — convertida em UTC ela cairia no dia certo por
    sorte, e em Londres (o dólar) cairia no dia seguinte no horário de verão.

    `agora` é o `regularMarketPrice` com o `regularMarketTime` — a hora do
    ÚLTIMO NEGÓCIO, e não a da coleta. Num sábado ela diz sexta à tarde, e a
    tela repete isso em vez de chamar o fechamento de sexta de "agora".

    Barra com fechamento nulo (feriado, pregão sem negócio) sai; zero seria um
    preço.
    """
    try:
        corpo = json.loads(conteudo)
        grafico = corpo["chart"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FormatoInesperado("o Yahoo não respondeu o JSON do gráfico") from exc
    if grafico.get("error"):
        raise FormatoInesperado("o Yahoo recusou: %s"
                                % str((grafico["error"] or {}).get("code", "erro"))[:60])
    try:
        r = grafico["result"][0]
        meta = r["meta"]
        fechamentos = r["indicators"]["quote"][0]["close"]
        preco, momento = meta["regularMarketPrice"], meta["regularMarketTime"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FormatoInesperado("gráfico do Yahoo sem preço ou sem série") from exc
    from zoneinfo import ZoneInfo
    try:
        fuso = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    except Exception:  # noqa: BLE001
        fuso = timezone.utc
    pontos = []
    for t, c in zip(r.get("timestamp") or [], fechamentos):
        n = _num(c)
        if n is not None and isinstance(t, (int, float)):
            pontos.append((datetime.fromtimestamp(t, fuso).date(), n))
    return {"pontos": pontos,
            "agora": {"valor": float(preco),
                      "momento": datetime.fromtimestamp(momento, timezone.utc),
                      "moeda": meta.get("currency"),
                      "simbolo": meta.get("symbol")}}


def ler_sgs(conteudo: bytes) -> list[tuple[date, float]]:
    """Série do SGS do Banco Central: `[{"data": "dd/mm/aaaa", "valor": "5.0962"}]`.

    Erro do SGS chega com HTTP 200 e um OBJETO no lugar da lista (ou uma
    página HTML) — por isso a forma se confere, e não só o código."""
    try:
        valores = json.loads(conteudo)
    except ValueError as exc:
        raise FormatoInesperado("o SGS não respondeu JSON") from exc
    if not isinstance(valores, list):
        raise FormatoInesperado("o SGS respondeu um objeto, não a série")
    saida = []
    for v in valores:
        n, d = _num(v.get("valor")), _data(v.get("data"))
        if n is not None and d is not None:
            saida.append((d, n))
    return saida


def ler_rss(conteudo: bytes) -> list[dict]:
    """Itens de um RSS do Google Notícias.

    O título chega como "Manchete - Veículo"; o veículo também vem em
    `<source>`, então o sufixo sai do título para não aparecer duas vezes.
    Link que não seja https não entra — ele vira `href` na tela.
    """
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError as exc:
        raise FormatoInesperado("o RSS não é XML válido") from exc
    if raiz.find("channel") is None:
        raise FormatoInesperado("RSS sem <channel>")
    saida = []
    for it in raiz.iter("item"):
        titulo = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        fonte = " ".join((it.findtext("source") or "").split())
        guid = (it.findtext("guid") or link).strip()
        try:
            quando = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            quando = None
        if quando is not None and quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        if fonte and titulo.endswith(" - " + fonte):
            titulo = titulo[: -len(" - " + fonte)].rstrip()
        if not titulo or not link.startswith("https://") or quando is None:
            continue
        saida.append({"guid": guid[:500], "titulo": titulo[:400],
                      "fonte": fonte[:120] or None, "link": link[:2000],
                      "publicada_em": quando})
    return saida
