"""Leitura da jornada — das tabelas `jor_*` do banco local do CÓRTEX.

Substitui a leitura direta de `sulista.rasterjor_*` no AVA. O contrato de saída
é o MESMO que a tela já consome; o que mudou foi de onde o dado vem, e isso
muda três coisas que importam:

1. **A defasagem agora é medida contra a NOSSA coleta**, não contra uma rotina
   de terceiro. `jor_carga` registra toda passagem — inclusive a que falhou —,
   então a Saúde do Servidor sabe dizer "parou de chegar" no dia em que parar.
   A rotina antiga vivia no AVA e ficou 136 dias parada sem sinal nenhum.

2. **`origem` distingue de onde cada linha veio**: `ava` é a carga inicial do
   histórico (01/01/2025 a 15/04/2026, o que a rotina externa chegou a trazer),
   `api` é a coleta própria. No dia em que os números divergirem, é essa coluna
   que responde.

3. **A deduplicação é nossa.** A tabela de origem no AVA não tem chave nenhuma
   e acumulou ~50% de duplicata por recarga repetida: 98.109 linhas para 49.208
   eventos distintos. A chave natural aqui recusa a repetição na entrada.

O banco é o PostgreSQL 16 local, então `FILTER (WHERE …)` seria permitido — mas
o `CASE WHEN` fica, porque é o que o resto da casa usa e alternar dialeto entre
módulos só cria dúvida em quem lê.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .. import pglocal
from .coleta import ESQUEMA as _ESQ_MOD  # noqa: F401  (documenta a origem)


def _esq(esquema: str | None) -> str | None:
    """Schema do teste, quando houver. O redirecionamento vive em `coleta`,
    que é quem escreve — ter duas variáveis seria duas chances de um teste
    redirecionar a leitura e gravar em produção."""
    from . import coleta
    return esquema or coleta.ESQUEMA

# Acima disto a coleta está parada, não atrasada. Jornada é dado diário.
DEFASAGEM_ALERTA_DIAS = 7

# `tipo` (journey_type) vem como letra (N, D, A, F) e NÃO HÁ TABELA DE DOMÍNIO
# nem rótulo no payload da RasterJOR. Não se inventa nome: a tela mostra a
# letra com o que se OBSERVA em cada uma. Mesma regra da coluna "Tipo (cód.)"
# da Manutenção.
JOURNEY_TYPE_SEM_DOMINIO = True


# ── Inconformidade de TEMPO × marcação NOTURNA ───────────────────────────────
#
# A RasterJOR chama tudo de "unconformity", e o tipo mais frequente — DIRECAO
# NOTURNA, 35% dos eventos — NÃO É VIOLAÇÃO de nada: é trabalho noturno, que é
# legal e gera adicional. Somar os dois num KPI só faz a taxa por jornada subir
# um terço por causa de um evento que ninguém precisa corrigir.
#
# A classificação abaixo é NOSSA e está dita na tela; o tipo cru continua na
# tabela, porque quem classifica jornada é o fornecedor e a leitura dele é que
# vale numa discussão trabalhista.
#
# O vínculo com a Lei 13.103/2015 é o que cada nome descreve:
#   DIRECAO ININTERRUPTA                  → 5h30 de direção contínua (art. 67-C)
#   NAO CUMPRIMENTO DO INTERVALO DE JORNADAS → interjornada de 11h
#   JORNADA SEM PARADA PARA REFEICAO      → intrajornada de 1h
#   EXCESSO DE JORNADA                    → jornada máxima do dia
# Teto do ranking de motoristas. Nomeado porque a TELA precisa dele para dizer
# "40 de N" em vez de deixar o corte passar por total.
RANKING_LIMITE = 40

TIPOS_TEMPO = (
    "DIRECAO ININTERRUPTA",
    "NAO CUMPRIMENTO DO INTERVALO DE JORNADAS",
    "JORNADA SEM PARADA PARA REFEICAO",
    "EXCESSO DE JORNADA",
)
# Fora da regra de tempo: marcação noturna e falha de equipamento. Não entram
# no KPI de risco trabalhista, mas continuam visíveis na tabela.
TIPOS_FORA = ("DIRECAO NOTURNA", "VEÍCULO SEM POSIÇÃO", "VEICULO SEM POSICAO")


def _classe(tipo: str) -> str:
    t = (tipo or "").upper().strip()
    if t in TIPOS_TEMPO:
        return "tempo"
    if t in TIPOS_FORA:
        return "fora"
    # Tipo novo do fornecedor entra como "tempo": errar para o lado de
    # MOSTRAR o risco é melhor que escondê-lo num balde silencioso.
    return "tempo"


def _h(minutos) -> float:
    return round(float(minutos or 0) / 60.0, 1)


def defasagem(esquema: str | None = None) -> dict:
    """Há quanto tempo o dado não chega, e o que a última coleta disse.

    Vai para o TOPO da tela e para a Saúde. É o primeiro número que alguém
    precisa ver: todos os outros descrevem um passado que pode ter meses.
    """
    hoje = date.today()
    d = {"corte_dias": DEFASAGEM_ALERTA_DIAS}
    try:
        r = pglocal.um("""
            SELECT max(data)::date AS ultimo, count(*)::int AS jornadas,
                   count(DISTINCT documento)::int AS motoristas,
                   sum(CASE WHEN origem='api' THEN 1 ELSE 0 END)::int AS da_api,
                   sum(CASE WHEN origem='ava' THEN 1 ELSE 0 END)::int AS do_ava
              FROM jor_jornadas""", esquema=_esq(esquema)) or {}
        ultimo = r.get("ultimo")
        d.update({
            "ultimo_dado": ultimo.isoformat() if ultimo else None,
            "dias": (hoje - ultimo).days if ultimo else None,
            "jornadas": r.get("jornadas") or 0,
            "motoristas": r.get("motoristas") or 0,
            "da_api": r.get("da_api") or 0,
            "do_ava": r.get("do_ava") or 0,
        })
        d["parada"] = bool(d["dias"] is not None
                           and d["dias"] > DEFASAGEM_ALERTA_DIAS)
        c = pglocal.um("""
            SELECT ts, recurso, ok, lidos, gravados, mensagem, origem
              FROM jor_carga ORDER BY id DESC LIMIT 1""",
                       esquema=_esq(esquema))
        d["ultima_carga"] = dict(c) if c else None
        f = pglocal.um("""
            SELECT count(*)::int AS n FROM jor_carga WHERE ok=0 AND ts >= %s""",
                       ((datetime.now() - timedelta(days=2)).isoformat(),),
                       esquema=_esq(esquema)) or {}
        d["falhas_48h"] = f.get("n") or 0
    except Exception as exc:  # noqa: BLE001
        d["erro"] = ("tabelas ausentes — rode scripts/migrar_schema.py"
                     if pglocal.sem_tabela(exc) else type(exc).__name__)
        d["parada"] = True
    from . import cliente
    d["coleta_configurada"] = cliente.configurado()
    d["coleta_falta"] = cliente.o_que_falta()
    return d


# Janela padrão da tela. DOZE MESES e não 90 dias por duas razões:
#
# 1. A tela não tem filtro de período, então este número é o único recorte que
#    existe — e com 90 dias o gráfico mensal mostrava três barras, o que não é
#    série nenhuma. Comparação vs período anterior, sazonalidade e "está
#    piorando?" precisam de um ano.
# 2. É o detalhe diário que fica caro de ler num ano, e é exatamente isso que
#    o zoom do ECharts resolve — o gráfico dia a dia abre nos últimos ~120
#    dias e o resto está a um arrasto de distância.
JANELA_TELA_DIAS = 365


def _janela(de, ate, esquema) -> tuple[str, str]:
    """Janela ANCORADA NO ÚLTIMO DADO, não em hoje.

    Com a coleta parada, `current_date - 365` devolve zero linha e a tela abre
    vazia — que é exatamente a leitura errada: "ninguém rodou" em vez de "parou
    de chegar". Foi essa confusão que deixou a parada passar meses sem alarme.
    """
    if de and ate:
        return de, ate
    r = pglocal.um("SELECT max(data)::date AS m FROM jor_jornadas",
                   esquema=_esq(esquema)) or {}
    fim = r.get("m") or date.today()
    return (de or (fim - timedelta(days=JANELA_TELA_DIAS)).isoformat(),
            ate or fim.isoformat())


# `n_com_km` e `m_direcao_com_km` existem porque **`km` é NULO em dois terços
# das jornadas** (16.950 de 25.990 medidas, e a proporção é a mesma nas duas
# origens): o fornecedor não reporta hodômetro em toda jornada. Sem elas, o
# km/h dividia o km de um terço das jornadas pelas HORAS DE TODAS e devolvia
# 35,9 km/h onde o número honesto é 43,2 — uma queda de um quarto sem que nada
# tivesse mudado na operação. Mesma família do "664 de 836 rastreadores sem
# sinal": o denominador tem de conter só quem podia entrar no numerador.
#
# As duas colunas usam O MESMO CRITÉRIO (`km > 0`). Com `count(km)` no
# contador e `km > 0` no divisor, uma jornada gravada com km ZERO entraria na
# cobertura e não no divisor — a cobertura diria que o campo está preenchido e
# a conta não usaria a hora dela. Hoje não há km zero no dado, e é por isso
# mesmo que a divergência passaria despercebida até o dia em que houvesse.
#
# (A explicação fica AQUI e não dentro da string: `%` dentro do SQL vira
# placeholder para o psycopg e derruba a consulta com "incomplete placeholder".)
_COMP = """
SELECT count(*)::int                         AS jornadas,
       count(DISTINCT documento)::int        AS motoristas,
       sum(min_direcao)::bigint              AS m_direcao,
       sum(min_parado)::bigint               AS m_parado,
       sum(min_refeicao)::bigint             AS m_refeicao,
       sum(min_descanso)::bigint             AS m_descanso,
       sum(min_repouso)::bigint              AS m_repouso,
       sum(min_extra)::bigint                AS m_extra,
       sum(min_falta)::bigint                AS m_falta,
       sum(min_falta_repouso)::bigint        AS m_falta_repouso,
       sum(min_total)::bigint                AS m_total,
       sum(km)::numeric                      AS km,
       sum(CASE WHEN km > 0 THEN 1 ELSE 0 END)::int
                                             AS n_com_km,
       sum(CASE WHEN km > 0 THEN min_direcao ELSE 0 END)::bigint
                                             AS m_direcao_com_km
