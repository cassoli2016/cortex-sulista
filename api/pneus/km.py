# -*- coding: utf-8 -*-
"""O KM RODADO por veículo — o denominador que faltava no módulo de pneus.

POR QUE ISTO EXISTE. Pneu não se mede em meses, se mede em quilômetros. Sem km
não há CPK, e sem CPK o módulo é um inventário bonito que não decide compra
nenhuma. A Prolog não traz km: `km_veiculo` estava NULO nos 2.497 eventos
importados, 100%. Então o km sai de casa.

SÃO DOIS PROBLEMAS DIFERENTES, e tratá-los como um só é o erro que faz o número
parecer certo e não ser:

**Tração (tem motor).** O odômetro vem do abastecimento —
`sulista.ctaplus_abastecimentos` guarda `veiculo_nome`, `odometro` e a data,
89.602 leituras desde 05/2023, mediana de 67 leituras por placa por ano (uma
por semana). Nenhum odômetro nulo. Cobertura medida sobre os pneus instalados
em tração: **516 de 537 (96%)**.

**Implemento (sem motor).** Carreta não abastece — por isso a cobertura crua
dava 22% e parecia um desastre. Não era: o denominador estava errado, a lição
do rastreador desta casa. O km da carreta é o km do CAVALO que a puxou, nos
dias em que puxou; o engate está em `manifesto` (`veiculo` × `carreta1..3`),
e **221 das 225 carretas com pneu (98%)** aparecem lá nos últimos 12 meses.

AS DUAS ARMADILHAS QUE JÁ CUSTARAM UM NÚMERO ERRADO AQUI:

1. **Somar por manifesto conta o mesmo dia várias vezes.** O mesmo cavalo puxa
   a mesma carreta em três manifestos no mesmo dia, e a soma ingênua triplica o
   dia. Medido: mediana de 65.681 km/ano que caiu para 36.812 ao deduplicar por
   `(carreta, cavalo, dia)` — inflação de 78%, e o número inflado era
   PERFEITAMENTE plausível. É a lição do join com histórico, na mesma forma.
2. **Um dia de cavalo não vira dois dias inteiros de carreta.** Bitrem, ou
   troca de carreta no meio do dia: o km do dia se REPARTE entre as carretas
   engatadas. Sem isso a frota de carretas somaria mais km do que os cavalos
   rodaram, que é impossível — e é exatamente essa impossibilidade que o
   `conferir()` daqui mede.

FAIXA FÍSICA VALIDA A LEITURA. Odômetro que anda para trás é troca de painel ou
digitação; mais de 1.500 km entre dois abastecimentos por dia decorrido não é
caminhão. Os dois casos SAEM da série em vez de virar km — 1,6% e 1,4% dos
pares, medidos. O que sobra é dito: cada resposta traz de quantos dias da
janela houve leitura, e por qual método.
"""
from __future__ import annotations

import datetime
import logging
from collections import defaultdict

from api import db, queries

log = logging.getLogger("cortex.pneus.km")

#: Teto físico de km por dia entre duas leituras de odômetro. Um cavalo em
#: dupla pegada faz ~1.000 km/dia; 1.500 é folga sobre isso e ainda pega o
#: dedo trocado (um zero a mais vira 10.000).
KM_DIA_MAX = 1500

#: Engate mais longo que isto não é uma viagem, é manifesto que ninguém
#: encerrou. Espalhar o km por 400 dias de "engate" atribuiria à carreta um
#: período em que ela pode ter ficado no pátio.
ENGATE_DIAS_MAX = 30

