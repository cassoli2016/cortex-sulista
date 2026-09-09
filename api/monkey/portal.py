# -*- coding: utf-8 -*-
"""Tela "Portal Tupy" (`tupy`) — a validação do que a Monkey entrega.

Lê o ESPELHO local (mky_recebiveis), nunca a API: a tela abre em
milissegundos e não cai junto com o fornecedor. O espelho é a varredura
completa do convênio (48,6 mil títulos desde jun/2024 na primeira carga) e
o frescor vem de mky_carga — dado velho é DITO, não disfarçado.

QUATRO DECISÕES DE LEITURA:
- Há DUAS séries mensais, e elas respondem a perguntas diferentes: `mensal`
  agrupa por VENCIMENTO ("quanto vence em cada mês", para projetar caixa) e
  `antecipado` agrupa pela DATA DE ANTECIPAÇÃO ("quanto antecipamos no mês",
  para fechar o mês). Cada uma é ancorada no último dado da SUA data, nunca
  em current_date, e os meses são GERADOS — mês sem título aparece vazio em
  vez de emendar abril em agosto.
- Deságio e percentuais saem da unidade de ORIGEM (somas primeiro, razão
  depois) — arredondar antes de dividir move o número de lado. Médias de
  taxa são PONDERADAS pelo valor: um investidor que levou dois títulos não
  pode pesar como um que levou mil.
- `purchased_tax` é taxa MENSAL — provado em 09/09/2026 contra os próprios
  dados (ver `TAXA_UNIDADE`), depois de um ano publicado sem unidade. O
  equivalente anual composto sai de `ao_ano()` e é o número comparável com
  as outras linhas de crédito da casa.
- O mês em curso é PISO, nunca denominador, e não se projeta: a cadência
  aqui é de lote irregular (ver `_resumo_mensal`).
"""
from __future__ import annotations

from datetime import date

from api import pglocal
from api.queries import cached

# O teste redireciona isto para um schema próprio (fixture `esquema_pg`).
ESQUEMA: str | None = None

# fora da posição = já saiu do portal (mesma régua do api/monkey/normaliza)
_FORA = "('SOLD', 'PAID', 'REFUSED', 'CANCELLED')"

KPIS_SQL = f"""
SELECT count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor_total,
       sum(CASE WHEN status = 'SOLD' THEN 1 ELSE 0 END)::int AS vendidos,
       coalesce(sum(CASE WHEN status = 'SOLD' THEN payment_value END), 0)::float8
         AS valor_vendido,
       coalesce(sum(CASE WHEN status = 'SOLD'
                         THEN payment_value - coalesce(receipt_value,
                                                       payment_value) END),
                0)::float8 AS desagio_vendido,
       coalesce(sum(payment_value - coalesce(receipt_value, payment_value)),
                0)::float8 AS desagio_total,
       sum(CASE WHEN buyer_cnpj IS NOT NULL THEN 1 ELSE 0 END)::int
         AS com_investidor,
       sum(CASE WHEN status = 'PAID' THEN 1 ELSE 0 END)::int AS liquidados,
       coalesce(sum(CASE WHEN status = 'PAID' THEN payment_value END), 0)::float8
         AS valor_liquidado,
       sum(CASE WHEN status NOT IN {_FORA} THEN 1 ELSE 0 END)::int AS abertos,
       coalesce(sum(CASE WHEN status NOT IN {_FORA} THEN payment_value END),
                0)::float8 AS valor_aberto,
       to_char(min(CASE WHEN invoice_date >= DATE '2000-01-01'
                        THEN invoice_date END), 'YYYY-MM-DD') AS primeira_nf,
       to_char(max(payment_date), 'YYYY-MM-DD') AS ultimo_venc
FROM mky_recebiveis
"""

