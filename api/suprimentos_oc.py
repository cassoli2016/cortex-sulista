"""Ordens de Compra — o fluxo inteiro, com a semântica que o ERP grava.

O QUE O ERP REALMENTE REGISTRA (medido em 01/09/2026, 38.424 OCs)
================================================================
- `aprovado` é o estado do fluxo: 1 = aprovada, 2 = pendente, 3 = reprovada.
  Toda reprovada tem `dtsuspensao` preenchida.
- `dtencaminhadoparaaprovador` separa a FILA REAL (encaminhada e sem decisão)
  do RASCUNHO (nunca encaminhado): hoje 60 OCs na fila, todas de dois dias,
  contra 41 rascunhos, alguns de 2023.
- `dtaprovador IS NULL` NÃO significa "sem aprovação": 965 OCs de 2023/24 têm
  aprovado=1, dtaprovador nulo e itens=0 (cadastro furado, todas com nota); e
  649 suspensas têm dtaprovador PREENCHIDO sem usuarioaprovador (a suspensão
  grava a data). O painel antigo contava as duas coisas como "pendentes".
- `dtprevisaoentrega` é o PRÓPRIO DIA DA EMISSÃO em 80% das OCs e anterior à
  emissão em 10%: não é promessa do fornecedor, é default do cadastro. Só
  vale como prazo quando é POSTERIOR à emissão. "Previsão vencida" crua era
  verdadeira no dia seguinte à emissão — 186 "atrasadas" que não existiam.
- O recebimento se prova pela EXISTÊNCIA do vínculo em
  `notafiscalentrada_item_ordemcomprarecebida` (crônica em docs/LICOES.md);
  o valor da linha de vínculo tem lixo (três linhas de bilhões numa OC de
  R$ 163 mil), então o valor recebido usa quantidade × preço da OC e, quando
  a quantidade vem zero, o menor entre o valor da linha e o da OC.
- Aprovação leva mediana de 3 horas (p90 de 1 dia) entre o encaminhamento e
  a decisão; da aprovação à nota, mediana de 1 dia em material e 3 em
  serviço. "Parada" começa em 30 dias — dez vezes o p90.
- `dtcancelamento` é nulo nas 38.424; `situacao` mistura estados. Nenhum dos
  dois serve de critério.

O AVA é PostgreSQL 9.3: sem FILTER (WHERE …), sem percentile_cont — os
percentis saem em Python. `%` em ILIKE vai dobrado por causa do psycopg.
"""
from __future__ import annotations

import time as _time
from datetime import date

from . import db

# ----------------------------------------------------------------------------
# UMA definição de cada estado, compartilhada pela tela, pela Visão Geral e
# pelo bloco "em aberto". Três caminhos com três regras foi como "Pendentes de
# aprovação" chegou a contar 965 OCs de 2023.
# ----------------------------------------------------------------------------
OC_APROVADO = "coalesce(o.aprovado, CASE WHEN o.dtaprovador IS NULL THEN 2 ELSE 1 END)"
OC_CAMPOS_ESTADO = f"""
         {OC_APROVADO} AS aprovado,
         (o.dtsuspensao IS NOT NULL) AS suspensa,
         (o.dtencaminhadoparaaprovador IS NOT NULL) AS encaminhada,
         (o.dtaprovador IS NULL) AS sem_data_aprovacao,
         (o.dtprevisaoentrega IS NOT NULL AND o.dtprevisaoentrega > o.dtemissao::date) AS prazo_informado,
         (o.dtprevisaoentrega IS NOT NULL AND o.dtprevisaoentrega > o.dtemissao::date
          AND o.dtprevisaoentrega < current_date) AS prazo_vencido,
         (current_date - coalesce(o.dtaprovador, o.dtemissao)::date)::int AS dias_aberta,
         CASE WHEN o.usuarioaprovador IS NOT NULL AND o.dtencaminhadoparaaprovador IS NOT NULL
                   AND o.dtaprovador IS NOT NULL
              THEN (extract(epoch FROM (o.dtaprovador - o.dtencaminhadoparaaprovador)) / 3600.0)::float8
              END AS horas_aprovacao"""

DIAS_PARADA = 30            # sem nota há mais de N dias desde a aprovação = parada

STATUS_TODOS = ("rascunho", "aprovacao", "aguardando", "atrasada",
                "recebida", "suspensa", "reprovada")

# Nome do fornecedor: nome fantasia, razão social, ou a ausência DITA.
_FORNECEDOR = ("coalesce(nullif(trim(c.nomefantasia),''), nullif(trim(c.razaosocial),''), "
               "'(sem cadastro)')")

