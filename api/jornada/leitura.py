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

# ── DIA DE FOLGA NÃO É JORNADA ───────────────────────────────────────────────
#
# O relatório de produtividade emite UMA LINHA POR MOTORISTA POR DIA, inclusive
# nos dias em que não houve trabalho: elas vêm com todos os tempos ZERADOS.
# São 15.565 de 34.548 linhas em doze meses — 45%.
#
# A assinatura é inequívoca: 88% dos domingos e 85% dos sábados são zerados,
# contra 24% a 36% nos dias úteis. Só 15% casam com uma ausência registrada,
# então a maioria é folga de escala, não afastamento.
#
# Contá-las como jornada inflava o KPI em 45% E diluía toda média na mesma
# proporção: a "jornada média" saía 6h57 quando a real, sobre os dias
# trabalhados, passa de 12h. O dia sem jornada não sumiu — virou o número ao
# lado, que é o que permite falar de folga e absenteísmo.
TRABALHADA = "min_total > 0"

# ── JORNADA NÃO FECHADA ──────────────────────────────────────────────────────
#
# 485 linhas (2,6% das trabalhadas) têm mais de 24 h de jornada em UM dia, e a
# maior tem 592 h — vinte e quatro dias dentro da linha de um dia. São jornadas
# que ninguém fechou: o sistema acumulou até algo reiniciar.
#
# O peso não é desprezível: elas carregam 10.314 h das 69.498 h de hora extra
# do período, 15% do total. Deixá-las dentro faz a média mentir e o total não
# bater com folha nenhuma; tirá-las em silêncio esconderia um problema de
# cadastro que alguém precisa consertar. Então elas saem de TODAS as contas de
# tempo e são CONTADAS num cartão próprio, com as horas que ficaram de fora.
#
# Mesma regra do alerta impossível da Manutenção Preventiva: desvio maior que
# um ciclo inteiro do próprio indicador é dado furado, não desempenho.
#
# Nas consultas agregadas o filtro entra como `AND min_total <= 1440` no WHERE,
# e não como CASE em cada soma: a linha ZERADA (folga) tem min_total = 0 e
# passa, que é o que se quer — só a não fechada sai. O `_COMP` é a exceção,
# porque é ele que CONTA as não fechadas.
JORNADA_MAX_MIN = 24 * 60

