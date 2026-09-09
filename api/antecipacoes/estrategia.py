# -*- coding: utf-8 -*-
"""A antecipação vista como LINHA DE CRÉDITO — e o contrafactual.

POR QUE ISTO EXISTE
===================
A tela sabia dizer quanto se antecipou e a que deságio. Não sabia responder a
pergunta que decide: **valeu a pena?** — e a resposta não está no deságio
percentual, que mede prazo, nem na escolha do título, que os dados mostram
ser irrelevante.

O convênio da Tupy antecipa 100% do que entra, em 0,4 dia, automaticamente.
Não há título a escolher. Então a pergunta certa não é "qual antecipar", é
"quanto capital estamos tomando, e a que preço".

O QUE SE MEDE, E POR QUE ASSIM
==============================
`capital_medio` = Σ(valor × prazo) / 365. É o capital que a antecipação
mantém empregado ao longo de um ano — não a soma do que foi antecipado.
Somar R$ 28,4 milhões e chamar de "dívida" seria errado por um fator de
cinco: o mesmo dinheiro gira várias vezes no ano.

`custo_efetivo_aa` = custo total ÷ capital médio. É a taxa que se compara com
qualquer outra linha de crédito da empresa — e a única forma de responder
"antecipar é caro?" sem converter de cabeça.

MEDIDO em 09/09/2026, 12 meses: R$ 28,4 mi antecipados custaram R$ 891 mil,
com prazo médio de 73 dias. Isso é **R$ 5,88 milhões de capital médio a
15,15% ao ano**.

O CONTRAFACTUAL, E A HIPÓTESE QUE ELE MATA
==========================================
A suspeita natural de quem olha R$ 891 mil de custo é "estamos pagando caro
porque não escolhemos o comprador". Dá para medir: para cada mês e faixa de
prazo, qual foi o MELHOR preço que algum investidor praticou de fato ali, e
quanto teria custado se todo o volume tivesse ido por ele.

Resultado: **R$ 12,4 mil em doze meses — 1,4% do custo.** O leilão já é
eficiente, e a hipótese morre com número em vez de voltar a cada trimestre.

O piso de base (`_MIN_OFERTA`) é o que separa preço de ruído: investidor que
levou dois títulos a uma taxa baixa não era uma alternativa disponível para o
volume inteiro, e deixá-lo definir o "melhor preço" inventaria uma economia
que ninguém poderia ter capturado.

E O QUE ESTE NÚMERO **NÃO** É: um limite inferior matemático. Ele compara
contra a MÉDIA do investidor mais barato daquele mês e faixa, e dentro de um
investidor a taxa varia título a título — então um título que saiu abaixo da
média do seu próprio comprador fica, no contrafactual, um pouco mais caro do
que foi. No agregado real isso é ruído (a economia medida é positiva e
pequena), mas quem ler o número precisa saber que ele responde "havia
contraparte mais barata disponível?", e não "qual era o piso possível".

OS CENÁRIOS DE CORTE, E POR QUE ELES VÊM COM O QUE SE PERDE
===========================================================
"Antecipar só o que vence em mais de N dias" economiza deságio. Publicar essa
economia sozinha seria enganoso: ela vem de abrir mão de caixa. Cada cenário
carrega OS DOIS lados — quanto se deixa de gastar e quanto se deixa de
receber —, porque um número de economia sem o seu custo é propaganda.
"""
from __future__ import annotations

from api import pglocal
from api.queries import cached

ESQUEMA: str | None = None

# Quantos títulos um investidor precisa ter levado num mês+faixa para o preço
# dele contar como alternativa REAL. Abaixo disso é ruído: dois títulos a uma
# taxa baixa não eram uma porta por onde o volume inteiro poderia ter passado.
_MIN_OFERTA = 20

# Os cortes de prazo que a tela oferece. Não são recomendação — são o
# tamanho da troca, para quem decide ver os dois lados.
_CORTES = (30, 60, 90)

_BASE = """
  SELECT to_char(date_trunc('month', criado_fornecedor), 'YYYY-MM') AS mes,
         buyer_nome AS investidor,
         width_bucket(payment_date - criado_fornecedor::date, 0, 120, 4) AS faixa,
         payment_value AS valor,
         purchased_tax AS taxa,
         (payment_date - criado_fornecedor::date) AS prazo,
         (payment_value - receipt_value) AS desagio
  FROM mky_recebiveis
  WHERE status IN ('SOLD', 'PAID')
    AND criado_fornecedor >= now() - interval '12 months'
    AND payment_date IS NOT NULL AND purchased_tax IS NOT NULL
    AND receipt_value IS NOT NULL AND payment_value > 0
"""