# Valor recebido por OC, robusto ao lixo da coluna `valortotal` do vínculo.
_REC_CTE = """
rec AS (
  SELECT r.grupo, r.empresa, r.filialordemcompra AS filial,
         r.diferenciadornumeroordemcompra AS diferenciadornumero,
         r.numeroordemcompra AS numero,
         count(*)::int AS vinculos,
         sum(CASE WHEN coalesce(r.quantidaderecebida,0) > 0
                  THEN r.quantidaderecebida * coalesce(r.valorprecoordemcompraitemprogramacaoentrega,0)
                  ELSE least(coalesce(r.valortotal,0), oc.valortotal) END) AS valor_recebido
  FROM notafiscalentrada_item_ordemcomprarecebida r
  JOIN oc ON oc.grupo=r.grupo AND oc.empresa=r.empresa AND oc.filial=r.filialordemcompra
         AND oc.diferenciadornumero=r.diferenciadornumeroordemcompra AND oc.numero=r.numeroordemcompra
  GROUP BY 1,2,3,4,5
)"""

# Uma ÚNICA execução da cadeia pesada (o join de recebimento não tem índice no
# 9.3): busca as linhas do período + filial e deriva KPIs, fornecedores,
# aprovadores, tempo de aprovação e facetas em Python.
OC_ROWS_SQL = f"""
WITH oc AS (
  SELECT o.grupo, o.empresa, o.filial, o.diferenciadornumero, o.numero,
         o.dtemissao, o.dtprevisaoentrega, o.dtaprovador, o.dtsuspensao, o.tipo,
         o.cnpjcpffornecedor, o.codigousuario, o.usuarioaprovador, o.usuarioaprovador2,
         o.usuarioaprovadordirecionado,
         coalesce(o.valortotal,0) AS valortotal,
         {_FORNECEDOR} AS fornecedor,{OC_CAMPOS_ESTADO}
  FROM ordemcompra o
  LEFT JOIN cadastro c ON c.codigo = o.cnpjcpffornecedor
  WHERE o.dtemissao >= %(dt_de)s::date AND o.dtemissao < %(dt_ate)s::date + 1
    AND (o.filial = %(filial)s OR %(filial)s::int IS NULL)
),{_REC_CTE}
SELECT oc.numero, oc.filial, oc.tipo,
       to_char(oc.dtemissao,'YYYY-MM-DD') AS emissao,
       to_char(oc.dtaprovador,'YYYY-MM-DD') AS aprovada_em,
       to_char(oc.dtsuspensao,'YYYY-MM-DD') AS suspensa_em,
       CASE WHEN oc.prazo_informado THEN to_char(oc.dtprevisaoentrega,'YYYY-MM-DD') END AS prazo,
       oc.aprovado, oc.suspensa, oc.encaminhada, oc.sem_data_aprovacao,
       oc.prazo_informado, oc.prazo_vencido, oc.dias_aberta, oc.horas_aprovacao,
       oc.fornecedor, oc.cnpjcpffornecedor AS codigo_forn,
       oc.codigousuario AS criador_cod, oc.usuarioaprovador AS aprovador_cod,
       oc.usuarioaprovador2 AS aprovador2_cod, oc.usuarioaprovadordirecionado AS direcionado_cod,
       (rec.vinculos IS NOT NULL) AS tem_nf,
       oc.valortotal::float8 AS valor,
       greatest(oc.valortotal - coalesce(rec.valor_recebido,0), 0)::float8 AS valor_pendente
FROM oc LEFT JOIN rec ON rec.grupo=oc.grupo AND rec.empresa=oc.empresa AND rec.filial=oc.filial
     AND rec.diferenciadornumero=oc.diferenciadornumero AND rec.numero=oc.numero
"""

# Série mensal de emissões (últimos 12 meses): leve, sem o join de recebimento.
# NÃO segue o filtro de período — a tela diz isso no hint.
OC_MENSAL_SQL = """
SELECT to_char(o.dtemissao,'YYYY-MM') AS mes, count(*)::int AS ocs,
       sum(coalesce(o.valortotal,0))::float8 AS valor
FROM ordemcompra o
LEFT JOIN cadastro c ON c.codigo = o.cnpjcpffornecedor
WHERE o.dtemissao >= date_trunc('month', current_date) - interval '11 months'
  AND (o.filial = %(filial)s OR %(filial)s::int IS NULL)
  AND (o.codigousuario = %(criador)s OR %(criador)s::int IS NULL)
  AND (o.usuarioaprovador = %(aprovador)s OR %(aprovador)s::int IS NULL)
  AND (%(fornecedor)s::text IS NULL OR c.nomefantasia ILIKE '%%'||%(fornecedor)s||'%%'
       OR c.razaosocial ILIKE '%%'||%(fornecedor)s||'%%')
GROUP BY 1 ORDER BY 1
"""