# ── FAIXA FÍSICA DO KM DIÁRIO ────────────────────────────────────────────────
#
# `kilometers_driven` traz leitura impossível no histórico: 10.520.569 km num
# único dia, e mais seis linhas acima de 1.500 km — todas da carga do AVA.
# Caminhão não roda dez milhões de km em 24 h; aquilo é odômetro ou lixo, e
# somado ao total ele empurrava 100 mil km para dentro do KPI.
#
# Mesma lição do Combustível: régua de saneamento não basta, é preciso validar
# a FAIXA FÍSICA. 1.500 km/dia já é folgado — são ~19 h a 80 km/h.
KM_MAX_DIA = 1500
KM_SANO = f"(km > 0 AND km <= {KM_MAX_DIA})"

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
        # A ÚLTIMA passagem DE CADA RECURSO, que é o que diz se a coleta está
        # de pé AGORA. A contagem de falhas em 48 h sozinha não serve para
        # decidir a cor: recusa por limite de taxa é resposta NORMAL do
        # fornecedor (clicar "Coletar agora" duas vezes já produz uma), e
        # pintar a Saúde de vermelho por dois dias por causa disso é a receita
        # para ensinar todo mundo a ignorar o vermelho.
        ult = pglocal.query("""
            SELECT DISTINCT ON (recurso) recurso, ok, ts, mensagem
              FROM jor_carga ORDER BY recurso, id DESC""",
                            esquema=_esq(esquema))
        d["ultima_por_recurso"] = [
            {"recurso": r["recurso"], "ok": bool(r["ok"]),
             "ts": r["ts"], "mensagem": r["mensagem"]} for r in ult]
        d["recursos_falhando"] = [r["recurso"] for r in ult if not r["ok"]]
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
SELECT sum(CASE WHEN min_total > 0 AND min_total <= 1440
                THEN 1 ELSE 0 END)::int      AS jornadas,
       count(*)::int                         AS linhas,
       sum(CASE WHEN min_total = 0 THEN 1 ELSE 0 END)::int AS dias_sem_jornada,
       sum(CASE WHEN min_total > 1440 THEN 1 ELSE 0 END)::int AS nao_fechadas,
       sum(CASE WHEN min_total > 1440 THEN min_extra ELSE 0 END)::bigint
                                             AS m_extra_nao_fechadas,
       max(CASE WHEN min_total > 1440 THEN min_total ELSE 0 END)::int
                                             AS maior_nao_fechada,
       count(DISTINCT documento)::int        AS motoristas,
       sum(CASE WHEN min_total <= 1440 THEN min_direcao ELSE 0 END)::bigint
                                             AS m_direcao,
       sum(CASE WHEN min_total <= 1440 THEN min_parado ELSE 0 END)::bigint
                                             AS m_parado,
       sum(CASE WHEN min_total <= 1440 THEN min_refeicao ELSE 0 END)::bigint
                                             AS m_refeicao,
       sum(CASE WHEN min_total <= 1440 THEN min_descanso ELSE 0 END)::bigint
                                             AS m_descanso,
       sum(CASE WHEN min_total <= 1440 THEN min_repouso ELSE 0 END)::bigint
                                             AS m_repouso,
       sum(CASE WHEN min_total <= 1440 THEN min_extra ELSE 0 END)::bigint
                                             AS m_extra,
       sum(CASE WHEN min_total <= 1440 THEN min_falta ELSE 0 END)::bigint
                                             AS m_falta,
       sum(CASE WHEN min_total <= 1440 THEN min_falta_repouso ELSE 0 END)::bigint
                                             AS m_falta_repouso,
       sum(CASE WHEN min_total <= 1440 THEN min_total ELSE 0 END)::bigint
                                             AS m_total,
       sum(CASE WHEN km > 0 AND km <= 1500 AND min_total <= 1440
                THEN km ELSE 0 END)::numeric AS km,
       sum(CASE WHEN km > 0 AND km <= 1500 AND min_total <= 1440
                THEN 1 ELSE 0 END)::int      AS n_com_km,
       sum(CASE WHEN km > 1500 THEN 1 ELSE 0 END)::int
                                             AS km_fora_da_faixa,
       sum(CASE WHEN km > 0 AND km <= 1500 AND min_total <= 1440
                THEN min_direcao ELSE 0 END)::bigint
                                             AS m_direcao_com_km
FROM jor_jornadas WHERE data >= %(de)s::date AND data <= %(ate)s::date
"""

_MENSAL = """
SELECT to_char(data,'YYYY-MM')               AS mes,
       sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END)::int AS jornadas,
       sum(CASE WHEN min_total = 0 THEN 1 ELSE 0 END)::int AS folgas,
       count(DISTINCT documento)::int        AS motoristas,
       sum(min_direcao)::bigint              AS m_direcao,
       sum(min_parado)::bigint               AS m_parado,
       sum(min_extra)::bigint                AS m_extra,
       sum(min_total)::bigint                AS m_total,
       count(DISTINCT data)::int             AS dias
FROM jor_jornadas
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND min_total <= 1440
GROUP BY 1 ORDER BY 1
"""

# SÉRIE DIÁRIA. É ela que justifica a biblioteca de gráficos nesta tela: são
# ~600 dias, e ler isso à mão num SVG sem zoom não é leitura, é adivinhação.
_DIARIO = """
SELECT data::text                            AS dia,
       sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END)::int AS jornadas,
       count(DISTINCT CASE WHEN min_total > 0 THEN documento END)::int
                                             AS motoristas,
       sum(min_direcao)::bigint              AS m_direcao,
       sum(min_extra)::bigint                AS m_extra
