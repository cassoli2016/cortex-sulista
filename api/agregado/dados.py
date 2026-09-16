# -*- coding: utf-8 -*-
"""O que o app do agregado LÊ do ERP — e o que ele se recusa a ler.

TODA FUNÇÃO AQUI RECEBE A SESSÃO, NUNCA O DONO. O escopo sai de
`sess["proprietario_codigo"]`, que veio do cookie assinado; nenhuma assinatura
deste módulo aceita "de quem" como parâmetro, porque função que aceita o dono
como argumento é função que um dia é chamada com o dono errado — e o defeito é
mudo: a tela responde, bonita, com o dinheiro de outra pessoa.

AS DUAS CHAVES DO ERP, e por que são duas (medidas em 16/09/2026):

* **O dono** é `cadastro.codigo`, e é para ele que apontam tanto
  `veiculo.proprietario` quanto `programacaoembarque.cnpjcpfcodigoveiculo` e
  `acertoviagemagregado.cnpjcpfcodigoveiculo`. O campo `cnpjcpfcodigo` do
  acerto NÃO serve: é nulo em 100% das linhas, e o `api/queries.py` já traz
  esse aviso escrito depois de ele ter zerado uma coluna inteira da tela de
  agregados.
* **A placa** é a chave do que não passa pelo acerto: abastecimento (CtaPlus),
  lançamento manual e ocorrência da carga. Por isso as placas saem SEMPRE de
  `veiculos()` — a lista do dono — e entram como filtro nas outras leituras.

O QUE NÃO ENTRA EM SELECT NENHUM DESTE ARQUIVO: `valorfrete` (o que o cliente
pagou à Sulista), qualquer margem, e qualquer linha de outro agregado. Não é
filtro que alguém esquece de aplicar; a coluna não está escrita.

A REDE DE LEITURA VELHA (`velha_ate`) ENTRA AQUI, e é o caso clássico dela: o
app publica dinheiro fechado — acerto, abastecimento do mês, viagem da semana.
A leitura de duas horas atrás não muda nenhuma decisão de quem lê, e o ERP é
réplica de terceiro com dia ruim. A tarja é a da casa (cabeçalho
`X-Leitura-Velha`, desenhada pelo gancho do fetch).
"""
from __future__ import annotations

import logging

from .. import db
from ..queries import VELHA_ATE, cached

log = logging.getLogger("cortex.agregado.dados")

#: A modalidade que este app atende. `AGR` é agregado; `TER` (terceiro) é outro
#: universo — viagem avulsa, quase sem acerto de viagem e sem abastecimento
#: pela CtaPlus —, e entra quando alguém medir o que existe para ele.
UTILIZACAO = "AGR"

#: Quantos dias a tela abre por padrão. Três meses cobre o ciclo de acerto
#: (quinzenal/mensal) com folga e não faz o celular baixar um ano de viagem.
JANELA_DIAS = 90

#: Teto de linhas por lista. Existe um número no mundo que a lista não pode
#: passar? Não: um dono com 15 veículos faz centenas de viagens por mês. Então
#: o corte é DECISÃO, o servidor corta e a tela DIZ "N de M".
MAX_LINHAS = 300

#: As ocorrências que interessam ao dono. O ciclo do SAC (394–401: chegada,
#: saída, em viagem, finalizada) é acompanhamento e some aqui de propósito:
#: são 110 mil linhas em 12 meses nas placas de agregado, e uma lista com tudo
#: isso esconde justamente o que ele precisa ver. Ficam os MOTIVOS DE ATRASO
#: (425–440 na coleta, 441–456 na entrega) e a ocorrência interna (271), que é
#: onde a casa registra o que deu errado na carga.
OCORRENCIAS_MOTIVO = "(o.ocorrencia BETWEEN 425 AND 456 OR o.ocorrencia = 271)"


# ════════════════════════════════════════════════════════════ os veículos
VEICULOS_SQL = f"""
SELECT btrim(v.placa) AS placa,
       btrim(coalesce(v.numerofrota, '')) AS frota,
       btrim(coalesce(mv.descricao, '')) AS marca,
       btrim(coalesce(v.modeloveiculo, '')) AS modelo,
       v.anofabricacao AS ano,
       btrim(coalesce(tv.descricao, '')) AS tipo,
       (v.ativoinativo = 1) AS ativo
FROM veiculo v
LEFT JOIN marcaveiculo mv ON mv.codigo = v.marcaveiculo
LEFT JOIN tipoveiculo tv ON tv.codigo = v.tipoveiculo
WHERE btrim(coalesce(v.proprietario, '')) = %(cod)s
  AND v.utilizacaoveiculo = '{UTILIZACAO}'
ORDER BY (v.ativoinativo = 1) DESC, btrim(v.placa)
"""


