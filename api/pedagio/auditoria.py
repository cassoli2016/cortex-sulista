# -*- coding: utf-8 -*-
"""Auditoria das travessias de pedágio: o que contestar e o que cobrar de volta.

DUAS PERGUNTAS DIFERENTES, COM DONOS DIFERENTES
===============================================
Esta camada separa de propósito o que se discute com o FORNECEDOR do que se
discute com a OPERAÇÃO, porque misturar os dois produz uma lista que ninguém
consegue acionar:

  * **Contestação** — a administradora cobrou o que não devia. A prova sai da
    própria fatura e não depende de nada do ERP: a mesma placa cobrada duas
    vezes na mesma praça em cinco minutos, ou lida no mesmo segundo em duas
    praças distantes. Vai para o chamado no Sem Parar.
  * **Eixo não levantado** — a cobrança está certa e o custo era evitável. A
    praça leu o que estava no chão; quem podia mudar isso era o motorista. Vai
    para a operação, com placa, viagem e condutor.

MEDIDO EM SETE FATURAS (fev a ago/2026, 119.856 travessias de tag)
=================================================================
    duas cobranças no MESMO SEGUNDO ..... 279 pares      R$ 6.479
        com categorias que se contradizem 273 pares      R$ 6.379
        idênticas                           6 pares      R$   100
    cobrança repetida em até 5 min .......   4 pares      R$    98
    leitura no mesmo segundo em praças
        diferentes .......................   1 par        R$    48
    eixo não levantado ................... 412 travessias R$ 3.190

Cerca de R$ 1.400 por mês sobre R$ 477 mil. Pequeno em proporção e atribuível a
uma praça, uma placa e um motorista — que é o que torna a conversa possível.

O QUE PARECIA DUPLICATA É PIOR QUE DUPLICATA
============================================
A primeira leitura desta análise foi "283 cobranças duplicadas em até 5
minutos". Estava mal enquadrada, e a checagem que a desfez vale mais que o
número: **279 dos 283 pares são no MESMO SEGUNDO, e em 273 deles as duas linhas
cobram CATEGORIAS DIFERENTES** — (5,4), (6,5), (7,6), sempre distando um ou dois
eixos.

Duas cobranças idênticas são uma linha repetida. Duas cobranças no mesmo
instante que DISCORDAM sobre quantos eixos o veículo tem são o equipamento
lendo o mesmo caminhão de duas formas e faturando as duas. O veículo passou uma
vez e pagou por nove eixos.

Isso também explica a concentração: **243 dos 283 estão na SP-021**, o Rodoanel,
que é free flow — pórtico, sem cancela, com a categoria inferida por sensor. É
onde esse modo de falhar existe.

Por isso a tela separa os pares IDÊNTICOS dos DIVERGENTES em vez de somar tudo
como "duplicata": o argumento da contestação é diferente, e o segundo é mais
forte que o primeiro.

A RÉGUA DO EIXO CONTROLA A COMPOSIÇÃO, E SEM ISSO ELA MENTE
===========================================================
A tentação é comparar os eixos cobrados da mesma placa entre viagens. NÃO
FUNCIONA: a tag fica no CAVALO, e ele troca de implemento ao longo do mês. As
mesmas placas aparecem de 1 a 9 eixos nas sete faturas, e caminhão nenhum
levanta seis eixos — a variação é a composição, não o eixo suspenso. Uma versão
anterior desta análise concluiu "a frota levanta eixo em 58% das travessias" a
partir disso, e estava simplesmente errada.

O que controla a composição é o MANIFESTO: dentro dele a carreta é a mesma, do
começo ao fim. Então:

    valor evitável = (eixos_cobrados - menor_eixo_do_manifesto)
                     / eixos_cobrados * valor

E a distribuição confirma a leitura: dos 4.939 manifestos com eixos variando,
**3.418 (69%) variam em exatamente UM eixo** — que é a assinatura do eixo que
sobe e desce. Amplitude acima de 2 é engate e desengate de carreta no meio da
viagem, não eixo suspenso, e fica de fora (`AMPLITUDE_MAX`).

O apontamento só existe quando o PRÓPRIO veículo, na MESMA viagem, já cruzou
uma praça com menos eixo. Não é um alvo teórico: é a travessia irmã dele.

O QUE NÃO DÁ PARA SABER, E ESTÁ DITO NA TELA
============================================
  * `eixolevantadovalepedagio`, `idavaziovalepedagio` e `voltavaziovalepedagio`
    existem no manifesto e são **ZERO em 57.290 registros de 12 meses**. O ERP
    não registra se o eixo subiu. Mesma família dos três campos de pedágio que
    a Validação de Pedágio já denuncia como sempre vazios.
  * O acoplamento cavalo↔carreta no momento da travessia também não é
    registrado: `rebocado`/`rebocador` estão vazios em 700 de 1.443 veículos e
    a tabela do MDF-e guarda uma placa só. Não dá para afirmar "esta carreta
    tinha eixo levantável".
  * `pesototalbrutomercadoria` está preenchido em 70% dos manifestos, então
    peso zero às vezes é falta de preenchimento e não viagem vazia.
  * **33% das travessias não caem em manifesto nenhum.** Ali não se sabe se o
    veículo estava vazio, e elas ficam FORA da conta em vez de virar palpite —
    o número desta tela erra para baixo, de propósito.
"""
from __future__ import annotations

