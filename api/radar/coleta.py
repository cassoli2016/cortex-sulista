# -*- coding: utf-8 -*-
"""Grava o que as fontes públicas publicaram. Idempotente, com cadência.

A CADÊNCIA É DE CADA FONTE, e sai do ritmo dela, não do relógio da thread:

- a ANP publica UMA vez por semana (a pesquisa fecha no sábado e sai na
  sexta seguinte). Olhar de seis em seis horas é folga, não excesso — a
  planilha tem 464 KB;
- Brent e dólar são o preço de AGORA: todo ciclo (10 min), que é o atraso
  que a própria fonte já tem. Só a primeira carga pede dois anos de série; as
  seguintes pedem um mês (a série antiga não muda);
- a PTAX sai uma vez por dia útil, ao fim da tarde. Três horas;
- rodovias (TomTom): 90 minutos, e o limite é a FRANQUIA GRÁTIS, que é
  mensal — 2.500 consultas, com teto conferido antes de cada passada
  (`rodovias.py`);
- frota (a lentidão medida pelos nossos caminhões nos mesmos corredores): todo
  ciclo, porque a consulta é ao nosso ERP (`frota.py`);
- notícia é o que envelhece em horas: meia hora (reforma e ANTT, uma).

A thread acorda de dez em dez minutos e só busca a fonte VENCIDA — o que está
decidido pelo banco (`rad_coleta.tentativa_em`), e não pela memória do
processo: o AutoDeploy reinicia a API várias vezes por dia, e cada reinício
com a cadência em memória baixaria tudo de novo.

FALHA NÃO MARTELA: fonte que falhou volta a ser tentada em 30 minutos, não no
próximo ciclo. E falha NÃO APAGA: o que já estava gravado continua sendo o que
a tela mostra, com a data do dado à vista.

COLETA VAZIA NÃO É SUCESSO nas séries: planilha sem nenhuma linha de diesel é
formato quebrado, não "o diesel acabou". Nas notícias é outra coisa — busca sem
manchete nova é possível, e como a gravação só ACRESCENTA (não há snapshot que
se substitua), zero itens não apaga nada.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from .. import pglocal
from . import fontes, frota, rodovias

log = logging.getLogger("cortex.radar.coleta")

ESQUEMA: str | None = None

#: Um pouco ABAIXO do ciclo da thread (600 s), e não igual: com a cadência
#: exatamente no ciclo, qualquer atraso de milissegundos da passada anterior
#: faria a fonte "ainda não vencida" pular um ciclo inteiro, e o preço de
#: agora envelheceria vinte minutos em vez de dez.
CADENCIA_S: dict[str, int] = {
    "anp": 6 * 3600,
    "brent": 540,
    "dolar": 540,
    "ptax": 3 * 3600,
    # 90 min, e não 20: a franquia grátis de ocorrências da TomTom é de 2.500
    # consultas POR MÊS (`rodovias.TETO_MES`), e quatro corredores a cada 20
    # minutos a gastariam em nove dias.
    "rodovias": 90 * 60 - 60,
    # A frota é nossa e a consulta é ao ERP: todo ciclo, como o preço de agora.
    "frota": 540,
    **{f"noticias_{t}": 30 * 60 - 60 for t in fontes.TEMAS},
    "noticias_reforma": 60 * 60 - 60,
    "noticias_antt": 60 * 60 - 60,
}

#: Com menos pontos que isto guardados, a coleta de mercado pede dois anos
#: de série (primeira carga); com mais, pede um mês.
PONTOS_CARGA_COMPLETA = 300

#: Fonte que falhou espera isto, e não a cadência inteira nem o próximo ciclo.
RETENTATIVA_S = 30 * 60

#: FAIXA FÍSICA de cada número. Fora dela é leitura quebrada (célula trocada,
#: série em outra unidade), e a linha é descartada e CONTADA — nunca gravada.
#: Diesel acima de R$ 20/l ou Brent acima de US$ 300 não aconteceu nunca; um
#: dia pode, e aí a faixa se revê com a evidência na mão.
FAIXA: dict[str, tuple[float, float]] = {
    "diesel": (2.0, 20.0),
    "brent": (5.0, 300.0),
    "dolar": (1.0, 20.0),
    "ptax": (1.0, 20.0),
}

#: Quanto das séries diárias se guarda: três anos cobrem a comparação de 12
#: meses com folga, e é o que a tela desenha no máximo.
JANELA_SERIE_DIAS = 3 * 365 + 30
#: Manchete mais velha que isto não entra; mais velha que a poda, sai.
JANELA_NOTICIA_DIAS = 30
PODA_NOTICIA_DIAS = 90


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def estado(esquema: str | None = None) -> dict[str, dict]:
    linhas = pglocal.query("SELECT * FROM rad_coleta", esquema=_esq(esquema))
    return {l["fonte"]: l for l in linhas}


def _vencida(fonte: str, est: dict, agora: datetime) -> bool:
    e = est.get(fonte)
    if not e or not e.get("tentativa_em"):
        return True
    espera = CADENCIA_S[fonte] if e.get("ok") else RETENTATIVA_S
    return (agora - e["tentativa_em"]).total_seconds() >= espera


def _registrar(fonte: str, esquema: str | None, ok: bool, itens: int | None = None,
               descartados: int | None = None, erro: str | None = None,
               dado_ate: date | None = None) -> None:
    # A HORA VEM DO PYTHON, e não do `now()` do banco: é a mesma régua que
    # `_vencida` usa para comparar. Duas réguas — uma gravando, outra lendo —
    # fazem a cadência depender do acerto entre dois relógios.
    agora = _agora()
    pglocal.executar(
        """INSERT INTO rad_coleta (fonte, tentativa_em, sucesso_em, ok, itens,
                                   descartados, erro, dado_ate)
           VALUES (%s, %s, CASE WHEN %s THEN %s::timestamptz END, %s, %s, %s, %s, %s)
           ON CONFLICT (fonte) DO UPDATE SET
             tentativa_em = EXCLUDED.tentativa_em,
             sucesso_em   = COALESCE(EXCLUDED.sucesso_em, rad_coleta.sucesso_em),
             ok           = EXCLUDED.ok,
             itens        = CASE WHEN EXCLUDED.ok THEN EXCLUDED.itens
                                 ELSE rad_coleta.itens END,
             descartados  = CASE WHEN EXCLUDED.ok THEN EXCLUDED.descartados
                                 ELSE rad_coleta.descartados END,
             erro         = EXCLUDED.erro,
             dado_ate     = COALESCE(EXCLUDED.dado_ate, rad_coleta.dado_ate)""",
        (fonte, agora, ok, agora, ok, itens, descartados, erro, dado_ate),
        esquema=esquema)


def _dentro(valor: float | None, faixa: tuple[float, float]) -> bool:
    return valor is not None and faixa[0] <= valor <= faixa[1]


# ---------------------------------------------------------------- por fonte

def _anp(baixar, esquema) -> dict:
    linhas = fontes.ler_anp(baixar(fontes.URL_ANP, 90))
    boas = [l for l in linhas if _dentro(l["preco_revenda"], FAIXA["diesel"])]
    if not boas:
        raise fontes.FormatoInesperado("a planilha veio sem nenhuma linha de diesel")
    with pglocal.get_conn(esquema) as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO rad_combustivel
                 (produto, semana_fim, semana_inicio, postos, unidade,
                  preco_revenda, preco_min, preco_max, preco_distribuicao)
               VALUES (%(produto)s, %(semana_fim)s, %(semana_inicio)s, %(postos)s,
                       %(unidade)s, %(preco_revenda)s, %(preco_min)s, %(preco_max)s,
                       %(preco_distribuicao)s)
               ON CONFLICT (produto, semana_fim) DO UPDATE SET
                 semana_inicio = EXCLUDED.semana_inicio, postos = EXCLUDED.postos,
                 unidade = EXCLUDED.unidade, preco_revenda = EXCLUDED.preco_revenda,
                 preco_min = EXCLUDED.preco_min, preco_max = EXCLUDED.preco_max,
                 preco_distribuicao = EXCLUDED.preco_distribuicao,
                 coletado_em = now()""", boas)
    return {"itens": len(boas), "descartados": len(linhas) - len(boas),
            "dado_ate": max(l["semana_fim"] for l in boas)}


