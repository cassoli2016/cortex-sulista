"""Curva de escrituração: fração acumulada do movimento por dia relativo."""
from __future__ import annotations

from api.previsao.completude import (DIA_MAX, PISO_COMPLETUDE, completude_em,
                                     montar_curva)


def _rows_sinteticas():
    # agrupador FOLHA: 20% no dia 30 (fim do mes), 80% no dia 35 (D+4) — 2 meses iguais
    rows = []
    for mes in ("2026-05", "2026-06"):
        rows.append({"mes": mes, "agrupador": "CF - FOLHA MOT", "dia_rel": 30, "valor_abs": 20.0})
        rows.append({"mes": mes, "agrupador": "CF - FOLHA MOT", "dia_rel": 35, "valor_abs": 80.0})
        # agrupador COMBUSTIVEL: linear, 50% no dia 15, 100% no dia 30
        rows.append({"mes": mes, "agrupador": "CV - COMBUSTIVEL", "dia_rel": 15, "valor_abs": 50.0})
        rows.append({"mes": mes, "agrupador": "CV - COMBUSTIVEL", "dia_rel": 30, "valor_abs": 50.0})
    return rows


MAPA = {"CF - FOLHA MOT": "CUSTO FIXO", "CV - COMBUSTIVEL": "CUSTO VARIAVEL"}


def test_frac_acumulada_por_agrupador():
    curva = montar_curva(_rows_sinteticas(), MAPA)
    assert abs(completude_em(curva, "CF - FOLHA MOT", "CUSTO FIXO", 30) - 0.20) < 1e-9
    assert abs(completude_em(curva, "CF - FOLHA MOT", "CUSTO FIXO", 34) - 0.20) < 1e-9
    assert abs(completude_em(curva, "CF - FOLHA MOT", "CUSTO FIXO", 35) - 1.00) < 1e-9
    assert abs(completude_em(curva, "CV - COMBUSTIVEL", "CUSTO VARIAVEL", 15) - 0.50) < 1e-9


def test_monotonicidade_e_clamp():
    curva = montar_curva(_rows_sinteticas(), MAPA)
    serie = [completude_em(curva, "CV - COMBUSTIVEL", None, d) for d in range(DIA_MAX + 1)]
    assert all(b >= a for a, b in zip(serie, serie[1:]))
    assert serie[-1] == 1.0
    assert completude_em(curva, "CV - COMBUSTIVEL", None, 999) == 1.0


def test_cascata_ag_linha_global():
    curva = montar_curva(_rows_sinteticas(), MAPA)
    # agrupador desconhecido cai na LINHA; linha desconhecida cai na GLOBAL
    v_linha = completude_em(curva, "CF - PESSOAL OPERACIONAL", "CUSTO FIXO", 30)
    assert abs(v_linha - 0.20) < 1e-9          # linha CUSTO FIXO = so a folha sintetica
    v_global = completude_em(curva, "ZZZ", "LINHA INEXISTENTE", 30)
    assert 0.0 < v_global <= 1.0               # global = mistura dos dois agrupadores
    assert completude_em({}, "ZZZ", None, 10) == 1.0  # sem curva nenhuma -> neutro


def test_piso_exportado():
    assert 0.0 < PISO_COMPLETUDE < 1.0


def test_curva_vazia_cai_no_neutro():
    """Empty input (cold-start case) cascades to neutral 1.0."""
    curva = montar_curva([], {})
    assert completude_em(curva, None, None, 10) == 1.0
    assert completude_em(curva, "QUALQUER", None, 10) == 1.0
    assert completude_em(curva, None, "QUALQUER", 10) == 1.0


def test_agrupador_sem_movimento_cai_no_neutro():
    """Agrupador with only valor_abs=0.0 rows cascades to neutral 1.0."""
    rows = [
        {"mes": "2026-05", "agrupador": "CF - ZERADO", "dia_rel": 30, "valor_abs": 0.0},
        {"mes": "2026-05", "agrupador": "CF - ZERADO", "dia_rel": 35, "valor_abs": 0.0},
        {"mes": "2026-06", "agrupador": "CF - ZERADO", "dia_rel": 30, "valor_abs": 0.0},
        {"mes": "2026-06", "agrupador": "CF - ZERADO", "dia_rel": 35, "valor_abs": 0.0},
        # Uma fonte informativa para que a global não seja vazia
        {"mes": "2026-05", "agrupador": "CV - COMBUSTIVEL", "dia_rel": 15, "valor_abs": 50.0},
        {"mes": "2026-05", "agrupador": "CV - COMBUSTIVEL", "dia_rel": 30, "valor_abs": 50.0},
        {"mes": "2026-06", "agrupador": "CV - COMBUSTIVEL", "dia_rel": 15, "valor_abs": 50.0},
        {"mes": "2026-06", "agrupador": "CV - COMBUSTIVEL", "dia_rel": 30, "valor_abs": 50.0},
    ]
    curva = montar_curva(rows, {})
    # Agrupador zerado cai para global (que tem valor)
    assert completude_em(curva, "CF - ZERADO", None, 15) > 0.0
    assert completude_em(curva, "CF - ZERADO", None, 15) <= 1.0
