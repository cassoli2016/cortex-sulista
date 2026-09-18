# -*- coding: utf-8 -*-
"""Reputação de seis ciclos, categoria e a medida disciplinar.

O que estes testes seguram:

- a reputação é HISTÓRIA e o ranking é o CICLO: uma pessoa em ATENÇÃO no mês
  pode seguir OURO, e é assim de propósito;
- ciclo limpo só conta A PARTIR DA ADMISSÃO — senão quem entrou há dois meses
  ganha bônus por ciclos em que não trabalhava aqui;
- o mérito sobe a reputação (e não a nota do ciclo), e por isso a faixa ELITE
  pode passar de 100;
- a medida é SUGERIDA pela reincidência, e desvio gravíssimo nunca fica abaixo
  de advertência escrita.
"""
from __future__ import annotations

import pytest

from api.premiacao import parametros, reputacao

P = parametros.defaults()
CICLO = "2026-09"
JANELA = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


def _d(cod="D07", grav="MODERADA", pts=7, data="2026-09-01"):
    return {"cod": cod, "grav": grav, "pts": pts, "data": data}


def _m(cod="M07", pts=30):
    return {"cod": cod, "nome": "Elogio", "pts": pts, "data": "2026-09-01"}


def _conduta(**por_ciclo):
    """{ciclo: {cpf: ficha}} — o formato que a janela devolve."""
    return {c.replace("_", "-"): {"X": v} for c, v in por_ciclo.items()}


# ------------------------------------------------------------- reputação
def test_ciclo_limpo_soma_bonus_e_a_reputacao_passa_de_100():
    """Sem desvio nenhum em seis ciclos: 100 + 6 × bônus."""
    r = reputacao.calcular(CICLO, "X", {}, {}, {}, P)
    assert r["ciclos_limpos"] == 6
    assert r["rep_conduta"] == 100 + 6 * P["bonus_ciclo_limpo"]
    assert r["categoria"] in ("DIAMANTE", "ELITE")


def test_o_bonus_so_conta_a_partir_da_ADMISSAO():
    """Quem entrou em julho não tem ciclo limpo em abril: ele não existia."""
    r = reputacao.calcular(CICLO, "X", {}, {}, {}, P, primeiro_ciclo="2026-07")
    assert r["ciclos_limpos"] == 3          # julho, agosto, setembro


def test_o_desvio_da_janela_derruba_a_reputacao_e_o_merito_levanta():
    conduta = _conduta(**{"2026_09": {"desvios": [_d(pts=12)], "meritos": [_m(pts=30)]}})
    r = reputacao.calcular(CICLO, "X", conduta, {}, {}, P)
    # 100 − 12 + 30 + (5 ciclos limpos × 2)
    assert r["rep_conduta"] == 128.0
    assert r["desvios"] == 1 and r["meritos"] == 1


def test_a_reputacao_usa_a_MEDIA_dos_pilares_na_janela():
    gobrax = {"2026-08": {"X": {"nota": 80}}, "2026-09": {"X": {"nota": 90}}}
    gr = {"2026-09": {"X": {"nota": 60}}}
    r = reputacao.calcular(CICLO, "X", {}, gobrax, gr, P)
    assert r["gobrax_media"] == 85.0 and r["gr_media"] == 60.0


def test_sem_gobrax_e_sem_GR_a_reputacao_sai_so_da_conduta():
    r = reputacao.calcular(CICLO, "X", {}, {}, {}, P)
    assert r["pilares"] == ["conduta"] and r["ausentes"] == ["gobrax", "gr"]
    assert r["reputacao"] == r["rep_conduta"]


def test_o_ciclo_ruim_nao_derruba_a_CATEGORIA_sozinho():
    """O ranking mede o mês; a categoria mede a história. Categoria que oscila
    todo mês não é categoria."""
    conduta = _conduta(**{"2026_09": {"desvios": [_d(pts=20)], "meritos": []}})
    r = reputacao.calcular(CICLO, "X", conduta, {}, {}, P)
    assert r["rep_conduta"] == 90.0        # 100 − 20 + 5 limpos × 2
    assert r["categoria"] == "OURO"


# -------------------------------------------------------------- medidas
def test_sem_desvio_no_ciclo_NAO_ha_medida():
    assert reputacao.sugerir_medida([], [_d()], [_d()]) is None


@pytest.mark.parametrize("n3, n6, esperado", [
    (1, 1, "N1"),          # primeiro desvio
    (2, 2, "N2"),          # dois em três ciclos
    (1, 3, "N3"),          # três em seis
    (1, 4, "N4"),          # quatro em seis
])
def test_a_escada_segue_a_REINCIDENCIA(n3, n6, esperado):
    r = reputacao.sugerir_medida([_d()], [_d()] * n3, [_d()] * n6)
    assert r["nivel"] == esperado and r["medida"] == reputacao.MEDIDAS[esperado]


def test_desvio_GRAVISSIMO_nunca_fica_abaixo_de_advertencia_escrita():
    """Quebra de PGR não se resolve com orientação verbal."""
    r = reputacao.sugerir_medida([_d("D08", "GRAVISSIMA", 20)],
                                 [_d("D08", "GRAVISSIMA", 20)],
                                 [_d("D08", "GRAVISSIMA", 20)])
    assert r["nivel"] == "N3" and "gravíssimo" in r["porque"]


def test_a_medida_e_SUGERIDA_e_diz_o_porque():
    """Motorista próprio é CLT: o rito é trabalhista e quem aplica é o RH."""
    r = reputacao.sugerir_medida([_d()], [_d()] * 2, [_d()] * 2)
    assert r["sugerida"] is True
    assert r["reincidencia_3"] == 2 and "3 ciclos" in r["porque"]


def test_a_janela_de_conduta_junta_os_ciclos_certos():
    conduta = {"2026-07": {"X": {"desvios": [_d()]}},
               "2026-08": {"X": {"desvios": [_d(), _d()]}},
               "2026-09": {"X": {"desvios": [_d()]}},
               "2026-03": {"X": {"desvios": [_d()]}}}   # fora da janela de 6
    assert len(reputacao.janela_de_conduta(CICLO, conduta, "X", 3)) == 4
    assert len(reputacao.janela_de_conduta(CICLO, conduta, "X", 6)) == 4
    assert reputacao.janela_de_conduta(CICLO, conduta, "OUTRO", 6) == []