def _gravar_serie(serie: str, pontos: list[tuple[date, float]], esquema) -> dict:
    corte = _agora().date() - timedelta(days=JANELA_SERIE_DIAS)
    janela = [(d, v) for d, v in pontos if d >= corte]
    boas = [(d, v) for d, v in janela if _dentro(v, FAIXA[serie])]
    if not boas:
        raise fontes.FormatoInesperado(f"a série {serie} veio sem ponto nos últimos três anos")
    with pglocal.get_conn(esquema) as c, c.cursor() as cur:
        cur.executemany(
            """INSERT INTO rad_serie (serie, dia, valor) VALUES (%s, %s, %s)
               ON CONFLICT (serie, dia) DO UPDATE SET valor = EXCLUDED.valor,
                                                       coletado_em = now()""",
            [(serie, d, v) for d, v in boas])
    return {"itens": len(boas), "descartados": len(janela) - len(boas),
            "dado_ate": max(d for d, _ in boas)}


#: O fuso da bolsa de cada série, para ler o "dia" do último negócio.
FUSO_DA_SERIE = {"brent": "America/New_York", "dolar": "Europe/London"}


def _mercado(serie: str, baixar, esquema) -> dict:
    """Brent ou dólar: a série diária E o preço de agora, na mesma leitura."""
    n = (pglocal.um("SELECT count(*) AS n FROM rad_serie WHERE serie = %s",
                    (serie,), esquema=esquema) or {}).get("n") or 0
    janela = "2y" if n < PONTOS_CARGA_COMPLETA else "1mo"
    lido = fontes.ler_yahoo(baixar(fontes.url_yahoo(serie, janela), 30))
    agora = lido["agora"]
    if not _dentro(agora["valor"], FAIXA[serie]):
        raise fontes.FormatoInesperado(
            f"preço de agora fora da faixa física ({agora['valor']})")
    r = _gravar_serie(serie, lido["pontos"], esquema)
    pglocal.executar(
        """INSERT INTO rad_cotacao (serie, valor, momento, moeda, simbolo, fuso)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (serie) DO UPDATE SET valor = EXCLUDED.valor,
             momento = EXCLUDED.momento, moeda = EXCLUDED.moeda,
             simbolo = EXCLUDED.simbolo, fuso = EXCLUDED.fuso,
             coletado_em = now()""",
        (serie, agora["valor"], agora["momento"], agora.get("moeda"),
         agora.get("simbolo"), FUSO_DA_SERIE.get(serie)), esquema=esquema)
    return r


