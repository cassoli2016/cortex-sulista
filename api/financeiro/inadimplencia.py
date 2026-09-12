# -*- coding: utf-8 -*-
"""A inadimplência do dia — o que o e-mail das 13h e o Copiloto leem.

PEDIDO DE QUEM OPERA (12/09/2026): "um e-mail automático da inadimplência
todos os dias às 13:00, exceto finais de semana, robusto, com gráficos e
indicadores relevantes para tomada de decisão".

A REGRA É A OFICIAL DA CASA, e não uma nova. O vencido é o de
`queries._COB_FROM`/`_COB_WHERE` — fatura × fatura_composicao × conhecimento,
só o faturado, documentos 6/8/10/11 e CT-e válido —, o MESMO das telas Contas
a Receber e Régua de Cobrança. Duas telas lendo a mesma fonte com política
própria discordam por construção, e o e-mail seria a terceira.

A SÉRIE É RECONSTRUÍDA DO ERP, e o método foi MEDIDO antes de ser escrito
(12/09/2026). O ponto de cada dia é o que estava vencido e em aberto ao FECHAR
o dia: venceu até ele, e não foi pago nem cancelado até ele. Em 29 de 29 dias,
fechamento anterior + entrou − recuperado − cancelado = fechamento do dia; e o
fechamento de ontem saiu IGUAL ao oficial de agora, ao centavo.
Duas aproximações, ditas no rodapé do e-mail:
- o que foi pago depois entra pelo VALOR DO TÍTULO da composição. O
  `valorpago` do ERP não fecha com ele (em 60 dias o pago somou ~30% menos que
  o título — retenção, desconto), e o que interessa é quanto estava pendente
  naquele dia;
- pagamento PARCIAL conta pelo que resta hoje: 0,4% das composições em
  aberto, quase todas ainda por vencer. É o teto do erro. Nenhuma data de
  previsão estava remarcada entre os vencidos.
(Os números medidos ficam fora deste arquivo de propósito: o repositório é
público, e a carteira da casa não é.)

O QUE FICOU DE FORA, e por quê:
- o ESTÁGIO DA COBRANÇA (`dtenvioemailinadimplente`, cartório, protesto,
  jurídico, extrajudicial): as colunas existem no ERP e estão VAZIAS em 12
  meses. Mostrá-las diria "nada feito" sobre toda a carteira — e o que falta é
  o lançamento, não necessariamente a cobrança.
- FERIADO: a casa não tem calendário; dia útil é de segunda a sexta.
- o DIA EM CURSO nos fluxos: às 13h metade dos pagamentos de hoje ainda não
  foi lançada. Entrou e recuperado medem dias úteis FECHADOS; o estoque de
  agora é o único número de hoje.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from api import db, queries

log = logging.getLogger("cortex.financeiro.inadimplencia")

#: Os documentos que contam — o MESMO trecho da regra oficial. Há teste que
#: exige este texto dentro de `_COB_WHERE` e de `_REC_OF_WHERE`: se a regra
#: mudar lá, a série daqui não pode ficar para trás calada.
DOCS = ("fc.tipodocumentoorigem = ANY(string_to_array('6,8,10,11',',')::int[])\n"
        "  AND (fc.tipodocumentoorigem <> 6 OR co.situacaocte = 3)")
VENC = queries._REC_OF_VENC

#: O semáforo da taxa — os MESMOS limiares do cartão "Vencido" da tela Contas
#: a Receber: acima de 5% pede cobrança ativa, acima de 10% é inadimplência
#: estrutural. Duas réguas para o mesmo número se contradiriam na primeira vez
#: que alguém comparasse a tela com o e-mail.
ATENCAO, ALTA = 0.05, 0.10

#: Saldo abaixo disto sai das LISTAS e fica nos TOTAIS. A regra oficial conta
#: todo pendente acima de zero, e há cliente com uma dúzia de títulos somando
#: centavos: na lista de quem cobrar, uma linha "R$ 0" é ruído que parece
#: defeito — e cobrança nenhuma começa por ela. O e-mail diz quantos saíram.
#: Medido em 12/09/2026: todos os vencidos abaixo de R$ 1 eram R$ 0,01 que
#: sobrou de pagamento parcial (o parcial lançado um centavo abaixo do título).
RESIDUO = 1.0

DIAS_SERIE = 30          # dias corridos reconstruídos (cobrem os 13 úteis com folga)
DIAS_UTEIS_SERIE = 12    # pontos do gráfico do vencido
DIAS_UTEIS_JANELA = 5    # entrou, recuperado, "entraram e seguem" e "vencem em"
TOP = 10

FAIXAS = (("2_vencido_ate_30", "até 30 dias"),
          ("3_vencido_31_90", "31 a 90 dias"),
          ("4_vencido_91_365", "91 a 365 dias"),
          ("5_vencido_mais_365", "mais de 1 ano"))

FONTE = ("fatura × fatura_composicao × conhecimento (AVA) · regra oficial das "
         "telas Contas a Receber e Régua de Cobrança")

# ------------------------------------------------------------------ as consultas

TOTAIS_SQL = f"""
SELECT coalesce(sum(fc.valorpendentecnpjcliente),0)::float8 AS vencido,
       count(*)::int AS titulos,
       count(DISTINCT f.cliente)::int AS clientes,
       coalesce(sum(CASE WHEN {queries._COB_DV} > 90
                         THEN fc.valorpendentecnpjcliente END),0)::float8 AS mais_90,
       coalesce(sum(CASE WHEN {queries._COB_DV} > 90 THEN 1 ELSE 0 END),0)::int AS titulos_mais_90
{queries._COB_FROM} {queries._COB_WHERE}
"""

ABERTO_SQL = f"""
SELECT coalesce(sum(fc.valorpendentecnpjcliente),0)::float8 AS aberto,
       count(*)::int AS titulos
{queries._REC_OF_FROM} {queries._REC_OF_WHERE}
"""

_NOME = ("coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), "
         "'(sem cadastro)')")

# Venceram desde `desde` e CONTINUAM em aberto: é a cobrança fresca — o cliente
# ainda lembra da fatura, e é o atraso mais barato de resolver.
NOVOS_SQL = f"""
SELECT {_NOME} AS cliente, count(*)::int AS titulos,
       sum(fc.valorpendentecnpjcliente)::float8 AS valor,
       min({VENC})::text AS venc_de, max({VENC})::text AS venc_ate
{queries._COB_FROM}
LEFT JOIN cadastro c ON c.codigo = f.cliente
{queries._COB_WHERE}
  AND {VENC} >= %(desde)s::date
