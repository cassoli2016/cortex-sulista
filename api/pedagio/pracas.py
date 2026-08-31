# -*- coding: utf-8 -*-
"""Praça e tarifa: a validação que NÃO depende de assinar API de ninguém.

A PERGUNTA QUE ORIGINOU ESTE MÓDULO
===================================
"Não vou assinar a API deles, existe outro lugar de onde pegar isso?" — e a
resposta, medida em 30/08/2026, é que DUAS DAS TRÊS FONTES JÁ ESTAVAM DENTRO
DO ERP e ninguém as lia:

    public.pracapedagio_valor          1.260 linhas ·   934 praças
        a TARIFA por praça e por eixo (2 a 15), com `dtvigencia`.
    public.valepedagio_pracapedagio  414.985 linhas ·   343 praças
        o que o sistema CALCULOU: praça, eixos e valor de cada travessia.
    public.valepedagio_pracapedagioadm 293.033 linhas · 385 códigos
        o que a ADMINISTRADORA devolveu, praça a praça. É o "fechamento da
        operadora" que eu ia escrever um parser para importar — ele já chega
        pela integração e está vivo até hoje (30/08/2026).

A tarifa do ERP CONFERE com a fonte paga, e é isso que a torna utilizável:
Garuva (BR-101/SC km 1,35) tem `valorpedagioeixo` = R$ 5,70 e
`valorpedagioveiculocarga5eixos` = R$ 28,50 — exatamente o que o QualP
devolveu na consulta avulsa. Não era falta de dado; era dado não lido.

MAS A TABELA DE TARIFA ESTÁ PARADA, E É O ACHADO CENTRAL
========================================================
A vigência mais recente de TODA a tabela é 01/08/2025, e a distribuição da
última vigência por praça é:

    2016 ..  31      2019 .. 151      2022 ..   1      2025 ..  65
    2017 . 169      2020 ..  19      2023 ..   1
    2018 ..  46      2021 . 151      2024 . 289

Pedágio reajusta uma vez por ano. 397 praças presas entre 2016 e 2021 não são
cadastro incompleto: são cadastro que parou. É a mesma família do marcador de
manutenção preventiva parado em 77.534 km com o odômetro em 531.970 — número
que existe, parece atual e decide errado.

E A CONSEQUÊNCIA É MENSURÁVEL, o que é raro
===========================================
Nas 13.333 travessias de 12 meses em que a administradora devolveu a praça,
ela cobrou MAIS em 77,9% e igual em só 10,1%. Garuva: o sistema calculou
R$ 28,31 em média (a tarifa de nov/2024) e foi cobrado R$ 32,40. Régis
Bittencourt trecho oeste: calculado R$ 4.104, cobrado R$ 17.039.

A diferença NÃO é acusação de cobrança indevida — é a tarifa do ERP
desatualizada encontrando a tarifa real. Por isso a tela mostra a vigência ao
lado de cada praça: é a evidência que explica o número acusado, como o
"531.970 -> 77.534" da manutenção preventiva.

A TARIFA CORRENTE ESTÁ SENDO OBSERVADA TODO DIA
===============================================
Se a administradora cobra a tarifa vigente, então `valor / eixos` do que ela
cobrou É a tarifa de hoje daquela praça. Não precisa de fornecedor: precisa
ler o que já se paga. É o que `observada()` faz, e é ela que diz quais linhas
de `pracapedagio_valor` estão erradas e por quanto.

O BURACO, DITO COM NOME
=======================
70,8% das travessias não têm contraparte da administradora — e é UMA SÓ:

    TARGET (173) ... 27.892 travessias · devolve a praça em   0% · R$ 931.443
    GPS PAMCARY (1)  10.417 travessias · devolve a praça em  66% · R$ 270.199
    EFRETE (50) ....  7.321 travessias · devolve a praça em  88% · R$ 195.432

Não é defeito do dado: é uma integração que não manda o detalhe. Dito assim
vira pedido ao fornecedor; dito como "70,8% sem dado" vira desconfiança do
sistema inteiro.

E A PRAÇA MUDA DE CAMPO CONFORME A ADMINISTRADORA
=================================================
No trimestre corrente a adm devolve `codigoexterno` em 98% e `descricao` em
5%; nos trimestres anteriores era o contrário. Uma primeira versão deste
módulo agrupou por `a.descricao` e produziu uma linha "-" com 11.606
travessias somadas, que era a maioria do volume com todas as praças
misturadas. QUEM IDENTIFICA A PRAÇA É `c.idpracapedagio`, 100% preenchido em
todos os trimestres, dos dois lados. O campo da administradora serve para o
VALOR, não para a identidade.

O QUE A ANTT ACRESCENTA, E O QUE ELA NÃO RESOLVE
================================================
`dados.antt.gov.br` é aberto e oficial, e a tarifa por eixo é DERIVÁVEL:
receita da praça dividida pelo volume de tráfego equivalente. Conferido em
Garuva — R$ 5,68 derivado contra R$ 5,70 real, 0,35% de erro. Mas:

  * cobre só concessão FEDERAL — 261 das 752 praças brasileiras do cadastro
    (PR 100%, SC 82%, GO 95%, MG 57%, e SP só 10%, porque lá é ARTESP);
  * a receita por praça é publicada UMA VEZ POR ANO e com atraso — a de 2025
    saiu em 08/06/2026, e não existe arquivo de 2026.

Ou seja: serve de auditoria independente do histórico, não de tarifa
operacional. Por isso este módulo não a consome em tempo de execução; quem
sustenta o dia a dia é o que a administradora cobra.
"""
from __future__ import annotations