def _rodovias(esquema, consultar_tomtom=None) -> dict:
    """O RETRATO das ocorrências, substituído inteiro numa transação.

    ZERO BRUTO NOS QUATRO CORREDORES É SUSPEITO, não "estrada livre": a Grande
    SP sozinha nunca fica sem uma obra registrada. Aí a leitura é recusada e o
    retrato anterior fica. Zero DEPOIS do filtro é possível (madrugada), e esse
    retrato vazio é gravado — é a resposta verdadeira.
    """
    lido = rodovias.consultar(consultar_tomtom, esquema=esquema)
    if lido["brutos"] == 0:
        raise fontes.FormatoInesperado("zero ocorrências nos quatro corredores")
    linhas = []
    for ordem, i in enumerate(lido["itens"]):
        linhas.append({
            "regiao": i["regiao"], "ordem": ordem,
            "rodovias": " · ".join(i["rodovias"])[:200],
            "categoria": str(i["categoria_rotulo"])[:80],
            "bloqueia": bool(i["bloqueia"]),
            "descricao": (i.get("descricao") or "")[:300] or None,
            "de": (i.get("de") or "")[:200] or None,
            "para": (i.get("para") or "")[:200] or None,
            "atraso_s": int(i["atraso_s"]) if i.get("atraso_s") is not None else None,
            "magnitude": i.get("magnitude")})
    with pglocal.get_conn(esquema) as c:
        c.execute("DELETE FROM rad_rodovia")
        if linhas:
            with c.cursor() as cur:
                cur.executemany(
                    """INSERT INTO rad_rodovia (regiao, ordem, rodovias, categoria,
                         bloqueia, descricao, de, para, atraso_s, magnitude)
                       VALUES (%(regiao)s, %(ordem)s, %(rodovias)s, %(categoria)s,
                               %(bloqueia)s, %(descricao)s, %(de)s, %(para)s,
                               %(atraso_s)s, %(magnitude)s)""", linhas)
    return {"itens": len(linhas), "descartados": lido["brutos"] - len(linhas),
            "dado_ate": _agora().date()}


def _ptax(baixar, esquema) -> dict:
    hoje = _agora().date()
    url = fontes.url_ptax(hoje - timedelta(days=JANELA_SERIE_DIAS), hoje)
    return _gravar_serie("ptax", fontes.ler_sgs(baixar(url, 45)), esquema)