@cached(ttl=300, velha_ate=VELHA_ATE)
def _veiculos(cod: str) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(VEICULOS_SQL, {"cod": cod})
        return [dict(r) for r in cur.fetchall()]


def veiculos(sess: dict) -> dict:
    linhas = _veiculos(str(sess["proprietario_codigo"]))
    return {"veiculos": linhas,
            "ativos": sum(1 for v in linhas if v["ativo"]),
            "total": len(linhas)}


def _placas(cod: str) -> list[str]:
    """As placas do dono. É o filtro de tudo que não passa pelo acerto — e sai
    daqui, e não do navegador, porque placa que vem de fora é escopo que vem
    de fora."""
    return [v["placa"] for v in _veiculos(cod) if v["placa"]]


# ════════════════════════════════════════════════════════════════ acertos
#
# O ACERTO É O EXTRATO DO AGREGADO. `concluido = 1` é o fechado; o resto está
# em aberto (medido: 2.884 fechados e 10 abertos em 12 meses). Pago é outra
# pergunta, e a resposta está na CONTA A PAGAR que a parcela do acerto aponta:
# um acerto fechado pode ter parcela em aberto (329 delas em 12 meses).
ACERTOS_SQL = """
WITH ac AS (
  SELECT a.filial, a.unidade, a.diferenciadornumero, a.numero, a.dtemissao,
         coalesce(a.valortotalfaturamento, 0) AS bruto,
         coalesce(a.valortotaldescontos, 0)   AS descontos,
         coalesce(a.valortotaladiantamento, 0) AS adiantamentos,
         coalesce(a.valortotaldespesas, 0)    AS despesas,
         coalesce(a.valortotalacrescimos, 0)  AS acrescimos,
         coalesce(a.valorpagarparaagregado, 0) AS liquido,
         (a.concluido = 1) AS fechado
  FROM acertoviagemagregado a
  WHERE a.semaforo = 1
    AND btrim(coalesce(a.cnpjcpfcodigoveiculo, '')) = %(cod)s
    AND a.dtemissao >= %(de)s::date
),
par AS (
  SELECT p.filial, p.unidade, p.diferenciadornumero, p.numero,
         count(*) AS parcelas,
         sum(CASE WHEN cp.dtpagamento IS NOT NULL THEN 1 ELSE 0 END) AS pagas,
         max(cp.dtpagamento) AS pago_em,
         min(p.dtvencimento) AS vence_em
  FROM acertoviagemagregado_contaapagar_parcela p
  JOIN ac ON ac.filial = p.filial AND ac.unidade = p.unidade
         AND ac.diferenciadornumero = p.diferenciadornumero AND ac.numero = p.numero
  LEFT JOIN contaapagar cp
    ON cp.filial = p.filialcontaapagar AND cp.unidade = p.unidadecontaapagar
   AND cp.sequencia = p.sequenciacontaapagar
  GROUP BY 1, 2, 3, 4
)
SELECT ac.filial, ac.numero, ac.diferenciadornumero, ac.unidade,
       to_char(ac.dtemissao, 'YYYY-MM-DD') AS emissao,
       ac.bruto::float8 AS bruto, ac.descontos::float8 AS descontos,
       ac.adiantamentos::float8 AS adiantamentos,
       ac.despesas::float8 AS despesas, ac.acrescimos::float8 AS acrescimos,
       ac.liquido::float8 AS liquido, ac.fechado,
       coalesce(par.parcelas, 0)::int AS parcelas,
       coalesce(par.pagas, 0)::int AS parcelas_pagas,
       to_char(par.pago_em, 'YYYY-MM-DD') AS pago_em,
       to_char(par.vence_em, 'YYYY-MM-DD') AS vence_em
FROM ac LEFT JOIN par ON par.filial = ac.filial AND par.unidade = ac.unidade
                     AND par.diferenciadornumero = ac.diferenciadornumero
                     AND par.numero = ac.numero
ORDER BY ac.dtemissao DESC, ac.numero DESC
"""