import datetime as dt
import logging

from api import db

log = logging.getLogger(__name__)

# Pedágio reajusta uma vez por ano, na data-base da concessão. Treze meses dá
# um mês de folga para o reajuste que ainda não passou pelo cadastro — abaixo
# disso a tela acusaria como parada a tarifa que só está esperando a data.
MESES_VIGENCIA_OK = 13

# Uma travessia só não estabelece tarifa: pode ser categoria errada, eixo
# suspenso ou o próprio dia do reajuste. Cinco é o piso para a moda valer.
MINIMO_OBSERVACOES = 5

# E ter cinco travessias não basta: se o valor mais frequente responde por
# menos da metade delas, não há tarifa a afirmar — há uma praça que cobra por
# eixo NO CHÃO enquanto o vale declara o total do veículo. Metade é o corte
# porque abaixo dele a "tarifa" perde até a maioria simples.
PCT_MODA_MINIMO = 50.0


# ── o estado da tabela de tarifa do ERP ─────────────────────────────────────

TARIFA_ESTADO_SQL = """
SELECT count(DISTINCT v.idpracapedagio)::int   AS pracas,
       count(*)::int                           AS linhas,
       max(v.dtvigencia)::date                 AS vigencia_max,
       min(v.dtvigencia)::date                 AS vigencia_min,
       sum(CASE WHEN v.valorpedagioeixo > 0 THEN 1 ELSE 0 END)::int AS com_eixo,
       sum(CASE WHEN v.dtvigencia IS NULL THEN 1 ELSE 0 END)::int   AS sem_vigencia
  FROM pracapedagio_valor v
"""

TARIFA_IDADE_SQL = """
SELECT extract(year FROM x.ult)::int AS ano, count(*)::int AS pracas
  FROM (SELECT idpracapedagio, max(dtvigencia) AS ult
          FROM pracapedagio_valor
         WHERE dtvigencia IS NOT NULL
         GROUP BY idpracapedagio) x
 GROUP BY 1
 ORDER BY 1
"""

# Quantas praças estão paradas — pela MESMA régua de `_parada`, recebendo o
# corte já calculado. Uma primeira versão contava por ANO (`ano < 2025`) e
# discordava da régua por linha: Régis Bittencourt, com vigência de 01/10/2024
# e 22 meses de idade, saía marcada como parada na tabela e NÃO entrava neste
# total. Dois jeitos de dizer "desatualizada" na mesma tela é a família dos
# dois armazéns do parâmetro da premiação, que concordavam por acaso até
# alguém editar um deles.
TARIFA_PARADAS_SQL = """
SELECT count(*)::int AS paradas
  FROM (SELECT idpracapedagio, max(dtvigencia) AS ult
          FROM pracapedagio_valor
         WHERE dtvigencia IS NOT NULL
         GROUP BY idpracapedagio) x
 WHERE x.ult < %(corte)s
"""