def _noticias(tema: str, baixar, esquema) -> dict:
    itens = fontes.ler_rss(baixar(fontes.url_noticias(tema), 30))
    corte = _agora() - timedelta(days=JANELA_NOTICIA_DIAS)
    novas = [dict(i, tema=tema) for i in itens if i["publicada_em"] >= corte]
    with pglocal.get_conn(esquema) as c:
        if novas:
            with c.cursor() as cur:
                cur.executemany(
                    """INSERT INTO rad_noticia (tema, guid, titulo, fonte, link, publicada_em)
                       VALUES (%(tema)s, %(guid)s, %(titulo)s, %(fonte)s, %(link)s,
                               %(publicada_em)s)
                       ON CONFLICT (tema, guid) DO UPDATE SET
                         titulo = EXCLUDED.titulo, fonte = EXCLUDED.fonte,
                         link = EXCLUDED.link, publicada_em = EXCLUDED.publicada_em,
                         visto_em = now()""", novas)
        c.execute("DELETE FROM rad_noticia WHERE tema = %s AND publicada_em < %s",
                  (tema, _agora() - timedelta(days=PODA_NOTICIA_DIAS)))
    return {"itens": len(novas), "descartados": len(itens) - len(novas),
            "dado_ate": max(i["publicada_em"] for i in novas).date() if novas else None}


def _frota(esquema, ler_frota=None) -> dict:
    """O RETRATO da nossa frota nos corredores (`frota.py`), substituído
    inteiro numa transação. Sem caminhão nenhum nos corredores (madrugada), o
    retrato zerado é gravado: é a resposta verdadeira. Falha levanta ANTES da
    transação, e o retrato anterior fica."""
    linhas = (ler_frota or frota.ler)()
    with pglocal.get_conn(esquema) as c:
        c.execute("DELETE FROM rad_frota")
        with c.cursor() as cur:
            cur.executemany(
                """INSERT INTO rad_frota (regiao, caminhoes, andando, lentos, parados,
                     indefinidos, lento_max_min, vel_lentos)
                   VALUES (%(regiao)s, %(caminhoes)s, %(andando)s, %(lentos)s,
                           %(parados)s, %(indefinidos)s, %(lento_max_min)s,
                           %(vel_lentos)s)""", linhas)
    return {"itens": sum(l["caminhoes"] for l in linhas), "dado_ate": _agora().date()}


def _plano(baixar, esquema, consultar_tomtom=None,
           ler_frota=None) -> list[tuple[str, object]]:
    plano = [("anp", lambda: _anp(baixar, esquema)),
             ("brent", lambda: _mercado("brent", baixar, esquema)),
             ("dolar", lambda: _mercado("dolar", baixar, esquema)),
             ("ptax", lambda: _ptax(baixar, esquema)),
             ("frota", lambda: _frota(esquema, ler_frota))]
    # Sem TomTom a fonte nem entra no plano: não é falha, é recurso que a
    # instalação não tem — e registrá-la como erro a cada 20 min pintaria a
    # Saúde de vermelho por um motivo que ninguém precisa consertar.
    if consultar_tomtom is not None or rodovias.ativo():
        plano.append(("rodovias", lambda: _rodovias(esquema, consultar_tomtom)))
    for tema in fontes.TEMAS:
        plano.append((f"noticias_{tema}",
                      lambda t=tema: _noticias(t, baixar, esquema)))
    return plano


def coletar(esquema: str | None = None, forcar: bool = False, baixar=None,
            so: set[str] | None = None, consultar_tomtom=None,
            ler_frota=None) -> dict[str, str]:
    """Uma passada por todas as fontes vencidas. `{fonte: ok|erro|no_prazo}`.

    Uma fonte que falha não impede as outras, e NUNCA levanta para quem chamou
    por causa de uma delas — a thread que chama isto não pode morrer porque o
    gov.br teve uma manhã ruim. `baixar`, `consultar_tomtom` e `ler_frota`
    existem para o teste: nenhum teste sai para a rede nem consulta o ERP.
    """
    esq = _esq(esquema)
    baixar = baixar or fontes.baixar
    est = estado(esq)
    agora = _agora()
    resultado: dict[str, str] = {}
    for fonte, fn in _plano(baixar, esq, consultar_tomtom, ler_frota):
        if so is not None and fonte not in so:
            continue
        if not forcar and not _vencida(fonte, est, agora):
            resultado[fonte] = "no_prazo"
            continue
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001
            desc = fontes.descrever_falha(exc)
            log.warning("radar: coleta de %s falhou: %s", fonte, desc)
            try:
                _registrar(fonte, esq, False, erro=desc)
            except Exception as exc2:  # noqa: BLE001
                log.warning("radar: nao deu para registrar a falha de %s: %s",
                            fonte, type(exc2).__name__)
            resultado[fonte] = "erro"
            continue
        _registrar(fonte, esq, True, **r)
        resultado[fonte] = "ok"
    return resultado
