# -*- coding: utf-8 -*-
"""O que AINDA DÁ para antecipar — e que não está em portal nenhum.

POR QUE ISTO EXISTE
===================
A conciliação que já havia (`api/antecipacoes/conciliacao.py`) olha numa
direção só: pega os documentos que o PORTAL listou e confere se o ERP os tem
em aberto. Ela responde "o que o portal diz é verdade?".

Falta a pergunta oposta, e é a que decide dinheiro: **o que está em aberto no
ERP, é de sacado com convênio, e nunca chegou a portal nenhum?** Medido em
09/09/2026, a resposta eram R$ 4,3 milhões — que ninguém via, porque nenhuma
tela cruzava esse lado.

O ERP É A FONTE DA VERDADE AQUI, e não o portal. Só a Tupy tem integração; os
demais convênios entram por planilha, quando alguém lembra. Uma posição de
portal desatualizada não pode se disfarçar de "não há nada a antecipar", e é
exatamente isso que acontecia: o portal Maxion trazia 6 títulos enquanto o
contas a receber tinha 598 do mesmo sacado.

A CHAVE, E O DEFEITO QUE ELA ESCONDE
====================================
O casamento é pelo número da nota, e os dois lados a escrevem diferente:

    Monkey     '000051366-1'   (zeros à esquerda + sufixo da parcela)
    ERP        '51414'         (inteiro puro)

Cruzando cru, NADA casa — e "nada casa" tem a mesma cara de "tudo está fora
do portal". Medido contra a posição vigente da Tupy: com a chave crua, 0 de
288 casam; normalizada, 285 de 288. A primeira versão desta análise concluiu
que havia R$ 5,6 milhões parados, e era artefato da chave.

O sinal de que era defeito e não achado foi o próprio 100%: quando um
cruzamento não casa NADA, o suspeito é a chave, nunca o mundo.

E O CRUZAMENTO É POR SACADO, não global. Número de nota se repete entre
emitentes — a nota 51311 da Adient não é a nota 51311 da Tupy. Cruzar sem
escopo faz o título de um sacado se dar por antecipado porque outro sacado
tem uma nota com o mesmo número. `sponsor_cnpj` do espelho casa exatamente
com o `cadastro.codigo` do ERP, então o escopo é exato.

FILIAL CADASTRADA × MESMA RAIZ DE CNPJ
======================================
`ant_sacados` cadastra por CNPJ de FILIAL, e o ERP tem outras filiais do
mesmo grupo com título em aberto. Medido: a Adient está cadastrada só em São
Bernardo (R$ 35 mil), enquanto Pouso Alegre e São José dos Pinhais somam
R$ 1,55 milhão — e ninguém sabe, olhando a tela, se o convênio cobre as três.

ESTE MÓDULO NÃO DECIDE ISSO. O cadastro é a autoridade sobre elegibilidade, e
inventar que "a raiz é elegível" criaria uma oportunidade que pode não
existir. As filiais não cadastradas saem em bloco PRÓPRIO, rotuladas — quem
opera confere o convênio e, se for o caso, cadastra. Heurística escondida
vira verdade do sistema; heurística mostrada dos dois lados vira pergunta.
"""
from __future__ import annotations

import re
from datetime import date

from api import db, pglocal
from api.queries import cached

# O teste redireciona isto para um schema próprio (fixture `esquema_pg`).
ESQUEMA: str | None = None

# PRAZO MÍNIMO PARA CONTAR COMO OPORTUNIDADE.
#
# Não é regra de portal, é aritmética: antecipar um título que vence em três
# dias troca três dias de caixa por um deságio, e nenhuma mesa opera isso.
# Abaixo deste prazo o título aparece na contagem geral mas fica FORA do
# total antecipável — e a tela diz quanto ficou de fora, para o número não
# encolher em silêncio.
PRAZO_MINIMO = 15