# As praças USADAS na janela, com a idade da tarifa de cada uma. É a lista que
# decide trabalho: praça que ninguém atravessa com tarifa de 2017 não custa
# nada; praça de 856 travessias com tarifa de 2021 custa toda vez.
TARIFA_EM_USO_SQL = """
SELECT c.idpracapedagio                                AS id,
       coalesce(p.descricao, '(praca nao cadastrada)')  AS praca,
       coalesce(p.uf, '')                               AS uf,
       count(*)::int                                    AS travessias,
       sum(c.valorpedagio)::float8                      AS calculado,
       max(v.dtvigencia)::date                          AS vigencia,
       max(v.valorpedagioeixo)::float8                  AS tarifa_eixo
  FROM valepedagio_pracapedagio c
  LEFT JOIN pracapedagio p       ON p.id = c.idpracapedagio
  LEFT JOIN pracapedagio_valor v ON v.idpracapedagio = c.idpracapedagio
 WHERE c.dtinc >= %(de)s AND c.dtinc < %(ate)s::date + 1
 GROUP BY c.idpracapedagio, p.descricao, p.uf
 ORDER BY count(*) DESC
"""


# ── o confronto: o que o sistema calculou × o que a administradora cobrou ───
#
# O join é pela chave COMPOSTA das duas tabelas (grupo, empresa, filial,
# unidade, diferenciadorsequencia, sequencia, sequenciapracapedagio).
# Conferido contra a contagem crua: 45.646 linhas dos dois lados, sem fan-out.
CONFRONTO_PRACA_SQL = """
SELECT c.idpracapedagio                                AS id,
       coalesce(p.descricao, '(praca nao cadastrada)')  AS praca,
       coalesce(p.uf, '')                               AS uf,
       count(*)::int                                    AS travessias,
       sum(c.valorpedagio)::float8                      AS calculado,
       sum(a.valor)::float8                             AS cobrado,
       max(v.dtvigencia)::date                          AS vigencia,
       sum(CASE WHEN abs(c.valorpedagio - a.valor) <= 0.01
                THEN 1 ELSE 0 END)::int                 AS iguais
  FROM valepedagio_pracapedagio c
  JOIN valepedagio_pracapedagioadm a
    ON a.grupo = c.grupo AND a.empresa = c.empresa AND a.filial = c.filial
   AND a.unidade = c.unidade
   AND a.diferenciadorsequencia = c.diferenciadorsequencia
   AND a.sequencia = c.sequencia
   AND a.sequenciapracapedagio = c.sequenciapracapedagio
  LEFT JOIN pracapedagio p       ON p.id = c.idpracapedagio
  LEFT JOIN pracapedagio_valor v ON v.idpracapedagio = c.idpracapedagio
 WHERE c.dtinc >= %(de)s AND c.dtinc < %(ate)s::date + 1
   AND a.valor > 0
 GROUP BY c.idpracapedagio, p.descricao, p.uf
 ORDER BY abs(sum(a.valor) - sum(c.valorpedagio)) DESC
"""

COBERTURA_ADM_SQL = """
SELECT vp.administradorapef                     AS adm,
       coalesce(ap.descricao, '(sem cadastro)') AS nome,
       count(*)::int                            AS travessias,
       sum(CASE WHEN a.sequenciapracapedagio IS NULL
                THEN 1 ELSE 0 END)::int         AS sem_praca,
       sum(c.valorpedagio)::float8              AS calculado
  FROM valepedagio_pracapedagio c
  JOIN valepedagio vp
    ON vp.grupo = c.grupo AND vp.empresa = c.empresa AND vp.filial = c.filial
   AND vp.unidade = c.unidade
   AND vp.diferenciadorsequencia = c.diferenciadorsequencia
   AND vp.sequencia = c.sequencia
  LEFT JOIN administradorapef ap ON ap.codigo = vp.administradorapef
  LEFT JOIN valepedagio_pracapedagioadm a
    ON a.grupo = c.grupo AND a.empresa = c.empresa AND a.filial = c.filial
   AND a.unidade = c.unidade
   AND a.diferenciadorsequencia = c.diferenciadorsequencia
   AND a.sequencia = c.sequencia
   AND a.sequenciapracapedagio = c.sequenciapracapedagio
 WHERE c.dtinc >= %(de)s AND c.dtinc < %(ate)s::date + 1
 GROUP BY vp.administradorapef, ap.descricao
 ORDER BY count(*) DESC
"""