GROUP BY f.cliente, c.nomefantasia, c.razaosocial
ORDER BY 3 DESC
"""

# Em aberto e AINDA NÃO vencido, vencendo até `ate`: o que dá para lembrar antes.
AVENCER_SQL = f"""
SELECT {_NOME} AS cliente, count(*)::int AS titulos,
       sum(fc.valorpendentecnpjcliente)::float8 AS valor,
       min({VENC})::text AS venc_de, max({VENC})::text AS venc_ate
{queries._REC_OF_FROM}
LEFT JOIN cadastro c ON c.codigo = f.cliente
{queries._REC_OF_WHERE}
  AND {VENC} >= current_date AND {VENC} <= %(ate)s::date
GROUP BY f.cliente, c.nomefantasia, c.razaosocial
ORDER BY 3 DESC
"""

# A SÉRIE, no FECHAMENTO de cada dia (ver o docstring do módulo). O LEFT JOIN
# mantém o dia sem nada vencido na série: `GROUP BY` não devolve o dia sem
# linha, e o gráfico emendaria o dia anterior no seguinte.
SERIE_SQL = f"""
WITH base AS (
  SELECT {VENC} AS venc, f.dtpagamento AS pago, f.dtcancelamento AS canc,
         CASE WHEN f.dtpagamento IS NULL AND f.dtcancelamento IS NULL
              THEN fc.valorpendentecnpjcliente ELSE fc.valortitulo END AS valor
  {queries._REC_OF_FROM}
  WHERE f.grupo=1 AND f.composicao=1 AND {DOCS}
    AND (f.dtpagamento IS NULL OR f.dtpagamento >= current_date - %(dias)s)
    AND (f.dtcancelamento IS NULL OR f.dtcancelamento >= current_date - %(dias)s)
    AND {VENC} < current_date
    AND (f.dtpagamento IS NOT NULL OR f.dtcancelamento IS NOT NULL
         OR fc.valorpendentecnpjcliente > 0)
), dias AS (
  SELECT t::date AS d FROM generate_series(current_date - %(dias)s, current_date - 1,
                                           interval '1 day') t
)
SELECT dias.d AS dia,
       coalesce(sum(CASE WHEN venc <= dias.d AND (pago IS NULL OR pago > dias.d)
                          AND (canc IS NULL OR canc > dias.d) THEN valor END),0)::float8 AS vencido,
       coalesce(sum(CASE WHEN venc = dias.d AND (pago IS NULL OR pago > dias.d)
                          AND (canc IS NULL OR canc > dias.d) THEN valor END),0)::float8 AS entrou,
       coalesce(sum(CASE WHEN pago = dias.d AND venc < dias.d THEN valor END),0)::float8 AS recuperado,
       coalesce(sum(CASE WHEN canc = dias.d AND venc < dias.d
                          AND (pago IS NULL OR pago > dias.d) THEN valor END),0)::float8 AS cancelado
  FROM dias LEFT JOIN base ON true
 GROUP BY dias.d ORDER BY dias.d
