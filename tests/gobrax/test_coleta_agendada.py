"""Coletor agendado da telemetria Gobrax.

Existe porque a coleta NÃO tinha quem a disparasse: as funções `sincronizar()`
só rodavam quando alguém abria uma tela com `force`, e o cache ficou cinco
dias parado sem ninguém notar — a Torre mostrava telemetria de 19/08 ao lado
de posições ao vivo.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from coletar_telemetria import competencias  # noqa: E402

from api.gobrax import armazenamento as arm


@pytest.mark.parametrize("hoje,esperado", [
    (date(2026, 8, 24), ["2026-08", "2026-07"]),
    (date(2026, 1, 15), ["2026-01", "2025-12"]),   # vira o ano
    (date(2026, 12, 31), ["2026-12", "2026-11"]),
])
def test_coleta_o_mes_corrente_e_o_anterior(hoje, esperado):
    """O anterior entra porque a Gobrax fecha dados com atraso: coletar só o
    corrente deixaria o fim do mês passado incompleto para sempre."""
    assert competencias(hoje) == esperado


def test_competencia_atual_e_a_maior_nao_a_ultima_gravada(tmp_path):
    """`ultima()` ordena por INSERÇÃO. O coletor grava o mês corrente e depois
    o anterior — com `ultima()`, a Torre voltava a mostrar o mês passado como
    se fosse a posição de hoje. Aconteceu na primeira execução real.
    """
    db = tmp_path / "telemetria.db"
    linha = [{"placa": "AAA1A11", "km": 100.0, "litros": 40.0, "km_l": 2.5,
              "vel_media": 60.0, "odometro": 1000.0, "freadas": 1,
              "freadas_alta": 0}]
    arm.gravar("estatisticas", "2026-08", linha, db)
    arm.gravar("estatisticas", "2026-07", linha, db)   # gravado DEPOIS

    assert arm.ultima("estatisticas", db)["competencia"] == "2026-07"
    assert arm.competencia_atual("estatisticas", db)["competencia"] == "2026-08"


def test_sem_coleta_nenhuma_devolve_nada(tmp_path):
    assert arm.competencia_atual("estatisticas", tmp_path / "vazio.db") is None


def test_tarefa_esta_no_monitoramento_da_saude():
    """Tarefa que não aparece na Saúde é tarefa que pode morrer em silêncio —
    foi exatamente o que aconteceu."""
    from api import servidor
    assert "Cortex Sulista - Telemetria" in servidor._TAREFAS