# A tarifa OBSERVADA: o que a administradora cobrou, por praça, eixo e VALOR.
#
# A MÉDIA NÃO É A TARIFA, e o dado real provou isso. Campina Grande do Sul com
# 5 eixos foi cobrada R$ 20,50 em 42 travessias (até 05/12/2025), R$ 21,50 em
# 85 (desde 09/01/2026) — um reajuste limpo, datado — e R$ 80,28 UMA vez. A
# média dá R$ 21,63 e a faixa vai de 20,50 a 80,28, o que faz a coluna parecer
# ruído. 59% das 303 combinações tinham faixa acima de 10% da média por causa
# desse tipo de cauda.
#
# A tarifa é o valor que SE REPETE. Agrupando também por valor, a moda é a
# tarifa vigente, a segunda mais frequente é a anterior, e a data da troca sai
# de graça — que é informação melhor do que qualquer média. Travessia única
# fica de fora por construção: não estabelece nada.
OBSERVADA_SQL = """
SELECT c.idpracapedagio                                AS id,
       coalesce(p.descricao, '(praca nao cadastrada)')  AS praca,
       coalesce(p.uf, '')                               AS uf,
       c.quantidadeeixos                                AS eixos,
       a.valor::float8                                  AS valor,
       count(*)::int                                    AS n,
       min(a.dtinc)::date                               AS visto_de,
       max(a.dtinc)::date                               AS visto_ate,
       max(v.dtvigencia)::date                          AS vigencia,
       max(v.valorpedagioeixo)::float8                  AS erp_eixo
  FROM valepedagio_pracapedagio c
  JOIN valepedagio_pracapedagioadm a
    ON a.grupo = c.grupo AND a.empresa = c.empresa AND a.filial = c.filial
   AND a.unidade = c.unidade
   AND a.diferenciadorsequencia = c.diferenciadorsequencia
   AND a.sequencia = c.sequencia
   AND a.sequenciapracapedagio = c.sequenciapracapedagio
  LEFT JOIN pracapedagio p       ON p.id = c.idpracapedagio
  LEFT JOIN pracapedagio_valor v ON v.idpracapedagio = c.idpracapedagio
 WHERE c.dtinc >= %(de)s AND c.dtinc < %(ate)s::date + 1
   AND a.valor > 0 AND c.quantidadeeixos > 0
 GROUP BY c.idpracapedagio, p.descricao, p.uf, c.quantidadeeixos, a.valor
 ORDER BY count(*) DESC
"""


# O VÍNCULO COM O MDF-e QUE NÃO EXISTE, e que precisa ser MEDIDO e não escrito
# à mão. A Lei 10.209/2001 e o layout do MDF-e (grupo infANTT/valePed) mandam o
# manifesto carregar o vale-pedágio, e `manifestoeletronico` tem os três campos
# para isso. Medido em 31/08/2026, no histórico INTEIRO — 126.295 manifestos
# desde 31/05/2023:
#
#     numerocomprovantevalepedagio ........ 0  (0,0%)
#     cnpjcpfcodigofornecedoravalepedagio . 0  (0,0%)
#     cnpjcpfcodigopagamentovalepedagio ... 0  (0,0%)
#     numerociot ..................... 71.185 (56,4%)  <- este É preenchido
#
# E do outro lado `valepedagio.numeromanifesto` é zero nas 69.028 linhas,
# enquanto `numerocomprovante` está em 68.643 (99,4%). Ou seja: o número do
# comprovante EXISTE, e simplesmente nunca chega ao registro do manifesto.
#
# O que dá para afirmar é isto e só isto: **o banco não permite conferir se o
# vale foi declarado no MDF-e**. Se o dado é injetado na hora da transmissão à
# SEFAZ, ou se não é declarado, o ERP não guarda — e inventar um veredito a
# partir da ausência seria pior que dizer que não dá. Mesma regra das multas,
# em que não se criou estimativa de custo sobre campo vazio.
#
# Fica como SENSOR e não como texto fixo: no dia em que o ERP passar a
# preencher, a tela muda sozinha.
MDFE_VALE_SQL = """
SELECT count(*)::int                                                   AS mdfe,
       sum(CASE WHEN m.numerocomprovantevalepedagio IS NOT NULL
                 AND m.numerocomprovantevalepedagio <> 0
                THEN 1 ELSE 0 END)::int                                AS com_comprovante,
       sum(CASE WHEN m.cnpjcpfcodigofornecedoravalepedagio IS NOT NULL
                THEN 1 ELSE 0 END)::int                                AS com_fornecedor,
       sum(CASE WHEN m.numerociot IS NOT NULL THEN 1 ELSE 0 END)::int   AS com_ciot
  FROM manifestoeletronico m
 WHERE m.dtemissao >= %(de)s AND m.dtemissao < %(ate)s::date + 1
"""