FROM jor_jornadas WHERE data >= %(de)s::date AND data <= %(ate)s::date
"""

_MENSAL = """
SELECT to_char(data,'YYYY-MM')               AS mes,
       count(*)::int                         AS jornadas,
       count(DISTINCT documento)::int        AS motoristas,
       sum(min_direcao)::bigint              AS m_direcao,
       sum(min_parado)::bigint               AS m_parado,
       sum(min_extra)::bigint                AS m_extra,
       sum(min_total)::bigint                AS m_total,
       count(DISTINCT data)::int             AS dias
FROM jor_jornadas WHERE data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1 ORDER BY 1
"""

# SÉRIE DIÁRIA. É ela que justifica a biblioteca de gráficos nesta tela: são
# ~600 dias, e ler isso à mão num SVG sem zoom não é leitura, é adivinhação.
_DIARIO = """
SELECT data::text                            AS dia,
       count(*)::int                         AS jornadas,
       count(DISTINCT documento)::int        AS motoristas,
       sum(min_direcao)::bigint              AS m_direcao,
       sum(min_extra)::bigint                AS m_extra
FROM jor_jornadas WHERE data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1 ORDER BY 1
"""

# TAXA POR JORNADA: só os dias que têm OS DOIS LADOS.
#
# Os recursos da API têm limites diferentes — o relatório de produtividade só
# aceita uma consulta a cada 10 minutos, as inconformidades não —, então é
# NORMAL a coleta ter três meses de inconformidade e uma semana de jornada. Uma
# divisão ingênua entre as duas contagens deu 8,55 inconformidades por jornada
# onde o real é 0,85: dez vezes, porque o numerador tinha 90 dias e o
# denominador tinha 8.
#
# É a mesma armadilha do "664 de 836 rastreadores sem sinal": o denominador
# precisa conter só quem podia aparecer no numerador. Aqui isso é literal —
# restringir aos dias em que existe jornada gravada.
# Quantos motoristas DISTINTOS têm ao menos uma inconformidade de tempo.
# Consulta separada de propósito: o ranking tem `LIMIT 40`, e contar as linhas
# devolvidas por ele daria sempre "40" — o KPI diria "40 de 135" tanto para 41
# motoristas quanto para 130. É a armadilha do top-N virando total falso, a
# mesma dos "1.373 veículos" que na verdade eram 1.414.
_MOT_ATINGIDOS = """
SELECT count(DISTINCT documento)::int AS n
FROM jor_inconformidades
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND upper(btrim(tipo)) = ANY(%(tempo)s)
"""

_UNCONF_PAREADO = """
SELECT count(*)::int AS n,
       sum(CASE WHEN upper(btrim(tipo)) = ANY(%(tempo)s) THEN 1 ELSE 0 END)::int
         AS n_tempo,
       count(DISTINCT data)::int AS dias