MENSAL_SQL = """
WITH ancora AS (
  SELECT date_trunc('month', max(payment_date))::date AS fim
  FROM mky_recebiveis WHERE payment_date IS NOT NULL
),
meses AS (
  SELECT generate_series((SELECT fim FROM ancora) - interval '12 months',
                         (SELECT fim FROM ancora),
                         interval '1 month')::date AS mes
)
SELECT to_char(m.mes, 'YYYY-MM') AS mes,
       count(r.external_id)::int AS titulos,
       coalesce(sum(r.payment_value), 0)::float8 AS valor,
       coalesce(sum(CASE WHEN r.status = 'SOLD' THEN r.payment_value END),
                0)::float8 AS vendido,
       coalesce(sum(CASE WHEN r.status = 'SOLD'
                         THEN r.payment_value - coalesce(r.receipt_value,
                                                         r.payment_value) END),
                0)::float8 AS desagio,
       coalesce(sum(CASE WHEN r.status = 'PAID' THEN r.payment_value END),
                0)::float8 AS liquidado,
       avg(CASE WHEN r.status = 'SOLD' THEN r.purchased_tax END)::float8
         AS taxa_media
FROM meses m
LEFT JOIN mky_recebiveis r
       ON date_trunc('month', r.payment_date)::date = m.mes
GROUP BY m.mes ORDER BY m.mes
"""

# GROUP BY seller_id, nunca pelo nome: as 5 filiais da Sulista têm a MESMA
# razão social no portal (medido: agrupar por nome colapsava tudo numa linha)
SELLERS_SQL = """
SELECT seller_id,
       max(seller_cnpj) AS cnpj,
       max(seller_nome) AS seller,
       count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       sum(CASE WHEN status = 'SOLD' THEN 1 ELSE 0 END)::int AS vendidos,
       coalesce(sum(CASE WHEN status = 'SOLD' THEN payment_value END),
                0)::float8 AS valor_vendido,
       avg(CASE WHEN status = 'SOLD' THEN purchased_tax END)::float8
         AS taxa_media
FROM mky_recebiveis
GROUP BY 1 ORDER BY 5 DESC
"""

STATUS_SQL = """
SELECT status, count(*)::int AS n,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       to_char(min(payment_date), 'YYYY-MM-DD') AS venc_min,
       to_char(max(payment_date), 'YYYY-MM-DD') AS venc_max
FROM mky_recebiveis GROUP BY 1 ORDER BY 2 DESC
"""

INVESTIDORES_SQL = """
SELECT coalesce(buyer_nome, buyer_cnpj, '(sem comprador)') AS investidor,
       count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       avg(purchased_tax)::float8 AS taxa_media
FROM mky_recebiveis WHERE status IN ('SOLD', 'PAID')
GROUP BY 1 ORDER BY 3 DESC LIMIT 12
"""

# ── A DATA DA ANTECIPAÇÃO, E POR QUE ELA É `criado_fornecedor` ───────────────
#
# O espelho NÃO guarda a data em que o título foi vendido, e as duas
# candidatas óbvias não servem — medido em 09/09/2026 sobre as 48.940 linhas:
#
#   real_payment_date        NULA em 48.940 de 48.940 (a Monkey nunca preenche)
#   effective_payment_date   coincide com o vencimento (diferença média 0,0
#                            dia) — é a liquidação prevista, não a venda
#
# O proxy é o `createdAt` deles, e é bom: entre o título entrar na plataforma
# e mudar de status passam **0,4 dia**. O mês de entrada é o mês da
# antecipação em praticamente todo título.
#
# ISTO NÃO SUBSTITUI O `MENSAL_SQL`, e as duas séries convivem de propósito:
# aquela agrupa por VENCIMENTO e responde "quanto vence em cada mês" (a
# pergunta de quem projeta caixa); esta responde "quanto antecipamos no mês"
# (a pergunta de quem fecha o mês). Enquanto só existia a primeira, a segunda
# era respondida com o número da primeira.
ANTECIPADO_SQL = """
WITH ancora AS (
  SELECT date_trunc('month', max(criado_fornecedor))::date AS fim
  FROM mky_recebiveis WHERE criado_fornecedor IS NOT NULL
),
meses AS (
  SELECT generate_series((SELECT fim FROM ancora) - interval '12 months',
                         (SELECT fim FROM ancora),
                         interval '1 month')::date AS mes
)
SELECT to_char(m.mes, 'YYYY-MM') AS mes,
       count(r.external_id)::int AS titulos,
       coalesce(sum(r.payment_value), 0)::float8 AS nominal,
       coalesce(sum(r.payment_value - coalesce(r.receipt_value,
                                               r.payment_value)),
                0)::float8 AS desagio,
       avg(r.purchased_tax)::float8 AS taxa_am,
       avg(r.payment_date - r.criado_fornecedor::date)::float8 AS prazo_dias
FROM meses m
LEFT JOIN mky_recebiveis r
       ON date_trunc('month', r.criado_fornecedor)::date = m.mes
      AND r.status IN ('SOLD', 'PAID')
GROUP BY m.mes ORDER BY m.mes
"""