LINHA_SQL = f"""
WITH t AS ({_BASE})
SELECT count(*)::int AS titulos,
       coalesce(sum(valor), 0)::float8 AS nominal,
       coalesce(sum(desagio), 0)::float8 AS custo,
       avg(prazo)::float8 AS prazo_medio,
       (sum(valor * prazo) / 365.0)::float8 AS capital_medio
FROM t
"""

# O melhor preço praticado DE FATO em cada mês+faixa, e o custo do volume
# inteiro por ele. `HAVING count(*) >= %(min)s` e' o piso de base.
CONTRAFACTUAL_SQL = f"""
WITH t AS ({_BASE}),
oferta AS (
  SELECT mes, faixa, investidor, avg(taxa) AS taxa, count(*)::int AS n
  FROM t GROUP BY 1, 2, 3 HAVING count(*) >= %(min)s
),
melhor AS (
  SELECT mes, faixa, min(taxa) AS melhor_taxa, count(*)::int AS ofertantes
  FROM oferta GROUP BY 1, 2
)
SELECT t.mes,
       count(*)::int AS titulos,
       coalesce(sum(t.valor), 0)::float8 AS nominal,
       coalesce(sum(t.desagio), 0)::float8 AS pago,
       coalesce(sum(t.valor * m.melhor_taxa / 100.0 * t.prazo / 30.0),
                0)::float8 AS no_melhor,
       max(m.ofertantes)::int AS ofertantes
FROM t JOIN melhor m ON m.mes = t.mes AND m.faixa = t.faixa
GROUP BY t.mes ORDER BY t.mes
"""

CORTES_SQL = f"""
WITH t AS ({_BASE})
SELECT %(dias)s::int AS dias,
       coalesce(sum(CASE WHEN prazo > %(dias)s THEN desagio END), 0)::float8
         AS custo_com_corte,
       coalesce(sum(desagio), 0)::float8 AS custo_atual,
       coalesce(sum(CASE WHEN prazo <= %(dias)s THEN valor END), 0)::float8
         AS caixa_abre_mao,
       count(*) FILTER (WHERE prazo <= %(dias)s)::int AS titulos_fora
FROM t
"""


@cached(ttl=600)
def get_estrategia() -> dict:
    return montar()


def montar(esquema: str | None = None) -> dict:
    try:
        with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
            cur.execute(LINHA_SQL)
            linha = dict(cur.fetchone() or {})
            if not linha.get("titulos"):
                return {"disponivel": False,
                        "motivo": "sem antecipação nos últimos 12 meses"}
            cur.execute(CONTRAFACTUAL_SQL, {"min": _MIN_OFERTA})
            meses = [dict(r) for r in cur.fetchall()]
            cortes = []
            for dias in _CORTES:
                cur.execute(CORTES_SQL, {"dias": dias})
                cortes.append(dict(cur.fetchone() or {}))
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"disponivel": False, "motivo": "migration 0036 pendente"}
        raise

    cap = linha.get("capital_medio") or 0.0
    custo = linha.get("custo") or 0.0
    linha["custo_efetivo_aa"] = (100.0 * custo / cap) if cap else None
    nominal = linha.get("nominal") or 0.0
    linha["desagio_pct"] = (100.0 * custo / nominal) if nominal else None
    # quantas vezes o capital girou no ano — é o que explica por que somar o
    # nominal e chamar de dívida erra por um fator de cinco
    linha["giros"] = (nominal / cap) if cap else None

    pago = sum(m["pago"] for m in meses)
    melhor = sum(m["no_melhor"] for m in meses)
    for m in meses:
        m["economia"] = m["pago"] - m["no_melhor"]

    for c in cortes:
        c["economia"] = (c["custo_atual"] or 0.0) - (c["custo_com_corte"] or 0.0)
        # o preço da economia, na mesma unidade em que ela é publicada: cada
        # real economizado custa X reais de caixa que se deixa de antecipar
        c["caixa_por_real"] = ((c["caixa_abre_mao"] / c["economia"])
                               if c["economia"] else None)

    return {
        "disponivel": True,
        "linha": linha,
        "contrafactual": {
            "pago": pago,
            "no_melhor_preco": melhor,
            "economia": pago - melhor,
            "economia_pct": (100.0 * (pago - melhor) / pago) if pago else None,
            "min_oferta": _MIN_OFERTA,
            "meses": meses,
        },
        "cortes": cortes,
        "fonte": ("Espelho local mky_recebiveis · 12 meses por data de "
                  "antecipação · contrafactual contra o melhor preço "
                  "efetivamente praticado no mesmo mês e faixa de prazo"),
    }
