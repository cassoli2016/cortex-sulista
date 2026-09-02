"""O AVA é PostgreSQL 9.3 e o psycopg dobra o `%`.

Sem `FILTER (WHERE …)` (só no 9.4) e sem `percentile_cont` — a mediana de
horas de aprovação CONVIDA a usar os dois, e o erro aponta para o meio do
agregado, não para a versão. E `%` solto dentro de string SQL vira placeholder
do psycopg (`ILIKE '%NF%'` estoura antes de chegar ao banco).
"""
from __future__ import annotations

import re

from api import suprimentos_oc as oc

CONSTANTES = {n: v for n, v in vars(oc).items()
              if isinstance(v, str) and (n.endswith("_SQL") or n.endswith("_CTE") or n.endswith("_BASE"))}


def test_ha_sql_para_conferir():
    assert {"OC_ROWS_SQL", "OC_ABERTA_KPI_SQL", "OC_FILA_SQL", "VG_OC_SQL", "OC_MENSAL_SQL"} <= set(CONSTANTES)


def test_sem_sintaxe_do_9_4_em_diante():
    for nome, sql in CONSTANTES.items():
        s = sql.upper()
        assert "FILTER (" not in s and "FILTER(" not in s, f"{nome}: FILTER (WHERE) não existe no 9.3"
        assert "PERCENTILE_" not in s and "WITHIN GROUP" not in s, f"{nome}: ordered-set aggregate não existe no 9.3"


def test_todo_porcento_e_placeholder_ou_dobrado():
    for nome, sql in CONSTANTES.items():
        resto = re.sub(r"%\(\w+\)s", "", sql).replace("%%", "")
        assert "%" not in resto, f"{nome}: '%' solto vira placeholder do psycopg"


def test_criterios_descartados_nao_voltam():
    """`dtcancelamento` é nulo nas 38 mil OCs e `situacao` mistura estados —
    os dois foram descartados com evidência (docs/LICOES.md)."""
    for nome, sql in CONSTANTES.items():
        assert "dtcancelamento" not in sql, nome
        assert re.search(r"\bsituacao\b", sql) is None, nome


def test_a_regra_de_estado_e_uma_so():
    """Tela, bloco em aberto e Visão Geral usam a MESMA expressão de estado —
    foi por ter três que 'Pendentes de aprovação' contou 965 OCs de 2023."""
    for nome in ("OC_ROWS_SQL", "_OC_ABERTA_BASE", "VG_OC_SQL"):
        assert oc.OC_CAMPOS_ESTADO in CONSTANTES[nome], nome
    assert "dtaprovador IS NULL) AS sem_aprovacao" not in "".join(CONSTANTES.values())