OC_USUARIOS_SQL = ("SELECT codigo, coalesce(nullif(trim(nomecompleto),''), 'usuário '||codigo) AS nome, "
                   "(ativoinativo = 1) AS ativo FROM usuario")
# Alçada = valor máximo cadastrado para o aprovador no ERP (tabela `aprovador`).
# O ERP não documenta o campo; o que se mede é que toda OC acima dele levou
# segundo aprovador. É essa a conferência que a tela faz.
OC_ALCADAS_SQL = ("SELECT usuarioaprovador AS cod, max(valormaximo)::float8 AS valormaximo "
                  "FROM aprovador WHERE ativoinativo = 1 AND usuarioaprovador IS NOT NULL "
                  "GROUP BY 1")

# ----------------------------------------------------------------------------
# EM ABERTO (todo o histórico, não segue os filtros da barra): a fila de
# aprovação e as aprovadas sem nota.
# ----------------------------------------------------------------------------
_OC_ABERTA_BASE = f"""
WITH oc AS (
  SELECT o.grupo, o.empresa, o.filial, o.diferenciadornumero, o.numero,
         o.dtemissao, o.dtprevisaoentrega, o.dtaprovador, o.dtsuspensao, o.tipo,
         o.cnpjcpffornecedor, o.observacao, coalesce(o.valortotal,0) AS vt,{OC_CAMPOS_ESTADO}
  FROM ordemcompra o
  WHERE coalesce(o.valortotal,0) > 0 AND o.semaforo = 1
),
vinc AS (
  SELECT DISTINCT r.grupo, r.empresa, r.filialordemcompra AS f,
         r.diferenciadornumeroordemcompra AS d, r.numeroordemcompra AS n
  FROM notafiscalentrada_item_ordemcomprarecebida r
),
aberta AS (
  SELECT oc.*, (oc.observacao ILIKE '%%NF%%') AS cita_nf,
         (oc.aprovado = 1 AND NOT oc.suspensa) AS viva
  FROM oc LEFT JOIN vinc ON vinc.grupo=oc.grupo AND vinc.empresa=oc.empresa
       AND vinc.f=oc.filial AND vinc.d=oc.diferenciadornumero AND vinc.n=oc.numero
  WHERE vinc.n IS NULL
)
"""
# `viva` = aprovada e não suspensa: é o que conta. A suspensa sem nota (em
# qualquer estado de aprovação) entra só no cartão "fora da conta", para o
# volume que o ERP parou de propósito não sumir sem explicação. Fila e
# rascunho (aprovado = 2) têm bloco próprio.

OC_ABERTA_KPI_SQL = _OC_ABERTA_BASE + """
SELECT
  sum(CASE WHEN viva THEN 1 ELSE 0 END)::int AS ocs,
  coalesce(sum(CASE WHEN viva THEN vt ELSE 0 END),0)::float8 AS valor,
  sum(CASE WHEN viva AND dias_aberta > %(dias_min)s THEN 1 ELSE 0 END)::int AS paradas,
  coalesce(sum(CASE WHEN viva AND dias_aberta > %(dias_min)s THEN vt ELSE 0 END),0)::float8 AS paradas_valor,
  sum(CASE WHEN viva AND prazo_vencido THEN 1 ELSE 0 END)::int AS prazo_vencido,
  coalesce(sum(CASE WHEN viva AND prazo_vencido THEN vt ELSE 0 END),0)::float8 AS prazo_vencido_valor,
  sum(CASE WHEN viva AND prazo_informado THEN 1 ELSE 0 END)::int AS prazo_informado,
  sum(CASE WHEN viva AND cita_nf THEN 1 ELSE 0 END)::int AS cita_nf,
  coalesce(sum(CASE WHEN viva AND cita_nf THEN vt ELSE 0 END),0)::float8 AS cita_nf_valor,
  sum(CASE WHEN suspensa THEN 1 ELSE 0 END)::int AS suspensas,
  coalesce(sum(CASE WHEN suspensa THEN vt ELSE 0 END),0)::float8 AS suspensas_valor,
  min(CASE WHEN viva THEN coalesce(dtaprovador, dtemissao) END)::date::text AS mais_antiga
FROM aberta
"""