def _idade_meses(vigencia, hoje: dt.date | None = None) -> int | None:
    """Meses inteiros desde a vigência. `None` quando não há vigência.

    Sem vigência NÃO é idade infinita: é ausência de cadastro, que tem outro
    dono e outro conserto. Devolver um número aqui faria a praça sem tarifa
    aparecer no topo da lista de "tarifa mais velha", empurrando para baixo a
    que realmente está velha.
    """
    if not vigencia:
        return None
    hoje = hoje or dt.date.today()
    return (hoje.year - vigencia.year) * 12 + (hoje.month - vigencia.month)


def _parada(idade: int | None) -> bool:
    return idade is not None and idade > MESES_VIGENCIA_OK


def _iso(d):
    """`date` -> "AAAA-MM-DD", no LIMITE do módulo.

    O `JSONResponse` da casa é a rede embaixo, não a regra: converter aqui é o
    certo porque a partir daqui o tipo do banco para de importar — e a tela
    espera string (o `fmtD` do painel fatia "AAAA-MM-DD"). A alternativa é
    descobrir na hora em que a serialização estoura DEPOIS do try/except da
    rota, com 500 em text/plain e nenhuma pista apontando para o campo.
    """
    return d.isoformat() if isinstance(d, dt.date) else d


def _corte(hoje: dt.date | None = None) -> dt.date:
    """A data a partir da qual a tarifa deixa de ser considerada parada.

    Sai do MESMO `MESES_VIGENCIA_OK` que `_parada` usa, para que o total do
    cartão e a marca de cada linha não possam discordar.
    """
    hoje = hoje or dt.date.today()
    m = hoje.month - MESES_VIGENCIA_OK
    ano, mes = hoje.year + (m - 1) // 12, (m - 1) % 12 + 1
    return dt.date(ano, mes, 1)


def estado_tarifa(hoje: dt.date | None = None) -> dict:
    """O estado da tabela de tarifa do ERP — quantas praças e de quando."""
    r = dict(db.query(TARIFA_ESTADO_SQL)[0])
    r["idade_meses"] = _idade_meses(r["vigencia_max"], hoje)
    r["parada"] = _parada(r["idade_meses"])
    r["por_ano"] = [dict(x) for x in db.query(TARIFA_IDADE_SQL)]
    corte = _corte(hoje)
    r["corte"] = _iso(corte)
    r["vigencia_max"] = _iso(r["vigencia_max"])
    r["vigencia_min"] = _iso(r["vigencia_min"])
    r["desatualizadas"] = db.query(TARIFA_PARADAS_SQL,
                                   {"corte": corte})[0]["paradas"]
    r["pct_desatualizadas"] = (round(100.0 * r["desatualizadas"] / r["pracas"], 1)
                               if r["pracas"] else None)
    return r


def em_uso(de: str, ate: str, hoje: dt.date | None = None) -> list[dict]:
    """As praças atravessadas na janela, com a idade da tarifa de cada uma."""
    fora = []
    for x in db.query(TARIFA_EM_USO_SQL, {"de": de, "ate": ate}):
        d = dict(x)
        d["idade_meses"] = _idade_meses(d["vigencia"], hoje)
        d["parada"] = _parada(d["idade_meses"])
        d["sem_tarifa"] = d["vigencia"] is None
        d["vigencia"] = _iso(d["vigencia"])
        fora.append(d)
    return fora


