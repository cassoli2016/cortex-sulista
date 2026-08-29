"""Painel de acompanhamento — o que está atrasado, de quem, e há quanto tempo.

Este módulo não escreve. Ele responde as cinco perguntas que uma reunião de
acompanhamento faz, e responde com o cuidado que o CLAUDE.md cobra de todo
painel da casa:

- **KPI que só pode dar zero por falta de preenchimento diz "não informado".**
  Aqui o caso é o tempo médio de conclusão: sem nenhuma ação concluída ele não
  é "0 dias", é ausência de base. Zero em verde faria parecer velocidade
  perfeita quando o que houve foi nada concluído.

- **Percentual sem piso de materialidade mente.** O ranking de responsáveis não
  abre por "% de conclusão": quem tem uma ação concluída apareceria em primeiro
  com 100%, na frente de quem carrega trinta. Ordena por ATRASADAS (que é a
  pergunta) e marca quem tem menos de 3 ações como base fraca.

- **Total que esconde composição vira composição.** O KPI de abertas traz a
  quebra por farol, porque "84 ações abertas" não diz se são 84 em dia ou 60
  atrasadas.

- **Média que junta populações diferentes.** O tempo de ciclo só considera
  ações CONCLUÍDAS e ignora as canceladas — cancelada tem `concluida_em` nulo
  e entraria como conclusão instantânea se alguém somasse por status.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import pglocal
from .comum import _esq

# Abaixo disto, o desempenho de um responsável é anedota, não série.
MIN_MATERIALIDADE = 3


def _pct(parte: float, total: float):
    return (parte / total) if total else None


def resumo(esquema: str | None = None, ref: date | None = None) -> dict:
    """Os números do topo da tela. Uma consulta só — a tela é a mais aberta do
    módulo e não vale pagar oito idas ao banco para desenhar uma banda."""
    ref = ref or date.today()
    k = pglocal.um("""
    SELECT
      count(*) FILTER (WHERE status IN ('aberta','em_andamento'))::int
        AS abertas,
      count(*) FILTER (WHERE status IN ('aberta','em_andamento')
                         AND prazo < %(ref)s)::int          AS atrasadas,
      count(*) FILTER (WHERE status IN ('aberta','em_andamento')
                         AND prazo >= %(ref)s
                         AND prazo <= %(ref)s + 7)::int     AS vence_7,
      count(*) FILTER (WHERE status = 'concluida')::int     AS concluidas,
      count(*) FILTER (WHERE status = 'cancelada')::int     AS canceladas,
      count(*)::int                                         AS total,
      count(*) FILTER (WHERE status IN ('aberta','em_andamento')
                         AND prioridade IN ('alta','critica')
                         AND prazo < %(ref)s)::int          AS atrasadas_criticas,
      count(*) FILTER (WHERE status = 'concluida'
                         AND concluida_em >= %(mes)s)::int  AS concluidas_mes,
      coalesce(sum(quanto) FILTER (WHERE status IN ('aberta','em_andamento')
                                     AND prazo < %(ref)s), 0)::float8
                                                            AS valor_atrasado,
      count(*) FILTER (WHERE quanto IS NOT NULL)::int       AS com_valor
    FROM ges_acoes
    """, {"ref": ref, "mes": ref.replace(day=1).isoformat()},
        esquema=_esq(esquema)) or {}

    # Tempo de ciclo: só o que CONCLUIU, e a cobertura vai junto. Sem a
    # cobertura, "12 dias" sobre duas ações passa como se fosse a régua da casa.
    ciclo = pglocal.um("""
    SELECT count(*)::int AS n,
           avg(concluida_em::date - criado_em::date)::float8  AS media,
           percentile_cont(0.5) WITHIN GROUP (
             ORDER BY concluida_em::date - criado_em::date)   AS mediana
    FROM ges_acoes
    WHERE status='concluida' AND concluida_em IS NOT NULL AND criado_em <> ''
    """, esquema=_esq(esquema)) or {}

    # No prazo × fora do prazo, entre as concluídas. É o indicador de
    # CONFIABILIDADE do plano, e o único que diz se os prazos são realistas.
    pontual = pglocal.um("""
    SELECT count(*)::int AS n,
           count(*) FILTER (WHERE concluida_em::date <= prazo)::int AS no_prazo
    FROM ges_acoes
    WHERE status='concluida' AND concluida_em IS NOT NULL
    """, esquema=_esq(esquema)) or {}

    abertas = k.get("abertas") or 0
    atras = k.get("atrasadas") or 0
    return {
        **k,
        "em_dia": abertas - atras,
        "pct_atrasadas": _pct(atras, abertas),
        "ciclo_n": ciclo.get("n") or 0,
        # `None` e não `0`: sem base, o número não existe. A tela escreve
        # "não informado", jamais "0 dias" em verde.
        "ciclo_medio": round(ciclo["media"], 1) if ciclo.get("n") else None,
        "ciclo_mediano": (round(float(ciclo["mediana"]), 1)
                          if ciclo.get("n") and ciclo.get("mediana") is not None
                          else None),
        "pontual_n": pontual.get("n") or 0,
        "pct_no_prazo": _pct(pontual.get("no_prazo") or 0, pontual.get("n") or 0),
        "ref": ref.isoformat(),
    }


def por_responsavel(esquema: str | None = None,
                    ref: date | None = None) -> list[dict]:
    """Ordenado por ATRASADAS, não por percentual.

    Ordenar por "% concluído" poria em primeiro quem tem uma ação concluída
    (100%) na frente de quem carrega trinta — o mesmo defeito que abria a DRE
    por Cliente com um cliente de R$ 2,8 mil no topo. `base_fraca` marca quem
    tem menos de três ações, que fica atenuado na tela em vez de escondido.
    """
    ref = ref or date.today()
    linhas = pglocal.query("""
    SELECT coalesce(u.nome, a.responsavel_nome)  AS responsavel,
           a.responsavel_id,
           u.email                               AS email,
           coalesce(u.setor,'')                  AS setor,
           count(*)::int                         AS total,
           count(*) FILTER (WHERE a.status IN ('aberta','em_andamento'))::int
                                                 AS abertas,
           count(*) FILTER (WHERE a.status IN ('aberta','em_andamento')
                              AND a.prazo < %(ref)s)::int AS atrasadas,
           count(*) FILTER (WHERE a.status='concluida')::int AS concluidas,
           max(CASE WHEN a.status IN ('aberta','em_andamento')
                         AND a.prazo < %(ref)s
                    THEN %(ref)s - a.prazo END)::int AS pior_atraso
    FROM ges_acoes a LEFT JOIN usuarios u ON u.id = a.responsavel_id
    GROUP BY 1,2,3,4
    ORDER BY atrasadas DESC, abertas DESC, responsavel
    """, {"ref": ref}, esquema=_esq(esquema))
    for r in linhas:
        r["base_fraca"] = r["total"] < MIN_MATERIALIDADE
        r["pct_concluidas"] = _pct(r["concluidas"], r["total"])
        r["pct_atrasadas"] = _pct(r["atrasadas"], r["abertas"])
    return linhas


def por_area(esquema: str | None = None, ref: date | None = None) -> list[dict]:
    ref = ref or date.today()
    return pglocal.query("""
    SELECT CASE WHEN area = '' THEN '(sem área)' ELSE area END AS area,
           count(*)::int AS total,
           count(*) FILTER (WHERE status IN ('aberta','em_andamento'))::int
             AS abertas,
           count(*) FILTER (WHERE status IN ('aberta','em_andamento')
                              AND prazo < %(ref)s)::int AS atrasadas,
           count(*) FILTER (WHERE status='concluida')::int AS concluidas
    FROM ges_acoes GROUP BY 1 ORDER BY atrasadas DESC, abertas DESC
    """, {"ref": ref}, esquema=_esq(esquema))


def evolucao(esquema: str | None = None, meses: int = 12) -> list[dict]:
    """Criadas × concluídas por mês. É a série que diz se o plano está
    ganhando ou perdendo terreno — mais criadas que concluídas, mês após mês,
    é backlog crescendo, e nenhum KPI pontual mostra isso."""
    return pglocal.query("""
    WITH m AS (
      SELECT to_char(d, 'YYYY-MM') AS mes
      FROM generate_series(date_trunc('month', current_date)
                             - make_interval(months => %(n)s - 1),
                           date_trunc('month', current_date),
                           interval '1 month') d
    )
    SELECT m.mes,
      (SELECT count(*) FROM ges_acoes a
        WHERE substr(a.criado_em,1,7) = m.mes)::int          AS criadas,
      (SELECT count(*) FROM ges_acoes a
        WHERE a.concluida_em IS NOT NULL
          AND substr(a.concluida_em,1,7) = m.mes)::int       AS concluidas
    FROM m ORDER BY m.mes
    """, {"n": int(meses)}, esquema=_esq(esquema))


def paradas(esquema: str | None = None, dias: int = 21,
            limite: int = 20) -> list[dict]:
    """Abertas sem NENHUM andamento há N dias.

    É o alerta que o status não dá: uma ação 'em andamento' há dois meses sem
    ninguém escrever nada não está em andamento, está esquecida — e o status
    diz o contrário com todas as letras.
    """
    from .acoes import _enriquecer
    linhas = pglocal.query("""
    SELECT a.id, a.o_que, a.prazo, a.status, a.prioridade, a.area,
           a.percentual, a.criado_em, a.responsavel_id, a.responsavel_nome,
           coalesce(u.nome, a.responsavel_nome) AS responsavel,
           (SELECT max(n.ts) FROM ges_andamentos n WHERE n.acao_id=a.id)
             AS ultimo_andamento
    FROM ges_acoes a LEFT JOIN usuarios u ON u.id = a.responsavel_id
    WHERE a.status IN ('aberta','em_andamento')
    """, esquema=_esq(esquema))
    saida = [_enriquecer(r) for r in linhas]
    saida = [r for r in saida
             if r.get("parada_dias") is not None and r["parada_dias"] >= dias]
    saida.sort(key=lambda r: -r["parada_dias"])
    return saida[:limite]


def tudo(esquema: str | None = None, ref: date | None = None) -> dict:
    """O payload da tela inteira, numa chamada."""
    from . import acoes as _acoes
    from .comum import AREAS, usuarios_ativos
    ref = ref or date.today()
    return {
        "resumo": resumo(esquema, ref),
        "por_responsavel": por_responsavel(esquema, ref),
        "por_area": por_area(esquema, ref),
        "evolucao": evolucao(esquema),
        "paradas": paradas(esquema),
        "atrasadas": _acoes.listar(esquema, atrasadas=True, limite=50),
        "atrasadas_total": _acoes.contar(esquema, atrasadas=True),
        "proximas": _acoes.listar(esquema, status="abertas", limite=50),
        "usuarios": usuarios_ativos(esquema),
        "areas": list(AREAS),
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": "CÓRTEX · ges_acoes e ges_reunioes (banco local)",
    }


def minhas(usuario_id: int | None, esquema: str | None = None) -> dict:
    """A fila de UMA pessoa. Separada de `tudo` porque a pergunta é outra:
    aqui ninguém quer ranking, quer a própria lista em ordem de urgência."""
    from . import acoes as _acoes
    if not usuario_id:
        return {"acoes": [], "abertas": 0, "atrasadas": 0, "vence_7": 0}
    lista = _acoes.listar(esquema, responsavel_id=usuario_id,
                          status="abertas", limite=200)
    return {
        "acoes": lista,
        "abertas": len(lista),
        "atrasadas": sum(1 for a in lista if a["atrasada"]),
        "vence_7": sum(1 for a in lista if a["vence_em_7"]),
    }