OC_ABERTA_FAIXA_SQL = _OC_ABERTA_BASE + """
SELECT CASE WHEN dias_aberta <= 7 THEN '1_ate_7'
            WHEN dias_aberta <= 30 THEN '2_8_30'
            WHEN dias_aberta <= 90 THEN '3_31_90'
            WHEN dias_aberta <= 180 THEN '4_91_180'
            ELSE '5_mais_180' END AS faixa,
       count(*)::int AS ocs, sum(vt)::float8 AS valor,
       sum(CASE WHEN prazo_vencido THEN 1 ELSE 0 END)::int AS prazo_vencido
FROM aberta WHERE viva
GROUP BY 1 ORDER BY 1
"""

# Radar: da mais antiga para a mais nova — a ordem em que se cobra.
OC_ABERTA_LISTA_SQL = _OC_ABERTA_BASE + """
SELECT a.numero, a.filial, a.tipo, a.dias_aberta AS dias,
       to_char(a.dtemissao,'YYYY-MM-DD') AS emissao,
       to_char(coalesce(a.dtaprovador, a.dtemissao),'YYYY-MM-DD') AS aprovada_em,
       CASE WHEN a.prazo_informado THEN to_char(a.dtprevisaoentrega,'YYYY-MM-DD') END AS prazo,
       a.prazo_vencido, a.cita_nf,
       a.vt::float8 AS valor,
       left(coalesce(a.observacao,''), 70) AS observacao,
       """ + _FORNECEDOR + """ AS fornecedor
FROM aberta a
LEFT JOIN cadastro c ON c.codigo = a.cnpjcpffornecedor
WHERE a.viva
ORDER BY coalesce(a.dtaprovador, a.dtemissao) ASC, a.vt DESC
LIMIT 200
"""

OC_ABERTA_FORN_SQL = _OC_ABERTA_BASE + """
SELECT """ + _FORNECEDOR + """ AS fornecedor,
       count(*)::int AS ocs, sum(a.vt)::float8 AS pendente,
       max(a.dias_aberta)::int AS dias_max
FROM aberta a
LEFT JOIN cadastro c ON c.codigo = a.cnpjcpffornecedor
WHERE a.viva AND a.dias_aberta > %(dias_min)s
GROUP BY 1 ORDER BY 3 DESC
"""

# A fila de aprovação de AGORA: encaminhada e sem decisão, mais os rascunhos
# que nunca chegaram a aprovador nenhum. Todo o histórico, não segue filtros.
OC_FILA_SQL = f"""
SELECT o.numero, o.filial, o.tipo,
       to_char(o.dtemissao,'YYYY-MM-DD') AS emissao,
       (o.dtencaminhadoparaaprovador IS NOT NULL) AS encaminhada,
       to_char(o.dtencaminhadoparaaprovador,'YYYY-MM-DD HH24:MI') AS encaminhada_em,
       round(extract(epoch FROM (current_timestamp
             - coalesce(o.dtencaminhadoparaaprovador, o.dtemissao))) / 3600.0)::int AS horas,
       o.codigousuario AS criador_cod, o.usuarioaprovadordirecionado AS direcionado_cod,
       coalesce(o.valortotal,0)::float8 AS valor,
       {_FORNECEDOR} AS fornecedor
FROM ordemcompra o
LEFT JOIN cadastro c ON c.codigo = o.cnpjcpffornecedor
WHERE {OC_APROVADO} = 2 AND o.dtsuspensao IS NULL AND o.dtaprovador IS NULL
ORDER BY (o.dtencaminhadoparaaprovador IS NOT NULL) DESC,
         coalesce(o.dtencaminhadoparaaprovador, o.dtemissao) ASC
LIMIT 300
"""


# ----------------------------------------------------------------------------
# Classificação — a MESMA para tela, Visão Geral e Copiloto.
# ----------------------------------------------------------------------------
def oc_status(r: dict) -> str:
    """Estado de uma OC a partir dos campos de `OC_CAMPOS_ESTADO` + `tem_nf`.

    reprovada  > suspensa > rascunho > aprovacao (fila) > recebida (tem nota)
    > atrasada (prazo informado e vencido, ou parada há mais de DIAS_PARADA)
    > aguardando.
    """
    if r.get("aprovado") == 3:
        return "reprovada"
    if r.get("suspensa"):
        return "suspensa"
    if r.get("aprovado") == 2:
        return "aprovacao" if r.get("encaminhada") else "rascunho"
    if r.get("tem_nf"):
        return "recebida"
    if r.get("prazo_vencido") or (r.get("dias_aberta") or 0) > DIAS_PARADA:
        return "atrasada"
    return "aguardando"


