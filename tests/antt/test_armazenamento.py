"""Base local do RNTRC: normalização, substituição atômica e a guarda da sync vazia."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from api.antt import armazenamento as arm


@pytest.fixture
def base():
    p = Path(tempfile.mkdtemp()) / "antt.db"
    arm.init_db(p)
    return p


def _linha(rntrc, situacao="ATIVO", nome="TRANSP", categoria="ETC", uf="SP"):
    return {"rntrc": rntrc, "nome": nome, "situacao": situacao,
            "categoria": categoria, "uf": uf, "municipio": "SBC",
            "data_situacao": "01/07/2026"}


def test_normalizar_tira_zeros_a_esquerda_e_nao_digitos():
    assert arm.normalizar_rntrc("007600540") == "7600540"
    assert arm.normalizar_rntrc("07600540") == "7600540"
    assert arm.normalizar_rntrc(" 7.600.540 ") == "7600540"
    assert arm.normalizar_rntrc(None) == ""


def test_o_lado_do_ava_e_o_da_antt_viram_a_mesma_chave(base):
    """O defeito que este teste trava: o AVA guarda 8 dígitos e a ANTT 9. Sem
    normalizar os dois lados, 19 transportadores em ordem foram acusados de
    não existir na base."""
    arm.gravar_lote([_linha("007600540")], "2026-07", base)
    assert arm.situacao(arm.normalizar_rntrc("07600540"), base) is not None


def test_gravar_lote_substitui_a_base_inteira(base):
    arm.gravar_lote([_linha("111"), _linha("222")], "2026-06", base)
    arm.gravar_lote([_linha("333")], "2026-07", base)
    assert set(arm.todas(base)) == {"333"}


def test_lote_vazio_nao_apaga_a_base_boa(base):
    """Regra herdada da Premiação: coleta vazia já apagou um mês de dados."""
    arm.gravar_lote([_linha("111")], "2026-06", base)
    with pytest.raises(arm.BaseVazia):
        arm.gravar_lote([], "2026-07", base)
    assert set(arm.todas(base)) == {"111"}
    assert arm.ultima_sync(base)["competencia"] == "2026-06"


def test_ultima_sync_registra_competencia_e_contagem(base):
    arm.gravar_lote([_linha("111"), _linha("222")], "2026-07", base)
    s = arm.ultima_sync(base)
    assert s["competencia"] == "2026-07"
    assert s["linhas"] == 2
    assert s["quando"]


def test_base_nunca_sincronizada_devolve_none(base):
    assert arm.ultima_sync(base) is None
    assert arm.todas(base) == {}
