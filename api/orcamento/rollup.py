"""Rollup conta -> agrupador -> linha da cascata da DRE.

Reusa `_dre_aloca` de api/queries.py, que é exatamente o mapeamento que a DRE
Gerencial já usa (DRE_MODELO). Aplicar aqui os mesmos ajustes contábeis locais
garante que reclassificar uma conta mova orçado e realizado juntos — sem isso as
duas telas divergiriam e ninguém saberia qual está certa.
"""
from __future__ import annotations

from api.queries import _dre_aloca


def _agrupador(conta: str, agrupador_por_conta: dict[str, str],
               ajustes: dict) -> str | None:
    aj = ajustes.get(conta)
    if aj and aj.get("agrupador"):
        return aj["agrupador"]
    return agrupador_por_conta.get(conta)


def linha_da_conta(conta: str, agrupador_por_conta: dict[str, str],
                   ajustes: dict) -> str | None:
    """Rótulo da linha do DRE_MODELO onde a conta soma, ou None se não classificada."""
    ag = _agrupador(conta, agrupador_por_conta, ajustes)
    if not ag:
        return None
    return _dre_aloca(ag)


def mapa_conta_linha(agrupador_por_conta: dict[str, str],
                     ajustes: dict) -> dict[str, str | None]:
    contas = set(agrupador_por_conta) | set(ajustes)
    return {c: linha_da_conta(c, agrupador_por_conta, ajustes) for c in sorted(contas)}


def contas_sem_agrupador(contas: list[str], agrupador_por_conta: dict[str, str],
                         ajustes: dict) -> list[str]:
    """Contas que não somam em linha nenhuma — precisam ser classificadas antes."""
    return [c for c in contas if not _agrupador(c, agrupador_por_conta, ajustes)]
