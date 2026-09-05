# -*- coding: utf-8 -*-
"""A coleta das INSPEÇÕES — sulco medido no pátio, com data e hodômetro.

POR QUE ELA VALE. A curva de desgaste se apoiava em 79 pneus com taxa própria
contra 2.299 usando a mediana da frota, porque o que existia eram as medições
de carona numa movimentação e o instantâneo do dia. A inspeção é o evento
próprio: alguém foi ao pátio, mediu os quatro sulcos de cada pneu do veículo, e
o registro traz a DATA e o HODÔMETRO.

O HODÔMETRO É O GANHO. Com ele a taxa vira uma subtração entre duas leituras do
MESMO hodômetro — sem placa, sem engate, sem janela. A derivação continua como
plano B e vira o segundo caminho para conferir esta.

OS TRÊS GUARDS QUE MAIS IMPORTAM aqui protegem de erros MUDOS — os que não
levantam exceção e aparecem como "esse mês veio menor":

1. `pageNumber` começa em ZERO neste endpoint e em UM no de movimentação.
2. `includeMeasures` é obrigatório e é ele que traz os sulcos; sem ele a
   resposta é 200 com as inspeções vazias, idêntico a "não mediram nada".
3. Hodômetro fora da faixa física vira NULO, nunca km. Um hodômetro errado não
   estraga a taxa: estraga em silêncio, com um número plausível.
"""
from __future__ import annotations

import pytest

from api.pneus import inspecoes


def _insp(ident=10, odo=350000, placa="\tABC1D23", medidas=None):
    return {
        "id": ident, "submittedAt": "2026-08-14T10:00:00Z",
        "submittedBy": {"name": "FULANO"},
        "vehicle": {"licensePlate": placa, "fleetId": "R3018"},
        "odometerReading": odo,
        "inspectionMeasures": medidas if medidas is not None else [{
            "tireId": 1650908, "tirePositionAtInspection": 321,
            "measuredPressure": 116.0, "recommendedPressure": 120.0,
            "measuredInnerTreadDepth": 10.0,
            "measuredMiddleInnerTreadDepth": 9.5,
            "measuredMiddleOuterTreadDepth": 9.4,
            "measuredOuterTreadDepth": 9.0}]}


class _Cur:
    """Cursor de mentira que registra o que foi gravado."""

    def __init__(self, conhece=(1650908,)):
        self.conhece = {str(x) for x in conhece}
        self.gravados = []
        self._ultimo = None

    def execute(self, sql, params=None):
        if "FROM pne_pneu WHERE prolog_id" in sql:
            self._ultimo = ({"id": 7} if params[0] in self.conhece else None)
        else:
            self.gravados.append((sql, params))
            self._ultimo = None

    def fetchone(self):
        return self._ultimo


# --------------------------------------------------------------------------
# a leitura de cada campo
# --------------------------------------------------------------------------
def test_a_medida_grava_sulcos_pressao_placa_e_HODOMETRO():
    cur = _Cur()
    assert inspecoes._gravar_inspecao(cur, _insp(), []) == 1
    _, p = cur.gravados[0]
    assert [float(x) for x in p[2]] == [10.0, 9.5, 9.4, 9.0]
    assert p[3] == 116.0 and p[4] == 120.0
    assert "ABC1D23" in p, "a placa não foi gravada"
    assert 350000 in p, "o hodômetro não foi gravado — é ele o ganho todo"


def test_os_quatro_sulcos_saem_na_ORDEM_declarada():
    """Interno, meio interno, meio externo, externo. A ordem é o que torna o
    array legível — sem ela seriam quatro números soltos, e o "menor sulco" que
    a lei mede sairia certo por acaso."""
    m = {"measuredInnerTreadDepth": 1, "measuredMiddleInnerTreadDepth": 2,
         "measuredMiddleOuterTreadDepth": 3, "measuredOuterTreadDepth": 4}
    assert inspecoes._sulcos(m) == [1, 2, 3, 4]


def test_sulco_parcial_PRESERVA_o_buraco():
    """Três medidas e uma faltando não vira lista de três: a posição do que
    faltou é informação."""
    m = {"measuredInnerTreadDepth": 1, "measuredOuterTreadDepth": 4}
    assert inspecoes._sulcos(m) == [1, None, None, 4]
    assert inspecoes._sulcos({}) is None


def test_a_placa_vem_SUJA_e_e_limpa_na_entrada():
    """Sem o `strip` o veículo não casa com o cadastro do ERP — e falha calada,
    virando "sem km"."""
    assert inspecoes._placa(_insp(placa="\tABC1D23")) == "ABC1D23"
    assert inspecoes._placa(_insp(placa="  ")) is None
    assert inspecoes._placa({}) is None


@pytest.mark.parametrize("valor", [1, 134, 7359990, 0, -5, None, "abc"])
def test_hodometro_fora_da_faixa_fisica_vira_NULO(valor):
    """Um hodômetro errado não estraga a taxa de desgaste — ele a estraga em
    SILÊNCIO, com um número plausível."""
    assert inspecoes._odometro(valor) is None
    assert inspecoes._odometro(350000) == 350000


