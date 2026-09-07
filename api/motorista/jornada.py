# -*- coding: utf-8 -*-
"""A jornada DELE, como a RasterJOR apurou — e o que ela não responde.

═══════════════════════════════════════════════════════════════════════════
A PERGUNTA QUE ESTE MÓDULO SE RECUSA A RESPONDER
═══════════════════════════════════════════════════════════════════════════
O rascunho do app (`docs/APP_MOTORISTA.md`, fase 1, item 5) pedia "quanto ainda
posso dirigir antes de parar?" — as 5h30 contínuas, o intervalo de 30 min, a
interjornada de 11h, com semáforo. **Isso não se responde com esta fonte, e por
isso não é respondido.**

`jor_jornadas` é uma linha por motorista por DIA, vinda do relatório de
produtividade da RasterJOR, coletada por tarefa agendada. Ela descreve o dia
FECHADO. Um app que somasse as horas de ontem e dissesse "faltam 2h10" estaria
inventando um saldo do dia de hoje a partir de dado que não é de hoje — e o
motorista pararia, ou não pararia, com base nisso. É a pior classe de erro que
este app pode cometer: número velho servido calado numa decisão em tempo real,
onde tela vazia é a resposta honesta (a regra da casa,
`tests/test_leitura_velha.py`).

Quem responde "posso dirigir agora?" é o equipamento da Raster na cabine, que é
a fonte legal e é o que vai para a folha. Este app LÊ e AVISA; não marca, não
corrige, não justifica, e não estima saldo.

**A DEFASAGEM É O PRIMEIRO CAMPO DO PAYLOAD**, não um rodapé. Todos os outros
números descrevem um passado que pode ter dias — e a página é obrigada a dizer
de quando é a leitura antes de mostrar qualquer hora.

═══════════════════════════════════════════════════════════════════════════
O QUE ELE VÊ, ENTÃO
═══════════════════════════════════════════════════════════════════════════
Os 30 dias apurados: dias trabalhados, horas, direção, hora extra, e as
INCONFORMIDADES que a RasterJOR marcou — que são o que de fato vira conversa
com o RH e com o jurídico, e que hoje ele só descobre quando alguém o chama.

**DIREÇÃO NOTURNA NÃO É VIOLAÇÃO**, e é 35% dos eventos. É trabalho noturno,
que é legal e gera adicional. Somá-la às outras faria a contagem dele subir um
terço por causa de um evento que ninguém precisa corrigir — e seria um susto
gratuito na tela de quem trabalha à noite por escala. A separação é a mesma de
`api/jornada/leitura.py` (`TIPOS_TEMPO` × `TIPOS_FORA`), importada de lá e não
recopiada: duas listas iguais em dois arquivos é uma lista que diverge.

**DIA ZERADO NÃO É JORNADA.** 45% das linhas do relatório vêm com todos os
tempos em zero — são folgas de escala (88% dos domingos). Contá-las derrubaria
a jornada média de mais de 12 h para 6h57. Elas saem das contas de tempo e
viram o número ao lado ("dias sem jornada"), que é o que permite falar de folga
sem falar de desempenho.

**JORNADA NÃO FECHADA SAI DAS CONTAS.** Linha com mais de 24 h num dia é
cadastro furado, não trabalho: 2,6% das linhas, carregando 15% de toda a hora
extra do período. Elas saem das somas e são CONTADAS, com aviso — mesma regra
do "|desvio| > 1 ciclo = cadastro furado" da Manutenção Preventiva.

O KM DA JORNADA NÃO SAI DAQUI. `jor_jornadas.km` traz `NULL` e absurdo (155 km
contra 179 h de direção no mesmo motorista, medido em 07/09/2026); o km do app
vem de `produtividade.py`, da `programacaoembarque`, que tem 100% de cobertura.
Dois números de km circulando entre motoristas é briga garantida.

═══════════════════════════════════════════════════════════════════════════
QUEM NÃO TEM JORNADA NÃO VÊ UMA TELA VAZIA
═══════════════════════════════════════════════════════════════════════════
A RasterJOR cobre o motorista EMPREGADO. Dois terços dos motoristas ativos são
agregados e nunca terão linha aqui — `tem_dado` é `false` para eles e a aba
some do app. "Item que não existe para o agregado não aparece vazio", que é
regra escrita do escopo: um app que diz "sem dados" para quem nunca vai ter
dado ensina a pessoa a não confiar no resto.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from .. import pglocal
from ..jornada.leitura import (DEFASAGEM_ALERTA_DIAS, JORNADA_MAX_MIN,
                               TIPOS_FORA, _classe)

log = logging.getLogger("cortex.motorista.jornada")

DIAS = 30


def _esq(esquema: str | None = None) -> str | None:
    from . import ESQUEMA
    return esquema if esquema is not None else ESQUEMA


def _doc(motorista_codigo: str) -> str:
    """O documento da RasterJOR são os dígitos do CPF.

    `mot_vinculos.motorista_codigo` é o `cadastro.codigo` do ERP, que para
    pessoa física É o CPF — mas o ERP grava como veio, e `jor_jornadas.documento`
    guarda só dígito. Medido em 07/09/2026: 78 dos 80 vinculados casam assim.
    """
    return re.sub(r"\D", "", motorista_codigo or "")


#: `min_total > 0` tira a folga; `min_total <= 1440` tira a jornada não
#: fechada. Os dois no WHERE e não em CASE dentro de cada soma: a linha de
#: folga tem `min_total = 0` e some no primeiro filtro, que é o que se quer.
_KPIS_SQL = """
SELECT count(*)::int                          AS dias,
       sum(min_total)::int                    AS m_total,
       sum(min_direcao)::int                  AS m_direcao,
       sum(min_refeicao)::int                 AS m_refeicao,
       sum(min_descanso)::int                 AS m_descanso,
       sum(min_extra)::int                    AS m_extra,
       sum(min_falta_repouso)::int            AS m_falta_repouso,
       max(data)::date                        AS ultima
  FROM jor_jornadas
 WHERE documento = %(doc)s AND data >= current_date - %(dias)s
   AND min_total > 0 AND min_total <= %(teto)s