# ── CONCENTRAÇÃO DO COMPRADOR ────────────────────────────────────────────────
#
# NÃO É ALARME DE DEFEITO, e o rótulo tem de dizer isso — senão o cartão
# ensina a coisa errada. Em 12/08/2026 o Sofisa entrou no leilão a 1,14-1,18%
# a.m., contra 1,24% dos outros três, e passou a levar 99,7% do valor: a
# concentração SUBIU porque o preço MELHOROU.
#
# O que o cartão mede é DEPENDÊNCIA. Se esse comprador recuar, o preço não
# cai no vazio: volta para a faixa em que Banco do Brasil e Votorantim
# operam, e isso vale R$ 49,8 mil por ano no volume atual.
#
# A JANELA É DE 30 DIAS, e escolher isto custou uma tentativa errada.
#
# Comecei com 90 dias, por parecerem mais estáveis. Medido: a janela de 90
# dias devolve 43,1% para o líder e pinta o cartão de VERDE, porque ela ainda
# carrega junho e julho, quando o leilão se dividia entre três bancos. Nos 30
# dias que importam o mesmo líder está com quase tudo.
#
# É o erro que o parágrafo acima acusa na média de doze meses, cometido de
# novo com um número menor: janela larga demais para uma pergunta que é sobre
# AGORA. Concentração não é uma característica do convênio, é o estado do
# leilão nesta semana.
#
# E COM PISO DE BASE, pela mesma razão da régua de preço de peça: a cadência
# é de lote irregular, e uma janela com um lote só daria 100% de concentração
# trivialmente — um número verdadeiro que não significa nada. Abaixo de
# `_LOTES_MINIMOS` o cartão diz que não tem base, em vez de acusar.
_LOTES_MINIMOS = 3

CONCENTRACAO_SQL = """
SELECT coalesce(buyer_nome, buyer_cnpj, '(sem comprador)') AS investidor,
       count(*)::int AS titulos,
       count(DISTINCT criado_fornecedor::date)::int AS lotes,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       avg(purchased_tax)::float8 AS taxa_am,
       avg(payment_date - criado_fornecedor::date)::float8 AS prazo_dias
FROM mky_recebiveis
WHERE status IN ('SOLD', 'PAID')
  AND criado_fornecedor >= now() - interval '30 days'
GROUP BY 1 ORDER BY 4 DESC
"""

# quantos DIAS DE LEILÃO distintos a janela tem — a base da régua acima, e o
# número que o cartão mostra para quem quiser julgar por conta própria
LOTES_JANELA_SQL = """
SELECT count(DISTINCT criado_fornecedor::date)::int AS lotes
FROM mky_recebiveis
WHERE status IN ('SOLD', 'PAID')
  AND criado_fornecedor >= now() - interval '30 days'
"""

# ── O LOTE EM ABERTO, COM IDADE ──────────────────────────────────────────────
#
# A tela já dizia QUANTOS títulos estão em aberto; não dizia HÁ QUANTO TEMPO,
# e é a idade que carrega o sinal. Com a venda acontecendo em 0,4 dia, um
# lote parado há dois dias é anomalia — e hoje ninguém a veria, porque
# "em aberto: 288" tem exatamente a mesma cara no dia normal e no dia ruim.
#
# Zero em aberto NÃO é alarme: é o estado mais comum, e significa que a mesa
# vendeu tudo. O alarme é idade, nunca contagem.
LOTE_ABERTO_SQL = f"""
SELECT count(*)::int AS titulos,
       coalesce(sum(payment_value), 0)::float8 AS valor,
       to_char(min(criado_fornecedor), 'YYYY-MM-DD HH24:MI') AS mais_antigo,
       (extract(epoch FROM now() - min(criado_fornecedor)) / 3600.0)::float8
         AS horas,
       to_char(min(payment_date), 'YYYY-MM-DD') AS venc_min,
       to_char(max(payment_date), 'YYYY-MM-DD') AS venc_max
FROM mky_recebiveis WHERE status NOT IN {_FORA}
"""