FROM jor_jornadas
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND min_total <= 1440
GROUP BY 1 HAVING sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END) > 0
ORDER BY 1
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
  AND EXISTS (SELECT 1 FROM jor_jornadas j
              WHERE j.data = i.data AND j.min_total > 0)
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
       sum(CASE WHEN EXISTS (SELECT 1 FROM jor_jornadas j
                              WHERE j.data = i.data AND j.min_total > 0)
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
  SELECT documento AS doc,
         sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END)::int AS jornadas,
         max(filial) AS filial, max(nome) AS nome,
         sum(min_extra)::bigint AS m_extra
    FROM jor_jornadas
   WHERE data >= %(de)s::date AND data <= %(ate)s::date
     AND min_total <= 1440
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
SELECT filial, sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END)::int AS jornadas,
       count(DISTINCT documento)::int AS motoristas,
       sum(min_direcao)::bigint AS m_direcao, sum(min_parado)::bigint AS m_parado,
       sum(min_extra)::bigint AS m_extra, sum(min_total)::bigint AS m_total
FROM jor_jornadas
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND min_total <= 1440
GROUP BY 1 ORDER BY 7 DESC
"""

_TIPO = """
SELECT tipo, count(*)::int AS jornadas,
       avg(min_direcao)::numeric AS med_direcao,
       avg(min_total)::numeric AS med_total,
       sum(CASE WHEN km > 0 AND km <= 1500 THEN km ELSE 0 END)::numeric AS km
FROM jor_jornadas
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND min_total > 0 AND min_total <= 1440
GROUP BY 1 ORDER BY 2 DESC
"""

# ── POR ESCALA ───────────────────────────────────────────────────────────────
#
# `work_schedule_name` vem preenchido em 100% das jornadas, e a dispersão é o
# achado: a hora extra média vai de 23 min numa escala a 293 min noutra — quase
# cinco horas de diferença entre turnos da mesma empresa. Isso é alavanca de
# gestão, não característica do motorista: quem define a escala define quanta
# hora extra vai pagar.
_ESCALA = """
SELECT escala,
       sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END)::int AS jornadas,
       count(DISTINCT documento)::int        AS motoristas,
       max(filial)                           AS filial,
       sum(min_extra)::bigint                AS m_extra,
       sum(min_total)::bigint                AS m_total,
       sum(min_direcao)::bigint              AS m_direcao,
       sum(min_falta_repouso)::bigint        AS m_falta_repouso
FROM jor_jornadas
WHERE data >= %(de)s::date AND data <= %(ate)s::date AND escala <> ''
  AND min_total <= 1440
GROUP BY 1 HAVING sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END) > 0
ORDER BY 5 DESC
"""

# ── AUSÊNCIAS ────────────────────────────────────────────────────────────────
#
# `jor_ausencias` tem início E fim em 100% das linhas, então dá para medir
# DURAÇÃO — que é o que separa uma folga (1,1 dia) de férias (19,6 dias) e de
# um afastamento médico (12,2). O tipo sozinho não diz o peso.
# Dos dias SEM jornada, quantos têm uma ausência registrada. É a decomposição
# que desarma o número grande: 15.565 dias sem jornada assusta até se ver que
# 85% são FOLGA DE ESCALA e só 15% são ausência (atestado, férias, falta).
_SEM_JORNADA_AUSENCIA = """
SELECT count(*)::int AS n
FROM jor_jornadas j
WHERE j.data >= %(de)s::date AND j.data <= %(ate)s::date AND j.min_total = 0
  AND EXISTS (SELECT 1 FROM jor_ausencias a
               WHERE a.documento = j.documento
                 AND j.data BETWEEN a.inicio::date AND a.fim::date)
"""

_AUSENCIA_RESUMO = """
SELECT count(*)::int AS n,
       count(DISTINCT documento)::int AS motoristas,
       sum(GREATEST((fim::date - inicio::date) + 1, 1))::int AS dias
FROM jor_ausencias
WHERE inicio::date <= %(ate)s::date AND fim::date >= %(de)s::date
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
            "folgas": (l or {}).get("folgas") or 0,
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


