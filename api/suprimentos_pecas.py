# -*- coding: utf-8 -*-
"""Preço de Peças — o que a oficina paga pela mesma peça, e onde isso destoa.

DE ONDE VEM (medido em 02/09/2026, janela de 12 meses)
======================================================
A compra de peça da manutenção passa por `solicitacaocompra` + `_item`, que no
AVA NÃO é requisição interna com fila e aprovação: é o passo técnico da ordem
de compra de manutenção (`ordemcompra.tipo` 6) amarrada a uma ordem de serviço.
Medido: prazo solicitação -> OC tem mediana ZERO (92-97% no mesmo dia), o campo
de supervisor é nulo em 100% das linhas e `dtcancelamento` também. Por isso a
tela não fala de fila nem de aprovação — fala de PREÇO, que é o que esses dados
respondem bem.

- `tipooperacao = 103` (MANUTENCAO PECAS) são 11.515 itens e R$ 2,6 mi em 12m.
  Serviços (121/168), pneus (205/206), sinistros (219) e reformas (149) ficam de
  FORA: misturar serviço com peça envenena a mediana do produto, que é o eixo
  da tela. Peça de sinistro e de reforma somam R$ 118 mil e têm contexto próprio.
- Cobertura é integral no recorte: preço unitário, quantidade, produto e
  fornecedor preenchidos em 11.515 de 11.515 itens; 888 produtos, 123
  fornecedores.
- `semaforo = 1` é obrigatório: `semaforo = 0` é rascunho que nunca virou OC
  (68% deles sem item nenhum). Não existe cancelamento nesta tabela.

O QUE LIMITA A LEITURA (e a tela precisa dizer na cara)
=======================================================
O catálogo é genérico: 3,7 mil códigos com a MARCA nula em 99,96% deles. O mesmo
código cobre peça original e paralela, unitária e conjunto. Consequências:
- "CONJUNTO PINTURA" tem mediana de R$ 120 e uma compra de R$ 4.100 — pintura de
  retoque e pintura inteira dividem o código;
- "AMORTECEDOR DIANTEIRO" tem mediana R$ 529 e uma compra de R$ 40.541,50 a
  unidade, que é quase certamente erro de digitação.
Por isso a tela NUNCA chama o desvio de sobrepreço: chama de item A CONFERIR, e
a economia da consolidação sai em FAIXA (conservadora x bruta), com a
conservadora excluindo produto cujo spread passa de 3x — a marca do código que
mistura coisas diferentes.

MEDIANA, NUNCA MÉDIA: um item a 76x a mediana move a média do produto e a régua
passa a inocentar o próprio outlier. E só entra na régua produto com pelo menos
`MIN_COMPRAS` compras na janela — com duas ou três, "mediana" é ruído.

O AVA é PostgreSQL 9.3: sem FILTER (WHERE …) e sem percentile_cont. A mediana
sai em Python, o que também deixa a regra testável sem banco (ver as funções
puras abaixo, todas usadas por tests/suprimentos/).
"""
from __future__ import annotations

from datetime import date

from . import db
from .queries import _mask_doc, cached

# Peças de manutenção. Ver o cabeçalho para por que serviço/pneu/sinistro ficam fora.
TIPO_PECA = 103

# Abaixo disto a "mediana do produto" é ruído e o item não entra na régua.
MIN_COMPRAS = 5

# Faixas do desvio contra a mediana do próprio produto.
FAIXA_GRAVE = 3.0        # acima disto: conferir com prioridade
FAIXA_ATENCAO = 1.5      # entre 1,5x e 3x: revisar
FAIXA_BARATO = 1 / 3.0   # abaixo de 1/3: unidade ou quantidade provavelmente errada

# Spread a partir do qual o produto é tratado como código que mistura itens
# diferentes — sai da economia conservadora.
SPREAD_SUSPEITO = 3.0

# Um fornecedor só entra na comparação de preço com pelo menos tantas compras
# do MESMO produto: uma compra isolada não é o preço praticado por ele.
MIN_COMPRAS_FORNECEDOR = 2