@cached(ttl=180, velha_ate=VELHA_ATE)
def _acertos(cod: str, dias: int) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(ACERTOS_SQL, {"cod": cod, "de": _de(dias)})
        return [dict(r) for r in cur.fetchall()]


def acertos(sess: dict, dias: int = JANELA_DIAS) -> dict:
    """Os acertos do dono, com o que cada um tem de bruto, desconto e líquido.

    TRÊS ESTADOS, e eles não são o mesmo: ABERTO (o acerto ainda está sendo
    montado pela casa), FECHADO A PAGAR (fechado, parcela sem pagamento) e
    PAGO. Juntar os dois últimos num "fechado" faria o app dizer que o dinheiro
    saiu quando ele só foi calculado.
    """
    linhas = _acertos(str(sess["proprietario_codigo"]), int(dias))
    abertos = [a for a in linhas if not a["fechado"]]
    a_pagar = [a for a in linhas
               if a["fechado"] and a["parcelas_pagas"] < a["parcelas"]]
    pagos = [a for a in linhas
             if a["fechado"] and a["parcelas"] and a["parcelas_pagas"] >= a["parcelas"]]
    return {
        "acertos": linhas[:MAX_LINHAS],
        "mostrados": min(len(linhas), MAX_LINHAS), "total": len(linhas),
        "dias": int(dias),
        "resumo": {
            "abertos": len(abertos),
            "valor_abertos": round(sum(a["liquido"] or 0 for a in abertos), 2),
            "a_pagar": len(a_pagar),
            "valor_a_pagar": round(sum(a["liquido"] or 0 for a in a_pagar), 2),
            "pagos": len(pagos),
            "valor_pago": round(sum(a["liquido"] or 0 for a in pagos), 2),
        },
    }


# ─────────────────────────────────────────────── o detalhe de UM acerto
#
# O ESCOPO ENTRA NO `WHERE` JUNTO DO NÚMERO, nunca numa conferência depois da
# busca: `WHERE numero = ... AND cnpjcpfcodigo... = dono` não tem caminho em
# que o acerto de outro dono seja lido e descartado — e é a diferença entre
# "não mostra" e "não lê", que é a única que vale.
_ACERTO_ONDE = """
  FROM acertoviagemagregado a
  JOIN {tab} x ON x.grupo = a.grupo AND x.empresa = a.empresa
              AND x.filial = a.filial AND x.unidade = a.unidade
              AND x.diferenciadornumero = a.diferenciadornumero
              AND x.numero = a.numero
 WHERE a.semaforo = 1 AND a.filial = %(filial)s AND a.numero = %(numero)s
   AND btrim(coalesce(a.cnpjcpfcodigoveiculo, '')) = %(cod)s
"""

ACERTO_RECEITA_SQL = """
SELECT btrim(coalesce(x.veiculo, '')) AS placa,
       x.numerotransporte::int AS viagem,
       to_char(x.dtemissaodocumentoorigem, 'YYYY-MM-DD') AS emissao,
       x.numerosequenciadocumentoorigem::text AS documento,
       x.valor::float8 AS valor,
       coalesce(x.valordescontos, 0)::float8 AS descontos
""" + _ACERTO_ONDE.format(tab="acertoviagemagregado_receita") + """
 ORDER BY x.dtemissaodocumentoorigem, x.sequencia
"""

# A DESPESA DIZ DE QUE TIPO ELA É, e o tipo vem do cadastro do ERP
# (`tipodocumento`), nunca de uma tradução escrita aqui: medido em 16/09/2026,
# as despesas do acerto são nota fiscal simplificada (30) e abastecimento
# interno (31). Código sem tabela de domínio não vira rótulo inventado — e o
# join é LEFT porque tipo novo no ERP não pode sumir com a linha do extrato.
ACERTO_DESPESA_SQL = """
SELECT btrim(coalesce(td.descricao, '')) AS tipo,
       btrim(coalesce(x.veiculodocumentoorigem, '')) AS placa,
       to_char(x.dtemissaodocumentoorigem, 'YYYY-MM-DD') AS emissao,
       x.numerosequenciadocumentoorigem::text AS documento,
       x.valor::float8 AS valor
""" + _ACERTO_ONDE.format(tab="acertoviagemagregado_despesa").replace(
    " WHERE a.semaforo = 1",
    " LEFT JOIN tipodocumento td ON td.codigo = x.tipodocumentoorigem"
    " WHERE a.semaforo = 1") + """
 ORDER BY x.dtemissaodocumentoorigem, x.sequencia
"""