"""

_FORA_SQL = """
SELECT sum(CASE WHEN min_total = 0 THEN 1 ELSE 0 END)::int          AS sem_jornada,
       sum(CASE WHEN min_total > %(teto)s THEN 1 ELSE 0 END)::int   AS nao_fechadas,
       sum(CASE WHEN min_total > %(teto)s THEN min_total ELSE 0 END)::int AS m_fora
  FROM jor_jornadas
 WHERE documento = %(doc)s AND data >= current_date - %(dias)s
"""

_UNCONF_SQL = """
SELECT tipo, count(*)::int AS n, max(data)::date AS ultima
  FROM jor_inconformidades
 WHERE documento = %(doc)s AND data >= current_date - %(dias)s
 GROUP BY tipo ORDER BY 2 DESC
"""

#: O último dia apurado DELE — não o da casa. A defasagem que importa para o
#: leitor é a da linha dele: a coleta pode estar em dia e ele estar de férias.
_MEU_ULTIMO_SQL = """
SELECT max(data)::date AS ultima,
       (SELECT count(*) FROM jor_jornadas WHERE documento = %(doc)s)::int AS total
  FROM jor_jornadas WHERE documento = %(doc)s
"""


def _h(minutos) -> float:
    return round(float(minutos or 0) / 60.0, 1)


def tem_apuracao(sessao: dict, esquema: str | None = None) -> bool:
    """Existe QUALQUER linha de jornada deste motorista?

    É o que decide se a aba aparece no app (`/api/motorista/eu`). Uma consulta
    de uma linha, no banco local, e o `LIMIT 1` é o ponto: a pergunta é "tem ou
    não tem", e contar 700 dias para responder isso seria pagar caro por um
    booleano no carregamento de um celular em 4G.
    """
    r = pglocal.um("SELECT 1 AS x FROM jor_jornadas WHERE documento = %(d)s LIMIT 1",
                   {"d": _doc(str(sessao["motorista_codigo"]))}, _esq(esquema))
    return bool(r)


def minha(sessao: dict, esquema: str | None = None) -> dict:
    """A jornada de QUEM ESTÁ LOGADO. O documento sai da sessão."""
    esq = _esq(esquema)
    doc = _doc(str(sessao["motorista_codigo"]))
    par = {"doc": doc, "dias": DIAS, "teto": JORNADA_MAX_MIN}
    hoje = date.today()

    meu = pglocal.um(_MEU_ULTIMO_SQL, {"doc": doc}, esq) or {}
    if not (meu.get("total") or 0):
        # SEM DADO NENHUM, NUNCA: é agregado (ou empregado que a RasterJOR não
        # cobre). A aba some no app em vez de mostrar zeros — ver o docstring.
        return {"tem_dado": False,
                "motivo": ("A apuração de jornada da RasterJOR cobre o motorista "
                           "com vínculo de emprego. Não há registro seu por lá."),
                "fonte": "RasterJOR · jor_jornadas"}

    k = pglocal.um(_KPIS_SQL, par, esq) or {}
    f = pglocal.um(_FORA_SQL, par, esq) or {}
    unconf = [dict(r) for r in pglocal.query(_UNCONF_SQL, par, esq)]

    ultima_minha = meu.get("ultima")
    atraso = (hoje - ultima_minha).days if ultima_minha else None

    tempo, fora = [], []
    for u in unconf:
        item = {"tipo": u["tipo"], "n": u["n"],
                "ultima": u["ultima"].isoformat() if u["ultima"] else None}
        (tempo if _classe(u["tipo"]) == "tempo" else fora).append(item)

    dias = int(k.get("dias") or 0)
    return {
        "tem_dado": True,
        # A DEFASAGEM VEM PRIMEIRO, e a página desenha antes de qualquer hora.
        "leitura": {
            "ultimo_dia": ultima_minha.isoformat() if ultima_minha else None,
            "dias_atras": atraso,
            "parada": bool(atraso is not None and atraso > DEFASAGEM_ALERTA_DIAS),
            "corte_dias": DEFASAGEM_ALERTA_DIAS,
        },
        "kpis": {
            "dias_trabalhados": dias,
            "dias_sem_jornada": int(f.get("sem_jornada") or 0),
            "h_total": _h(k.get("m_total")),
            "h_direcao": _h(k.get("m_direcao")),
            "h_refeicao": _h(k.get("m_refeicao")),
            "h_descanso": _h(k.get("m_descanso")),
            "h_extra": _h(k.get("m_extra")),
            "h_falta_repouso": _h(k.get("m_falta_repouso")),
            # Média sobre DIA TRABALHADO. Com a folga no denominador, a jornada
            # média da casa saía 6h57 contra as mais de 12 h reais.
            "h_media_dia": (round(float(k.get("m_total") or 0) / dias / 60.0, 1)
                            if dias else None),
        },
        "nao_fechadas": {
            "dias": int(f.get("nao_fechadas") or 0),
            "h_fora": _h(f.get("m_fora")),
        },
        # As duas listas SEPARADAS, sempre — direção noturna não é violação.
        "inconformidades": tempo,
        "marcacoes": fora,
        "marcacoes_rotulo": "Marcações que não são violação (%s)" % ", ".join(
            t.title() for t in TIPOS_FORA[:2]),
        "janela_dias": DIAS,
        "aviso": ("Esta é a apuração fechada da RasterJOR, por dia. Ela não diz "
                  "quanto você ainda pode dirigir agora — quem diz isso é o "
                  "equipamento na cabine."),
        "fonte": "RasterJOR · jor_jornadas e jor_inconformidades",
    }