# Consulta enxuta para o painel de ALERTAS, que roda a cada carga da Visao
# Geral e nao pode pagar as nove consultas do payload da tela.
#
# `DIRECAO ININTERRUPTA` e o nome que a RasterJOR da para a violacao dos 5h30
# de direcao continua da Lei 13.103 — a MESMA regra que o alerta media pelo
# ERP antes. A troca de fonte importa: a apuracao do fornecedor de jornada
# nomeia a inconformidade, enquanto a do ERP a derivava dos macros.
_ALERTA = """
SELECT count(*)::int AS n, count(DISTINCT documento)::int AS motoristas,
       max(data)::date AS ultimo
FROM jor_inconformidades
WHERE tipo = 'DIRECAO ININTERRUPTA'
  AND data >= date_trunc('month', current_date)::date
"""


def alerta_direcao_continua(esquema: str | None = None) -> dict:
    """Violações de direção contínua no mês corrente, para o painel de alertas.

    Devolve `{}` quando não há o que alertar — inclusive quando a tabela ainda
    não existe nesta instalação, porque um alerta que estoura é pior que um
    alerta ausente: ele derruba a lista inteira, com os outros dez avisos
    dentro.
    """
    try:
        r = pglocal.um(_ALERTA, esquema=_esq(esquema)) or {}
    except Exception:  # noqa: BLE001
        return {}
    if not (r.get("n") or 0):
        return {}
    return {"n": r["n"], "motoristas": r.get("motoristas") or 0,
            "ultimo": r["ultimo"].isoformat() if r.get("ultimo") else None}


# ══════════════════════════════════════════════════════════════════════════
#  FICHA DO MOTORISTA
# ══════════════════════════════════════════════════════════════════════════
#
# Substitui a ficha que lia a apuração do ERP. Três decisões que vieram das
# lições das outras fichas desta casa:
#
# 1. A JANELA É A MESMA DA TELA PRINCIPAL. Uma ficha com janela própria fixa
#    gera contradição entre telas — foi o que aconteceu na Consulta de Veículo,
#    onde 30 dias fixos davam 9% de retorno vazio numa placa que a Análise de
#    KM mostrava com 33,5%, e os dois estavam certos. Aqui a ficha recebe `de`
#    e `ate` e os ecoa no rótulo.
# 2. TODO NÚMERO VEM COM A REFERÊNCIA. Uma ficha isolada não diz se 3h de hora
#    extra por jornada é muito: o que responde é a média da FILIAL e a da
#    frota, lado a lado.
# 3. O CPF NÃO APARECE INTEIRO. Ele é a chave da consulta, mas identificar o
#    motorista na tela é trabalho do nome; mostrar o documento completo é PII
#    sem função. Vai mascarado.

_FICHA_CAB = """
SELECT m.documento, m.nome, m.filial, m.escala, m.cargo, m.cidade_base,
       m.ativo, m.admissao
FROM jor_motoristas m WHERE m.documento = %(doc)s
"""

# Se o motorista não estiver no cadastro (a coleta de `drivers` traz os ATIVOS,
# e um desligado tem jornada mas pode não ter cadastro), o cabeçalho é montado
# a partir da própria jornada. Ficha que recusa a abrir por falta de cadastro
# esconderia justamente o histórico de quem saiu.
_FICHA_CAB_JOR = """
SELECT max(nome) AS nome, max(filial) AS filial, max(escala) AS escala
FROM jor_jornadas WHERE documento = %(doc)s
"""

