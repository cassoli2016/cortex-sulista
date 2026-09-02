# -*- coding: utf-8 -*-
"""Compras da OS — o que a oficina compra por ordem de serviço, e quando.

O QUE ISTO MEDE (e o que NÃO mede)
==================================
A compra da manutenção nasce de uma ordem de serviço: a `solicitacaocompra`
carrega em `numerodocumento` o número da OS, e o vínculo casa em 99,6% das
solicitações. Duas perguntas saem daí e não existem em tela nenhuma hoje:

1. **Quanto tempo passa entre abrir a OS e formalizar a compra** dos itens dela.
   Medido em 12 meses: mediana de 3 dias, p90 de 16, e a fatia acima de 15 dias
   caiu de 38,7% em 2024 para 8,9% em 2026 — melhora real de processo.
2. **O mix do que se compra** por classe de operação (peça, serviço, sinistro,
   reforma, pneu), com o vínculo à OS, ao tipo de manutenção e ao veículo, que
   o Painel de Custos não tem (lá o corte é por agrupador gerencial).

**NÃO é "veículo parado esperando peça".** `ordemservico.dtfechamento` é
ANTERIOR à compra em 58% das OSs e igual em 27%: a OS se fecha antes de a
compra ser lançada. O que se mede aqui é o atraso ADMINISTRATIVO entre abrir a
OS e formalizar a compra, e o rótulo da tela diz isso com todas as letras.

RECOMPRA PRECOCE
================
Mesma peça comprada de novo para o MESMO veículo dentro de 60 dias, em ORDENS
DE SERVIÇO DIFERENTES, é sinal de falha prematura, retrabalho ou garantia não
acionada. Medido em 12 meses: **291 casos, R$ 59,2 mil, 97 veículos** (465
contando consumível). Duas exclusões, as duas medidas e não arbitradas:

- **par da mesma OS** (64 pares) é o mesmo reparo lançado em duas solicitações,
  quase todos com um dia de intervalo — ver o comentário em `recompras()`;
- **consumível** (parafuso, porca, graxa, faixa refletiva) se recompra por
  natureza. O filtro é uma HEURÍSTICA declarada (`CONSUMIVEIS`), não um campo
  do ERP: o catálogo não marca isso. A tela mostra os dois números e diz qual é
  qual, para a oficina poder corrigir a lista.

Carreta tem muitas rodas e eixos, então a mesma peça trocada em POSIÇÕES
diferentes é recompra legítima — o ERP não grava posição, e por isso a tela
chama a lista de "conferir com a oficina", nunca de defeito.

O AVA é PostgreSQL 9.3: sem `FILTER (WHERE …)` e sem `percentile_cont`. Os
percentis saem em Python (funções puras abaixo, testadas sem banco).
"""
from __future__ import annotations

import re
from datetime import date

from . import db
from .queries import cached

# Classes de compra da oficina, pelo tipo de operação do item. Os códigos vêm
# de `tipooperacao` e foram conferidos contra a descrição do próprio ERP.
CLASSES = [
    ("pecas",     "Peças",     (103,)),
    ("servicos",  "Serviços",  (121, 168)),
    ("pneus",     "Pneus",     (205, 206, 108)),
    ("sinistros", "Sinistros", (219, 135)),
    ("reformas",  "Reformas",  (149, 198)),
]
_DE_CODIGO = {cod: chave for chave, _rot, cods in CLASSES for cod in cods}

TIPO_MANUTENCAO = {1: "Preventiva", 2: "Corretiva", 3: "Ambas"}

# Acima disto a compra da OS deixa de ser rotina administrativa. É dez vezes o
# p90 medido de 1 dia entre encaminhamento e decisão da OC, e o mesmo corte que
# `suprimentos_oc.DIAS_PARADA` usa para "parada".
DIAS_DEMORA = 15

# Janela em que recomprar a mesma peça para o mesmo veículo levanta suspeita.
DIAS_RECOMPRA = 60