FROM jor_inconformidades i
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND EXISTS (SELECT 1 FROM jor_jornadas j WHERE j.data = i.data)
"""

# Inconformidade por tipo E por mês: sem o corte temporal não dá para dizer se
# um tipo está piorando ou se só há mais jornada no mês.
_UNCONF_MES = """
SELECT to_char(data,'YYYY-MM') AS mes, tipo, count(*)::int AS n
FROM jor_inconformidades WHERE data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1,2 ORDER BY 1,2
"""

# `n_pareado` existe pela MESMA razão que a taxa geral usa só os dias com os
# dois lados — e foi esquecido aqui na primeira versão, o que só apareceu
# olhando a tela renderizada com dado real: a coluna "por jornada" mostrava
# 3,05 para DIRECAO NOTURNA, dividindo 90 dias de evento por 8 dias de
# jornada. O total (`n`) continua sendo a contagem real do período; quem entra
# na divisão é o subconjunto que tem denominador.
_UNCONF = """
SELECT tipo, count(*)::int AS n, count(DISTINCT documento)::int AS motoristas,
       sum(duracao_min)::bigint AS minutos, avg(duracao_min)::numeric AS media_min,
       sum(CASE WHEN EXISTS (SELECT 1 FROM jor_jornadas j WHERE j.data = i.data)
                THEN 1 ELSE 0 END)::int AS n_pareado