# O AVA é PostgreSQL 9.3: sem `FILTER (WHERE …)`, mas com window function
# (existe desde o 8.4). A regexp existe porque `odometro` é texto no cadastro e
# chega com ponto de milhar em parte das linhas.
TRECHOS_SQL = r"""
WITH s AS (
  SELECT upper(trim(veiculo_nome)) AS placa,
         data_inicio_abastecimento::date AS d,
         max(NULLIF(REGEXP_REPLACE(odometro::text,'\D','','g'),'')::bigint) AS odo
  FROM sulista.ctaplus_abastecimentos
  WHERE data_inicio_abastecimento >= %(de)s
    AND data_inicio_abastecimento <  %(ate)s
  GROUP BY 1, 2
), p AS (
  SELECT placa, d, odo,
         lag(odo) OVER (PARTITION BY placa ORDER BY d) AS odo_ant,
         lag(d)   OVER (PARTITION BY placa ORDER BY d) AS d_ant
  FROM s WHERE odo > 0
)
SELECT placa, d_ant AS de, d AS ate, (odo - odo_ant) AS km, (d - d_ant) AS dias
FROM p
WHERE odo_ant IS NOT NULL
  AND odo > odo_ant            -- odômetro que regride é troca de painel
  AND d > d_ant
  AND (odo - odo_ant) <= %(teto)s * (d - d_ant)
"""

ENGATES_SQL = """
SELECT upper(trim(m.veiculo))  AS cavalo,
       upper(trim(c.carreta))  AS carreta,
       coalesce(m.dtsaida, m.dtemissao)::date            AS de,
       coalesce(m.dtchegada, m.dtsaida, m.dtemissao)::date AS ate
FROM manifesto m
JOIN (SELECT 1 AS i UNION ALL SELECT 2 UNION ALL SELECT 3) n ON true
JOIN LATERAL (SELECT CASE n.i WHEN 1 THEN m.carreta1
                              WHEN 2 THEN m.carreta2
                              ELSE m.carreta3 END AS carreta) c ON true
WHERE m.dtemissao >= %(de)s AND m.dtemissao < %(ate)s
  AND m.dtcancelamento IS NULL
  AND trim(coalesce(c.carreta,'')) <> ''
  AND trim(coalesce(m.veiculo,'')) <> ''
"""


def _dias(de: datetime.date, ate: datetime.date):
    d = de
    while d <= ate:
        yield d
        d += datetime.timedelta(days=1)


def _km_por_dia_do_cavalo(de: datetime.date, ate: datetime.date) -> dict:
    """`(placa, dia) -> km`, espalhando cada trecho pelos dias que ele cobre.

    O abastecimento é semanal, então o km de um trecho é o km de vários dias.
    Espalhar uniformemente é a única distribuição defensável sem telemetria — e
    ela não distorce a SOMA, que é o que o pneu consome.
    """
    fora: dict = {}
    for t in db.query(TRECHOS_SQL, {"de": de, "ate": ate, "teto": KM_DIA_MAX}):
        por_dia = float(t["km"]) / t["dias"]
        d = t["de"]
        for _ in range(t["dias"]):
            d += datetime.timedelta(days=1)
            fora[(t["placa"], d)] = fora.get((t["placa"], d), 0.0) + por_dia
    return fora


def _km_das_carretas(km_cavalo: dict, de, ate) -> tuple[dict, dict]:
    """Km e dias rodados por carreta, pelo engate. Devolve (km, dias)."""
    # PARES ÚNICOS primeiro. Somar direto sobre os manifestos conta o mesmo dia
    # duas ou três vezes — 78% de inflação, medida.
    pares: set = set()
    for e in db.query(ENGATES_SQL, {"de": de, "ate": ate}):
        if not e["de"] or not e["ate"] or e["ate"] < e["de"]:
            continue
        if (e["ate"] - e["de"]).days >= ENGATE_DIAS_MAX:
            continue
        for d in _dias(e["de"], e["ate"]):
            pares.add((e["carreta"], e["cavalo"], d))

    por_cavalo_dia = defaultdict(list)
    for carreta, cavalo, d in pares:
        por_cavalo_dia[(cavalo, d)].append(carreta)

    por_dia: dict = defaultdict(dict)
    for (cavalo, d), carretas in por_cavalo_dia.items():
        k = km_cavalo.get((cavalo, d))
        if not k:
            continue
        # O DIA SE REPARTE. Duas carretas no mesmo dia do mesmo cavalo é bitrem
        # ou troca no meio do dia — não é o dobro de km rodado.
        quota = k / len(carretas)
        for carreta in carretas:
            por_dia[carreta][d] = por_dia[carreta].get(d, 0.0) + quota
    # O TOTAL SAI DO DIÁRIO, nunca de uma segunda contagem em paralelo: dois
    # caminhos para o mesmo número é o jeito de eles divergirem em silêncio.
    km = {p: sum(v.values()) for p, v in por_dia.items()}
    return km, dict(por_dia)