import collections
import logging

from api import pglocal

log = logging.getLogger(__name__)

ESQUEMA: str | None = None

# Um caminhão não cruza a mesma praça no mesmo sentido duas vezes em cinco
# minutos. As janelas maiores existem para a tela MOSTRAR a concentração, que
# é o que sustenta a leitura de duplicidade.
JANELAS_DUPLICADA = (5, 15, 60)
JANELA_CONTESTAR = 5

# Amplitude de eixo dentro de um manifesto. Até 2 é eixo suspenso; acima é
# troca de composição no meio da viagem, que não é falha de ninguém.
AMPLITUDE_MAX = 2


def _esq(esquema: str | None) -> str | None:
    return esquema if esquema is not None else ESQUEMA


def _filtro(competencia: str | None):
    if competencia:
        return "AND f.competencia = %(comp)s", {"comp": competencia}
    return "", {}


# ── o que se contesta com o fornecedor ──────────────────────────────────────

_DUPLICADAS_SQL = """
SELECT a.id, a.placa, a.praca, a.ts AS ts_2, b.ts AS ts_1,
       a.valor::float8 AS valor, a.eixos, a.categoria,
       b.valor::float8 AS valor_par, b.eixos AS eixos_par, b.categoria AS categoria_par,
       a.rodovia,
       round(extract(epoch FROM a.ts - b.ts) / 60.0)::int AS minutos
  FROM ped_travessias a
  JOIN ped_faturas f ON f.id = a.fatura_id
  JOIN ped_travessias b
    ON b.placa = a.placa AND b.praca = a.praca AND b.id <> a.id
   AND b.ts <= a.ts AND a.ts - b.ts <= make_interval(mins => %(jan)s)
   AND b.tipo = 'tag' AND b.dc = 'D'
 WHERE a.tipo = 'tag' AND a.dc = 'D' AND a.id > b.id
   {FILTRO}
 ORDER BY a.valor DESC
"""


def duplicadas(competencia: str | None = None, janela: int = JANELA_CONTESTAR,
               esquema: str | None = None) -> list[dict]:
    """Cobranças repetidas: mesma placa, mesma praça, dentro da janela.

    A praça já carrega o SENTIDO no texto, então duas leituras aqui são no
    mesmo sentido — ida e volta não colidem.

    Cada par sai CLASSIFICADO, porque os dois casos pedem argumentos
    diferentes na contestação:
      * `identica`   — mesma categoria e mesmo valor: linha repetida;
      * `divergente` — mesmo instante, categorias que se contradizem: o
        equipamento leu o mesmo caminhão de duas formas e faturou as duas.
        É o caso dominante (273 de 279) e o mais forte dos dois.
    """
    filtro, params = _filtro(competencia)
    params["jan"] = janela
    linhas = []
    for r in pglocal.query(_DUPLICADAS_SQL.replace("{FILTRO}", filtro), params,
                           esquema=_esq(esquema)):
        d = dict(r)
        mesmo_instante = d["ts_1"] == d["ts_2"]
        identica = (d["eixos"] == d["eixos_par"]
                    and abs(d["valor"] - d["valor_par"]) < 0.005)
        d["mesmo_instante"] = mesmo_instante
        d["tipo"] = ("identica" if identica else
                     "divergente" if mesmo_instante else "repetida")
        d["eixos_par"] = d["eixos_par"]
        linhas.append(d)
    return linhas


def concentracao_duplicadas(competencia: str | None = None,
                            esquema: str | None = None) -> list[dict]:
    """Quantos pares em cada janela — é isto que prova (ou desmente) a tese.

    Curva que cresce pouco = leitura dupla. Curva que cresce muito = travessia
    legítima, e aí o apontamento estaria errado.
    """
    out = []
    for jan in JANELAS_DUPLICADA:
        linhas = duplicadas(competencia, jan, esquema)
        out.append({"janela_min": jan, "travessias": len(linhas),
                    "valor": round(sum(x["valor"] for x in linhas), 2)})
    return out


