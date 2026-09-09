"""Diária paga × jornada trabalhada.

A MESMA DIÁRIA VEM DUAS VEZES NA FOLHA — LER `_consolidar()` PRIMEIRO
====================================================================
O evento 428 (DIARIAS PAGAS) é gravado em DUAS granularidades: o pagamento
SEMANAL (`tipo_folha = 3`, uma linha por semana) e a folha MENSAL
(`tipo_folha = 1`, uma linha no último dia do mês) cujo valor é a SOMA das
semanais daquela pessoa naquele mês. Somar as duas — que foi o que este módulo
fez até 08/09/2026 — conta o mesmo dinheiro duas vezes: **R$ 868.421 em doze
meses (31,3%)**, R$ 3,46 milhões na história inteira. A regra e as três provas
estão em `_consolidar()`.

O QUE ISSO ENVENENAVA ERA A LEITURA, NÃO SÓ O TOTAL. A folha mensal parou de
ser carregada em 02/2026, então set/25–jan/26 vinham DOBRADOS e mar/26 em
diante vinham certos: a série desenhava uma queda de 80% que era, na maior
parte, o fim da duplicidade — e o R$/dia trabalhado marcava **R$ 214 a R$ 267**
nos meses dobrados, contra uma diária INTEIRA de R$ 107,44. Estava escrito
neste arquivo que aquela razão era "ordem de grandeza" por defasagem de
competência: era duplicidade, e o número impossível estava à vista de quem
soubesse quanto vale uma diária. Corrigida, a razão fica entre R$ 74 e R$ 133
em todos os treze meses.

A PERGUNTA QUE ISTO RESPONDE
===========================
"Quanto se paga de diária" tem resposta fácil e inútil: R$ 159 mil em julho
contra R$ 233 mil em setembro é uma queda de 32% que não diz nada, porque no
mesmo período os motoristas com jornada caíram de 121 para 80. O número que
compara é **por motorista** e **por dia trabalhado** — a mesma correção da
cobertura mensal da jornada e do prêmio por motorista da premiação.

DUAS FONTES, EM DOIS BANCOS
===========================
- `sulista.diariaspagas_globus` (AVA): o que a FOLHA pagou. 18.762 lançamentos
  desde 12/2020, R$ 11,1 milhões depois de tirada a duplicidade (os R$ 14,6
  milhões que a soma crua devolve NÃO saíram do caixa). É a verdade do
  dinheiro, uma vez só.
- `jor_jornadas` (banco local do CÓRTEX): os dias efetivamente trabalhados,
  vindos da RasterJOR.

Estão em bancos DIFERENTES, então o cruzamento é feito em Python — não há
`JOIN` possível. E a chave é o NOME normalizado: a folha tem matrícula e a
jornada tem o documento do motorista, e os dois não conversam. Medido: **120
dos 134 nomes** da folha nos últimos 12 meses aparecem na jornada (90%). Os 14
que não aparecem são contados à parte, nunca somados como se tivessem zero dia.

A INTEGRAÇÃO GRANULAR ESTÁ PARADA, E ISSO É DITO
================================================
Existe `sulista.integracao_diarias_rasterjor` — diária por DIA, por motorista,
com tipo (Meia R$ 53,72 / Inteira R$ 107,44 na última vigência que ela viu) e
cidade-base. Seriam os dados mais ricos que há sobre o assunto. Ela tem 2.526 linhas e **parou em
12/02/2026**: seis meses e meio sem carga, exatamente o formato da RasterJOR
que ficou 136 dias fora do ar sem ninguém notar, porque o sintoma é uma tela
vazia e tela vazia se lê como "ninguém rodou".

Enquanto ela não voltar, o detalhe por dia não existe e a análise é mensal.
Isso aparece na tela como AVISO, não como ausência silenciosa — a lição é que
integração parada se disfarça de dado que não existe.

NÃO EXISTE A QUANTIDADE DE DIÁRIAS, E ISSO LIMITA A ANÁLISE
==========================================================
A folha tem uma coluna `referencia`, que em folha costuma ser a QUANTIDADE.
Aqui ela é **0,00 em todos os lançamentos** — nunca preenchida. É a mesma
família do "mão de obra R$ 0 com 747 OSs" da Manutenção: campo que existe,
parece número e não é.

A consequência é dura e precisa estar dita: **não dá para saber quantas
diárias foram pagas**, só quanto. E como a única fonte que tinha a quantidade
por dia (`integracao_diarias_rasterjor`) parou em 12/02, a única razão possível
é R$ ÷ dias trabalhados.

E ESSA RAZÃO É ORDEM DE GRANDEZA, NÃO PRECISÃO — mas agora por um motivo
menor. Tirada a duplicidade, ela dá **R$ 99,92 por dia trabalhado** na janela
de doze meses (mediana de R$ 99,67 por pessoa-mês), o que cabe entre a meia
(R$ 53,72) e a inteira (R$ 107,44) e é exatamente o que se espera de uma
mistura das duas. O que sobra de imprecisão é a competência: a folha paga em
janeiro trabalho do fim de dezembro, e por isso a comparação boa continua sendo
entre motoristas na MESMA janela, onde a defasagem é igual para todos.

O QUE NÃO SE AFIRMA
===================
Não há aqui julgamento de "diária a mais" ou "a menos". A regra de quem tem
direito a meia ou inteira é da empresa e depende de pernoite, distância e
acordo — nada disso está nestas duas fontes. O que a tela mostra é quanto se
pagou, para quem, e quem está fora da curva dos colegas. Quem decide se aquilo
é certo é quem conhece a regra.

O ACHADO QUE NÃO DEPENDE DE RAZÃO NENHUMA é a reconciliação, e é o mais
acionável: **26 pessoas receberam diária sem NENHUM dia de jornada** nos doze
meses (R$ 189.530), e são MOTORISTA de cargo — carreteiro, truck, instrutor.
Não é gente de escritório viajando. E o outro lado: **18 pessoas têm jornada e
não receberam diária** na competência. Os dois números são perguntas para quem
opera, não veredito.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

from api import db, pglocal

log = logging.getLogger(__name__)

ESQUEMA: str | None = None       # os testes redirecionam

# A carga granular por dia, que não vem desde então. Fica como constante para
# a tela poder dizer a data em vez de "faz tempo".
GRANULAR_PAROU_EM = "2026-02-12"

# O tipo de folha que CONSOLIDA. Ver `_consolidar()` — é a distinção que
# separa somar dinheiro de somar a mesma quantia duas vezes.
TIPO_FOLHA_MENSAL = 1

FOLHA_SQL = """
WITH base AS (
  SELECT to_char(data_competencia,'YYYY-MM')    AS competencia,
         upper(trim(nome_funcionario))          AS nome,
         tipo_folha                             AS tipo,
         sum(valor_total)                       AS valor,
         count(*)                               AS lancamentos,
         max(trim(matricula))                   AS matricula,
         max(trim(cargo))                       AS cargo,
         sum(coalesce(referencia,0))            AS quantidade
    FROM sulista.diariaspagas_globus
   WHERE data_competencia >= %(de)s AND data_competencia < %(ate)s
     AND nome_funcionario IS NOT NULL
   GROUP BY 1, 2, 3
)
SELECT competencia,
       nome,
       max(matricula)                                                AS matricula,
       max(cargo)                                                    AS cargo,
       sum(CASE WHEN tipo = 1 THEN valor ELSE 0 END)::float8         AS mensal,
       sum(CASE WHEN tipo =  1 THEN 0 ELSE valor END)::float8        AS detalhe,
       sum(CASE WHEN tipo = 1 THEN lancamentos ELSE 0 END)           AS lanc_mensal,
       sum(CASE WHEN tipo =  1 THEN 0 ELSE lancamentos END)          AS lanc_detalhe,
       sum(CASE WHEN tipo = 1 THEN quantidade ELSE 0 END)::float8    AS qtd_mensal,
       sum(CASE WHEN tipo =  1 THEN 0 ELSE quantidade END)::float8   AS qtd_detalhe
  FROM base
 GROUP BY 1, 2