# ── DESÁGIO POR FAIXA DE PRAZO ───────────────────────────────────────────────
#
# O resultado é contraintuitivo e estável: quanto MAIS LONGO o título, MAIS
# BARATA a taxa mensal (1,2875% até 29 dias contra 1,2385% acima de 84 —
# monotônico nas cinco faixas, medido em 12 meses). É coerente com a taxa ser
# mensal: há custo fixo por operação, e prazo curto tem menos meses para
# diluí-lo. A amplitude de 4% não decide sozinha, mas é previsível.
FAIXA_PRAZO_SQL = """
SELECT CASE WHEN d < 30 THEN 'até 29 dias'
            WHEN d < 46 THEN '30 a 45 dias'
            WHEN d < 66 THEN '46 a 65 dias'
            WHEN d < 84 THEN '66 a 83 dias'
            ELSE '84 dias ou mais' END AS faixa,
       min(d)::int AS de,
       max(d)::int AS ate,
       count(*)::int AS titulos,
       avg(tx)::float8 AS taxa_am,
       coalesce(sum(nominal), 0)::float8 AS nominal
FROM (
  SELECT (payment_date - criado_fornecedor::date) AS d,
         purchased_tax AS tx,
         payment_value AS nominal
  FROM mky_recebiveis
  WHERE status IN ('SOLD', 'PAID')
    AND criado_fornecedor IS NOT NULL AND payment_date IS NOT NULL
    AND criado_fornecedor >= now() - interval '12 months'
) x
WHERE d >= 0
GROUP BY 1 ORDER BY min(d)
"""

# a VALIDAÇÃO propriamente: as perguntas que dizem se o dado merece confiança
QUALIDADE_SQL = f"""
SELECT count(*)::int AS total,
       sum(CASE WHEN coalesce(invoice_key, '') = '' THEN 1 ELSE 0 END)::int
         AS sem_chave_nfe,
       sum(CASE WHEN receipt_value > payment_value THEN 1 ELSE 0 END)::int
         AS recebe_mais_que_nominal,
       sum(CASE WHEN payment_date < invoice_date THEN 1 ELSE 0 END)::int
         AS vence_antes_de_emitir,
       sum(CASE WHEN coalesce(total_installment, 1) > 1 THEN 1 ELSE 0 END)::int
         AS parcelados,
       sum(CASE WHEN invoice_date < DATE '2000-01-01' THEN 1 ELSE 0 END)::int
         AS emissao_zerada,
       sum(CASE WHEN real_payment_date IS NOT NULL THEN 1 ELSE 0 END)::int
         AS com_data_real,
       sum(CASE WHEN effective_payment_date IS NOT NULL THEN 1 ELSE 0 END)::int
         AS com_data_efetiva,
       avg(CASE WHEN status = 'PAID' AND effective_payment_date IS NOT NULL
                THEN (effective_payment_date - payment_date) END)::float8
         AS atraso_medio_liq_dias,
       count(DISTINCT asset_type)::int AS tipos_de_ativo,
       count(DISTINCT sponsor_cnpj)::int AS sacados_distintos,
       to_char(max(alterado_fornecedor), 'YYYY-MM-DD HH24:MI') AS ultima_alteracao
FROM mky_recebiveis
"""

CARGA_SQL = """
SELECT to_char(terminado_em, 'YYYY-MM-DD HH24:MI') AS quando,
       recebidos, gravados, sem_chave, erro
FROM mky_carga ORDER BY id DESC LIMIT 1
"""

TITULOS_SQL = """
SELECT external_id, invoice_number, installment, total_installment,
       status, asset_type,
       to_char(invoice_date, 'YYYY-MM-DD') AS emissao,
       to_char(payment_date, 'YYYY-MM-DD') AS vencimento,
       to_char(effective_payment_date, 'YYYY-MM-DD') AS pago_em,
       payment_value, receipt_value, purchased_tax, fee_amount,
       coalesce(seller_nome, seller_cnpj) AS seller,
       coalesce(buyer_nome, '') AS investidor
FROM mky_recebiveis
WHERE (%(q)s = '' OR invoice_number ILIKE %(q_like)s
       OR external_id ILIKE %(q_like)s)
ORDER BY payment_date DESC NULLS LAST, external_id DESC
LIMIT 80
"""