FROM jor_inconformidades i
WHERE data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1 ORDER BY 2 DESC
"""

# Ranking de motorista: as inconformidades DE TEMPO, junto com o número de
# jornadas do mesmo motorista no período. Sem o denominador, o ranking é uma
# lista de quem mais trabalhou — quem roda 90 dias aparece na frente de quem
# roda 12, mesmo tendo taxa menor. A taxa entra ao lado da contagem, e o piso
# de materialidade fica na tela (lição do ranking da DRE por Cliente).
_UNCONF_MOT = """
WITH u AS (
  SELECT documento AS doc, max(nome) AS nome, count(*)::int AS n,
         count(DISTINCT tipo)::int AS tipos, count(DISTINCT data)::int AS dias,
         sum(CASE WHEN upper(btrim(tipo)) = ANY(%(tempo)s) THEN 1 ELSE 0 END)::int
           AS n_tempo
    FROM jor_inconformidades
   WHERE data >= %(de)s::date AND data <= %(ate)s::date
   GROUP BY 1
), j AS (
  SELECT documento AS doc, count(*)::int AS jornadas,
         max(filial) AS filial, max(nome) AS nome,
         sum(min_extra)::bigint AS m_extra
    FROM jor_jornadas
   WHERE data >= %(de)s::date AND data <= %(ate)s::date
   GROUP BY 1
)
-- O nome CAI DE VOLTA para o da jornada: nem toda linha de inconformidade
-- traz `driver_name`, e sem o coalesce a linha aparece sem nome nenhum —
-- uma tabela de motoristas com a coluna do motorista em branco.
SELECT u.doc,
       coalesce(nullif(u.nome,''), nullif(j.nome,''), u.doc) AS nome,
       u.n, u.tipos, u.dias, u.n_tempo,
       coalesce(j.jornadas,0) AS jornadas, coalesce(j.filial,'') AS filial,
       coalesce(j.m_extra,0) AS m_extra
  FROM u LEFT JOIN j ON j.doc = u.doc
 ORDER BY u.n_tempo DESC, u.n DESC LIMIT %(limite)s
"""

_FILIAL = """
SELECT filial, count(*)::int AS jornadas,
       count(DISTINCT documento)::int AS motoristas,
       sum(min_direcao)::bigint AS m_direcao, sum(min_parado)::bigint AS m_parado,
       sum(min_extra)::bigint AS m_extra, sum(min_total)::bigint AS m_total
