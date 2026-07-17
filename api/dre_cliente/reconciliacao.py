"""Reconciliacao por plug contra a DRE oficial (get_dre) como total de controle.

Para cada linha L:  descido[L] + NAO_ALOCADO[L] + VARIACAO_ABSORCAO[L] = oficial[L]
=> NAO_ALOCADO[L] = oficial[L] - descido[L] - variacao[L]  (fecha por construcao).
A metrica de qualidade e a cobertura: 1 - |NAO_ALOCADO| / |oficial|.
"""
from __future__ import annotations

_TOL = 1e-6


def reconciliar(
    descido_por_linha: dict[str, float],
    dre_oficial: dict[str, float],
    variacao: dict[str, float],
) -> dict[str, dict[str, float]]:
    linhas = set(dre_oficial) | set(descido_por_linha) | set(variacao)
    out: dict[str, dict[str, float]] = {}
    for L in linhas:
        descido = descido_por_linha.get(L, 0.0)
        oficial = dre_oficial.get(L, 0.0)
        var = variacao.get(L, 0.0)
        nao_alocado = oficial - descido - var

        if abs(oficial) < 1e-9:
            cobertura = 1.0 if abs(nao_alocado) < 1e-9 else 0.0
        else:
            cobertura = 1.0 - abs(nao_alocado) / abs(oficial)

        # balanco garantido por construcao
        assert abs(descido + nao_alocado + var - oficial) < _TOL, f"balanco falhou em {L}"

        out[L] = {
            "descido": descido,
            "nao_alocado": nao_alocado,
            "variacao_absorcao": var,
            "oficial": oficial,
            "cobertura_pct": cobertura,
        }
    return out