"""


# ------------------------------------------------------------------- dias úteis

def dia_util(d: date) -> bool:
    """Segunda a sexta. Sem feriado — a casa não tem calendário."""
    return d.isoweekday() <= 5


def uteis_antes(hoje: date, n: int) -> list[date]:
    """Os `n` últimos dias úteis ANTES de hoje, do mais antigo ao mais novo."""
    out, d = [], hoje
    while len(out) < n:
        d -= timedelta(days=1)
        if dia_util(d):
            out.append(d)
    return out[::-1]


def uteis_depois(hoje: date, n: int) -> date:
    """O `n`-ésimo dia útil DEPOIS de hoje (fim da janela "vencem em")."""
    d, k = hoje, 0
    while k < n:
        d += timedelta(days=1)
        if dia_util(d):
            k += 1
    return d


def por_dia_util(serie: list[dict], dias: list[date]) -> list[dict]:
    """A série corrida vira série de dias úteis.

    Cada dia útil leva o fechamento DELE e o fluxo desde o dia útil anterior:
    o título que venceu no sábado entrou em atraso no fim de semana, e é na
    segunda que alguém pode fazer algo com ele. O primeiro dia da lista só
    serve de borda para o fluxo do segundo, e não sai.
    """
    idx = {(s["dia"] if isinstance(s["dia"], date) else date.fromisoformat(str(s["dia"])[:10])): s
           for s in serie}
    out = []
    for i in range(1, len(dias)):
        d, ini = dias[i], dias[i - 1] + timedelta(days=1)
        janela = [idx[x] for x in (ini + timedelta(days=k) for k in range((d - ini).days + 1))
                  if x in idx]
        fech = idx.get(d)
        out.append({"dia": d,
                    "vencido": float(fech["vencido"]) if fech else None,
                    "entrou": sum(float(j["entrou"] or 0) for j in janela),
                    "recuperado": sum(float(j["recuperado"] or 0) for j in janela),
                    "cancelado": sum(float(j["cancelado"] or 0) for j in janela)})
    return out


def estado_taxa(taxa: float | None) -> str:
    if taxa is None:
        return "neutro"
    return "bad" if taxa > ALTA else "warn" if taxa > ATENCAO else "ok"


def _data(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _lista(linhas: list[dict], campo_data: str) -> dict:
    itens = sorted(({"cliente": str(l.get("cliente") or "(sem cadastro)"),
                     "valor": float(l.get("valor") or 0),
                     "titulos": int(l.get("titulos") or 0),
                     "data": str(l.get(campo_data) or "")[:10]} for l in linhas),
                   key=lambda x: -x["valor"])
    listaveis = [i for i in itens if i["valor"] >= RESIDUO]
    return {"itens": listaveis[:TOP], "clientes": len(itens),
            "listaveis": len(listaveis),
            "residuais": len(itens) - len(listaveis),
            "titulos": sum(i["titulos"] for i in itens),
            "valor": sum(i["valor"] for i in itens)}


# ---------------------------------------------------------------------- o dia

def montar(*, hoje: date, tot: dict, ab: dict, aging: list, top: list,
           novos: list, avencer: list, pend: dict | None, serie: list,
           lido_em) -> dict:
    """Do que o ERP devolveu, o dia. FUNÇÃO PURA: o teste chega aqui sem ERP."""
    vencido = float(tot.get("vencido") or 0)
    aberto = float(ab.get("aberto") or 0)
    taxa = (vencido / aberto) if aberto else None

    pontos = por_dia_util(serie, uteis_antes(hoje, DIAS_UTEIS_SERIE + 1))
    janela = pontos[-DIAS_UTEIS_JANELA:]
    antes = pontos[-DIAS_UTEIS_JANELA - 1] if len(pontos) > DIAS_UTEIS_JANELA else None
    ultimo = pontos[-1] if pontos else None

    por_faixa = {a["faixa"]: a for a in aging}
    faixas = []
    for chave, rotulo in FAIXAS:
        a = por_faixa.get(chave) or {}
        v = float(a.get("valor") or 0)
        faixas.append({"faixa": chave, "rotulo": rotulo, "valor": v,
                       "titulos": int(a.get("qtd") or 0),
                       "pct": (v / vencido) if vencido else None})

    # O CÓDIGO DO CLIENTE (CNPJ) NÃO SAI DAQUI: o e-mail e o Copiloto leem
    # nome e número, e o documento só existiria para vazar.
    devedores = []
    for c in [t for t in top if float(t.get("vencido") or 0) >= RESIDUO][:TOP]:
        v = float(c.get("vencido") or 0)
        antigo = _data(c.get("vencimento_mais_antigo"))
        devedores.append({"cliente": str(c.get("cliente") or "(sem cadastro)"),
                          "vencido": v, "pct": (v / vencido) if vencido else None,
                          "titulos": int(c.get("titulos") or 0),
                          "dias_mais_antigo": (hoje - antigo).days if antigo else None})
    soma_top = sum(d["vencido"] for d in devedores)

    ref = ultimo["vencido"] if ultimo and ultimo["vencido"] is not None else None
    ref_janela = antes["vencido"] if antes and antes["vencido"] is not None else None
    return {
        "hoje": hoje.isoformat(),
        "lido_em": lido_em.isoformat() if hasattr(lido_em, "isoformat") else lido_em,
        "vencido": vencido, "aberto": aberto, "taxa": taxa,
        "estado_taxa": estado_taxa(taxa),
        "titulos": int(tot.get("titulos") or 0),
        "clientes": int(tot.get("clientes") or 0),
        "mais_90": float(tot.get("mais_90") or 0),
        "titulos_mais_90": int(tot.get("titulos_mais_90") or 0),
        "ultimo_fechamento": ({"dia": ultimo["dia"].isoformat(), "vencido": ref}
                              if ref is not None else None),
        "variacao": (vencido - ref) if ref is not None else None,
        "variacao_janela": (vencido - ref_janela) if ref_janela is not None else None,
        "entrou": sum(p["entrou"] for p in janela),
        "recuperado": sum(p["recuperado"] for p in janela),
        "cancelado": sum(p["cancelado"] for p in janela),
        "pontos": [{**p, "dia": p["dia"].isoformat()} for p in pontos],
        "faixas": faixas,
        "devedores": devedores,
        "concentracao": (soma_top / vencido) if vencido else None,
        "novos": _lista(novos, "venc_ate"),
        "a_vencer": _lista(avencer, "venc_de"),
        "a_vencer_ate": uteis_depois(hoje, DIAS_UTEIS_JANELA).isoformat(),
        "pendente_faturamento": {"valor": float((pend or {}).get("valor") or 0),
                                 "docs": int((pend or {}).get("docs") or 0)},
        "janela_dias_uteis": DIAS_UTEIS_JANELA,
        "fonte": FONTE,
    }


@queries.cached(ttl=300, velha_ate=queries.VELHA_ATE)
def resumo() -> dict:
    """Uma leitura só, numa conexão só: o vencido, a taxa e a série têm de ser
    do MESMO instante, senão o "desde o último fechamento" compara duas fotos."""
    hoje = date.today()
    p_cob = {"filial": None}
    p_rec = {"filial": None, "clientes": None}
    p_aging = {"filial": None, "data_ref": None, "venc_de": None,
               "venc_ate": None, "clientes": None}
    desde = uteis_antes(hoje, DIAS_UTEIS_JANELA + 1)[0] + timedelta(days=1)
    ate = uteis_depois(hoje, DIAS_UTEIS_JANELA)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(TOTAIS_SQL, p_cob)
        tot = cur.fetchone() or {}
        cur.execute(ABERTO_SQL, p_rec)
        ab = cur.fetchone() or {}
        cur.execute(queries.AGING_AR_SQL, p_aging)
        aging = cur.fetchall()
        cur.execute(queries.COB_CLI_SQL, {"filial": None, "cliente": None})
        top = cur.fetchall()
        cur.execute(NOVOS_SQL, {**p_cob, "desde": desde.isoformat()})
        novos = cur.fetchall()
        cur.execute(AVENCER_SQL, {**p_rec, "ate": ate.isoformat()})
        avencer = cur.fetchall()
        cur.execute(queries.COB_PENDENTE_SQL, p_cob)
        pend = cur.fetchone()
        cur.execute(SERIE_SQL, {"dias": DIAS_SERIE})
        serie = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        lido_em = (cur.fetchone() or {}).get("ts") or datetime.now()
    return montar(hoje=hoje, tot=tot, ab=ab, aging=aging, top=top, novos=novos,
                  avencer=avencer, pend=pend, serie=serie, lido_em=lido_em)


def resumo_copiloto() -> dict:
    """Para o snapshot do Copiloto: SÓ ESCALARES. Os nomes dos devedores ficam
    no e-mail — o snapshot vai para o prompt do chat, que pode cair no fallback
    externo, e é por levar só número que esse fallback pode existir."""
    r = resumo()
    return {
        "vencido": r["vencido"], "aberto": r["aberto"],
        "taxa_inadimplencia_pct": (round(100 * r["taxa"], 2)
                                   if r["taxa"] is not None else None),
        "titulos_vencidos": r["titulos"], "clientes_em_atraso": r["clientes"],
        "vencido_mais_90_dias": r["mais_90"],
        "variacao_desde_ultimo_fechamento": r["variacao"],
        "entrou_em_atraso_5_dias_uteis": r["entrou"],
        "recuperado_5_dias_uteis": r["recuperado"],
        "vence_nos_proximos_5_dias_uteis": r["a_vencer"]["valor"],
        "concentracao_10_maiores_pct": (round(100 * r["concentracao"], 1)
                                        if r["concentracao"] is not None else None),
        "pendente_faturamento_vencido": r["pendente_faturamento"]["valor"],
        "lido_em": r["lido_em"],
    }
