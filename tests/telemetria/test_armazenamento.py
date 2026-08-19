"""Cache das coletas lentas de telemetria."""
from __future__ import annotations

import pytest

from api.gobrax import armazenamento as arm


@pytest.fixture
def base(tmp_path):
    p = tmp_path / "telemetria.db"
    arm.init_db(p)
    return p


def _reg(placa="AAA1A11", **kw):
    return {"placa": placa, "km": 1000.0, **kw}


def test_grava_e_le_por_colecao_e_competencia(base):
    arm.gravar("estatisticas", "2026-07", [_reg(), _reg("BBB2B22")], base)
    lido = arm.ler("estatisticas", "2026-07", base)
    assert {r["placa"] for r in lido} == {"AAA1A11", "BBB2B22"}


def test_colecoes_diferentes_nao_se_misturam(base):
    arm.gravar("estatisticas", "2026-07", [_reg("AAA1A11")], base)
    arm.gravar("odometro", "2026-07", [_reg("ZZZ9Z99")], base)
    assert [r["placa"] for r in arm.ler("odometro", "2026-07", base)] == ["ZZZ9Z99"]


def test_competencias_diferentes_convivem(base):
    arm.gravar("estatisticas", "2026-06", [_reg("AAA1A11")], base)
    arm.gravar("estatisticas", "2026-07", [_reg("BBB2B22")], base)
    assert len(arm.ler("estatisticas", "2026-06", base)) == 1
    assert len(arm.ler("estatisticas", "2026-07", base)) == 1


def test_recoleta_substitui_a_competencia(base):
    arm.gravar("estatisticas", "2026-07", [_reg("AAA1A11"), _reg("BBB2B22")], base)
    arm.gravar("estatisticas", "2026-07", [_reg("CCC3C33")], base)
    assert [r["placa"] for r in arm.ler("estatisticas", "2026-07", base)] == ["CCC3C33"]


def test_coleta_vazia_nao_apaga_o_que_estava_la(base):
    """Mesma regra da premiação e do RNTRC: vazio não sobrescreve dado bom."""
    arm.gravar("estatisticas", "2026-07", [_reg()], base)
    with pytest.raises(arm.ColetaVazia):
        arm.gravar("estatisticas", "2026-07", [], base)
    assert len(arm.ler("estatisticas", "2026-07", base)) == 1


def test_ultima_diz_de_quando_e_o_dado(base):
    """Número de telemetria sem data engana: a tela precisa mostrar a idade."""
    arm.gravar("estatisticas", "2026-07", [_reg()], base)
    u = arm.ultima("estatisticas", base)
    assert u["competencia"] == "2026-07" and u["registros"] == 1 and u["quando"]


def test_sem_coleta_devolve_vazio_sem_quebrar(base):
    assert arm.ler("estatisticas", "2026-01", base) == []
    assert arm.ultima("estatisticas", base) is None