ACERTO_ADIANT_SQL = """
SELECT to_char(x.dtemissaodocumentoorigem, 'YYYY-MM-DD') AS emissao,
       x.numerosequenciadocumentoorigem::text AS documento,
       x.valor::float8 AS valor
""" + _ACERTO_ONDE.format(tab="acertoviagemagregado_adiantamento") + """
 ORDER BY x.dtemissaodocumentoorigem, x.sequencia
"""

ACERTO_DESCONTO_SQL = """
SELECT to_char(x.dtemissaodocumentoorigem, 'YYYY-MM-DD') AS emissao,
       x.numerosequenciadocumentoorigem::text AS documento,
       x.valor::float8 AS valor
""" + _ACERTO_ONDE.format(tab="acertoviagemagregado_desconto") + """
 ORDER BY x.dtemissaodocumentoorigem, x.sequencia
"""


def acerto_detalhe(sess: dict, filial: int, numero: int) -> dict:
    """Do que este acerto é feito: as viagens que entraram, as despesas, os
    adiantamentos e os descontos. Sem o acerto do dono, devolve vazio — e a
    rota traduz isso em recusa legível, nunca em 500."""
    cod = str(sess["proprietario_codigo"])
    par = {"cod": cod, "filial": int(filial), "numero": int(numero)}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT to_char(a.dtemissao, 'YYYY-MM-DD') AS emissao,
                      coalesce(a.valortotalfaturamento, 0)::float8 AS bruto,
                      coalesce(a.valorpagarparaagregado, 0)::float8 AS liquido,
                      (a.concluido = 1) AS fechado
                 FROM acertoviagemagregado a
                WHERE a.semaforo = 1 AND a.filial = %(filial)s AND a.numero = %(numero)s
                  AND btrim(coalesce(a.cnpjcpfcodigoveiculo, '')) = %(cod)s""",
            par)
        cabeca = cur.fetchone()
        if not cabeca:
            return {}
        saida = {"acerto": dict(cabeca), "filial": int(filial), "numero": int(numero)}
        for chave, sql in (("viagens", ACERTO_RECEITA_SQL),
                           ("despesas", ACERTO_DESPESA_SQL),
                           ("adiantamentos", ACERTO_ADIANT_SQL),
                           ("descontos", ACERTO_DESCONTO_SQL)):
            cur.execute(sql, par)
            saida[chave] = [dict(r) for r in cur.fetchall()]
    return saida


# ════════════════════════════════════════════════════════════════ viagens
#
# A VIAGEM É A DO `programacaoembarque`, a mesma fonte canônica da tela de
# agregados da casa (`api/queries.py::_agr_base`) — e o valor que sai é o
# `valorfretecompra`, que é o que a Sulista PAGA. O `valorfrete` (o que o
# cliente pagou) não está escrito em lugar nenhum deste arquivo.
VIAGENS_SQL = """
SELECT p.numero::int AS viagem, p.filial::int AS filial,
       to_char(p.dtemissao, 'YYYY-MM-DD') AS emissao,
       btrim(coalesce(p.veiculo, '')) AS placa,
       coalesce(nullif(btrim(p.cidadeorigem), ''), '?')
         || '/' || coalesce(p.uforigem, '?') AS origem,
       coalesce(nullif(btrim(p.cidadedestino), ''), '?')
         || '/' || coalesce(p.ufdestino, '?') AS destino,
       coalesce(p.kmfretecompra, 0)::float8 AS km,
       coalesce(p.valorfretecompra, 0)::float8 AS valor,
       (p.tipo = 3) AS vazio
FROM programacaoembarque p
WHERE p.dtcancelamento IS NULL AND p.semaforo = 1 AND p.numero < 1000000
  AND btrim(coalesce(p.cnpjcpfcodigoveiculo, '')) = %(cod)s
  AND p.dtemissao >= %(de)s::date
