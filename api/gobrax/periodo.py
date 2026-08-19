"""Primeiro e último instante de uma competência AAAA-MM."""
from __future__ import annotations

import calendar
from datetime import date

from api.gobrax.cliente import periodo_api


def mes_inteiro(competencia: str) -> tuple[str, str]:
    ano, mes = (int(x) for x in competencia.split("-"))
    ultimo = calendar.monthrange(ano, mes)[1]
    return periodo_api(date(ano, mes, 1), date(ano, mes, ultimo))