"""
# O lado do DETALHE é escrito como `ELSE`, e não como `tipo <> 1`, de propósito:
# a tabela é do ERP e não tem contrato de tipo (a `agrupadorgerencial` já trocou
# de tipo de coluna debaixo de cinco telas). Com `tipo <> 1`, uma linha de
# `tipo_folha` NULO ficaria de fora dos DOIS lados — o dinheiro sumiria do total
# em silêncio, que é a pior falha possível aqui. Como `ELSE`, o desconhecido cai
# no detalhe e é somado. Hoje são 0 nulos em 18.762 linhas; o `ELSE` custa nada
# e continua valendo quando deixarem de ser.

# DIA COM TRABALHO, e não dia com LINHA. A RasterJOR emite uma linha por
# motorista por dia INCLUSIVE nos dias parados, todos zerados — 15.565 de
# 34.548 linhas em doze meses. Contá-las inflaria o denominador em 78% e a
# diária por dia desabaria na mesma proporção.
#
# (E a explicação mora AQUI, em comentário Python, e não dentro da string SQL:
#  um `%` ali dentro vira placeholder do psycopg e derruba a consulta com
#  "incomplete placeholder" — que foi exatamente o que aconteceu ao escrever
#  "78%" no comentário do SQL.)
JORNADA_SQL = """
SELECT to_char(data,'YYYY-MM')                  AS competencia,
       upper(trim(nome))                        AS nome,
       count(DISTINCT data)                     AS dias,
       count(DISTINCT data) FILTER (WHERE min_total > 0) AS dias_com_trabalho,
       sum(min_total)::float8 / 60.0            AS horas,
       sum(min_extra)::float8 / 60.0            AS horas_extra
  FROM jor_jornadas
 WHERE data >= %(de)s AND data < %(ate)s AND nome IS NOT NULL
 GROUP BY 1, 2