def oc_parcial(r: dict) -> bool:
    """Tem nota e ainda falta mais de 1% (ou R$ 1) do valor: recebimento parcial."""
    if not r.get("tem_nf"):
        return False
    return (r.get("valor_pendente") or 0.0) > max(1.0, 0.01 * (r.get("valor") or 0.0))


def acao_sugerida(dias: int, prazo_vencido: bool = False) -> str:
    """Chip igual para 2 e para 200 dias não prioriza nada."""
    if dias > 90:
        return "suspender"
    if dias > DIAS_PARADA or prazo_vencido:
        return "validar"
    return "cobrar"


def percentil(vals: list, p: float) -> float | None:
    """Percentil por posição (o AVA 9.3 não tem percentile_cont)."""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    # arredondamento "meio para cima" explícito: round() do Python é bancário
    # (round(4.5) == 4) e a mediana de dez valores cairia no quinto, não no sexto
    k = int(p * (len(v) - 1) + 0.5)
    return float(v[max(0, min(len(v) - 1, k))])


def _mask_doc(doc: str | None) -> str:
    from .queries import _mask_doc as _m
    return _m(doc)


# ----------------------------------------------------------------------------
# Cache de cadastros pequenos e estáveis (usuários, alçadas): uma hora.
# ----------------------------------------------------------------------------
_CADASTROS: dict = {"ts": 0.0, "usuarios": {}, "alcadas": {}}


def _cadastros(cur) -> tuple[dict, dict]:
    if _time.time() - _CADASTROS["ts"] > 3600 or not _CADASTROS["usuarios"]:
        cur.execute(OC_USUARIOS_SQL)
        _CADASTROS["usuarios"] = {u["codigo"]: {"nome": u["nome"], "ativo": bool(u["ativo"])}
                                  for u in cur.fetchall()}
        cur.execute(OC_ALCADAS_SQL)
        _CADASTROS["alcadas"] = {a["cod"]: a["valormaximo"] for a in cur.fetchall()}
        _CADASTROS["ts"] = _time.time()
    return _CADASTROS["usuarios"], _CADASTROS["alcadas"]


def _nome(usuarios: dict, cod) -> str | None:
    if cod is None:
        return None
    u = usuarios.get(cod)
    return u["nome"] if u else f"usuário {cod}"


def _ativo(usuarios: dict, cod) -> bool | None:
    if cod is None:
        return None
    u = usuarios.get(cod)
    return u["ativo"] if u else None


def _horas_resumo(horas: list) -> dict:
    v = [h for h in horas if h is not None]
    return {"n": len(v), "mediana_h": percentil(v, 0.5), "p90_h": percentil(v, 0.9),
            "max_h": max(v) if v else None}