def confronto_praca(de: str, ate: str, hoje: dt.date | None = None) -> dict:
    """Calculado × cobrado pela administradora, praça a praça."""
    linhas = []
    for x in db.query(CONFRONTO_PRACA_SQL, {"de": de, "ate": ate}):
        d = dict(x)
        d["diferenca"] = round((d["cobrado"] or 0) - (d["calculado"] or 0), 2)
        # A razão sai dos TOTAIS, não de valores já arredondados: arredondar
        # antes de dividir move o número de lado da fronteira, e o limiar de
        # leitura aqui é 1,00.
        d["razao"] = (round((d["cobrado"] or 0) / d["calculado"], 3)
                      if (d["calculado"] or 0) > 0 else None)
        d["idade_meses"] = _idade_meses(d["vigencia"], hoje)
        d["parada"] = _parada(d["idade_meses"])
        d["vigencia"] = _iso(d["vigencia"])
        linhas.append(d)
    calc = round(sum(l["calculado"] or 0 for l in linhas), 2)
    cobr = round(sum(l["cobrado"] or 0 for l in linhas), 2)
    trav = sum(l["travessias"] for l in linhas)
    iguais = sum(l["iguais"] for l in linhas)
    # Quanto da diferença vem de praça com tarifa PARADA. É o número que separa
    # "a operadora está cobrando errado" de "o nosso cadastro está velho" — e
    # são consertos em lugares diferentes, com donos diferentes.
    dif_parada = round(sum(l["diferenca"] for l in linhas if l["parada"]), 2)
    total_dif = round(cobr - calc, 2)
    return {
        "linhas": linhas,
        "pracas": len(linhas),
        "travessias": trav,
        "calculado": calc,
        "cobrado": cobr,
        "diferenca": total_dif,
        "iguais": iguais,
        "pct_iguais": (round(100.0 * iguais / trav, 1) if trav else None),
        "diferenca_parada": dif_parada,
        "pct_diferenca_parada": (round(100.0 * dif_parada / total_dif, 1)
                                 if abs(total_dif) > 0.01 else None),
    }


def por_administradora(de: str, ate: str) -> list[dict]:
    """Quem devolve a quebra por praça e quem não devolve.

    Sem esta quebra, "70,8% sem contraparte" lê-se como dado furado. Com ela,
    lê-se como uma integração específica que não manda o detalhe — que é um
    pedido ao fornecedor, não uma desconfiança do sistema inteiro. Mesma regra
    do denominador dos 664 rastreadores "sem sinal".
    """
    fora = []
    for x in db.query(COBERTURA_ADM_SQL, {"de": de, "ate": ate}):
        d = dict(x)
        n = d["travessias"] or 1
        d["com_praca"] = n - d["sem_praca"]
        d["pct_com_praca"] = round(100.0 * d["com_praca"] / n, 1)
        fora.append(d)
    return fora