"""


def _norm(nome: str) -> str:
    """Nome sem acento, em MAIÚSCULA e com espaço simples.

    As duas fontes vêm de sistemas diferentes e digitação diferente: sem
    normalizar, "JOSÉ DA SILVA" e "JOSE  DA SILVA" viram duas pessoas, e a
    reconciliação acusaria as duas — uma sem jornada e outra sem diária.
    """
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def _consolidar(mensal: float, detalhe: float) -> tuple[float, float]:
    """O total de UMA pessoa numa competência, e o quanto NÃO se soma.

    A MESMA DIÁRIA APARECE DUAS VEZES NA FOLHA, em duas granularidades:

    - `tipo_folha = 3` — o pagamento SEMANAL, uma linha por semana, com a data
      da semana em `data_competencia` (terça, quase sempre).
    - `tipo_folha = 1` — a folha MENSAL, uma única linha no último dia do mês,
      cujo valor é a SOMA das semanais daquela pessoa naquele mês.

    Não é opinião, é medido: em **549 de 566** pares pessoa×mês da janela em
    que as duas convivem, `mensal` e a soma das semanais são IGUAIS ao centavo
    (um caso de 02/2026: semanais 600 + 500 + 400 e a mensal 1.500,00). Os 17
    restantes divergem por semana que atravessa a virada do mês — a competência
    da folha não é o mês do calendário —, e a diferença é de dezenas de reais.

    Somar as duas contava o mesmo dinheiro duas vezes: **R$ 868.421 em doze
    meses, 31,3% do total**, e o pior é que a inflação NÃO era uniforme. A
    folha mensal parou de ser carregada em 02/2026, então set/25–jan/26 vinham
    exatamente DOBRADOS e mar/26 em diante vinham certos: a série desenhava uma
    queda de 80% que era, na maior parte, o fim da duplicidade. Corrigida, a
    queda de set/25 a jul/26 é de 32% — que ainda é queda, e ainda se explica
    em boa parte pela frota menor, mas é outra conversa.

    E há uma TERCEIRA fonte que arbitra, independente das duas: a carga
    granular por dia (`sulista.integracao_diarias_rasterjor`, viva até
    12/02/2026) mede 01/2026 em 1.717 diárias, R$ 132.874. A soma crua da folha
    dava R$ 217.844 — R$ 85 mil a MAIS do que existe de diária no mês. A regra
    devolve R$ 109.249, abaixo e do lado certo, que é o da defasagem de
    competência (janeiro paga trabalho do fim de dezembro).

    A REGRA É O MAIOR DOS DOIS LADOS, NUNCA A SOMA. Ela se sustenta sozinha em
    todos os regimes que a tabela teve, sem lista de meses escrita à mão:

    - até 07/2024 só há folha mensal          → o maior é a mensal;
    - 08/2024 a 01/2026 as duas convivem      → iguais, o maior é qualquer uma;
    - 2023–2024 a semanal era parcial         → o maior é a mensal, que é a
      completa (953 de 1.502 pares na janela);
    - de 02/2026 em diante só há semanal      → o maior é a semanal.

    O que ela sacrifica é o complemento: em 07/2026 sobraram 29 linhas mensais
    de R$ 32 a R$ 65 ao lado de semanais de milhares — dinheiro de verdade, mas
    indistinguível de uma consolidação que só carregou pela metade. Escolhe-se
    ficar R$ 1.216 abaixo (0,8% do mês) em vez de arriscar contar em dobro; a
    tela mostra o valor NÃO somado, para que a escolha seja visível.
    """
    return max(mensal, detalhe), min(mensal, detalhe)


def _competencias(de: date, ate: date) -> list[str]:
    """Os meses do recorte, GERADOS e não colhidos.

    `GROUP BY` não devolve o mês que não tem linha, e um mês sem diária
    paga sumiria do gráfico — emendando o anterior com o seguinte e desenhando
    continuidade sobre um buraco. É a lição da série mensal da jornada.
    """
    fora, a, m = [], de.year, de.month
    while (a, m) <= (ate.year, ate.month):
        fora.append("%04d-%02d" % (a, m))
        m += 1
        if m > 12:
            a, m = a + 1, 1
    return fora


def levantar(de: date, ate: date, *, esquema: str | None = None) -> dict:
    """Cruza folha e jornada no recorte. `ate` é EXCLUSIVO."""
    folha = [dict(r) for r in db.query(FOLHA_SQL, {"de": de, "ate": ate})]
    jorn = [dict(r) for r in pglocal.query(
        JORNADA_SQL, {"de": de, "ate": ate}, esquema=esquema or ESQUEMA)]

    por_j: dict[tuple[str, str], dict] = {}
    for r in jorn:
        por_j[(r["competencia"], _norm(r["nome"]))] = r

    linhas = []
    for r in folha:
        chave = (r["competencia"], _norm(r["nome"]))
        j = por_j.get(chave)
        dias = (j or {}).get("dias_com_trabalho") or 0
        # A MESMA DIÁRIA VEM NAS DUAS RÉGUAS — ver `_consolidar()`.
        valor, duplicado = _consolidar(r["mensal"] or 0.0, r["detalhe"] or 0.0)
        pela_mensal = (r["mensal"] or 0.0) >= (r["detalhe"] or 0.0)
        linhas.append({
            "competencia": r["competencia"],
            "nome": r["nome"], "matricula": r["matricula"],
            "cargo": (r["cargo"] or "").strip() or None,
            "valor": round(valor, 2),
            # O que NÃO foi somado. Vai no payload porque escolha de régua que
            # não se mostra vira verdade do sistema: a tela diz o quanto a
            # duplicidade valia, e quem confere contra a folha acha a diferença
            # em vez de suspeitar do número.
            "duplicado": round(duplicado, 2),
            # o contador de lançamentos acompanha a régua ESCOLHIDA — somar os
            # dois lados devolveria o mesmo pagamento duas vezes na contagem.
            "lancamentos": (r["lanc_mensal"] if pela_mensal
                            else r["lanc_detalhe"]) or 0,
            # 0,00 em 100% das linhas hoje. Vem no payload assim mesmo: no dia
            # em que a folha passar a preencher, a tela mostra sozinha, em vez
            # de alguém precisar lembrar que o campo existe.
            "quantidade": (r["qtd_mensal"] if pela_mensal
                           else r["qtd_detalhe"]) or None,
            "dias": dias,
            "horas": round((j or {}).get("horas") or 0.0, 1),
            "tem_jornada": j is not None,
            # SÓ quem tem jornada tem razão. Sem dia trabalhado a divisão não
            # existe — e preencher com zero faria a pessoa parecer barata.
            "por_dia": round(valor / dias, 2) if dias else None,
        })

    # quem TEM jornada e NÃO recebeu diária no mês — o outro lado da conta
    pagos = {(l["competencia"], _norm(l["nome"])) for l in linhas}
    sem_diaria = [
        {"competencia": c, "nome": j["nome"], "dias": j["dias_com_trabalho"],
         "horas": round(j["horas"], 1)}
        for (c, n), j in por_j.items()
        if (c, n) not in pagos and (j["dias_com_trabalho"] or 0) > 0
    ]
    return {"linhas": linhas, "sem_diaria": sem_diaria,
            "competencias": _competencias(de, ate)}


def mensal(dados: dict, *, competencia_aberta: str | None = None) -> list[dict]:
    """Série por competência, com os denominadores ao lado do total.

    `competencia_aberta` marca o mês que a folha ainda não fechou — sem isso
    ele aparece como queda, que é o erro do mês parcial desenhado como barra
    cheia.
    """
    vazio = {"valor": 0.0, "duplicado": 0.0, "pessoas": 0, "dias": 0,
             "horas": 0.0, "com_jornada": 0}
    por_comp: dict[str, dict] = {c: {"competencia": c, **vazio}
                                 for c in dados["competencias"]}
    for l in dados["linhas"]:
        b = por_comp.setdefault(l["competencia"],
                                {"competencia": l["competencia"], **vazio})
        b["valor"] += l["valor"]
        b["duplicado"] += l.get("duplicado") or 0.0
        b["pessoas"] += 1
        b["dias"] += l["dias"]
        b["horas"] += l["horas"]
        b["com_jornada"] += 1 if l["tem_jornada"] else 0
    fora = []
    for c in sorted(por_comp):
        b = por_comp[c]
        fora.append({
            **b,
            "valor": round(b["valor"], 2),
            "duplicado": round(b["duplicado"], 2),
            "horas": round(b["horas"], 1),
            # OS DOIS NÚMEROS QUE COMPARAM ENTRE MESES. O total sozinho caiu
            # 80% de set/25 a jul/26 — e no mesmo período os motoristas caíram
            # de 127 para 79. Sem estes, a leitura é de economia onde pode ser
            # só frota menor.
            "por_pessoa": round(b["valor"] / b["pessoas"], 2) if b["pessoas"] else None,
            "por_dia": round(b["valor"] / b["dias"], 2) if b["dias"] else None,
            "sem_dado": b["pessoas"] == 0,
            "aberta": c == competencia_aberta,
        })
    return fora


def por_motorista(dados: dict, *, limite: int = 40) -> list[dict]:
    """Um motorista por linha, somando o recorte inteiro.

    Ordenado por VALOR, que é materialidade — ordenar por "por dia" sem piso
    poria no topo quem trabalhou um dia e recebeu uma diária, que é o erro do
    ranking por percentual da DRE por Cliente.
    """
    acc: dict[str, dict] = {}
    for l in dados["linhas"]:
        b = acc.setdefault(_norm(l["nome"]), {
            "nome": l["nome"], "matricula": l["matricula"], "cargo": l["cargo"],
            "valor": 0.0, "dias": 0, "horas": 0.0, "meses": 0,
            "tem_jornada": False})
        b["valor"] += l["valor"]
        b["dias"] += l["dias"]
        b["horas"] += l["horas"]
        b["meses"] += 1
        b["tem_jornada"] = b["tem_jornada"] or l["tem_jornada"]
    fora = []
    for b in acc.values():
        fora.append({**b, "valor": round(b["valor"], 2),
                     "horas": round(b["horas"], 1),
                     "por_dia": round(b["valor"] / b["dias"], 2) if b["dias"] else None})
    fora.sort(key=lambda x: -x["valor"])
    return fora[:limite], len(fora)


def resumo(dados: dict, linhas_mes: list[dict]) -> dict:
    """Os números do cabeçalho, cada um com o denominador que o sustenta."""
    total = sum(l["valor"] for l in dados["linhas"])
    com_j = [l for l in dados["linhas"] if l["tem_jornada"]]
    sem_j = [l for l in dados["linhas"] if not l["tem_jornada"]]
    dias = sum(l["dias"] for l in com_j)
    pessoas = len({_norm(l["nome"]) for l in dados["linhas"]})
    fechados = [m for m in linhas_mes if not m["aberta"] and not m["sem_dado"]]
    return {
        "total": round(total, 2),
        "pessoas": pessoas,
        "lancamentos": sum(l["lancamentos"] for l in dados["linhas"]),
        # A COBERTURA DO CRUZAMENTO, sempre visível: sem ela, "R$ 3,20 por dia
        # trabalhado" pareceria valer para todo mundo quando vale para quem a
        # jornada conhece.
        "com_jornada": len({_norm(l["nome"]) for l in com_j}),
        "sem_jornada": len({_norm(l["nome"]) for l in sem_j}),
        "valor_sem_jornada": round(sum(l["valor"] for l in sem_j), 2),
        "dias_trabalhados": dias,
        "por_dia": round(sum(l["valor"] for l in com_j) / dias, 2) if dias else None,
        "com_jornada_sem_diaria": len({_norm(s["nome"]) for s in dados["sem_diaria"]}),
        # média só sobre meses FECHADOS: o mês aberto da folha puxaria para
        # baixo e pareceria queda.
        "media_mensal": (round(sum(m["valor"] for m in fechados) / len(fechados), 2)
                         if fechados else None),
        "granular_parou_em": GRANULAR_PAROU_EM,
        # O QUE A RÉGUA TIROU DA CONTA. Somar folha mensal com pagamento
        # semanal contava o mesmo dinheiro duas vezes (R$ 868 mil em doze
        # meses); publicar o valor evitado é o que permite conferir contra a
        # folha em vez de desconfiar do total. Ver `_consolidar()`.
        "duplicidade_evitada": round(
            sum(l.get("duplicado") or 0.0 for l in dados["linhas"]), 2),
        # A COBERTURA DO CAMPO DE QUANTIDADE. Zero aqui é o que impede dizer
        # "quantas diárias" — e dizer isso é melhor que estimar.
        "com_quantidade": sum(1 for l in dados["linhas"] if l["quantidade"]),
    }