# ----------------------------------------------------------------------------
# A tela: período + filtros.
# ----------------------------------------------------------------------------
def get_ordens_compra(filial: int | None, dt_de: str, dt_ate: str,
                      status: str | None = None, fornecedor: str | None = None,
                      criador: int | None = None, aprovador: int | None = None) -> dict:
    params = {"filial": filial, "dt_de": dt_de, "dt_ate": dt_ate,
              "status": status, "fornecedor": fornecedor,
              "criador": criador, "aprovador": aprovador}
    MAX_OCS_POR_FORN = 50
    with db.get_conn() as conn, conn.cursor() as cur:
        # o planner do 9.3 escolhe merge join por (grupo,empresa) — quase
        # constantes — e o join OC×recebimentos vira O(n×m) (~50s); com hash
        # join a mesma consulta sai em <1s
        cur.execute("SET LOCAL enable_mergejoin = off")
        cur.execute(OC_ROWS_SQL, params)
        rows = cur.fetchall()
        usuarios, alcadas = _cadastros(cur)
        cur.execute(OC_MENSAL_SQL, params)
        mensal = cur.fetchall()
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    forn_lower = fornecedor.lower() if fornecedor else None
    for r in rows:
        r["status"] = oc_status(r)
        r["parcial"] = oc_parcial(r)
        # acima da alçada do 1º aprovador e sem 2º aprovador — a conferência
        # de compliance que os dados permitem; None = aprovador sem alçada
        alc = alcadas.get(r["aprovador_cod"]) if r["aprovador_cod"] is not None else None
        r["alcada"] = alc
        r["acima_alcada"] = (alc is not None and r["valor"] > alc
                             and r["aprovador2_cod"] is None and r["status"] not in
                             ("suspensa", "reprovada", "rascunho", "aprovacao"))

    def match(r: dict, skip: str = "") -> bool:
        if skip != "status" and status and r["status"] != status:
            return False
        if skip != "fornecedor" and forn_lower and forn_lower not in r["fornecedor"].lower():
            return False
        if skip != "criador" and criador is not None and r["criador_cod"] != criador:
            return False
        if skip != "aprovador" and aprovador is not None and r["aprovador_cod"] != aprovador:
            return False
        return True

    sel = [r for r in rows if match(r)]

    def _soma(cond, campo="valor"):
        return round(sum(r[campo] for r in sel if cond(r)), 2)

    def _n(cond):
        return sum(1 for r in sel if cond(r))

    em_espera = ("aguardando", "atrasada")
    kpis = {
        "ocs": len(sel), "valor": _soma(lambda r: True),
        "recebidas": _n(lambda r: r["status"] == "recebida"),
        "recebidas_valor": _soma(lambda r: r["status"] == "recebida"),
        "parciais": _n(lambda r: r["parcial"]),
        "fila": _n(lambda r: r["status"] == "aprovacao"),
        "fila_valor": _soma(lambda r: r["status"] == "aprovacao"),
        "rascunhos": _n(lambda r: r["status"] == "rascunho"),
        "rascunhos_valor": _soma(lambda r: r["status"] == "rascunho"),
        "aguardando": _n(lambda r: r["status"] in em_espera),
        "aguardando_valor": _soma(lambda r: r["status"] in em_espera, "valor_pendente"),
        "atrasadas": _n(lambda r: r["status"] == "atrasada"),
        "atrasadas_valor": _soma(lambda r: r["status"] == "atrasada", "valor_pendente"),
        "suspensas": _n(lambda r: r["status"] == "suspensa"),
        "suspensas_valor": _soma(lambda r: r["status"] == "suspensa"),
        "reprovadas": _n(lambda r: r["status"] == "reprovada"),
        "reprovadas_valor": _soma(lambda r: r["status"] == "reprovada"),
        # cadastro furado: aprovada sem data de aprovação (2023/24) — fora dos
        # KPIs de fluxo, dita à parte
        "cadastro_sem_data": _n(lambda r: r["aprovado"] == 1 and r["sem_data_aprovacao"]),
        "cadastro_sem_data_valor": _soma(lambda r: r["aprovado"] == 1 and r["sem_data_aprovacao"]),
        "acima_alcada": _n(lambda r: r["acima_alcada"]),
        "acima_alcada_valor": _soma(lambda r: r["acima_alcada"]),
        "com_segundo_aprovador": _n(lambda r: r["aprovador2_cod"] is not None),
        "prazo_informado": _n(lambda r: r["prazo_informado"]),
    }
    tempo = _horas_resumo([r["horas_aprovacao"] for r in sel
                           if r["status"] not in ("suspensa", "reprovada")])

    # aprovadores do recorte: volume, tempo (mediana, não média — uma OC de 12
    # dias distorce), 2º aprovador e alçada
    por_apr: dict = {}
    for r in sel:
        cod = r["aprovador_cod"]
        if cod is None or r["status"] in ("suspensa", "reprovada"):
            continue
        g = por_apr.setdefault(cod, {"cod": cod, "ocs": 0, "valor": 0.0, "_h": [],
                                     "com_segundo": 0, "acima_alcada": 0})
        g["ocs"] += 1
        g["valor"] += r["valor"]
        g["_h"].append(r["horas_aprovacao"])
        g["com_segundo"] += 1 if r["aprovador2_cod"] is not None else 0
        g["acima_alcada"] += 1 if r["acima_alcada"] else 0
    aprovadores_tab = []
    for cod, g in sorted(por_apr.items(), key=lambda kv: -kv[1]["ocs"]):
        h = _horas_resumo(g.pop("_h"))
        alc = alcadas.get(cod)
        aprovadores_tab.append({
            **g, "valor": round(g["valor"], 2), "nome": _nome(usuarios, cod),
            "ativo": _ativo(usuarios, cod), **h, "alcada": alc,
            "acima_alcada": g["acima_alcada"] if alc is not None else None,
        })

    # fornecedores agregados (top 30 por valor) com ordens aninhadas
    grupos: dict[str, dict] = {}
    for r in sel:
        g = grupos.setdefault(r["codigo_forn"], {
            "fornecedor": r["fornecedor"], "ocs": 0, "valor": 0.0,
            "valor_pendente": 0.0, "atrasadas": 0, "em_aprovacao": 0,
            "suspensas": 0, "_rows": []})
        g["ocs"] += 1
        g["valor"] += r["valor"]
        g["valor_pendente"] += r["valor_pendente"] if r["status"] in em_espera else 0.0
        g["atrasadas"] += 1 if r["status"] == "atrasada" else 0
        g["em_aprovacao"] += 1 if r["status"] in ("aprovacao", "rascunho") else 0
        g["suspensas"] += 1 if r["status"] in ("suspensa", "reprovada") else 0
        g["_rows"].append(r)
    fornecedores = []
    top = sorted(grupos.items(), key=lambda kv: -kv[1]["valor"])[:30]
    for codigo, g in top:
        ordens = sorted(g.pop("_rows"), key=lambda r: (-r["valor_pendente"], r["emissao"]))
        g["valor"] = round(g["valor"], 2)
        g["valor_pendente"] = round(g["valor_pendente"], 2)
        g["doc"] = _mask_doc(codigo)
        g["ocultas"] = max(0, len(ordens) - MAX_OCS_POR_FORN)
        g["ordens"] = [{
            "numero": r["numero"], "filial": r["filial"], "tipo": r["tipo"],
            "emissao": r["emissao"], "aprovada_em": r["aprovada_em"],
            "suspensa_em": r["suspensa_em"],
            "prazo": r["prazo"], "dias_aberta": r["dias_aberta"],
            "criador": _nome(usuarios, r["criador_cod"]),
            "aprovador": _nome(usuarios, r["aprovador_cod"]),
            "aprovador2": _nome(usuarios, r["aprovador2_cod"]),
            "valor": r["valor"],
            "valor_pendente": r["valor_pendente"] if r["status"] in em_espera or r["parcial"] else 0.0,
            "parcial": r["parcial"], "acima_alcada": r["acima_alcada"],
            "status": r["status"],
        } for r in ordens[:MAX_OCS_POR_FORN]]
        fornecedores.append(g)

    # opções facetadas (todos os filtros exceto o próprio)
    def facet(campo: str, skip: str) -> list:
        cont: dict = {}
        for r in rows:
            if r[campo] is None or not match(r, skip=skip):
                continue
            cont[r[campo]] = cont.get(r[campo], 0) + 1
        return [{"codigo": c, "nome": _nome(usuarios, c), "ocs": n}
                for c, n in sorted(cont.items(), key=lambda kv: -kv[1])]

    return {
        "kpis": kpis,
        "tempo_aprovacao": tempo,
        "por_aprovador": aprovadores_tab,
        "fornecedores": fornecedores,
        "fornecedores_total": len(grupos),
        "fornecedores_top_valor": round(sum(g["valor"] for _, g in top), 2),
        "mensal": mensal,
        "criadores": facet("criador_cod", "criador"),
        "aprovadores": facet("aprovador_cod", "aprovador"),
        "dt_de": dt_de, "dt_ate": dt_ate,
        "filial": filial, "status": status, "fornecedor": fornecedor,
        "criador": criador, "aprovador": aprovador,
        "dias_parada": DIAS_PARADA,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · ordemcompra (aprovado, encaminhamento, suspensão) × "
                  "notafiscalentrada_item_ordemcomprarecebida (existência do vínculo) × "
                  "aprovador (alçada) · leitura"),
    }