# HEURÍSTICA declarada: o catálogo do ERP não marca consumível, e sem esta
# lista o topo da recompra vira parafuso e graxa, que se recompram por
# natureza. A tela mostra o número COM e SEM o filtro, e pede validação da
# oficina — é lista de trabalho, não verdade do sistema.
CONSUMIVEIS = re.compile(
    r"\b(PARAFUSO|PORCA|ARRUELA|GRAXA|OLEO|ÓLEO|LUBRIFICANTE|FITA|COLA|SILICONE|"
    r"ABRACADEIRA|ABRAÇADEIRA|REBITE|PINO|TRAVA ARANHA|FAIXA REFLETIVA|LAMPADA|"
    r"LÂMPADA|FUSIVEL|FUSÍVEL|ESTOPA|SOLDA|ELETRODO|ELETRODO|DESENGRAXANTE|"
    r"SPRAY|TINTA|LIXA|VEDANTE|ANEL O|ORING|O-RING)\b", re.IGNORECASE)


ITENS_SQL = """
SELECT s.filial,
       s.numero                              AS solicitacao,
       to_char(s.dtemissao, 'YYYY-MM-DD')    AS data,
       s.numerodocumento                     AS os,
       to_char(os.dtemissao, 'YYYY-MM-DD')   AS os_data,
       os.tipomanutencao,
       os.veiculo,
       i.tipooperacao,
       i.produto,
       coalesce(nullif(trim(p.descricao), ''), '(sem descrição no catálogo)') AS descricao,
       coalesce(i.valortotal, 0)::float8     AS valor
FROM solicitacaocompra s
JOIN solicitacaocompra_item i
  ON i.grupo = s.grupo AND i.empresa = s.empresa AND i.filial = s.filial
 AND i.unidade = s.unidade AND i.diferenciadornumero = s.diferenciadornumero
 AND i.numero = s.numero
LEFT JOIN ordemservico os
  ON os.grupo = s.grupo AND os.empresa = s.empresa AND os.filial = s.filialdocumento
 AND os.unidade = s.unidadedocumento AND os.numero = s.numerodocumento
LEFT JOIN produto p
  ON p.grupo = i.grupo AND p.empresa = i.empresa AND p.codigo = i.produto
WHERE s.semaforo = 1
  AND s.dtemissao >= %(dt_de)s::date
  AND s.dtemissao < %(dt_ate)s::date + 1
  AND (s.filial = %(filial)s OR %(filial)s::int IS NULL)
"""


# ---------------------------------------------------------------- puro (testável)

def percentil(valores: list[float], p: float) -> float:
    """Percentil por posição (o `percentile_disc` que o PG 9.3 não tem).

    Lista vazia devolve 0. `p` em fração (0,5 = mediana).
    """
    if not valores:
        return 0.0
    v = sorted(valores)
    i = min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))
    return v[i]


def classe_do_item(tipooperacao) -> str:
    """Classe de compra da oficina. Código fora do mapa vira 'outros' — não se
    inventa rótulo para código sem domínio conhecido."""
    return _DE_CODIGO.get(tipooperacao, "outros")


def e_consumivel(descricao: str) -> bool:
    return bool(CONSUMIVEIS.search(descricao or ""))


def dias_ate_a_compra(itens: list[dict]) -> list[dict]:
    """Uma linha por OS, com os dias entre abrir a OS e a PRIMEIRA solicitação.

    Só a primeira: uma OS pode gerar várias compras, e contar todas puxaria a
    mediana para cima por causa de complementos legítimos. Diferença negativa
    (compra lançada antes da OS) ou acima de 400 dias sai — é lançamento
    retroativo, não prazo.
    """
    primeira: dict = {}
    for it in itens:
        if not it.get("os") or not it.get("os_data") or not it.get("data"):
            continue
        chave = (it["filial"], it["os"])
        atual = primeira.get(chave)
        if atual is None or it["data"] < atual["data"]:
            primeira[chave] = it

    saida = []
    for (filial, os_num), it in primeira.items():
        d = (date.fromisoformat(it["data"]) - date.fromisoformat(it["os_data"])).days
        if d < 0 or d > 400:
            continue
        saida.append({"filial": filial, "os": os_num, "dias": d,
                      "mes": it["data"][:7],
                      "tipomanutencao": it.get("tipomanutencao"),
                      "veiculo": it.get("veiculo")})
    return saida