def observada(de: str, ate: str, minimo: int = MINIMO_OBSERVACOES,
              hoje: dt.date | None = None) -> list[dict]:
    """A tarifa que está sendo COBRADA, por praça e por eixo.

    É a resposta operacional a "de onde tirar a tarifa sem assinar API": ela
    já chega, todo dia, no que a administradora cobra.

    A tarifa é a MODA — o valor que se repete —, nunca a média. Medido: 59%
    das 303 combinações tinham faixa acima de 10% da média, e a decomposição
    mostrou que isso é cauda, não dispersão: Campina Grande do Sul com 5 eixos
    teve R$ 20,50 (42 vezes), R$ 21,50 (85 vezes) e R$ 80,28 UMA vez. A média
    de R$ 21,63 não é tarifa de nada, e a faixa de 20,50 a 80,28 faz a coluna
    parecer ruído. A moda é R$ 21,50, o anterior é R$ 20,50, e a data da troca
    vem junto — que é melhor do que qualquer média.
    """
    # agrupa as linhas (praça, eixos, valor) por combinação
    combos: dict[tuple, list[dict]] = {}
    meta: dict[tuple, dict] = {}
    for x in db.query(OBSERVADA_SQL, {"de": de, "ate": ate}):
        d = dict(x)
        chave = (d["id"], d["eixos"])
        combos.setdefault(chave, []).append(d)
        meta.setdefault(chave, d)

    fora = []
    for chave, valores in combos.items():
        base = meta[chave]
        total = sum(v["n"] for v in valores)
        if total < minimo:
            continue
        # A moda é o valor mais frequente; empate desempata pelo mais RECENTE,
        # porque num reajuste no meio da janela o que interessa é o de agora.
        valores.sort(key=lambda v: (v["n"], v["visto_ate"]), reverse=True)
        atual, resto = valores[0], valores[1:]
        eixos = base["eixos"] or 0
        por_eixo = round(atual["valor"] / eixos, 2) if eixos else None
        # O anterior é o segundo mais frequente que ainda tenha repetição: um
        # valor visto UMA vez é lançamento avulso, não tarifa antiga, e
        # apresentá-lo como "era R$ 80,28" seria inventar um reajuste.
        anteriores = [v for v in resto if v["n"] >= 2]
        ant = anteriores[0] if anteriores else None
        erp = base["erp_eixo"]
        d = {
            "id": base["id"], "praca": base["praca"], "uf": base["uf"],
            "eixos": base["eixos"],
            "travessias": total,
            "valor": atual["valor"],
            "n": atual["n"],
            "por_eixo": por_eixo,
            "desde": _iso(atual["visto_de"]),
            "ate": _iso(atual["visto_ate"]),
            "anterior": ant["valor"] if ant else None,
            "anterior_n": ant["n"] if ant else None,
            "anterior_ate": _iso(ant["visto_ate"]) if ant else None,
            # Quantas travessias NÃO caem na moda nem no anterior. É o resíduo
            # honesto: dizer "a tarifa é R$ 21,50" com 20% das cobranças fora
            # dela seria esconder o que não se explicou.
            "fora": total - atual["n"] - (ant["n"] if ant else 0),
            "vigencia": _iso(base["vigencia"]),
            "erp_eixo": erp,
            "idade_meses": _idade_meses(base["vigencia"], hoje),
        }
        d["parada"] = _parada(d["idade_meses"])
        d["pct_moda"] = round(100.0 * atual["n"] / total, 1)
        # MODA FRACA NÃO É TARIFA, e a tela precisa dizer isso em vez de
        # afirmar um número. Medido: 143 das 303 combinações têm moda acima de
        # 80% (tarifa nítida, e o "anterior" é o reajuste), mas Ribeirão Pires
        # com 6 eixos tem moda de 20% — ali o mesmo veículo paga valores
        # diferentes, o que é esperado quando a praça cobra pelo eixo NO CHÃO e
        # a carreta roda com eixo suspenso. Afirmar "a tarifa é R$ 32,40" numa
        # linha dessas seria inventar precisão. Mesma régua do `confidence`
        # abaixo de 0,5 da TomTom, que vira n/d em vez de verde ou vermelho.
        d["estabelecida"] = d["pct_moda"] >= PCT_MODA_MINIMO
        # O desvio contra a tarifa cadastrada. `None` quando não há cadastro:
        # comparar contra zero produziria "-100%" em toda praça sem tarifa e
        # afogaria as que têm cadastro E estão erradas, que são as acionáveis.
        # Também `None` sem tarifa estabelecida — desvio contra um número que
        # a própria tela não afirma seria pior que não mostrar.
        d["desvio_pct"] = (round(100.0 * (por_eixo - erp) / erp, 1)
                           if erp and por_eixo and d["estabelecida"] else None)
        fora.append(d)
    fora.sort(key=lambda x: x["travessias"], reverse=True)
    return fora


def mdfe_vale(de: str, ate: str) -> dict:
    """O vale-pedágio declarado no MDF-e — hoje, nenhum.

    Devolve os números para a tela DIZER o que não dá para conferir, em vez de
    calar. O CIOT vai junto de propósito: ele prova que o ERP preenche campo de
    documento eletrônico quando tem o dado, então o vazio dos outros três não é
    "o ERP não preenche nada" — é este dado, especificamente, que não chega.
    """
    r = dict(db.query(MDFE_VALE_SQL, {"de": de, "ate": ate})[0])
    n = r["mdfe"] or 1
    for campo in ("com_comprovante", "com_fornecedor", "com_ciot"):
        r["pct_" + campo[4:]] = round(100.0 * r[campo] / n, 1)
    # `conferivel` é o que a tela usa para decidir entre mostrar a conferência
    # e explicar por que ela não existe.
    r["conferivel"] = r["com_comprovante"] > 0
    return r