ORDER BY p.dtemissao DESC, p.numero DESC
"""


@cached(ttl=180, velha_ate=VELHA_ATE)
def _viagens(cod: str, dias: int) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(VIAGENS_SQL, {"cod": cod, "de": _de(dias)})
        return [dict(r) for r in cur.fetchall()]


def viagens(sess: dict, dias: int = JANELA_DIAS) -> dict:
    linhas = _viagens(str(sess["proprietario_codigo"]), int(dias))
    return {"viagens": linhas[:MAX_LINHAS],
            "mostrados": min(len(linhas), MAX_LINHAS), "total": len(linhas),
            "dias": int(dias),
            "km": round(sum(v["km"] or 0 for v in linhas), 1),
            "valor": round(sum(v["valor"] or 0 for v in linhas), 2)}


# ═══════════════════════════════════════════════════════════ abastecimentos
#
# A FONTE É A CTAPLUS (`sulista.ctaplus_abastecimentos`), a mesma da tela de
# Combustível da casa, casada por PLACA. A `ordemabastecimento` do ERP está
# vazia nos últimos 12 meses (medido em 16/09/2026) e não serve.
ABASTEC_SQL = """
SELECT to_char(a.data_inicio_abastecimento, 'YYYY-MM-DD') AS data,
       btrim(coalesce(a.veiculo_placa, '')) AS placa,
       coalesce(a.volume, 0)::float8 AS litros,
       coalesce(a.custo, 0)::float8 AS valor,
       coalesce(a.custo_unitario, 0)::float8 AS preco_litro,
       coalesce(a.odometro, 0)::float8 AS odometro,
       coalesce(a.media_kilometro_litro, 0)::float8 AS km_litro
FROM sulista.ctaplus_abastecimentos a
WHERE btrim(coalesce(a.veiculo_placa, '')) = ANY(%(placas)s)
  AND a.data_inicio_abastecimento >= %(de)s::date
ORDER BY a.data_inicio_abastecimento DESC
"""


@cached(ttl=300, velha_ate=VELHA_ATE)
def _abastecimentos(cod: str, dias: int) -> list[dict]:
    placas = _placas(cod)
    if not placas:
        return []
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(ABASTEC_SQL, {"placas": placas, "de": _de(dias)})
        return [dict(r) for r in cur.fetchall()]


def abastecimentos(sess: dict, dias: int = JANELA_DIAS) -> dict:
    linhas = _abastecimentos(str(sess["proprietario_codigo"]), int(dias))
    return {"abastecimentos": linhas[:MAX_LINHAS],
            "mostrados": min(len(linhas), MAX_LINHAS), "total": len(linhas),
            "dias": int(dias),
            "litros": round(sum(a["litros"] or 0 for a in linhas), 1),
            "valor": round(sum(a["valor"] or 0 for a in linhas), 2)}


# ════════════════════════════════════════ lançamentos manuais (e as multas)
#
# AQUI ESTÁ O QUE A CASA LANÇA À MÃO no acerto do agregado: adicional de
# coleta, de entrega, de diária, km que faltou pagar, km pago a mais, vazio que
# faltou pagar. O tipo vem do cadastro do ERP (`tipocalculoacertoviagem`), e
# não de uma tradução escrita aqui — código sem tabela de domínio não vira
# rótulo inventado.
#
# E É AQUI QUE A MULTA APARECERIA. A Smartec, que abastece a tela de multas da
# casa, NÃO cobre agregado: 634 infrações em 12 meses, ZERO em placa AGR
# (medido em 16/09/2026) — ela lê a frota própria. Por isso o app não tem uma
# aba "multas" com zero, que seria lida como "não tenho multa": o que existe de
# multa para o agregado é desconto no acerto, e é onde ele deve procurar.
LANC_SQL = """
SELECT l.id::int AS id,
       to_char(l.data, 'YYYY-MM-DD') AS data,
       btrim(coalesce(l.placa, '')) AS placa,
       coalesce(l.valor, 0)::float8 AS valor,
       btrim(coalesce(t.descricao, '')) AS tipo,
       btrim(coalesce(l.observacao, '')) AS observacao,
       l.statuslancamento::int AS situacao
FROM sulista.lancamento_manual_agregado l
LEFT JOIN tipocalculoacertoviagem t ON t.codigo = l.calculo
WHERE btrim(coalesce(l.placa, '')) = ANY(%(placas)s)
  AND l.data >= %(de)s::date
