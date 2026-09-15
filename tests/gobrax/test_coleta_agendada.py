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
from coletar_telemetria import CONDUCAO_HORAS, competencias, conducao_a_coletar  # noqa: E402

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


# ── a cadência dos indicadores de condução (15/09/2026) ────────────────────
#
# Medido no dia da troca: 3 de 10 placas com indicador diferente do da coleta
# de 4 h antes. O corrente vai a cada ~3 h; o anterior, uma vez por dia.

def _quando(**por_comp):
    return lambda comp: por_comp.get(comp.replace("-", "_"))


def test_conducao_do_mes_corrente_vence_em_duas_horas_e_meia():
    from datetime import datetime
    agora = datetime(2026, 9, 15, 3, 30)
    ontem_cedo = "2026-09-14 08:00:00"          # anterior coletado há 19 h 30
    assert conducao_a_coletar(date(2026, 9, 15), _quando(
        **{"2026_09": "2026-09-15 00:31:00", "2026_08": ontem_cedo}), agora) == ["2026-09"], (
        "a passagem das 03:30 tem de varrer o corrente: com trava de 3 h ela "
        "pularia por um minuto e a cadência real viraria de 4 em 4 h")
    assert conducao_a_coletar(date(2026, 9, 15), _quando(
        **{"2026_09": "2026-09-15 01:31:00", "2026_08": ontem_cedo}), agora) == []


def test_o_mes_anterior_so_volta_depois_de_vinte_horas():
    from datetime import datetime
    agora = datetime(2026, 9, 15, 10, 30)
    assert conducao_a_coletar(date(2026, 9, 15), _quando(
        **{"2026_09": "2026-09-15 06:31:00", "2026_08": "2026-09-14 14:31:00"}), agora) == [
        "2026-09", "2026-08"]
    assert CONDUCAO_HORAS == (2.5, 20)


def test_conducao_nunca_coletada_ou_com_data_ilegivel_varre():
    assert conducao_a_coletar(date(2026, 9, 15), _quando()) == ["2026-09", "2026-08"]
    assert conducao_a_coletar(date(2026, 9, 15), _quando(
        **{"2026_09": "ontem de tarde", "2026_08": None})) == ["2026-09", "2026-08"]


def test_quando_da_e_por_competencia(tmp_path):
    """`ultima()` diria a última gravação de QUALQUER mês: o coletor grava o
    corrente e o anterior na mesma passagem."""
    db = tmp_path / "telemetria.db"
    arm.gravar("performance", "2026-09", [{"placa": "AAA1A11"}], db)
    assert arm.quando_da("performance", "2026-09", db)
    assert arm.quando_da("performance", "2026-08", db) is None
    assert arm.quando_da("performance", "2026-09", tmp_path / "nao-existe.db") is None


def test_a_tarefa_e_registrada_de_hora_em_hora():
    """O instalador precisa de administrador e não roda na suíte; o texto é a
    única coisa conferível daqui. Se o intervalo voltar a 3 h, o alarme da
    Saúde (150 min) acenderia a cada ciclo com a coleta funcionando."""
    raiz = Path(__file__).resolve().parent.parent.parent
    ps1 = (raiz / "scripts" / "instalar_tarefa_telemetria.ps1").read_text(encoding="utf-8")
    assert "-RepetitionInterval (New-TimeSpan -Hours 1)" in ps1
    assert "-RepetitionInterval (New-TimeSpan -Hours 3)" not in ps1


def test_tarefa_esta_no_monitoramento_da_saude():
    """Tarefa que não aparece na Saúde é tarefa que pode morrer em silêncio —
    foi exatamente o que aconteceu."""
    from api import servidor
    assert "Cortex Sulista - Telemetria" in servidor._TAREFAS


def test_script_da_tarefa_e_ascii_puro():
    """PowerShell 5.1 lê .ps1 SEM BOM como ANSI: os 3 bytes UTF-8 de um
    travessão viram três caracteres, um deles fecha string, e o parse quebra
    LONGE dali — um traço na linha 23 derrubou a linha 93 com "a cadeia de
    caracteres não tem o terminador". ASCII puro é imune a como o arquivo for
    gravado depois, por qualquer editor.
    """
    raiz = Path(__file__).resolve().parent.parent.parent
    # RECURSIVO E COM .vbs desde 06/09/2026. O glob era `scripts/*.ps1`, que
    # deixava de fora os sete `.ps1` de `scripts/win/` — e os `.vbs`, que o
    # `wscript` lê com a MESMA regra: sem BOM, codepage ANSI do sistema. Os
    # quatro lançadores versionados tinham acento e nenhum BOM, e ninguém viu
    # porque o guard não olhava para eles.
    alvos = sorted(list((raiz / "scripts").rglob("*.ps1"))
                   + list((raiz / "scripts").rglob("*.vbs")))
    assert alvos, "não achei script nenhum — o glob quebrou"
    for arq in alvos:
        texto = arq.read_text(encoding="utf-8")
        if texto.startswith("﻿"):
            continue                      # com BOM o acento é lido certo
        fora = [(n, l) for n, l in enumerate(texto.splitlines(), 1)
                if not l.isascii()]
        assert not fora, (
            f"{arq.relative_to(raiz)} não tem BOM e tem caractere fora do "
            f"ASCII: {fora[:3]}")