_IMPOSSIVEIS_SQL = """
SELECT a.placa, a.ts, a.praca AS praca_a, b.praca AS praca_b,
       a.valor::float8 AS valor_a, b.valor::float8 AS valor_b,
       a.rodovia, abs(a.km - b.km)::float8 AS km_entre
  FROM ped_travessias a
  JOIN ped_faturas f ON f.id = a.fatura_id
  JOIN ped_travessias b
    ON b.placa = a.placa AND b.ts = a.ts AND b.praca <> a.praca AND b.id < a.id
   AND b.tipo = 'tag' AND b.dc = 'D'
 WHERE a.tipo = 'tag' AND a.dc = 'D'
   {FILTRO}
 ORDER BY a.valor + b.valor DESC
"""


def impossiveis(competencia: str | None = None,
                esquema: str | None = None) -> list[dict]:
    """A mesma placa lida no MESMO SEGUNDO em duas praças diferentes.

    Não há interpretação alternativa: uma das duas leituras é de outro veículo
    ou é erro do equipamento. É o achado mais limpo que esta fatura produz.
    """
    filtro, params = _filtro(competencia)
    return [dict(r) for r in pglocal.query(
        _IMPOSSIVEIS_SQL.replace("{FILTRO}", filtro), params or None,
        esquema=_esq(esquema))]


# ── o que se cobra da operação ──────────────────────────────────────────────

_TRAVESSIAS_SQL = """
SELECT t.id, t.placa, t.ts, t.praca, t.eixos, t.categoria, t.valor::float8 AS valor
  FROM ped_travessias t
  JOIN ped_faturas f ON f.id = t.fatura_id
 WHERE t.tipo = 'tag' AND t.dc = 'D' AND t.eixos IS NOT NULL AND t.eixos > 0
   {FILTRO}
"""

# O manifesto é do AVA e as travessias são do banco local: não há JOIN possível
# entre os dois bancos, então o cruzamento é em PYTHON — o mesmo caminho que a
# reconciliação de diárias já usa.
_MANIFESTOS_SQL = """
SELECT m.veiculo AS placa, m.numero, m.dtsaida, m.dtchegada, m.motorista,
       coalesce(m.pesototalbrutomercadoria, 0)::float8 AS peso
  FROM manifesto m
 WHERE m.veiculo = ANY(%(placas)s) AND m.semaforo = 1
   AND m.dtsaida IS NOT NULL AND m.dtchegada IS NOT NULL
   AND m.dtchegada >= %(de)s AND m.dtsaida <= %(ate)s
"""


def eixo_nao_levantado(competencia: str | None = None,
                       esquema: str | None = None) -> dict:
    """Travessias cobradas acima do menor eixo do PRÓPRIO manifesto.

    Ver o cabeçalho do módulo para por que a comparação é dentro do manifesto
    e não entre viagens. O resultado traz `cobertura`, que é o que impede o
    número de ser lido como se fosse a frota inteira: um terço das travessias
    não cai em manifesto nenhum, e essas ficam de fora.
    """
    from api import db

    filtro, params = _filtro(competencia)
    trav = pglocal.query(_TRAVESSIAS_SQL.replace("{FILTRO}", filtro),
                         params or None, esquema=_esq(esquema))
    if not trav:
        return {"vazio": True, "linhas": [], "motoristas": [], "cobertura": {}}

    placas = sorted({t["placa"] for t in trav})
    de = min(t["ts"] for t in trav)
    ate = max(t["ts"] for t in trav)
    try:
        mans = db.query(_MANIFESTOS_SQL,
                        {"placas": placas, "de": de, "ate": ate})
    except Exception as exc:  # noqa: BLE001
        # Sem o AVA não há manifesto, e sem manifesto não há como controlar a
        # composição. A tela DIZ isso — uma lista vazia se leria como "nenhum
        # caso", que é o oposto de "não deu para olhar".
        log.warning("auditoria de eixo sem o AVA: %s", exc)
        return {"erro": "sem_erp", "linhas": [], "motoristas": [],
                "cobertura": {"travessias": len(trav)}}

    por_placa: dict[str, list] = collections.defaultdict(list)
    for m in mans:
        por_placa[m["placa"]].append(m)

    # cada travessia no manifesto que a contém
    grupos: dict[tuple, list] = collections.defaultdict(list)
    dono: dict[tuple, dict] = {}
    fora = 0
    for t in trav:
        achou = None
        for m in por_placa.get(t["placa"], ()):
            if m["dtsaida"] <= t["ts"] <= m["dtchegada"]:
                achou = m
                break
        if achou is None:
            fora += 1
            continue
        k = (achou["placa"], achou["numero"])
        grupos[k].append(t)
        dono[k] = achou

    linhas = []
    descartados_amplitude = 0
    for k, ts in grupos.items():
        eixos = {x["eixos"] for x in ts}
        if len(eixos) < 2:
            continue
        menor, maior = min(eixos), max(eixos)
        if maior - menor > AMPLITUDE_MAX:
            descartados_amplitude += 1
            continue
        m = dono[k]
        # Só a viagem SEM CARGA DECLARADA: com carga, o eixo no chão é
        # obrigação, não desperdício.
        if m["peso"] > 0:
            continue
        for x in ts:
            if x["eixos"] <= menor:
                continue
            evitavel = round(x["valor"] * (x["eixos"] - menor) / x["eixos"], 2)
            linhas.append({
                "placa": x["placa"], "ts": x["ts"], "praca": x["praca"],
                "eixos_cobrados": x["eixos"], "eixos_minimos": menor,
                "categoria": x["categoria"], "valor": x["valor"],
                "evitavel": evitavel, "manifesto": m["numero"],
                "motorista": m["motorista"],
                "dtsaida": m["dtsaida"], "dtchegada": m["dtchegada"]})

    linhas.sort(key=lambda x: -x["evitavel"])
    por_mot: dict[str, dict] = {}
    for x in linhas:
        a = por_mot.setdefault(x["motorista"] or "—",
                               {"motorista": x["motorista"] or "—",
                                "travessias": 0, "evitavel": 0.0,
                                "placas": set()})
        a["travessias"] += 1
        a["evitavel"] += x["evitavel"]
        a["placas"].add(x["placa"])
    motoristas = sorted(
        ({"motorista": a["motorista"], "travessias": a["travessias"],
          "evitavel": round(a["evitavel"], 2), "placas": len(a["placas"])}
         for a in por_mot.values()),
        key=lambda x: -x["evitavel"])

    return {
        "vazio": not linhas, "linhas": linhas, "motoristas": motoristas,
        "travessias": len(linhas),
        "evitavel": round(sum(x["evitavel"] for x in linhas), 2),
        "cobertura": {
            "travessias": len(trav), "em_manifesto": len(trav) - fora,
            "fora_de_manifesto": fora,
            "pct_em_manifesto": round(100.0 * (len(trav) - fora) / len(trav), 1),
            "manifestos": len(grupos),
            "descartados_amplitude": descartados_amplitude},
    }