def _resumo_dias(linhas: list[dict]) -> dict:
    d = [x["dias"] for x in linhas]
    return {"os": len(d),
            "mediana": percentil(d, 0.5), "p90": percentil(d, 0.9),
            "demoradas": sum(1 for x in d if x > DIAS_DEMORA)}


def tempo_por_mes(linhas: list[dict]) -> list[dict]:
    por: dict = {}
    for x in linhas:
        por.setdefault(x["mes"], []).append(x)
    return [{"mes": m, **_resumo_dias(por[m])} for m in sorted(por)]


def tempo_por_dimensao(linhas: list[dict], campo: str) -> list[dict]:
    por: dict = {}
    for x in linhas:
        por.setdefault(x.get(campo), []).append(x)
    saida = [{"chave": k, **_resumo_dias(v)} for k, v in por.items()]
    saida.sort(key=lambda x: -x["os"])
    return saida


def mix_mensal(itens: list[dict]) -> list[dict]:
    chaves = [c[0] for c in CLASSES] + ["outros"]
    por: dict = {}
    for it in itens:
        m = it["data"][:7]
        e = por.setdefault(m, {"mes": m, "valor": 0.0, "itens": 0,
                               "solicitacoes": set(), **{c: 0.0 for c in chaves}})
        e[classe_do_item(it["tipooperacao"])] += it["valor"]
        e["valor"] += it["valor"]
        e["itens"] += 1
        e["solicitacoes"].add((it["filial"], it["solicitacao"]))
    saida = []
    for m in sorted(por):
        e = por[m]
        e["solicitacoes"] = len(e["solicitacoes"])
        saida.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in e.items()})
    return saida


def recompras(itens: list[dict], dias: int = DIAS_RECOMPRA) -> list[dict]:
    """Mesma peça, mesmo veículo, de novo dentro da janela.

    Só peça (classe `pecas`): serviço e pneu se repetem por natureza. Cada
    linha traz a compra ANTERIOR mais próxima, que é a evidência.

    PAR DA MESMA OS NÃO É RECOMPRA. Medido em 12 meses: 64 dos 355 pares têm a
    MESMA ordem de serviço dos dois lados, e o intervalo deles é quase todo de
    UM dia — é o mesmo reparo lançado em duas solicitações, não falha precoce.
    Um piso de dias não separava isso (a distribuição por dias é lisa, sem
    degrau: 19 pares em 1 dia, 25 em 2-3, 28 em 4-7, 141 em 31-60); a OS
    separa. Sobram 291 recorrências de verdade, em OSs diferentes.
    """
    porto: dict = {}
    for it in itens:
        if classe_do_item(it["tipooperacao"]) != "pecas":
            continue
        if not it.get("veiculo") or it["valor"] <= 0:
            continue
        porto.setdefault((it["veiculo"], it["produto"]), []).append(it)

    saida = []
    for (veiculo, produto), compras in porto.items():
        compras.sort(key=lambda x: x["data"])
        for anterior, atual in zip(compras, compras[1:]):
            delta = (date.fromisoformat(atual["data"]) - date.fromisoformat(anterior["data"])).days
            if not 0 < delta <= dias:
                continue
            if anterior.get("os") and atual.get("os") and anterior["os"] == atual["os"]:
                continue      # mesmo reparo, duas solicitações
            if True:
                saida.append({
                    "veiculo": veiculo, "produto": produto,
                    "descricao": atual["descricao"],
                    "data": atual["data"], "data_anterior": anterior["data"],
                    "dias": delta, "valor": round(atual["valor"], 2),
                    "filial": atual["filial"], "solicitacao": atual["solicitacao"],
                    "os": atual.get("os"), "os_anterior": anterior.get("os"),
                    "consumivel": e_consumivel(atual["descricao"]),
                })
    saida.sort(key=lambda x: (x["consumivel"], x["dias"]))
    return saida