def _janela(dias: int) -> tuple[datetime.date, datetime.date]:
    hoje = datetime.date.today()
    return hoje - datetime.timedelta(days=dias), hoje + datetime.timedelta(days=1)


def _calcular(dias_janela: int) -> dict:
    de, ate = _janela(dias_janela)
    km_cavalo_dia = _km_por_dia_do_cavalo(de, ate)

    tracao: dict = {}
    dias_tracao: dict = defaultdict(set)
    for (placa, d), k in km_cavalo_dia.items():
        tracao[placa] = tracao.get(placa, 0.0) + k
        dias_tracao[placa].add(d)

    carreta, carreta_por_dia = _km_das_carretas(km_cavalo_dia, de, ate)

    veiculos: dict = {}
    for placa, k in tracao.items():
        veiculos[placa] = {"km": round(k, 1), "metodo": "odometro",
                           "dias_com_dado": len(dias_tracao[placa])}
    for placa, k in carreta.items():
        # UMA PLACA NÃO É AS DUAS COISAS. Se ela abastece, é tração e o
        # odômetro manda: ele é medição direta, o engate é atribuição.
        if placa in veiculos:
            continue
        veiculos[placa] = {"km": round(k, 1), "metodo": "engate",
                           "dias_com_dado": len(carreta_por_dia[placa])}

    # O MAPA POR DIA VAI JUNTO, e não é desperdício: é ele que permite pedir o
    # km de UM PEDAÇO da janela — desde a instalação daquele pneu, por exemplo,
    # que é o único recorte que interessa ao CPK. Sem ele, cada pergunta dessas
    # seria uma ida nova ao ERP.
    por_dia: dict = defaultdict(dict)
    for (placa, d), k in km_cavalo_dia.items():
        por_dia[placa][d.isoformat()] = round(k, 1)
    for placa, ds in carreta_por_dia.items():
        # O ODÔMETRO MANDA quando existe: ele é medição direta, o engate é
        # atribuição. Uma placa que abastece não é recalculada pelo engate.
        if placa in por_dia:
            continue
        por_dia[placa] = {d.isoformat(): round(k, 1) for d, k in ds.items()}

    return {"janela_dias": dias_janela, "de": de.isoformat(),
            "ate": (ate - datetime.timedelta(days=1)).isoformat(),
            "veiculos": veiculos, "por_dia": dict(por_dia),
            "km_tracao_total": round(sum(tracao.values()), 1),
            "km_carreta_total": round(sum(carreta.values()), 1),
            "placas_tracao": len(tracao), "placas_carreta": len(carreta)}


# TTL LONGO de propósito: o abastecimento entra uma vez por semana por placa, e
# o AVA é réplica de produção compartilhada com um Power BI. Recalcular isto a
# cada abertura de tela seria pagar 0,8 s de banco alheio para ver o mesmo
# número. `velha_ate` mantém a última leitura boa servida COM TARJA quando o
# ERP tem um dia ruim — número velho servido calado é pior que tela vazia.
obter = queries.cached(3600, velha_ate=6 * 3600)(_calcular)