def ao_ano(taxa_am: float | None) -> float | None:
    """Taxa mensal -> equivalente anual COMPOSTO, em pontos percentuais.

    POR QUE ESTE NÚMERO EXISTE: a taxa que o portal publica é mensal (prova
    abaixo), e ninguém decide entre linhas de crédito comparando 1,25% a.m.
    com 16% a.a. de cabeça. O equivalente anual é o único número que responde
    "antecipar é caro?" ao lado do custo de capital da casa.

    Composto, não multiplicado por 12: a operação se repete mês a mês, e
    1,2488 x 12 = 14,99% subestimaria o custo real em mais de um ponto.
    """
    if taxa_am is None:
        return None
    return ((1.0 + float(taxa_am) / 100.0) ** 12 - 1.0) * 100.0


# A TAXA É MENSAL, e isto deixou de ser suposição em 09/09/2026.
#
# O módulo dizia — e a tela repetia no ⓘ — que "a Monkey ainda não confirmou
# se é a.m. ou a.a.", então o número saía cru, sem unidade. Os próprios dados
# respondem: sobre 13.113 títulos dos últimos 12 meses,
#
#     deságio% = purchased_tax x prazo/30
#
# reproduz o deságio REAL com correlação 0,9997 e erro médio de 0,005 ponto
# percentual. Na hipótese anual o mesmo cálculo daria 0,25% contra os 3,05%
# observados — não é margem de dúvida, é doze vezes.
#
# Rótulo cru era a decisão certa enquanto não havia prova; mantê-lo depois da
# prova seria esconder o que se sabe.
TAXA_UNIDADE = "% a.m."


def _concentracao(linhas: list[dict], lotes: int) -> dict:
    """Resumo da dependência de comprador nos últimos 30 dias.

    O ESTADO NÃO É "quanto maior pior". Concentração alta aqui conviveu com o
    melhor preço da série inteira, então o cartão informa DEPENDÊNCIA e nomeia
    quem: 'ok' abaixo de 50%, 'atencao' de 50 a 80, 'alerta' acima — e nunca
    vermelho, porque não há defeito a consertar, há um risco a conhecer.

    `taxa_outros` é o que se paga SEM o líder — é ele que dá tamanho ao risco:
    a diferença entre as duas taxas, aplicada ao volume, é quanto custaria o
    líder sair.

    SEM BASE NÃO HÁ VEREDITO: com menos de `_LOTES_MINIMOS` dias de leilão na
    janela o percentual continua sendo publicado (é verdadeiro), mas o estado
    é 'info' e o motivo diz por quê. Um lote sozinho dá 100% de concentração
    sem que nada tenha acontecido.
    """
    total = sum(float(x.get("valor") or 0.0) for x in linhas)
    if not linhas or total <= 0:
        return {"investidores": 0, "valor": 0.0, "lider": None,
                "lider_pct": None, "estado": "info", "lotes": lotes,
                "motivo": "nenhuma venda nos últimos 30 dias"}
    lider = linhas[0]
    pct = 100.0 * float(lider.get("valor") or 0.0) / total
    outros = linhas[1:]
    vo = sum(float(x.get("valor") or 0.0) for x in outros)
    # média PONDERADA pelo valor, nunca a média das médias: um investidor que
    # levou dois títulos pesaria igual a um que levou mil.
    taxa_outros = (sum(float(x["taxa_am"]) * float(x["valor"])
                       for x in outros if x.get("taxa_am") is not None)
                   / vo) if vo else None
    sem_base = lotes < _LOTES_MINIMOS
    return {
        "investidores": len(linhas),
        "valor": total,
        "lotes": lotes,
        "lider": lider.get("investidor"),
        "lider_pct": pct,
        "lider_taxa": lider.get("taxa_am"),
        "taxa_outros": taxa_outros,
        "estado": ("info" if sem_base
                   else "alerta" if pct >= 80
                   else "atencao" if pct >= 50 else "ok"),
        "motivo": (f"só {lotes} dia(s) de leilão na janela — sem base para "
                   f"julgar concentração" if sem_base else None),
    }