def resumo(itens: list[dict], linhas: list[dict], recomp: list[dict]) -> dict:
    r = _resumo_dias(linhas)
    sem_cons = [x for x in recomp if not x["consumivel"]]
    com_os = sum(1 for it in itens if it.get("os"))
    return {
        "itens": len(itens),
        "valor": round(sum(it["valor"] for it in itens), 2),
        "solicitacoes": len({(it["filial"], it["solicitacao"]) for it in itens}),
        "cobertura_os": com_os,
        "os": r["os"], "mediana_dias": r["mediana"], "p90_dias": r["p90"],
        "demoradas": r["demoradas"],
        "dias_demora": DIAS_DEMORA,
        "recompras": len(sem_cons),
        "recompras_valor": round(sum(x["valor"] for x in sem_cons), 2),
        "recompras_veiculos": len({x["veiculo"] for x in sem_cons}),
        "recompras_com_consumivel": len(recomp),
        "por_classe": {c: round(sum(it["valor"] for it in itens
                                    if classe_do_item(it["tipooperacao"]) == c), 2)
                       for c, _rot, _cods in CLASSES},
    }


# ---------------------------------------------------------------- consulta

MAX_RECOMPRAS = 150


@cached(ttl=300)
def get_compras_os(filial: int | None, dt_de: str, dt_ate: str) -> dict:
    params = {"dt_de": dt_de, "dt_ate": dt_ate, "filial": filial}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL enable_mergejoin = off")
        cur.execute(ITENS_SQL, params)
        itens = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    linhas = dias_ate_a_compra(itens)
    recomp = recompras(itens)
    return {
        "kpis": resumo(itens, linhas, recomp),
        "mix": mix_mensal(itens),
        "classes": [{"chave": c, "rotulo": r} for c, r, _ in CLASSES] + [
            {"chave": "outros", "rotulo": "Outros"}],
        "tempo_mensal": tempo_por_mes(linhas),
        "tempo_tipo": [{**x, "rotulo": TIPO_MANUTENCAO.get(x["chave"], "não informado")}
                       for x in tempo_por_dimensao(linhas, "tipomanutencao")],
        "tempo_filial": tempo_por_dimensao(linhas, "filial"),
        "recompras": recomp[:MAX_RECOMPRAS],
        "recompras_total": len(recomp),
        "dt_de": dt_de, "dt_ate": dt_ate, "filial": filial,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · solicitacaocompra × item × ordemservico "
                  "(vínculo pelo número do documento) · leitura"),
    }


def snapshot_copiloto() -> dict:
    """Só KPIs escalares — sem placa, sem número de OS, sem descrição de peça.
    Doze meses, o mesmo recorte que a sub-aba abre."""
    hoje = date.today()
    ano, mes = hoje.year, hoje.month - 11
    while mes < 1:
        mes += 12
        ano -= 1
    de, ate = date(ano, mes, 1).isoformat(), hoje.isoformat()
    k = get_compras_os(None, de, ate)["kpis"]
    return {
        "janela": {"de": de, "ate": ate},
        "comprado_via_os": k["valor"], "itens": k["itens"],
        "solicitacoes": k["solicitacoes"],
        "os_medidas": k["os"],
        "dias_ate_a_compra_mediana": k["mediana_dias"],
        "dias_ate_a_compra_p90": k["p90_dias"],
        "os_demoradas": k["demoradas"], "corte_de_demora_dias": k["dias_demora"],
        "recompra_precoce": k["recompras"],
        "recompra_precoce_valor": k["recompras_valor"],
        "recompra_precoce_veiculos": k["recompras_veiculos"],
        "por_classe": k["por_classe"],
    }
