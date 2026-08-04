"""Curva de escrituração: fração acumulada do movimento por dia relativo."""
from __future__ import annotations

from api.previsao.completude import (DIA_MAX, DISPERSAO_MAX, PISO_COMPLETUDE,
                                     completude_em, dispersao_em, montar_curva)


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


def _rows_bimodais():
    """3 meses escrituram CEDO (100% ja no dia 10), 3 meses so' escrituram
    TARDE (3% no dia 10, o resto so' aparece depois do dia 40) - a mesma forma
    medida ao vivo na receita (fev/mar/mai ~3% em D34 x abr/jun/jul 83-100%).
    A MEDIA das fracoes nao representa nenhum dos dois grupos."""
    rows = []
    for mes in ("2026-02", "2026-04", "2026-06"):  # "cedo"
        rows.append({"mes": mes, "agrupador": "RECEITA X", "dia_rel": 5, "valor_abs": 970.0})
        rows.append({"mes": mes, "agrupador": "RECEITA X", "dia_rel": 10, "valor_abs": 30.0})
    for mes in ("2026-03", "2026-05", "2026-07"):  # "lote tardio"
        rows.append({"mes": mes, "agrupador": "RECEITA X", "dia_rel": 10, "valor_abs": 30.0})
        rows.append({"mes": mes, "agrupador": "RECEITA X", "dia_rel": 42, "valor_abs": 970.0})
    return rows


def test_dispersao_alta_em_curva_bimodal():
    curva = montar_curva(_rows_bimodais(), {"RECEITA X": "RECEITA BRUTA"})
    # media no dia 10: (1.0 + 1.0 + 1.0 + 0.03 + 0.03 + 0.03) / 6 = 0.515 -
    # nao representa NEM os "cedo" (1.0) NEM os "tardios" (0.03).
    assert 0.4 < completude_em(curva, "RECEITA X", "RECEITA BRUTA", 10) < 0.6
    assert dispersao_em(curva, "RECEITA X", "RECEITA BRUTA", 10) > DISPERSAO_MAX
    # cascata ag -> linha funciona igual para a dispersao
    assert dispersao_em(curva, "AG INEXISTENTE", "RECEITA BRUTA", 10) > DISPERSAO_MAX


def test_dispersao_baixa_em_curva_homogenea_regressao():
    """Curva onde todos os meses tem a MESMA forma - dispersao ~0 em todo
    dia, comportamento identico ao de antes desta correcao."""
    rows = []
    for mes in ("2026-05", "2026-06", "2026-07"):
        rows.append({"mes": mes, "agrupador": "CV - COMBUSTIVEL", "dia_rel": 15, "valor_abs": 50.0})
        rows.append({"mes": mes, "agrupador": "CV - COMBUSTIVEL", "dia_rel": 30, "valor_abs": 50.0})
    curva = montar_curva(rows, {"CV - COMBUSTIVEL": "CUSTO VARIAVEL"})
    for d in (5, 15, 20, 30, 40):
        assert dispersao_em(curva, "CV - COMBUSTIVEL", "CUSTO VARIAVEL", d) < 1e-9
    assert dispersao_em({}, "X", None, 10) == 0.0          # sem curva -> neutro
    # ag/linha ausentes caem para o global - mesma serie homogenea -> 0.0 tambem
    assert dispersao_em(curva, "AUSENTE", "AUSENTE", 10) == 0.0