_FICHA_KPIS = """
SELECT sum(CASE WHEN min_total > 0 AND min_total <= 1440
                THEN 1 ELSE 0 END)::int      AS jornadas,
       count(*)::int                         AS linhas,
       sum(CASE WHEN min_total = 0 THEN 1 ELSE 0 END)::int AS dias_sem_jornada,
       sum(CASE WHEN min_total > 1440 THEN 1 ELSE 0 END)::int AS nao_fechadas,
       count(DISTINCT CASE WHEN min_total > 0 AND min_total <= 1440
                           THEN filial END)::int AS filiais,
       max(CASE WHEN min_total > 0 THEN filial END) AS filial,
       -- A escala do cabeçalho é a MAIS FREQUENTE, não a última: o nome
       -- carrega o tipo do dia, então `max()` costumava devolver a variante
       -- alfabeticamente maior (FÉRIAS, Feriado) e a ficha abria dizendo que
       -- a escala do motorista é "férias".
       (SELECT j2.escala FROM jor_jornadas j2
         WHERE j2.documento = %(doc)s AND j2.min_total > 0
           AND j2.data >= %(de)s::date AND j2.data <= %(ate)s::date
         GROUP BY j2.escala ORDER BY count(*) DESC, j2.escala LIMIT 1) AS escala,
       min(data)::date                       AS primeira,
       max(CASE WHEN min_total > 0 THEN data END)::date AS ultima,
       sum(CASE WHEN min_total <= 1440 THEN min_total ELSE 0 END)::bigint AS m_total,
       sum(CASE WHEN min_total <= 1440 THEN min_direcao ELSE 0 END)::bigint AS m_direcao,
       sum(CASE WHEN min_total <= 1440 THEN min_parado ELSE 0 END)::bigint AS m_parado,
       sum(CASE WHEN min_total <= 1440 THEN min_extra ELSE 0 END)::bigint AS m_extra,
       sum(CASE WHEN min_total <= 1440 THEN min_falta_repouso ELSE 0 END)::bigint
                                             AS m_falta_repouso,
       sum(CASE WHEN km > 0 AND km <= 1500 AND min_total <= 1440
                THEN km ELSE 0 END)::numeric AS km
FROM jor_jornadas
WHERE documento = %(doc)s AND data >= %(de)s::date AND data <= %(ate)s::date
"""

# A REFERÊNCIA: a média por jornada da filial do motorista e a da frota. Sem
# ela a ficha é um número solto, e número solto não decide nada.
_FICHA_REF = """
SELECT
  sum(CASE WHEN min_total > 0 THEN 1 ELSE 0 END)::int AS jornadas,
  sum(min_extra)::bigint  AS m_extra,
  sum(min_total)::bigint  AS m_total,
  sum(min_direcao)::bigint AS m_direcao
FROM jor_jornadas
WHERE data >= %(de)s::date AND data <= %(ate)s::date
  AND min_total <= 1440
  AND (%(filial)s = '' OR filial = %(filial)s)
"""

_FICHA_DIA = """
SELECT data::text AS dia, min_total, min_direcao, min_parado, min_extra,
       min_falta_repouso, km, escala, tipo,
       to_char(inicio,'HH24:MI') AS h_inicio, to_char(fim,'HH24:MI') AS h_fim
FROM jor_jornadas
WHERE documento = %(doc)s AND data >= %(de)s::date AND data <= %(ate)s::date
  AND min_total > 0 AND min_total <= 1440
ORDER BY data
"""

_FICHA_UNCONF = """
SELECT tipo, count(*)::int AS n, count(DISTINCT data)::int AS dias,
       max(data)::date AS ultima,
       sum(CASE WHEN duracao_min > 0 THEN duracao_min ELSE 0 END)::bigint AS minutos
FROM jor_inconformidades
WHERE documento = %(doc)s AND data >= %(de)s::date AND data <= %(ate)s::date
GROUP BY 1 ORDER BY 2 DESC
"""

_FICHA_AUS = """
SELECT tipo, descricao, inicio::date AS de, fim::date AS ate,
       GREATEST((fim::date - inicio::date) + 1, 1)::int AS dias
FROM jor_ausencias
WHERE documento = %(doc)s
  AND inicio::date <= %(ate)s::date AND fim::date >= %(de)s::date - 365
ORDER BY inicio DESC LIMIT 40
"""


def mascara_documento(doc: str) -> str:
    """CPF na tela vira `***.***.891-**`.

    O documento é a CHAVE da consulta e precisa trafegar; o que não precisa é
    aparecer inteiro para quem abre a ficha. Quem identifica o motorista é o
    nome — o CPF completo ali seria PII sem função.
    """
    d = "".join(ch for ch in (doc or "") if ch.isdigit())
    if len(d) != 11:
        return doc or "—"
    return f"***.***.{d[6:9]}-**"