# A CURVA DE TAXA É MEDIDA, NÃO ESCRITA — e a primeira versão deste módulo a
# escreveu, o que custou um teste vermelho e uma lição.
#
# Eu havia fixado a curva medida nos últimos 30 dias como constante, e afirmado
# no comentário que "título mais longo custa menos por mês". As duas coisas não
# cabem juntas: a relação decrescente é verdadeira na janela de 12 MESES
# (1,2875% até 29 dias contra 1,2385% acima de 84, monotônica nas cinco
# faixas), e na janela de 30 dias a curva NÃO é monotônica — porque as faixas
# curtas têm base de 13 e 35 títulos, e 13 títulos não formam um preço.
#
# Curva fixa também envelhece calada: a taxa caiu 13% em doze meses, e uma
# constante escrita hoje estaria errada no trimestre que vem sem avisar.
#
# Então ela sai do banco a cada leitura, com PISO DE BASE: faixa com menos de
# `BASE_MINIMA` títulos na janela não vira preço próprio, cai na média
# ponderada da janela inteira. É a mesma régua do preço de peça — desvio só
# existe onde há base para medi-lo.
#
# E vale para a TUPY. Para Maxion e Adient é REFERÊNCIA, porque são outras
# mesas e nenhuma publica taxa antes da operação: deságio estimado com taxa de
# terceiro, apresentado como cotação, é pior que deságio nenhum. A tela diz.
BASE_MINIMA = 50

CURVA_SQL = """
SELECT CASE WHEN d < 20 THEN 20 WHEN d < 40 THEN 40 WHEN d < 60 THEN 60
            WHEN d < 84 THEN 84 ELSE 999999 END AS teto,
       count(*)::int AS base,
       avg(tx)::float8 AS taxa,
       sum(v)::float8 AS nominal,
       sum(tx * v)::float8 AS tx_ponderada
FROM (SELECT (payment_date - criado_fornecedor::date) AS d,
             purchased_tax AS tx, payment_value AS v
      FROM mky_recebiveis
      WHERE status IN ('SOLD', 'PAID') AND purchased_tax IS NOT NULL
        AND payment_date IS NOT NULL AND criado_fornecedor IS NOT NULL
        AND criado_fornecedor >= now() - interval '30 days') x
WHERE d >= 0
GROUP BY 1 ORDER BY 1
"""


def montar_curva(linhas: list[dict], base_minima: int = BASE_MINIMA):
    """(faixas, taxa_de_referência) a partir da medição da janela.

    Devolve `(None, None)` quando não há medição nenhuma — e aí o deságio não
    é estimado. Inventar uma taxa para poder preencher a coluna seria
    exatamente o zero-que-parece-desempenho que a casa proíbe, com vírgula.
    """
    linhas = [l for l in linhas if (l.get("base") or 0) > 0]
    if not linhas:
        return None, None
    peso = sum(float(l["nominal"] or 0.0) for l in linhas)
    ref = (sum(float(l["tx_ponderada"] or 0.0) for l in linhas) / peso
           if peso else None)
    if ref is None:
        return None, None
    faixas = [(int(l["teto"]),
               float(l["taxa"]) if int(l["base"]) >= base_minima else ref,
               int(l["base"]))
              for l in linhas]
    return faixas, ref


def taxa_estimada(prazo_dias: int, faixas, referencia) -> float | None:
    """Taxa mensal para um prazo. `None` quando não houve medição."""
    if not faixas:
        return referencia
    for teto, tx, _base in faixas:
        if prazo_dias < teto:
            return tx
    return faixas[-1][1]


def normalizar_documento(valor) -> str | None:
    """A chave de casamento entre portal e ERP.

    Tira o sufixo de parcela, os não-dígitos e os zeros à esquerda. É a única
    forma que faz `'000051366-1'` (Monkey) e `'51366'` (ERP) serem o mesmo
    documento — ver o bloco A CHAVE lá em cima.

    Devolve `None` para o que não sobra dígito nenhum: documento vazio não
    casa com nada, e deixá-lo virar string vazia faria TODOS os vazios
    casarem entre si.
    """
    s = str(valor or "").strip().split("-")[0]
    s = re.sub(r"\D", "", s).lstrip("0")
    return s or None