def test_pneu_DESCONHECIDO_nao_vira_cadastro_inventado():
    """Carcaça que a Prolog já removeu do cadastro: o movimento existe, o pneu
    não. Criar aqui seria inventar cadastro a partir de uma medida."""
    cur = _Cur(conhece=())
    perdidos = []
    assert inspecoes._gravar_inspecao(cur, _insp(), perdidos) == 0
    assert perdidos == ["1650908"], "o perdido sumiu em silêncio"


def test_medida_sem_sulco_E_sem_pressao_nao_vira_linha():
    cur = _Cur()
    vazia = _insp(medidas=[{"tireId": 1650908}])
    assert inspecoes._gravar_inspecao(cur, vazia, []) == 0


def test_inspecao_sem_data_ou_sem_id_e_DESCARTADA():
    """Sem data ela não entra na série; sem id não há chave para não duplicar."""
    cur = _Cur()
    assert inspecoes._gravar_inspecao(cur, dict(_insp(), submittedAt=None), []) == 0
    assert inspecoes._gravar_inspecao(cur, dict(_insp(), id=None), []) == 0


def test_a_posicao_INTEIRA_fica_crua():
    """A sigla só existe no endpoint de movimentação. Código sem tabela de
    domínio não vira rótulo inventado."""
    cur = _Cur()
    inspecoes._gravar_inspecao(cur, _insp(), [])
    _, p = cur.gravados[0]
    assert "321" in p


# --------------------------------------------------------------------------
# a paginação — os erros MUDOS
# --------------------------------------------------------------------------
class _Cli:
    def __init__(self, paginas=2):
        self.paginas = paginas
        self.chamadas = []

    def get(self, caminho, params=None):
        self.chamadas.append(dict(params or {}))
        p = (params or {}).get("pageNumber")
        return {"content": [_insp(ident=100 + p)],
                "lastPage": p >= self.paginas - 1}


def test_a_paginacao_comeca_em_ZERO_neste_endpoint():
    """Começar em 1 pula a primeira página inteira — sem erro, e a falta só
    aparece como "esse mês veio menor". O endpoint de movimentação começa em 1;
    regra genérica vale por ENDPOINT."""
    cli, cur = _Cli(), _Cur()
    inspecoes._mes_completo(cur, cli, "2026-08", 5, [])
    assert cli.chamadas[0]["pageNumber"] == 0


def test_includeMeasures_VAI_SEMPRE():
    """Sem ele a resposta é 200 com as inspeções vazias de medida — idêntico a
    "não mediram nada", e a coleta ficaria varrendo meses e gravando zero."""
    cli, cur = _Cli(), _Cur()
    inspecoes._mes_completo(cur, cli, "2026-08", 5, [])
    assert all(c.get("includeMeasures") for c in cli.chamadas)


def test_o_mes_inteiro_e_varrido_ate_a_ultima_pagina():
    cli, cur = _Cli(paginas=3), _Cur()
    gastas, novas, fim = inspecoes._mes_completo(cur, cli, "2026-08", 9, [])
    assert (gastas, novas, fim) == (3, 3, True)


def test_o_ORCAMENTO_interrompe_sem_marcar_o_mes_como_completo():
    """Mês pela metade não pode avançar o cursor: a próxima execução refaz o
    mês inteiro, e refazer é barato porque tudo entra por chave natural."""
    cli, cur = _Cli(paginas=10), _Cur()
    gastas, _, fim = inspecoes._mes_completo(cur, cli, "2026-08", 2, [])
    assert gastas == 2 and fim is False


# --------------------------------------------------------------------------
# a coleta não derruba nada
# --------------------------------------------------------------------------
def test_sem_credencial_a_coleta_RECUSA_sem_levantar(monkeypatch):
    monkeypatch.setattr(inspecoes.cliente, "pronto", lambda: False)
    r = inspecoes.sincronizar()
    assert r["ok"] is False and r["erro"]


def test_a_cota_estourada_NAO_derruba_a_coleta(monkeypatch):
    """Falha de rede ou cota não é defeito nosso e não pode derrubar a tarefa:
    ela se registra e a próxima execução continua de onde parou."""
    class _Explode:
        def get(self, *a, **k):
            raise RuntimeError("HTTP 429")

    monkeypatch.setattr(inspecoes.cliente, "pronto", lambda: True)
    monkeypatch.setattr(inspecoes.cliente, "Cliente", lambda *a, **k: _Explode())
    monkeypatch.setattr(inspecoes, "_estado", lambda: {"cursor": None})
    monkeypatch.setattr(inspecoes, "_gravar_estado", lambda *a, **k: None)
    r = inspecoes.sincronizar()
    assert r["ok"] is False and "429" in r["erro"]


def test_a_coleta_ANDA_PARA_TRAS_um_mes_por_vez():
    assert inspecoes._anterior("2026-01") == "2025-12"
    assert inspecoes._anterior("2026-08") == "2026-07"


def test_os_limites_do_mes_cobrem_o_mes_INTEIRO():
    assert inspecoes._limites("2026-02") == ("2026-02-01", "2026-02-28")
    assert inspecoes._limites("2024-02") == ("2024-02-01", "2024-02-29")
    assert inspecoes._limites("2026-08") == ("2026-08-01", "2026-08-31")