FROM jor_jornadas WHERE data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1 ORDER BY 7 DESC
"""

_TIPO = """
SELECT tipo, count(*)::int AS jornadas,
       avg(min_direcao)::numeric AS med_direcao,
       avg(min_total)::numeric AS med_total, sum(km)::numeric AS km
FROM jor_jornadas WHERE data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1 ORDER BY 2 DESC
"""

_AUSENCIA = """
SELECT tipo, count(*)::int AS n, count(DISTINCT documento)::int AS motoristas,
       max(inicio)::date AS mais_recente
FROM jor_ausencias WHERE inicio >= %(de)s::date - interval '365 days'
GROUP BY 1 ORDER BY 2 DESC
"""


def _dias_no_recorte(mes: str, de: str, ate: str) -> int:
    """Dias do mês que estão DENTRO da janela pedida.

    Um período de 90 dias começa no meio do mês: o divisor tem de ser o que
    cabe no recorte, senão o primeiro mês aparece com cobertura de 50% sem que
    falte coleta nenhuma.
    """
    ano, m = int(mes[:4]), int(mes[5:7])
    ini = date(ano, m, 1)
    fim = date(ano + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    ini = max(ini, date.fromisoformat(de))
    fim = min(fim, date.fromisoformat(ate))
    return max((fim - ini).days + 1, 0)


def _mensal_com_cobertura(linhas: list, de: str, ate: str) -> list:
    """A série mensal COM OS MESES QUE NÃO EXISTEM.

    É a correção mais importante desta tela. A coleta externa ficou parada de
    15/04 a 27/08/2026, então maio, junho e julho não têm UMA linha — e um
    `GROUP BY mês` simplesmente não os devolve. O gráfico então emenda abril em
    agosto e desenha uma série contínua: quem olha lê queda de operação onde
    houve ausência de coleta.
    
    Meses de cobertura PARCIAL têm o mesmo problema, mais discreto: outubro/25
    tem 10 dias de dado e 1.206 jornadas contra 3.672 de setembro. Parece
    despencar, mas por dia coletado são 121 contra 122 — está plano.
    
    Daí cada mês sair daqui com `dias`, `dias_possiveis`, `cobertura`,
    `sem_coleta` e `jornadas_dia`. A barra hachura quando a cobertura é
    parcial, o mês sem coleta vira falha no eixo, e o número comparável entre
    meses é o POR DIA.
    """
    achadas = {l["mes"]: l for l in linhas}
    d0, d1 = date.fromisoformat(de), date.fromisoformat(ate)
    saida, cur = [], date(d0.year, d0.month, 1)
    while cur <= d1:
        mes = cur.strftime("%Y-%m")
        l = achadas.get(mes)
        possiveis = _dias_no_recorte(mes, de, ate)
        dias = (l or {}).get("dias") or 0
        cob = round(dias / possiveis, 3) if possiveis else None
        saida.append({
            "mes": mes,
            "jornadas": (l or {}).get("jornadas") or 0,
            "motoristas": (l or {}).get("motoristas") or 0,
            "h_direcao": _h((l or {}).get("m_direcao")),
            "h_parado": _h((l or {}).get("m_parado")),
            "h_extra": _h((l or {}).get("m_extra")),
            "h_total": _h((l or {}).get("m_total")),
            "dias": dias, "dias_possiveis": possiveis, "cobertura": cob,
            "sem_coleta": dias == 0,
            # PARCIAL a partir de 90%: mês fechado normal tem dia sem jornada
            # (domingo, feriado) e marcar isso como falha de coleta seria
            # hachurar a série inteira.
            "parcial": bool(dias and cob is not None and cob < 0.9),
            "jornadas_dia": (round(((l or {}).get("jornadas") or 0) / dias, 1)
                             if dias else None),
            "h_extra_media": (round(_h((l or {}).get("m_extra"))
                                    / ((l or {}).get("jornadas") or 1), 2)
                              if (l or {}).get("jornadas") else None),
        })
        cur = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
    return saida


def get_jornada_raster(de: str | None = None, ate: str | None = None,
                       esquema: str | None = None) -> dict:
    """O payload da tela. Nome mantido: o contrato com o front não mudou."""
    p_de, p_ate = _janela(de, ate, esquema)
    par = {"de": p_de, "ate": p_ate, "tempo": list(TIPOS_TEMPO),
           "limite": RANKING_LIMITE}
    q = lambda sql: pglocal.query(sql, par, esquema=_esq(esquema))  # noqa: E731

    comp = (pglocal.um(_COMP, par, esquema=_esq(esquema)) or {})
    mensal, unconf = q(_MENSAL), q(_UNCONF)
    unconf_mot, filiais = q(_UNCONF_MOT), q(_FILIAL)
    tipos, ausencias = q(_TIPO), q(_AUSENCIA)
    diario, unconf_mes = q(_DIARIO), q(_UNCONF_MES)
    par_ = (pglocal.um(_UNCONF_PAREADO, par, esquema=_esq(esquema)) or {})
    mot_at = (pglocal.um(_MOT_ATINGIDOS, par, esquema=_esq(esquema)) or {})

    total, direcao = _h(comp.get("m_total")), _h(comp.get("m_direcao"))
    parado, jornadas = _h(comp.get("m_parado")), comp.get("jornadas") or 0

    partes = [
        {"chave": "direcao", "rotulo": "Direção", "horas": direcao},
        {"chave": "parado", "rotulo": "Parado em jornada", "horas": parado},
        {"chave": "refeicao", "rotulo": "Refeição", "horas": _h(comp.get("m_refeicao"))},
        {"chave": "descanso", "rotulo": "Descanso", "horas": _h(comp.get("m_descanso"))},
    ]
    m_total = float(comp.get("m_total") or 0)
    _min = {"direcao": comp.get("m_direcao"), "parado": comp.get("m_parado"),
            "refeicao": comp.get("m_refeicao"), "descanso": comp.get("m_descanso")}
    for p in partes:
        p["pct"] = (round(100 * float(_min[p["chave"]] or 0) / m_total, 1)
                    if m_total else None)
    soma = sum(p["horas"] for p in partes)
    total_unconf = sum(u["n"] for u in unconf)
    n_tempo = sum(u["n"] for u in unconf if _classe(u["tipo"]) == "tempo")
    # Denominador honesto: só os dias em que existe jornada gravada.
    pareado_n = par_.get("n") or 0
    pareado_tempo = par_.get("n_tempo") or 0
    pareado_dias = par_.get("dias") or 0

    mensal = _mensal_com_cobertura(mensal, p_de, p_ate)
    meses_vazios = [m["mes"] for m in mensal if m["sem_coleta"]]
    tipos_mes = sorted({u["tipo"] for u in unconf_mes})
    por_mes = {m["mes"]: {} for m in mensal}
    for u in unconf_mes:
        por_mes.setdefault(u["mes"], {})[u["tipo"]] = u["n"]

    return {
        "defasagem": defasagem(esquema),
        "kpis": {
            "jornadas": jornadas,
            "motoristas": comp.get("motoristas") or 0,
            "h_total": total, "h_direcao": direcao, "h_parado": parado,
            "h_extra": _h(comp.get("m_extra")),
            "h_falta": _h(comp.get("m_falta")),
            "h_repouso": _h(comp.get("m_repouso")),
            "h_falta_repouso": _h(comp.get("m_falta_repouso")),
            "km": round(float(comp.get("km") or 0)),
            # DOS MINUTOS, não das horas já arredondadas: 300 min sobre
            # 200 min é 1,50, mas 5,0 h sobre 3,3 h dá 1,52. Arredondar antes
            # de dividir move o número na terceira casa e, num indicador que
            # tem 1,00 como limiar de leitura, isso muda o lado da fronteira.
            "razao_parado_direcao": (
                round(float(comp.get("m_parado") or 0)
                      / float(comp["m_direcao"]), 2)
                if comp.get("m_direcao") else None),
            "pct_parado": (round(100 * float(comp.get("m_parado") or 0) / m_total, 1)
                           if m_total else None),
            "pct_direcao": (round(100 * float(comp.get("m_direcao") or 0) / m_total, 1)
                            if m_total else None),
            "unconformidades": total_unconf,
            "unconf_por_jornada": (round(pareado_n / jornadas, 2)
                                   if jornadas else None),
            # O KPI que decide ação: só o que é regra de TEMPO. O total inclui
            # DIRECAO NOTURNA, que é 35% dos eventos e não é violação de nada.
            "unconf_tempo": n_tempo,
            "unconf_tempo_por_jornada": (round(pareado_tempo / jornadas, 2)
                                         if jornadas else None),
            # A tela DIZ quando os dois lados não cobrem a mesma janela: sem
            # isso a taxa parece medir a operação quando mede a coleta.
            "unconf_pareadas": pareado_n,
            "unconf_fora_do_pareamento": total_unconf - pareado_n,
            "dias_pareados": pareado_dias,
            "motoristas_com_unconf_tempo": mot_at.get("n") or 0,
            "ranking_limite": RANKING_LIMITE,
            "pct_noturna": (round(100 * (total_unconf - n_tempo) / total_unconf, 1)
                            if total_unconf else None),
            "dias_com_dado": sum(m["dias"] for m in mensal),
            "dias_no_periodo": sum(m["dias_possiveis"] for m in mensal),
            "meses_sem_coleta": len(meses_vazios),
            # Só as horas das jornadas QUE TÊM km. O total continua ao lado,
            # e a cobertura vai dita no cartão — cobertura ruim de campo é
            # informação, não sujeira para esconder.
            "km_por_h_direcao": (
                round(float(comp.get("km") or 0)
                      / (float(comp["m_direcao_com_km"]) / 60.0), 1)
                if comp.get("m_direcao_com_km") else None),
            "jornadas_com_km": comp.get("n_com_km") or 0,
            "pct_jornadas_com_km": (
                round(100 * (comp.get("n_com_km") or 0) / jornadas, 1)
                if jornadas else None),
        },
        "partes": partes,
        "diferenca": round(total - soma, 1),
        "mensal": mensal,
        "meses_sem_coleta": meses_vazios,
        "diario": [{"dia": d["dia"], "jornadas": d["jornadas"],
                    "motoristas": d["motoristas"],
                    "h_direcao": _h(d["m_direcao"]),
                    "h_extra": _h(d["m_extra"])} for d in diario],
        "unconf_tipos_mes": tipos_mes,
        "unconf_por_mes": [{"mes": m["mes"], "sem_coleta": m["sem_coleta"],
                            "por_tipo": por_mes.get(m["mes"], {})}
                           for m in mensal],
        "unconformidades": [{
            "tipo": u["tipo"], "n": u["n"], "motoristas": u["motoristas"],
            "horas": _h(u["minutos"]),
            "media_min": round(float(u["media_min"] or 0)),
            "pct": round(100 * u["n"] / total_unconf, 1) if total_unconf else None,
            "classe": _classe(u["tipo"]),
            "por_jornada": (round(u["n_pareado"] / jornadas, 2)
                            if jornadas else None),
        } for u in unconf],
        "unconf_motoristas": [{
            "nome": u["nome"], "n": u["n"], "tipos": u["tipos"],
            "dias": u["dias"], "n_tempo": u["n_tempo"],
            "jornadas": u["jornadas"], "filial": u["filial"],
            "h_extra": _h(u["m_extra"]),
            # A TAXA precisa do denominador: sem ele o ranking premia quem
            # rodou mais dias. Quem tem poucas jornadas fica marcado na tela
            # em vez de sumir — registro de baixo volume é atenuado, não
            # escondido.
            "por_jornada": (round(u["n_tempo"] / u["jornadas"], 2)
                            if u["jornadas"] else None),
        } for u in unconf_mot],
        "filiais": [{
            "filial": f["filial"] or "(sem filial)", "jornadas": f["jornadas"],
            "motoristas": f["motoristas"], "h_direcao": _h(f["m_direcao"]),
            "h_parado": _h(f["m_parado"]), "h_extra": _h(f["m_extra"]),
            "h_total": _h(f["m_total"]),
            "pct_parado": (round(100 * float(f["m_parado"] or 0)
                                 / float(f["m_total"]), 1) if f["m_total"] else None),
        } for f in filiais],
        "tipos": [{"tipo": t["tipo"] or "—", "jornadas": t["jornadas"],
                   "med_direcao_min": round(float(t["med_direcao"] or 0)),
                   "med_total_min": round(float(t["med_total"] or 0)),
                   "km": round(float(t["km"] or 0))} for t in tipos],
        "ausencias": [{"tipo": a["tipo"] or "—", "n": a["n"],
                       "motoristas": a["motoristas"],
                       "mais_recente": (a["mais_recente"].isoformat()
                                        if a["mais_recente"] else None)}
                      for a in ausencias],
        "de": p_de, "ate": p_ate,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": ("CÓRTEX · jor_* (banco local) · coleta própria da API "
                  "RasterJOR + carga inicial do histórico"),
    }