# Contas a receber em aberto, por RAIZ de CNPJ. A raiz e não o CNPJ inteiro
# de propósito: é assim que as filiais não cadastradas aparecem, em vez de
# sumirem silenciosamente (ver o bloco FILIAL CADASTRADA lá em cima).
#
# `f.composicao = 1` e `dtpagamento IS NULL` são a mesma régua do
# `conciliacao.CONC_SQL` — duas telas que medem "em aberto" com critérios
# diferentes discordam entre si, e aí ninguém confia em nenhuma.
ERP_SQL = """
SELECT fc.numerosequenciadocumentoorigem::text AS documento,
       ca.codigo AS cnpj,
       coalesce(f.dtprevisaopagamento, f.dtvencimento)::date AS vencimento,
       min(coalesce(nullif(trim(ca.nomefantasia), ''),
                    nullif(trim(ca.razaosocial), ''))) AS sacado,
       sum(fc.valorpendentecnpjcliente)::float8 AS valor
FROM fatura f
JOIN fatura_composicao fc USING (grupo, empresa, filial, unidade, sequencia)
JOIN cadastro ca ON ca.codigo = f.cliente
WHERE f.grupo = 1 AND fc.valorpendentecnpjcliente > 0
  AND f.dtcancelamento IS NULL AND f.composicao = 1 AND f.dtpagamento IS NULL
  AND substr(ca.codigo, 1, 8) = ANY(%(raizes)s)
GROUP BY fc.numerosequenciadocumentoorigem, ca.codigo,
         coalesce(f.dtprevisaopagamento, f.dtvencimento)
"""

SACADOS_SQL = """
SELECT cnpj, nome, portal, elegivel FROM ant_sacados WHERE elegivel = 1
"""

# O que JÁ está em portal, com o CNPJ do sacado junto — é ele que dá escopo
# ao casamento. Duas fontes porque só a Tupy tem integração:
#   - mky_recebiveis: o espelho da Monkey, varrido 2x/dia
#   - ant_titulos: a posição importada por planilha dos demais portais
PORTAL_MONKEY_SQL = """
SELECT sponsor_cnpj AS cnpj, invoice_number AS documento
FROM mky_recebiveis WHERE invoice_number IS NOT NULL
"""

PORTAL_PLANILHA_SQL = """
SELECT t.cnpj_sacado AS cnpj, t.documento
FROM ant_titulos t JOIN ant_envios e ON e.id = t.envio_id
WHERE e.vigente = 1 AND t.documento IS NOT NULL
"""


def _faixa(dias: int) -> str:
    if dias < 0:
        return "vencido"
    if dias < PRAZO_MINIMO:
        return "menos de %d dias" % PRAZO_MINIMO
    if dias <= 30:
        return "15 a 30 dias"
    if dias <= 60:
        return "31 a 60 dias"
    if dias <= 90:
        return "61 a 90 dias"
    return "mais de 90 dias"


@cached(ttl=300)
def get_elegiveis() -> dict:
    return montar()