ITENS_SQL = """
SELECT s.filial,
       s.numero                                   AS solicitacao,
       to_char(s.dtemissao, 'YYYY-MM-DD')         AS data,
       s.numerodocumento                          AS os,
       i.produto,
       coalesce(nullif(trim(p.descricao), ''), '(sem descrição no catálogo)') AS descricao,
       i.fornecedor                               AS fornecedor_doc,
       coalesce(nullif(trim(c.nomefantasia), ''), nullif(trim(c.razaosocial), ''),
                '(sem cadastro)')                 AS fornecedor,
       coalesce(i.quantidade, 0)::float8          AS quantidade,
       coalesce(i.valorunitario, 0)::float8       AS preco,
       coalesce(i.valortotal, 0)::float8          AS valor
FROM solicitacaocompra s
JOIN solicitacaocompra_item i
  ON i.grupo = s.grupo AND i.empresa = s.empresa AND i.filial = s.filial
 AND i.unidade = s.unidade AND i.diferenciadornumero = s.diferenciadornumero
 AND i.numero = s.numero
LEFT JOIN produto p
  ON p.grupo = i.grupo AND p.empresa = i.empresa AND p.codigo = i.produto
LEFT JOIN cadastro c ON c.codigo = i.fornecedor
WHERE s.semaforo = 1
  AND i.tipooperacao = %(tipo)s
  AND s.dtemissao >= %(dt_de)s::date
  AND s.dtemissao < %(dt_ate)s::date + 1
  AND coalesce(i.valorunitario, 0) > 0
  AND coalesce(i.quantidade, 0) > 0
  AND (s.filial = %(filial)s OR %(filial)s::int IS NULL)
"""


# ---------------------------------------------------------------- puro (testável)

def mediana(valores: list[float]) -> float:
    """Mediana de uma lista já materializada. Lista vazia devolve 0.0.

    Par: média dos dois centrais — o mesmo que o `percentile_cont` que o PG 9.3
    não tem, e que o PG 16 do futuro espelho vai ter.
    """
    if not valores:
        return 0.0
    v = sorted(valores)
    n = len(v)
    meio = n // 2
    return v[meio] if n % 2 else (v[meio - 1] + v[meio]) / 2.0


def medianas_por_produto(itens: list[dict]) -> dict:
    """{produto: (mediana, n_compras)} — a régua de cada código."""
    precos: dict = {}
    for it in itens:
        precos.setdefault(it["produto"], []).append(it["preco"])
    return {p: (mediana(v), len(v)) for p, v in precos.items()}


def classificar(preco: float, med: float) -> str:
    """Onde o item cai contra a mediana do próprio produto."""
    if med <= 0:
        return "sem_regua"
    r = preco / med
    if r > FAIXA_GRAVE:
        return "grave"
    if r > FAIXA_ATENCAO:
        return "atencao"
    if r < FAIXA_BARATO:
        return "barato"
    return "normal"


def alertas_de_preco(itens: list[dict]) -> list[dict]:
    """Itens fora do padrão do próprio produto, do maior impacto para o menor.

    `impacto` é quanto se pagou ACIMA da mediana naquele item (preço − mediana,
    vezes a quantidade). Em item barato o impacto é negativo e serve de sinal de
    unidade errada, não de economia — por isso o sinal fica preservado.
    """
    med = medianas_por_produto(itens)
    fora = []
    for it in itens:
        m, n = med.get(it["produto"], (0.0, 0))
        if n < MIN_COMPRAS:
            continue
        classe = classificar(it["preco"], m)
        if classe in ("normal", "sem_regua"):
            continue
        fora.append({**it,
                     "mediana": round(m, 4),
                     "compras_do_produto": n,
                     "multiplo": round(it["preco"] / m, 2) if m else None,
                     "impacto": round((it["preco"] - m) * it["quantidade"], 2),
                     "classe": classe})
    # Ordem: primeiro o que se PAGOU A MAIS, do maior para o menor; depois os
    # baratos demais. Ordenar tudo por |impacto| juntava as duas coisas e o
    # segundo lugar da tela virava um item de R$ 0,62 — informação boa, leitura
    # errada numa tela cujo assunto é sobrepreço.
    ordem = {"grave": 0, "atencao": 1, "barato": 2}
    fora.sort(key=lambda x: (ordem.get(x["classe"], 9), -abs(x["impacto"])))
    return fora


