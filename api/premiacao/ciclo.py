# -*- coding: utf-8 -*-
"""O CICLO da premiação — e por que ele não é o mês do calendário.

Decisão de quem opera (18/09/2026), vinda do modelo de gestão de motoristas:
**o ciclo vai do dia 16 ao dia 15**. Uma ocorrência do dia 16 em diante conta
para o ciclo do mês SEGUINTE, e é assim que a reunião de resultados enxerga o
mês — o fechamento precisa de alguns dias para apurar, e um ciclo que termina
no último dia do mês não dá tempo de conferir nada antes de pagar.

O ciclo continua sendo NOMEADO por uma competência 'AAAA-MM' (o mês em que ele
TERMINA), porque é assim que a casa inteira já fala de período — inclusive a
configuração versionada da premiação (`prem_versoes.vigente_de`) e o snapshot
da Gobrax. O que muda são as DATAS que ele cobre:

    ciclo 2026-09  =  16/08/2026 00:00  ate  15/09/2026 23:59:59

CUIDADO QUE ISSO CRIA, e que este módulo existe para concentrar: a Gobrax
fecha a nota dela por MÊS CIVIL (o `driversOverview` é do dia 1 ao último). Ou
seja, o ciclo 09 usa a nota de um mês que não é o mesmo período das
ocorrências. Isso é uma escolha consciente — a alternativa seria pedir à
Gobrax uma janela por dia, que a API não oferece do mesmo jeito — e a tela
DECLARA de que mês é a nota, em vez de deixar parecer que tudo veio da mesma
janela.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

#: O dia em que o ciclo vira. Dia 16 pertence ao ciclo do mês seguinte.
DIA_VIRADA = 16

#: Quantos ciclos a reputação olha para trás (o modelo usa 6 meses).
JANELA_REPUTACAO = 6


def valido(ciclo: str) -> bool:
    try:
        ano, mes = str(ciclo).split("-")
        return len(ano) == 4 and 1 <= int(mes) <= 12 and ano.isdigit()
    except (ValueError, AttributeError):
        return False


def de_data(quando) -> str:
    """O ciclo ('AAAA-MM') a que uma data pertence.

    Aceita `date`, `datetime` ou texto ISO. Do dia 16 em diante, o ciclo é o do
    mês seguinte — inclusive em dezembro, que vira janeiro do ano que vem.
    """
    if isinstance(quando, str):
        quando = date.fromisoformat(quando[:10])
    if isinstance(quando, datetime):
        quando = quando.date()
    ano, mes = quando.year, quando.month
    if quando.day >= DIA_VIRADA:
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return f"{ano:04d}-{mes:02d}"


def periodo(ciclo: str) -> tuple[date, date]:
    """(primeiro dia, último dia) que o ciclo cobre — o 16 do mês anterior ao 15.

    Devolve datas INCLUSIVAS nas duas pontas: quem consulta o banco usa
    `>= inicio` e `< fim + 1 dia`, e `fim` é o dia 15, que existe em todo mês —
    ao contrário do 31, que é a armadilha equivalente no mês civil.
    """
    if not valido(ciclo):
        raise ValueError(f"Ciclo inválido: {ciclo!r}. Use 'AAAA-MM'.")
    ano, mes = (int(x) for x in ciclo.split("-"))
    fim = date(ano, mes, DIA_VIRADA - 1)
    ini_mes, ini_ano = mes - 1, ano
    if ini_mes < 1:
        ini_mes, ini_ano = 12, ano - 1
    return date(ini_ano, ini_mes, DIA_VIRADA), fim


def limites(ciclo: str) -> tuple[str, str]:
    """As duas datas em ISO, prontas para a consulta: [de, ate_exclusivo)."""
    ini, fim = periodo(ciclo)
    return ini.isoformat(), (fim + timedelta(days=1)).isoformat()


def atual(hoje: date | None = None) -> str:
    return de_data(hoje or date.today())


def somar(ciclo: str, n: int) -> str:
    ano, mes = (int(x) for x in ciclo.split("-"))
    total = ano * 12 + (mes - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def janela(ciclo: str, n: int = JANELA_REPUTACAO) -> list[str]:
    """Os `n` ciclos que terminam neste, do mais antigo para o mais novo."""
    return [somar(ciclo, -i) for i in range(n - 1, -1, -1)]


def mes_da_gobrax(ciclo: str) -> str:
    """De que MÊS CIVIL sai a nota da Gobrax deste ciclo.

    O ciclo 2026-09 cobre 16/08 a 15/09 — e a Gobrax fecha por mês civil. Vale
    o mês que responde pela MAIOR parte do ciclo, que é o mês ANTERIOR ao nome
    do ciclo (16 dias de agosto contra 15 de setembro). A tela diz qual é.
    """
    return somar(ciclo, -1)


def rotulo(ciclo: str) -> str:
    """'16/08 a 15/09 de 2026' — a frase que a tela mostra."""
    ini, fim = periodo(ciclo)
    if ini.year == fim.year:
        return f"{ini:%d/%m} a {fim:%d/%m} de {fim:%Y}"
    return f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