def resumo(competencia: str | None = None, esquema: str | None = None) -> dict:
    """Os dois blocos e o total acionável do mês."""
    dup = duplicadas(competencia, JANELA_CONTESTAR, esquema)
    imp = impossiveis(competencia, esquema)
    eixo = eixo_nao_levantado(competencia, esquema)
    v_dup = round(sum(x["valor"] for x in dup), 2)
    v_imp = round(sum(min(x["valor_a"], x["valor_b"]) for x in imp), 2)

    # A quebra por TIPO é o que a contestação usa: o argumento de "linha
    # repetida" e o de "o equipamento discordou de si mesmo" são diferentes.
    tipos: dict[str, dict] = {}
    for x in dup:
        a = tipos.setdefault(x["tipo"], {"tipo": x["tipo"], "n": 0, "valor": 0.0})
        a["n"] += 1
        a["valor"] += x["valor"]
    for a in tipos.values():
        a["valor"] = round(a["valor"], 2)

    # E por praça: 86% caem na SP-021, que é free flow. Uma praça que responde
    # por um terço dos casos é um chamado sobre AQUELE equipamento, não uma
    # lista de 283 ocorrências avulsas.
    pracas: dict[str, dict] = {}
    for x in dup:
        a = pracas.setdefault(x["praca"], {"praca": x["praca"], "rodovia": x["rodovia"],
                                           "n": 0, "valor": 0.0})
        a["n"] += 1
        a["valor"] += x["valor"]
    for a in pracas.values():
        a["valor"] = round(a["valor"], 2)
    ranking = sorted(pracas.values(), key=lambda x: -x["valor"])

    return {
        "competencia": competencia,
        "contestar": {
            "duplicadas": dup[:200], "duplicadas_n": len(dup), "duplicadas_valor": v_dup,
            "por_tipo": sorted(tipos.values(), key=lambda x: -x["valor"]),
            "por_praca": ranking[:20], "pracas_n": len(ranking),
            "impossiveis": imp[:50], "impossiveis_n": len(imp), "impossiveis_valor": v_imp,
            "concentracao": concentracao_duplicadas(competencia, esquema),
            "valor": round(v_dup + v_imp, 2)},
        "operacao": eixo,
        # O total acionável NÃO soma o que não é acionável: as travessias fora
        # de manifesto e os manifestos sem peso que não provaram nada ficam de
        # fora. Este número erra para baixo por construção.
        "total": round(v_dup + v_imp + (eixo.get("evitavel") or 0), 2),
    }
