# -*- coding: utf-8 -*-
"""O que ele rodou nos últimos 30 dias — e contra o que isso se compara.

═══════════════════════════════════════════════════════════════════════════
A COMPARAÇÃO É COM ELE MESMO, NUNCA COM O COLEGA
═══════════════════════════════════════════════════════════════════════════
Um número sozinho não decide nada: "22 viagens" é muito? A referência óbvia
seria a média da frota — e ela está proibida aqui pela regra do app ("nada da
operação de qualquer outro motorista"), que existe porque o leitor não é
gestor: é a pessoa medida.

Então a régua são os 30 dias ANTERIORES DELE. Isso responde a pergunta que ele
de fato faz ("estou rodando mais ou menos que no mês passado?") sem publicar a
operação de ninguém. A única comparação com colegas no app inteiro é a posição
no ranking de nota da Gobrax, e ela entra porque a premiação já é pública entre
eles — está em `desempenho.py`, com a razão escrita.

═══════════════════════════════════════════════════════════════════════════
O KM SAI DE `kmfretecompra`, E NÃO DA JORNADA
═══════════════════════════════════════════════════════════════════════════
Há três fontes de km na casa e elas discordam. Medido em 07/09/2026 sobre os
vinculados com jornada nos últimos 30 dias, `jor_jornadas.km` traz linhas com
`NULL` e linhas absurdas (155 km contra 179 h de direção no mesmo motorista) —
é campo que a RasterJOR preenche quando o equipamento manda, e ele não manda
sempre. `kmfretecompra` da `programacaoembarque` tem cobertura **100% nas
viagens dos vinculados** (medido: 66 de 66, 43 de 43, 41 de 41…) porque é o km
que a própria operação usa para pagar frete de compra — número que alguém
confere quando erra.

É KM CONTRATADO DA VIAGEM, não hodômetro. A tela diz isso: "km das viagens",
não "km rodado". A diferença aparece no desvio de rota e no deslocamento vazio
não programado, e prometer hodômetro entregando contrato é o tipo de coisa que
o motorista descobre antes de nós.

═══════════════════════════════════════════════════════════════════════════
NÃO SAI DAQUI
═══════════════════════════════════════════════════════════════════════════
`valorfrete`, `valorfretecompra`, adiantamento, pedágio — nada de dinheiro. A
consulta NÃO TRAZ essas colunas, e isso não é esquecimento na hora de montar o
payload: filtro se esquece num `SELECT *` que alguém acrescenta depois; coluna
que não está na consulta não vaza.

VIAGEM VAZIA APARECE, e é dele: `tipo = 3` é o retorno vazio, que ele conhece
melhor que qualquer relatório. Contar é operação, não julgamento — e o app não
diz nada sobre "seu retorno vazio está alto", porque a decisão de mandar um
veículo vazio é da programação, não do motorista.

CACHE COM ÚLTIMA LEITURA BOA na janela da casa (2 h): a menor faixa que esta
tela publica é um DIA. Critério de `tests/test_leitura_velha.py`.
"""
from __future__ import annotations

import logging

from .. import db
from ..queries import VELHA_ATE, cached

log = logging.getLogger("cortex.motorista.produtividade")

#: A janela que quem opera pediu. O período anterior tem o MESMO tamanho —
#: comparar 30 dias com "o mês passado" (28 a 31) daria variação nascida do
#: calendário, e é a primeira coisa que faz alguém desconfiar do painel.
DIAS = 30

#: A consulta devolve UMA LINHA POR PERÍODO (`atual` e `anterior`), e não duas
#: consultas: é a mesma varredura da mesma tabela pelo mesmo motorista, e
#: separar em duas idas ao ERP dobraria o custo para responder a mesma coisa.
#:
#: `CASE WHEN` e não `FILTER (WHERE …)`: o AVA é PostgreSQL **9.3**. O erro do
#: `FILTER` aponta para o meio do agregado e não para a versão, e é meia hora
#: de procura no lugar errado.
_SQL = """
SELECT CASE WHEN p.dtsaida >= current_date - %(dias)s THEN 'atual'
            ELSE 'anterior' END                                  AS periodo,
       count(*)                                                  AS viagens,
       sum(CASE WHEN p.dtchegada IS NOT NULL THEN 1 ELSE 0 END)  AS concluidas,
       sum(CASE WHEN p.dtchegada IS NULL THEN 1 ELSE 0 END)      AS em_curso,
       sum(CASE WHEN p.tipo = 3 THEN 1 ELSE 0 END)               AS vazias,
       sum(coalesce(p.kmfretecompra, 0))                         AS km,
       sum(CASE WHEN coalesce(p.kmfretecompra,0) > 0 THEN 1 ELSE 0 END) AS com_km,
       count(DISTINCT p.dtsaida::date)                           AS dias_com_viagem,
       count(DISTINCT p.ufdestino)                               AS ufs,
       count(DISTINCT p.veiculo)                                 AS placas
  FROM programacaoembarque p
 WHERE trim(cast(p.motorista AS text)) = %(mot)s
   AND p.dtcancelamento IS NULL
   AND p.semaforo = 1
   AND p.dtsaida IS NOT NULL
   AND p.dtsaida >= current_date - %(dobro)s
 GROUP BY 1
"""