def dispersao_por_produto(itens: list[dict]) -> list[dict]:
    """Produto comprado de mais de um fornecedor, e quanto custa essa dispersão.

    O preço de cada fornecedor é a MEDIANA dele naquele produto — média deixaria
    uma compra atípica definir o "melhor preço" e inflar a economia.
    `economia` é o teto teórico de comprar tudo pelo melhor preço mediano:
    disponibilidade, prazo e frete não entram, e a tela diz isso.
    """
    porto: dict = {}
    for it in itens:
        porto.setdefault(it["produto"], {}).setdefault(
            it["fornecedor"], {"precos": [], "qtd": 0.0, "valor": 0.0, "n": 0,
                               "doc": it["fornecedor_doc"], "desc": it["descricao"]})
        e = porto[it["produto"]][it["fornecedor"]]
        e["precos"].append(it["preco"])
        e["qtd"] += it["quantidade"]
        e["valor"] += it["valor"]
        e["n"] += 1

    saida = []
    for produto, fornecedores in porto.items():
        validos = {f: e for f, e in fornecedores.items() if e["n"] >= MIN_COMPRAS_FORNECEDOR}
        if len(validos) < 2:
            continue
        precos = {f: mediana(e["precos"]) for f, e in validos.items()}
        melhor_f = min(precos, key=lambda f: precos[f])
        pior_f = max(precos, key=lambda f: precos[f])
        melhor, pior = precos[melhor_f], precos[pior_f]
        if melhor <= 0:
            continue
        gasto = sum(e["valor"] for e in validos.values())
        qtd = sum(e["qtd"] for e in validos.values())
        spread = pior / melhor
        saida.append({
            "produto": produto,
            "descricao": next(iter(validos.values()))["desc"],
            "fornecedores": len(validos),
            "melhor_preco": round(melhor, 4), "melhor_fornecedor": melhor_f,
            "pior_preco": round(pior, 4), "pior_fornecedor": pior_f,
            "spread": round(spread, 2),
            "quantidade": round(qtd, 2),
            "gasto": round(gasto, 2),
            "economia": round(max(gasto - melhor * qtd, 0.0), 2),
            "suspeito": spread >= SPREAD_SUSPEITO,
        })
    saida.sort(key=lambda x: -x["economia"])
    return saida


def serie_mensal(itens: list[dict]) -> list[dict]:
    """Gasto e nº de itens por mês de emissão da solicitação."""
    acc: dict = {}
    for it in itens:
        m = it["data"][:7]
        e = acc.setdefault(m, {"mes": m, "valor": 0.0, "itens": 0})
        e["valor"] += it["valor"]
        e["itens"] += 1
    return [{"mes": m, "valor": round(acc[m]["valor"], 2), "itens": acc[m]["itens"]}
            for m in sorted(acc)]


def resumo(itens: list[dict], alertas: list[dict], dispersao: list[dict]) -> dict:
    """Os números do topo da tela.

    `economia_conservadora` exclui produto com spread >= SPREAD_SUSPEITO: é o
    número que se pode levar a uma negociação sem passar vergonha. A bruta fica
    ao lado, declarada como teto.
    """
    med = medianas_por_produto(itens)
    com_regua = sum(1 for it in itens if med.get(it["produto"], (0, 0))[1] >= MIN_COMPRAS)
    graves = [a for a in alertas if a["classe"] == "grave"]
    atencao = [a for a in alertas if a["classe"] == "atencao"]
    baratos = [a for a in alertas if a["classe"] == "barato"]
    return {
        "itens": len(itens),
        "valor": round(sum(it["valor"] for it in itens), 2),
        "produtos": len(med),
        "fornecedores": len({it["fornecedor"] for it in itens}),
        "itens_com_regua": com_regua,
        "graves": len(graves),
        "graves_impacto": round(sum(a["impacto"] for a in graves), 2),
        "atencao": len(atencao),
        "atencao_impacto": round(sum(a["impacto"] for a in atencao), 2),
        "baratos": len(baratos),
        "produtos_multi": len(dispersao),
        "gasto_multi": round(sum(d["gasto"] for d in dispersao), 2),
        "economia_conservadora": round(sum(d["economia"] for d in dispersao
                                           if not d["suspeito"]), 2),
        "economia_bruta": round(sum(d["economia"] for d in dispersao), 2),
    }