# ----------------------------------------------------------------------------
# Em aberto: fila de aprovação de agora + aprovadas sem nota (todo o histórico).
# ----------------------------------------------------------------------------
def get_oc_pendentes(dias_min: int = DIAS_PARADA) -> dict:
    params = {"dias_min": dias_min}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL enable_mergejoin = off")
        cur.execute(OC_ABERTA_KPI_SQL, params)
        kpis = cur.fetchone()
        cur.execute(OC_ABERTA_FAIXA_SQL)
        faixas = cur.fetchall()
        cur.execute(OC_ABERTA_LISTA_SQL)
        lista = cur.fetchall()
        cur.execute(OC_ABERTA_FORN_SQL, params)
        forn = cur.fetchall()
        cur.execute(OC_FILA_SQL)
        fila = cur.fetchall()
        usuarios, _alcadas = _cadastros(cur)
        cur.execute("SELECT current_timestamp AS ts")
        meta = cur.fetchone()

    for r in lista:
        r["acao"] = acao_sugerida(r["dias"] or 0, bool(r["prazo_vencido"]))
    for r in fila:
        r["criador"] = _nome(usuarios, r["criador_cod"])
        r["direcionado"] = _nome(usuarios, r["direcionado_cod"])
        r["direcionado_ativo"] = _ativo(usuarios, r["direcionado_cod"])
        r["situacao"] = "fila" if r["encaminhada"] else "rascunho"
    na_fila = [r for r in fila if r["encaminhada"]]
    rascunhos = [r for r in fila if not r["encaminhada"]]
    fila_kpis = {
        "fila": len(na_fila),
        "fila_valor": round(sum(r["valor"] for r in na_fila), 2),
        "fila_horas_max": max((r["horas"] for r in na_fila), default=None),
        "fila_direcionado_inativo": sum(1 for r in na_fila if r["direcionado_ativo"] is False),
        "rascunhos": len(rascunhos),
        "rascunhos_valor": round(sum(r["valor"] for r in rascunhos), 2),
        "rascunho_mais_antigo": min((r["emissao"] for r in rascunhos), default=None),
    }
    return {
        "sem_nota": {
            "kpis": kpis, "faixas": faixas,
            "lista": lista, "lista_total": kpis["ocs"],
            "fornecedores": forn[:20], "fornecedores_total": len(forn),
        },
        "fila": {"kpis": fila_kpis, "itens": fila},
        "dias_min": dias_min,
        "atualizado_em": meta["ts"].isoformat(),
        "fonte": ("ERP AVA · ordemcompra aprovada SEM vínculo em "
                  "notafiscalentrada_item_ordemcomprarecebida, e a fila (aprovado=2) · "
                  "todo o histórico · não segue os filtros da tela · leitura"),
    }