#: Para onde ele foi mais. Top-N LEVA CONTADOR (o payload diz quantas viagens
#: os N destinos representam do total) — senão vira total falso, que é a
#: armadilha clássica do ranking cortado.
_DESTINOS_SQL = """
SELECT coalesce(nullif(trim(p.cidadedestino),''),'?') AS cidade,
       coalesce(nullif(trim(p.ufdestino),''),'?')     AS uf,
       count(*)                                       AS viagens
  FROM programacaoembarque p
 WHERE trim(cast(p.motorista AS text)) = %(mot)s
   AND p.dtcancelamento IS NULL
   AND p.semaforo = 1
   AND p.dtsaida IS NOT NULL
   AND p.dtsaida >= current_date - %(dias)s
 GROUP BY 1, 2
 ORDER BY 3 DESC, 1
 LIMIT %(topo)s
"""

TOPO = 5


def _n(v) -> float:
    return float(v or 0)


def _variacao(atual: float, anterior: float) -> float | None:
    """Variação percentual, ou `None` quando não há base.

    `None` E NÃO ZERO: motorista que não rodou nos 30 dias anteriores (entrou
    agora, estava de férias, estava afastado) não teve variação de 0% — ele não
    tem com o que comparar, e um "0%" ali seria uma afirmação falsa com cara de
    medida. Zero que é ausência não é desempenho.
    """
    if not anterior:
        return None
    return round(100.0 * (atual - anterior) / anterior, 1)


@cached(ttl=300, velha_ate=VELHA_ATE)
def _consultar(motorista_codigo: str) -> dict:
    par = {"mot": str(motorista_codigo), "dias": DIAS, "dobro": DIAS * 2}
    linhas = {r["periodo"]: dict(r) for r in db.query(_SQL, par)}
    destinos = [dict(r) for r in db.query(
        _DESTINOS_SQL, {"mot": str(motorista_codigo), "dias": DIAS,
                        "topo": TOPO})]
    return {"linhas": linhas, "destinos": destinos}


def _periodo(linha: dict | None) -> dict:
    l = linha or {}
    viagens = int(l.get("viagens") or 0)
    km = _n(l.get("km"))
    dias = int(l.get("dias_com_viagem") or 0)
    return {
        "viagens": viagens,
        "concluidas": int(l.get("concluidas") or 0),
        "em_curso": int(l.get("em_curso") or 0),
        "vazias": int(l.get("vazias") or 0),
        "km": round(km),
        "com_km": int(l.get("com_km") or 0),
        "dias_com_viagem": dias,
        "ufs": int(l.get("ufs") or 0),
        "placas": int(l.get("placas") or 0),
        # Média POR DIA COM VIAGEM, não por dia de calendário: dia de folga no
        # denominador mede escala, não produtividade. É a mesma escolha da
        # jornada, onde 45% das linhas do relatório são dias zerados.
        "km_por_dia": round(km / dias) if dias else None,
    }


def minha(sessao: dict) -> dict:
    """Os 30 dias de QUEM ESTÁ LOGADO, contra os 30 anteriores DELE."""
    d = _consultar(str(sessao["motorista_codigo"]))
    atual = _periodo(d["linhas"].get("atual"))
    anterior = _periodo(d["linhas"].get("anterior"))

    destinos = [{"destino": f"{x['cidade']}/{x['uf']}",
                 "viagens": int(x["viagens"] or 0)} for x in d["destinos"]]
    return {
        "atual": atual,
        "anterior": anterior,
        "variacao": {
            "viagens": _variacao(atual["viagens"], anterior["viagens"]),
            "km": _variacao(atual["km"], anterior["km"]),
        },
        "destinos": destinos,
        # O CONTADOR DO TOP-N. Sem ele, cinco linhas somando 12 viagens em
        # cima de um total de 30 lêem-se como o total.
        "destinos_viagens": sum(x["viagens"] for x in destinos),
        "destinos_topo": TOPO,
        "janela_dias": DIAS,
        "fonte": "ERP AVA · programacaoembarque (km contratado da viagem)",
        # O CARIMBO ATRAVESSA. `cached` marca o dicionário QUE ELE GUARDOU, e
        # esta função monta outro por cima — sem repassar, a rede existiria no
        # servidor e a tarja nunca apareceria na tela: número velho servido
        # CALADO, que é o pior dos três estados possíveis. Quem transforma isto
        # no cabeçalho `X-Leitura-Velha` é o `JSONResponse` da casa.
        **_carimbo(d),
    }


def _carimbo(bruto: dict) -> dict:
    """As três chaves que o `cached` põe quando serve a última leitura boa."""
    if not bruto.get("leitura_velha"):
        return {}
    return {"leitura_velha": True,
            "leitura_idade_seg": bruto.get("leitura_idade_seg"),
            "leitura_em": bruto.get("leitura_em")}