# ---------------------------------------------------------------- consulta

MAX_ALERTAS = 200
MAX_DISPERSAO = 100


@cached(ttl=300)
def get_precos_pecas(filial: int | None, dt_de: str, dt_ate: str) -> dict:
    params = {"tipo": TIPO_PECA, "dt_de": dt_de, "dt_ate": dt_ate, "filial": filial}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL enable_mergejoin = off")
        cur.execute(ITENS_SQL, params)
        itens = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    alertas = alertas_de_preco(itens)
    dispersao = dispersao_por_produto(itens)
    kpis = resumo(itens, alertas, dispersao)

    def limpa(a: dict) -> dict:
        """O documento do fornecedor sai mascarado: pode ser CPF de pessoa
        física (14 dígitos = CNPJ, 11 = CPF) e a tela não precisa dele."""
        d = {k: v for k, v in a.items() if k != "fornecedor_doc"}
        d["fornecedor_doc"] = _mask_doc(a.get("fornecedor_doc"))
        return d

    return {
        "kpis": kpis,
        "alertas": [limpa(a) for a in alertas[:MAX_ALERTAS]],
        "alertas_total": len(alertas),
        "dispersao": [{k: v for k, v in d.items()} for d in dispersao[:MAX_DISPERSAO]],
        "dispersao_total": len(dispersao),
        "serie": serie_mensal(itens),
        "dt_de": dt_de, "dt_ate": dt_ate, "filial": filial,
        "min_compras": MIN_COMPRAS,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · solicitacaocompra × item (tipo de operação "
                  f"{TIPO_PECA}, peças de manutenção) × produto × cadastro · leitura"),
    }


def periodo_padrao() -> tuple[str, str]:
    """Doze meses em MESES FECHADOS mais o corrente: a régua da mediana precisa
    de volume por produto (com 90 dias sobram 2,8 mil itens dos 11,4 mil, e
    metade dos produtos cai abaixo do mínimo de compras).

    Começa no dia 1 do mês de 11 meses atrás, não em "hoje menos 365 dias" —
    senão a série abre e fecha no mesmo mês pela metade e o gráfico mostra
    treze barras, com a primeira e a última parciais sem que nada diga isso.
    """
    hoje = date.today()
    ano, mes = hoje.year, hoje.month - 11
    while mes < 1:
        mes += 12
        ano -= 1
    return date(ano, mes, 1).isoformat(), hoje.isoformat()


def snapshot_copiloto() -> dict:
    """Só KPIs escalares — sem produto, sem fornecedor, sem número de
    solicitação. Lê o cache do AVA pelo mesmo caminho da tela; nunca dispara
    coleta externa (não há nenhuma aqui, e a regra vale de qualquer forma)."""
    de, ate = periodo_padrao()
    d = get_precos_pecas(None, de, ate)
    k = d["kpis"]
    return {
        "janela": {"de": de, "ate": ate},
        "comprado": k["valor"], "itens": k["itens"],
        "produtos": k["produtos"], "fornecedores": k["fornecedores"],
        "itens_a_conferir": k["graves"], "acima_da_mediana": k["graves_impacto"],
        "itens_acima_do_padrao": k["atencao"],
        "itens_baratos_demais": k["baratos"],
        "produtos_multi_fornecedor": k["produtos_multi"],
        "economia_consolidacao": k["economia_conservadora"],
        "economia_teto": k["economia_bruta"],
        "cobertura_da_regua": k["itens_com_regua"],
        "min_compras": MIN_COMPRAS,
    }