# ----------------------------------------------------------------------------
# Visão Geral: três escalares dos últimos 12 meses, com a MESMA regra da tela.
# ----------------------------------------------------------------------------
VG_OC_SQL = f"""
WITH oc AS (
  SELECT o.grupo, o.empresa, o.filial, o.diferenciadornumero, o.numero,
         coalesce(o.valortotal,0) AS valortotal,{OC_CAMPOS_ESTADO}
  FROM ordemcompra o
  WHERE o.dtemissao >= current_date - 365 AND o.dtemissao < current_date + 1
),{_REC_CTE}
SELECT
  coalesce(sum(CASE WHEN oc.aprovado = 1 AND NOT oc.suspensa AND rec.vinculos IS NULL
                     AND (oc.prazo_vencido OR oc.dias_aberta > {DIAS_PARADA})
                    THEN 1 ELSE 0 END),0)::int AS oc_atrasadas,
  coalesce(sum(CASE WHEN oc.aprovado = 1 AND NOT oc.suspensa AND rec.vinculos IS NULL
                     AND (oc.prazo_vencido OR oc.dias_aberta > {DIAS_PARADA})
                    THEN greatest(oc.valortotal - coalesce(rec.valor_recebido,0), 0) ELSE 0 END),0)::float8
                    AS oc_atraso_valor,
  coalesce(sum(CASE WHEN oc.aprovado = 2 AND oc.encaminhada AND NOT oc.suspensa
                    THEN 1 ELSE 0 END),0)::int AS oc_aprovacao,
  coalesce(sum(CASE WHEN oc.aprovado = 2 AND NOT oc.encaminhada AND NOT oc.suspensa
                    THEN 1 ELSE 0 END),0)::int AS oc_rascunhos
FROM oc LEFT JOIN rec ON rec.grupo=oc.grupo AND rec.empresa=oc.empresa AND rec.filial=oc.filial
     AND rec.diferenciadornumero=oc.diferenciadornumero AND rec.numero=oc.numero
"""


def snapshot_copiloto() -> dict:
    """Só KPIs escalares (sem fornecedor, sem número de OC, sem nome) para o
    snapshot do Copiloto. Lê caches; nunca dispara coleta."""
    from . import queries as _q
    p = _q.get_oc_pendentes()
    hoje = date.today()
    ini = date(hoje.year, hoje.month, 1).isoformat()
    o = _q.get_ordens_compra(None, ini, hoje.isoformat())
    sn, fi = p["sem_nota"]["kpis"], p["fila"]["kpis"]
    return {
        "fila_aprovacao": fi["fila"], "fila_valor": fi["fila_valor"],
        "fila_horas_max": fi["fila_horas_max"],
        "rascunhos": fi["rascunhos"], "rascunhos_valor": fi["rascunhos_valor"],
        "sem_nota": sn["ocs"], "sem_nota_valor": sn["valor"],
        "sem_nota_paradas": sn["paradas"], "sem_nota_paradas_valor": sn["paradas_valor"],
        "sem_nota_prazo_vencido": sn["prazo_vencido"],
        "suspensas_sem_nota": sn["suspensas"],
        "mes": {k: o["kpis"][k] for k in ("ocs", "valor", "recebidas", "fila", "rascunhos",
                                          "aguardando", "atrasadas", "atrasadas_valor",
                                          "suspensas", "reprovadas", "acima_alcada")},
        "tempo_aprovacao_mes": o["tempo_aprovacao"],
        "dias_parada": DIAS_PARADA,
    }