def ficha_motorista(documento: str, de: str | None = None,
                    ate: str | None = None, esquema: str | None = None) -> dict:
    """Tudo o que a RasterJOR sabe sobre um motorista na janela."""
    doc = "".join(ch for ch in (documento or "") if ch.isdigit())
    if not doc:
        return {"erro": "Informe o motorista."}
    p_de, p_ate = _janela(de, ate, esquema)
    par = {"doc": doc, "de": p_de, "ate": p_ate}
    esq = _esq(esquema)
    q = lambda sql, pr=par: pglocal.query(sql, pr, esquema=esq)  # noqa: E731

    cab = pglocal.um(_FICHA_CAB, {"doc": doc}, esquema=esq) or {}
    k = pglocal.um(_FICHA_KPIS, par, esquema=esq) or {}
    if not cab.get("nome"):
        # sem cadastro: monta do que a jornada guardou
        j = pglocal.um(_FICHA_CAB_JOR, {"doc": doc}, esquema=esq) or {}
        cab = {"documento": doc, "nome": j.get("nome") or "", "ativo": None,
               "filial": j.get("filial") or "", "escala": j.get("escala") or "",
               "cargo": "", "cidade_base": "", "admissao": None,
               "sem_cadastro": True}
    if not (k.get("linhas") or 0) and not cab.get("nome"):
        return {"erro": "Motorista não encontrado na apuração da RasterJOR."}

    filial = k.get("filial") or cab.get("filial") or ""
    ref_fil = pglocal.um(_FICHA_REF, {**par, "filial": filial},
                         esquema=esq) or {}
    ref_frota = pglocal.um(_FICHA_REF, {**par, "filial": ""},
                           esquema=esq) or {}

    def _med(r, campo):
        n = r.get("jornadas") or 0
        return round(float(r.get(campo) or 0) / n) if n else None

    jor = k.get("jornadas") or 0
    dias = q(_FICHA_DIA)
    unconf = q(_FICHA_UNCONF)
    n_tempo = sum(u["n"] for u in unconf if _classe(u["tipo"]) == "tempo")

    return {
        "documento": doc,
        "documento_fmt": mascara_documento(doc),
        "nome": cab.get("nome") or "—",
        "filial": filial,
        "escala": k.get("escala") or cab.get("escala") or "",
        "cargo": cab.get("cargo") or "",
        "cidade_base": cab.get("cidade_base") or "",
        "ativo": cab.get("ativo"),
        "sem_cadastro": bool(cab.get("sem_cadastro")),
        "admissao": (cab["admissao"].isoformat() if cab.get("admissao") else None),
        "filiais": k.get("filiais") or 0,
        "primeira": (k["primeira"].isoformat() if k.get("primeira") else None),
        "ultima": (k["ultima"].isoformat() if k.get("ultima") else None),
        "kpis": {
            "jornadas": jor,
            "linhas": k.get("linhas") or 0,
            "dias_sem_jornada": k.get("dias_sem_jornada") or 0,
            "nao_fechadas": k.get("nao_fechadas") or 0,
            "h_total": _h(k.get("m_total")),
            "h_direcao": _h(k.get("m_direcao")),
            "h_parado": _h(k.get("m_parado")),
            "h_extra": _h(k.get("m_extra")),
            "h_falta_repouso": _h(k.get("m_falta_repouso")),
            "km": round(float(k.get("km") or 0)),
            "min_total_medio": (round(float(k.get("m_total") or 0) / jor)
                                if jor else None),
            "min_extra_medio": (round(float(k.get("m_extra") or 0) / jor)
                                if jor else None),
            "unconf": sum(u["n"] for u in unconf),
            "unconf_tempo": n_tempo,
            "unconf_tempo_por_jornada": (round(n_tempo / jor, 2) if jor else None),
        },
        # A referência é o que transforma o número da ficha em leitura.
        "referencia": {
            "filial": filial,
            "filial_min_extra": _med(ref_fil, "m_extra"),
            "filial_min_total": _med(ref_fil, "m_total"),
            "filial_jornadas": ref_fil.get("jornadas") or 0,
            "frota_min_extra": _med(ref_frota, "m_extra"),
            "frota_min_total": _med(ref_frota, "m_total"),
            "frota_jornadas": ref_frota.get("jornadas") or 0,
        },
        "dias": [{
            "dia": r["dia"], "min_total": r["min_total"],
            "min_direcao": r["min_direcao"], "min_parado": r["min_parado"],
            "min_extra": r["min_extra"],
            "min_falta_repouso": r["min_falta_repouso"],
            "km": (round(float(r["km"])) if r["km"] is not None else None),
            "escala": r["escala"] or "", "tipo": r["tipo"] or "",
            "inicio": r["h_inicio"], "fim": r["h_fim"],
        } for r in dias],
        "unconformidades": [{
            "tipo": u["tipo"], "n": u["n"], "dias": u["dias"],
            "classe": _classe(u["tipo"]),
            "horas": _h(u["minutos"]),
            "ultima": (u["ultima"].isoformat() if u.get("ultima") else None),
        } for u in unconf],
        "ausencias": [{
            "tipo": a["tipo"] or "—", "descricao": a["descricao"] or "",
            "de": a["de"].isoformat() if a["de"] else None,
            "ate": a["ate"].isoformat() if a["ate"] else None,
            "dias": a["dias"],
        } for a in q(_FICHA_AUS)],
        "de": p_de, "ate": p_ate,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "CÓRTEX · jor_* (banco local) · apuração da RasterJOR",
    }


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
    escalas = q(_ESCALA)
    aus_r = (pglocal.um(_AUSENCIA_RESUMO, par, esquema=_esq(esquema)) or {})
    sj_aus = (pglocal.um(_SEM_JORNADA_AUSENCIA, par,
                         esquema=_esq(esquema)) or {}).get("n") or 0
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
            # JORNADAS TRABALHADAS, não linhas do relatório: o dia de
            # folga vem como linha zerada e inflava isto em 45%.
            "jornadas": jornadas,
            "linhas_relatorio": comp.get("linhas") or 0,
            "dias_sem_jornada": comp.get("dias_sem_jornada") or 0,
            "pct_dias_sem_jornada": (
                round(100 * (comp.get("dias_sem_jornada") or 0)
                      / comp["linhas"], 1) if comp.get("linhas") else None),
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
            "km_fora_da_faixa": comp.get("km_fora_da_faixa") or 0,
            "jornadas_nao_fechadas": comp.get("nao_fechadas") or 0,
            "h_extra_nao_fechadas": _h(comp.get("m_extra_nao_fechadas")),
            "maior_nao_fechada_h": round(
                float(comp.get("maior_nao_fechada") or 0) / 60.0),
            "ausencias": aus_r.get("n") or 0,
            "ausencias_motoristas": aus_r.get("motoristas") or 0,
            "ausencias_dias": aus_r.get("dias") or 0,
            "sem_jornada_com_ausencia": sj_aus,
            "sem_jornada_folga": (comp.get("dias_sem_jornada") or 0) - sj_aus,
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
            # O documento vai para a tela porque é a chave da ficha. Ele NÃO
            # entra na URL: a tela o guarda em memória e navega para #jornf,
            # que mantém o CPF fora do histórico do navegador.
            "documento": u["doc"],
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
        "escalas": [{
            "escala": e["escala"], "jornadas": e["jornadas"],
            "motoristas": e["motoristas"], "filial": e["filial"] or "",
            "h_extra": _h(e["m_extra"]), "h_total": _h(e["m_total"]),
            "h_direcao": _h(e["m_direcao"]),
            "h_falta_repouso": _h(e["m_falta_repouso"]),
            # A MÉDIA POR JORNADA é o número comparável entre escalas: o total
            # só diz qual escala tem mais gente.
            "min_extra_medio": (round(float(e["m_extra"]) / e["jornadas"])
                                if e["jornadas"] else None),
            "min_total_medio": (round(float(e["m_total"]) / e["jornadas"])
                                if e["jornadas"] else None),
        } for e in escalas],
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