def _resumo_mensal(antecipado: list[dict], mes_atual: str) -> dict:
    """Quanto se antecipou NO MÊS CORRENTE, e contra o que comparar.

    Três regras da casa governam este cartão, e cada uma já custou caro em
    outra tela:

    1. O MÊS EM CURSO É PISO, NUNCA DENOMINADOR. Ele só sobe até virar o mês,
       então entra rotulado `parcial` e a tela é obrigada a dizer isso. Um
       "antecipado no mês" que se lê como número fechado no dia 9 faz alguém
       concluir que o volume despencou.

    2. A MÉDIA DE REFERÊNCIA SAI SÓ DE MESES FECHADOS. Incluir o mês em curso
       na média que ele próprio é comparado puxa a régua para baixo na
       proporção exata do quanto falta para o mês acabar.

    3. NÃO HÁ PROJEÇÃO, e a ausência é deliberada. A cadência aqui é de LOTE
       IRREGULAR — medido: 13 dias sem nenhuma entrada entre 29/07 e 11/08, e
       julho e agosto com ZERO nos dias 1 a 9. Projetar o mês pela fração de
       dias corridos multiplicaria um lote que caiu hoje por três, ou daria
       zero para um mês que fechará normal. Piso medido é honesto; projeção
       sobre cadência irregular é chute com cara de número.

    Mês sem nenhuma antecipação devolve zero DE VERDADE (não `None`): aqui o
    zero é uma medição — nenhum título entrou —, não ausência de dado.
    """
    fechados = [m for m in antecipado
                if m["mes"] < mes_atual and (m.get("titulos") or 0) > 0]
    corrente = next((m for m in antecipado if m["mes"] == mes_atual), None)
    media = (sum(float(m["nominal"]) for m in fechados) / len(fechados)
             if fechados else None)
    nominal = float(corrente["nominal"]) if corrente else 0.0
    return {
        "mes": mes_atual,
        "parcial": True,
        "titulos": int(corrente["titulos"]) if corrente else 0,
        "nominal": nominal,
        "desagio": float(corrente["desagio"]) if corrente else 0.0,
        "taxa_am": (corrente or {}).get("taxa_am"),
        "media_fechada": media,
        "meses_na_media": len(fechados),
        "pct_da_media": (100.0 * nominal / media) if media else None,
    }


def _posicao_painel() -> dict:
    """O que o painel de Antecipações tem gravado para a Tupy — a
    conferência de dois caminhos para o mesmo número."""
    try:
        from api.antecipacoes import registro
        ultimo = registro.ultimo_envio("tupy") or {}
        return {"titulos": int(ultimo.get("titulos") or 0),
                "valor_saldo": float(ultimo.get("valor_saldo") or 0.0),
                "quando": ultimo.get("ts") or None,
                "origem": ultimo.get("origem") or None}
    except Exception:  # noqa: BLE001 — painel indisponível não derruba a tela
        return {}


@cached(ttl=120)
def get_portal_tupy(q: str = "") -> dict:
    return montar(q)