def de_placas(placas, dias_janela: int = 365) -> dict:
    """O km de um punhado de placas, com a cobertura DITA.

    Quem não aparece volta com `km: None` e o motivo — nunca com zero. Zero que
    é ausência de leitura não é veículo parado, e essa diferença decide troca de
    pneu.
    """
    d = obter(dias_janela)
    todos = d.get("veiculos") or {}
    fora = {}
    for p in placas:
        chave = (p or "").strip().upper()
        v = todos.get(chave)
        fora[chave] = v or {"km": None, "metodo": None, "dias_com_dado": 0,
                            "motivo": "sem leitura de odômetro nem engate "
                                      "na janela"}
    achou = sum(1 for v in fora.values() if v.get("km") is not None)
    return {"veiculos": fora, "pedidas": len(fora), "com_km": achou,
            "janela_dias": dias_janela,
            "leitura_velha": d.get("leitura_velha"),
            "leitura_em": d.get("leitura_em")}


def conferir(dias_janela: int = 365) -> dict:
    """O segundo caminho para o mesmo número — é ele que denuncia o erro.

    A frota de CARRETAS não pode ter rodado mais que a de CAVALOS: toda carreta
    só anda puxada. Se esta razão passar de 100%, a atribuição está contando
    dia duas vezes, e o total inflado seria plausível o bastante para ninguém
    reparar. Foi assim que a inflação de 78% apareceu.
    """
    d = obter(dias_janela)
    cav, car = d["km_tracao_total"], d["km_carreta_total"]
    razao = (car / cav * 100.0) if cav else None
    return {"km_cavalos": cav, "km_carretas": car,
            "razao_pct": round(razao, 1) if razao is not None else None,
            "ok": razao is not None and razao <= 100.0,
            "placas_tracao": d["placas_tracao"],
            "placas_carreta": d["placas_carreta"],
            "explicacao": "carreta só anda puxada: o km atribuído a elas tem "
                          "de ser MENOR que o rodado pelos cavalos"}


def no_periodo(placa: str, de, ate=None, dias_janela: int = 365) -> dict:
    """O km de UMA placa entre duas datas, dentro da janela já calculada.

    É este o recorte que interessa ao pneu: km desde a INSTALAÇÃO dele, não km
    do ano. Um pneu montado há três semanas num cavalo que roda 200 mil km/ano
    não rodou 200 mil km.

    Fora da janela cacheada a resposta é `None` com o motivo — nunca um número
    truncado se apresentando como o total. Truncar aqui daria um CPK baixo
    demais em pneu antigo, que é justamente o pneu sobre o qual se decide.
    """
    d = obter(dias_janela)
    dias = (d.get("por_dia") or {}).get((placa or "").strip().upper())
    if not dias:
        return {"km": None, "dias_com_dado": 0,
                "motivo": "sem leitura de odômetro nem engate na janela"}

    if isinstance(de, str):
        de = datetime.date.fromisoformat(de[:10])
    if isinstance(ate, str):
        ate = datetime.date.fromisoformat(ate[:10])
    if isinstance(de, datetime.datetime):
        de = de.date()
    if isinstance(ate, datetime.datetime):
        ate = ate.date()
    ate = ate or datetime.date.today()

    inicio_janela = datetime.date.fromisoformat(d["de"])
    truncado = de < inicio_janela
    de_efetivo = max(de, inicio_janela)

    total = 0.0
    n = 0
    for iso, k in dias.items():
        dia = datetime.date.fromisoformat(iso)
        if de_efetivo <= dia <= ate:
            total += k or 0.0
            n += 1
    fora = {"km": round(total, 1), "dias_com_dado": n,
            "de": de_efetivo.isoformat(), "ate": ate.isoformat(),
            "metodo": (d["veiculos"].get((placa or "").strip().upper())
                       or {}).get("metodo")}
    if truncado:
        # SE DECLARA em vez de mentir por omissão: o pedaço anterior à janela
        # não foi medido, e um CPK calculado sobre isto seria otimista.
        fora["truncado_em"] = inicio_janela.isoformat()
        fora["motivo"] = ("o período começa antes da janela medida (%s) — "
                          "o km é PARCIAL" % inicio_janela.isoformat())
    return fora