def montar(esquema: str | None = None, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    faixas, ref = None, None
    try:
        with pglocal.get_conn(esquema or ESQUEMA) as conn, conn.cursor() as cur:
            cur.execute(SACADOS_SQL)
            sacados = [dict(r) for r in cur.fetchall()]
            if not sacados:
                return {"disponivel": False,
                        "motivo": "nenhum sacado elegível cadastrado "
                                  "(Antecipação › sacados)"}
            cur.execute(PORTAL_PLANILHA_SQL)
            no_portal = [dict(r) for r in cur.fetchall()]
            try:
                cur.execute(PORTAL_MONKEY_SQL)
                no_portal += [dict(r) for r in cur.fetchall()]
                cur.execute(CURVA_SQL)
                faixas, ref = montar_curva([dict(r) for r in cur.fetchall()])
                integrado = True
            except Exception as exc:  # noqa: BLE001
                # espelho ausente NÃO pode virar "tudo está fora do portal":
                # seria o alarme mais caro possível, e falso.
                if not pglocal.sem_tabela(exc):
                    raise
                integrado = False
                faixas, ref = None, None
    except Exception as exc:  # noqa: BLE001
        if pglocal.sem_tabela(exc):
            return {"disponivel": False, "motivo": "migration 0006 pendente"}
        raise

    cadastrados = {s["cnpj"] for s in sacados}
    raizes = sorted({s["cnpj"][:8] for s in sacados if s["cnpj"]})
    nome_por_cnpj = {s["cnpj"]: s["nome"] for s in sacados}

    # (cnpj, documento normalizado) -> já está em portal
    ja = set()
    for r in no_portal:
        d = normalizar_documento(r.get("documento"))
        if d and r.get("cnpj"):
            ja.add((str(r["cnpj"]).strip(), d))

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(ERP_SQL, {"raizes": raizes})
        erp = [dict(r) for r in cur.fetchall()]

    grupos: dict = {}
    for r in erp:
        cnpj = str(r["cnpj"]).strip()
        doc = normalizar_documento(r["documento"])
        dias = (r["vencimento"] - hoje).days if r["vencimento"] else None
        em_portal = bool(doc) and (cnpj, doc) in ja
        g = grupos.setdefault(cnpj, {
            "cnpj": cnpj,
            "sacado": r["sacado"] or nome_por_cnpj.get(cnpj) or cnpj,
            "cadastrado": cnpj in cadastrados,
            "portal": next((s["portal"] for s in sacados
                            if s["cnpj"] == cnpj), None),
            "titulos": 0, "valor": 0.0,
            "no_portal": 0, "valor_no_portal": 0.0,
            "fora": 0, "valor_fora": 0.0,
            "curto": 0, "valor_curto": 0.0,
            "antecipavel": 0, "valor_antecipavel": 0.0, "desagio": 0.0,
            "faixas": {},
        })
        g["titulos"] += 1
        g["valor"] += r["valor"]
        if em_portal:
            g["no_portal"] += 1
            g["valor_no_portal"] += r["valor"]
            continue
        g["fora"] += 1
        g["valor_fora"] += r["valor"]
        f = g["faixas"].setdefault(_faixa(dias if dias is not None else -1),
                                   {"titulos": 0, "valor": 0.0})
        f["titulos"] += 1
        f["valor"] += r["valor"]
        if dias is None or dias < PRAZO_MINIMO:
            g["curto"] += 1
            g["valor_curto"] += r["valor"]
            continue
        g["antecipavel"] += 1
        g["valor_antecipavel"] += r["valor"]
        tx = taxa_estimada(dias, faixas, ref)
        if tx is not None:
            g["desagio"] += r["valor"] * tx / 100.0 * dias / 30.0

    linhas = sorted(grupos.values(), key=lambda x: -x["valor_antecipavel"])
    for g in linhas:
        g["faixas"] = [{"faixa": k, **v} for k, v in sorted(
            g["faixas"].items(), key=lambda kv: -kv[1]["valor"])]
        g["liquido"] = g["valor_antecipavel"] - g["desagio"]
        g["desagio_pct"] = (100.0 * g["desagio"] / g["valor_antecipavel"]
                            if g["valor_antecipavel"] else None)

    def _soma(sel) -> dict:
        alvo = [g for g in linhas if sel(g)]
        v = sum(g["valor_antecipavel"] for g in alvo)
        d = sum(g["desagio"] for g in alvo)
        return {"sacados": len(alvo),
                "titulos": sum(g["antecipavel"] for g in alvo),
                "valor": v, "desagio": d, "liquido": v - d,
                "desagio_pct": (100.0 * d / v) if v else None}

    return {
        "disponivel": True,
        "integrado": integrado,
        "hoje": hoje.isoformat(),
        "prazo_minimo": PRAZO_MINIMO,
        "taxa_referencia": ref,
        "curva": [{"ate": t, "taxa": x, "base": b}
                  for t, x, b in (faixas or [])],
        "cadastrados": _soma(lambda g: g["cadastrado"]),
        "mesma_raiz": _soma(lambda g: not g["cadastrado"]),
        "linhas": linhas,
        "fonte": ("Contas a receber do ERP (fatura × fatura_composicao, em "
                  "aberto) cruzado por nota normalizada com o espelho da "
                  "Monkey e a posição importada dos demais portais · leitura"),
    }