def montar(q: str = "", esquema: str | None = None) -> dict:
    q = (q or "").strip()[:60]
    params = {"q": q, "q_like": f"%{q}%"}
    try:
        with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
            cur.execute(KPIS_SQL)
            kpis = dict(cur.fetchone() or {})
            if not kpis.get("titulos"):
                return {"disponivel": False,
                        "motivo": "espelho vazio — a coleta ainda não rodou "
                                  "(scripts/coletar_monkey.py)"}
            cur.execute(MENSAL_SQL)
            mensal = [dict(r) for r in cur.fetchall()]
            cur.execute(SELLERS_SQL)
            sellers = [dict(r) for r in cur.fetchall()]
            cur.execute(STATUS_SQL)
            por_status = [dict(r) for r in cur.fetchall()]
            cur.execute(INVESTIDORES_SQL)
            investidores = [dict(r) for r in cur.fetchall()]
            cur.execute(ANTECIPADO_SQL)
            antecipado = [dict(r) for r in cur.fetchall()]
            cur.execute(CONCENTRACAO_SQL)
            conc_linhas = [dict(r) for r in cur.fetchall()]
            cur.execute(LOTES_JANELA_SQL)
            lotes_janela = int((cur.fetchone() or {}).get("lotes") or 0)
            cur.execute(LOTE_ABERTO_SQL)
            lote = dict(cur.fetchone() or {})
            cur.execute(FAIXA_PRAZO_SQL)
            faixas = [dict(r) for r in cur.fetchall()]
            cur.execute(QUALIDADE_SQL)
            qualidade = dict(cur.fetchone() or {})
            cur.execute(CARGA_SQL)
            carga_row = cur.fetchone()
            carga = dict(carga_row) if carga_row else {}
            cur.execute(TITULOS_SQL, params)
            titulos = [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"disponivel": False, "motivo": "migration 0036 pendente"}
        raise

    # deságio percentual calculado das SOMAS (unidade de origem). MEDIDO em
    # 01/09/2026: 100% dos títulos (SOLD e PAID) têm deságio, taxa e
    # investidor — TODO título deste convênio passa pelo leilão; PAID é
    # "antecipado e já liquidado", nunca "liquidado sem antecipar". Por isso
    # o "antecipado histórico" é o TOTAL, e o corte por status diz só em que
    # fase do ciclo cada um está.
    vt = kpis.get("valor_total") or 0.0
    kpis["desagio_pct"] = (100.0 * (kpis.get("desagio_total") or 0.0) / vt
                           if vt else None)

    # custo dos ÚLTIMOS 12 MESES, não do histórico: a taxa caiu 13% no
    # período, e a média desde 2024 responderia uma pergunta que ninguém faz.
    doze = [m for m in antecipado if (m.get("titulos") or 0) > 0]
    peso = sum(float(m["nominal"]) for m in doze)
    kpis["taxa_am_12m"] = (sum(float(m["taxa_am"]) * float(m["nominal"])
                               for m in doze if m.get("taxa_am") is not None)
                           / peso) if peso else None
    kpis["custo_aa_12m"] = ao_ano(kpis["taxa_am_12m"])
    kpis["nominal_12m"] = peso
    kpis["desagio_12m"] = sum(float(m["desagio"]) for m in doze)
    kpis["prazo_12m"] = (sum(float(m["prazo_dias"]) * float(m["nominal"])
                             for m in doze if m.get("prazo_dias") is not None)
                         / peso) if peso else None

    concentracao = _concentracao(conc_linhas, lotes_janela)
    concentracao["linhas"] = conc_linhas
    # o custo de o líder sair, em reais por ano: a diferença entre a taxa dele
    # e a dos demais, aplicada ao volume anual. Sem isto a concentração é um
    # percentual sem consequência, e percentual sem consequência não decide.
    if (concentracao.get("taxa_outros") is not None
            and concentracao.get("lider_taxa") is not None
            and kpis.get("prazo_12m") and peso):
        delta = concentracao["taxa_outros"] - concentracao["lider_taxa"]
        concentracao["risco_anual"] = (peso * delta / 100.0
                                       * kpis["prazo_12m"] / 30.0)

    # o lote em aberto: a idade é o sinal, a contagem não
    lote["estado"] = ("info" if not (lote.get("titulos") or 0)
                      else "alerta" if (lote.get("horas") or 0) >= 48
                      else "atencao" if (lote.get("horas") or 0) >= 24
                      else "ok")

    return {
        "disponivel": True,
        "kpis": kpis,
        "mensal": mensal,
        "antecipado": antecipado,
        "mes_corrente": _resumo_mensal(antecipado, date.today().strftime("%Y-%m")),
        "concentracao": concentracao,
        "lote_aberto": lote,
        "faixas_prazo": faixas,
        "taxa_unidade": TAXA_UNIDADE,
        "sellers": sellers,
        "por_status": por_status,
        "investidores": investidores,
        "qualidade": qualidade,
        "carga": carga,
        "titulos": titulos,
        "busca": q,
        "conferencia": {
            "espelho_abertos": kpis.get("abertos") or 0,
            "espelho_valor_aberto": kpis.get("valor_aberto") or 0.0,
            "painel": _posicao_painel(),
        },
        "fonte": ("Monkey Exchange · espelho local mky_recebiveis (varredura "
                  "completa por seller, 2×/dia) + ant_envios (posição do "
                  "painel) · leitura"),
    }