ORDER BY l.data DESC, l.id DESC
"""


@cached(ttl=300, velha_ate=VELHA_ATE)
def _lancamentos(cod: str, dias: int) -> list[dict]:
    placas = _placas(cod)
    if not placas:
        return []
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(LANC_SQL, {"placas": placas, "de": _de(dias)})
        return [dict(r) for r in cur.fetchall()]


def lancamentos(sess: dict, dias: int = JANELA_DIAS) -> dict:
    """`situacao` vem do ERP: 1 é aprovado, 0 é pendente de aprovação (medido:
    560 contra 9 em 12 meses). O app mostra os dois, com a palavra — lançamento
    pendente é dinheiro que ainda não entrou no acerto, e o dono precisa saber
    que ele existe."""
    linhas = _lancamentos(str(sess["proprietario_codigo"]), int(dias))
    for l in linhas:
        l["aprovado"] = (l.get("situacao") == 1)
    return {"lancamentos": linhas[:MAX_LINHAS],
            "mostrados": min(len(linhas), MAX_LINHAS), "total": len(linhas),
            "dias": int(dias),
            "pendentes": sum(1 for l in linhas if not l["aprovado"])}


# ════════════════════════════════════════════════════════════ ocorrências
OCORRENCIAS_SQL = f"""
SELECT to_char(o.dtocorrencia, 'YYYY-MM-DD HH24:MI') AS quando,
       btrim(coalesce(oc.descricao, '')) AS ocorrencia,
       c.numero::int AS coleta,
       btrim(coalesce(c.veiculo, '')) AS placa
FROM coleta_ocorrencia o
JOIN coleta c ON c.grupo = o.grupo AND c.empresa = o.empresa
             AND c.filial = o.filial AND c.unidade = o.unidade
             AND c.diferenciadornumero = o.diferenciadornumero
             AND c.serie = o.serie AND c.numero = o.numero
LEFT JOIN ocorrencia oc ON oc.codigo = o.ocorrencia
WHERE c.dtcancelamento IS NULL
  AND btrim(coalesce(c.veiculo, '')) = ANY(%(placas)s)
  AND o.dtocorrencia >= %(de)s::date
  AND {OCORRENCIAS_MOTIVO}
ORDER BY o.dtocorrencia DESC
"""


@cached(ttl=300, velha_ate=VELHA_ATE)
def _ocorrencias(cod: str, dias: int) -> list[dict]:
    placas = _placas(cod)
    if not placas:
        return []
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(OCORRENCIAS_SQL, {"placas": placas, "de": _de(dias)})
        return [dict(r) for r in cur.fetchall()]


def ocorrencias(sess: dict, dias: int = JANELA_DIAS) -> dict:
    """Só motivo de atraso e ocorrência interna — ver `OCORRENCIAS_MOTIVO`. O
    ciclo do SAC fica fora: ele conta a viagem, não o que deu errado nela."""
    linhas = _ocorrencias(str(sess["proprietario_codigo"]), int(dias))
    return {"ocorrencias": linhas[:MAX_LINHAS],
            "mostrados": min(len(linhas), MAX_LINHAS), "total": len(linhas),
            "dias": int(dias)}


# ═══════════════════════════════════════════════════════════════ o resumo
def resumo(sess: dict, dias: int = JANELA_DIAS) -> dict:
    """A primeira tela: o que ele tem a receber, o que rodou e o que pede
    atenção. Cada bloco é tolerante à falha do vizinho — o ERP com dia ruim
    não pode apagar a tela inteira, e o que falhar vira `None`, que a página
    desenha como "indisponível" em vez de zero (zero seria afirmação)."""
    saida: dict = {"dias": int(dias)}
    for chave, fn in (("veiculos", lambda: veiculos(sess)),
                      ("acertos", lambda: acertos(sess, dias)),
                      ("viagens", lambda: viagens(sess, dias)),
                      ("abastecimentos", lambda: abastecimentos(sess, dias)),
                      ("lancamentos", lambda: lancamentos(sess, dias))):
        try:
            saida[chave] = fn()
        except Exception as exc:  # noqa: BLE001
            log.warning("resumo do agregado sem %s: %s", chave, type(exc).__name__)
            saida[chave] = None
    return saida


def _de(dias: int) -> str:
    """A data de corte, em texto ISO — calculada no Python e não no SQL para
    a mesma janela valer em todas as consultas da tela, inclusive as que
    tocam bancos diferentes (ERP e CtaPlus vivem no mesmo banco, mas a regra
    vale para quando isso mudar)."""
    from datetime import date, timedelta
    return (date.today() - timedelta(days=max(1, int(dias)))).isoformat()
