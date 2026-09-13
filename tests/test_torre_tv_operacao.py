# -*- coding: utf-8 -*-
"""O que a TV de operação passou a receber do servidor (13/09/2026).

Três pedidos de quem opera, e cada um mudou um payload:

* CARGA CRÍTICA — a ocorrência 261 ("CARGA CRITICA" no cadastro do ERP)
  lançada no PEDIDO DE COLETA põe a viagem no topo das chegadas da TV. O
  servidor publica `critica` por viagem e a contagem nos kpis.
* FROTA NO LUGAR DA PLACA — a viagem em trânsito ganha a mesma identidade das
  posições (`frota` só quando é número de verdade, `rotulo` completo).
* TRAÇÃO E MOTORISTAS SEPARADOS — agregado e frota são dois universos: a
  tração disponível só contava frota + locação, e o "motorista disponível"
  somava agregado e terceiro que só estavam sem viagem CONOSCO (157 "livres",
  93 deles de fora, medido no dia).

As consultas rodam contra um cursor falso: o que se testa aqui é a montagem
do payload. As SQL foram executadas contra o ERP real antes da entrega.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from api import queries


@pytest.fixture(autouse=True)
def cache_limpo():
    """`cached` guarda por função e argumentos: sem limpar, o segundo teste
    leria a resposta do primeiro e mediria o cache, não o código."""
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


class _Cursor:
    def __init__(self, respostas, vistos):
        self._r, self._vistos, self._ultimo = respostas, vistos, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._ultimo = sql
        self._vistos.append((sql, params))

    def _resposta(self):
        for sql, valor in self._r.items():
            if self._ultimo == sql:
                return valor
        if "current_timestamp AS ts" in (self._ultimo or ""):
            return {"ts": datetime(2026, 9, 13, 18, 0)}
        return None

    def fetchall(self):
        v = self._resposta()
        return [dict(x) for x in v] if isinstance(v, list) else []

    def fetchone(self):
        v = self._resposta()
        return dict(v) if isinstance(v, dict) else None


class _Conn:
    def __init__(self, respostas, vistos):
        self._r, self._v = respostas, vistos

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cursor(self._r, self._v)


def _banco(monkeypatch, respostas):
    vistos: list = []
    monkeypatch.setattr(queries.db, "get_conn", lambda: _Conn(respostas, vistos))
    return vistos


# ------------------------------------------------------------------ a torre

def _viagem(placa, numerofrota, critica, atrasada=False):
    return {"numero": 1, "filial": 1, "placa": placa, "utilizacao": "AGREGADOS",
            "motorista": "M", "cliente": "C", "origem": "A/PR", "destino": "B/SP",
            "saida": "2026-09-13 08:00", "previsao_chegada": "2026-09-14 10:00",
            "atrasada": atrasada, "vazio": False, "km": 100.0, "valorfrete": 1.0,
            "numerofrota": numerofrota, "critica": critica}


def _posicao(placa, numerofrota, tipo):
    return {"placa": placa, "utilizacao": "FROTA", "numerofrota": numerofrota,
            "lat": -25.0, "lng": -49.0, "posicao_em": "2026-09-13 17:55",
            "velocidade": 60, "com_motor": True, "recente": True,
            "tipo_veiculo": tipo}


def _torre(monkeypatch, transito, posicoes=(), frota=()):
    vistos = _banco(monkeypatch, {
        queries.TORRE_POS_SQL: list(posicoes),
        queries.TORRE_TRANSITO_SQL: list(transito),
        queries.TORRE_FROTA_SQL: [{"placa": p} for p in frota],
    })
    capturado = {}
    import api.gobrax.torre as gt

    def resumo(frota=None):
        capturado["frota"] = frota
        return {"disponivel": False, "motivo": "dublê"}
    monkeypatch.setattr(gt, "resumo", resumo)
    return queries.get_torre(), vistos, capturado


def test_a_carga_critica_chega_por_viagem_e_na_contagem(monkeypatch):
    d, vistos, _ = _torre(monkeypatch, [
        _viagem("AAA1A11", "101", True),
        _viagem("BBB2B22", "102", False),
        _viagem("CCC3C33", "103", 1),          # o driver pode devolver int
    ])
    assert [v["critica"] for v in d["transito"]] == [True, False, True]
    assert d["kpis"]["criticas"] == 2


def test_a_consulta_leva_o_codigo_da_ocorrencia_como_PARAMETRO(monkeypatch):
    """O código mora numa constante nomeada e viaja como parâmetro. Escrito
    no texto do SQL, trocar o código exigiria achar o número no meio da
    consulta — e o próximo que lesse `261` solto não saberia o que é."""
    _, vistos, _ = _torre(monkeypatch, [])
    params = [p for sql, p in vistos if sql == queries.TORRE_TRANSITO_SQL]
    assert params and params[0]["ocorrencia_critica"] == 261
    assert queries.OCORRENCIA_CARGA_CRITICA == 261
    assert "%(ocorrencia_critica)s" in queries.TORRE_TRANSITO_SQL


def test_a_viagem_ganha_o_numero_de_frota_so_quando_e_numero(monkeypatch):
    """A placa copiada no campo de frota não é número de frota — é a regra de
    frota_identidade, que agora vale também para a viagem."""
    d, _, _ = _torre(monkeypatch, [
        _viagem("AAA1A11", "582", False),
        _viagem("BBB2B22", "BBB2B22", False),   # placa copiada no campo
        _viagem("CCC3C33", None, False),
    ])
    frotas = [(v["frota"], v["rotulo"]) for v in d["transito"]]
    assert frotas == [("582", "582 · AAA1A11"), (None, "BBB2B22"), (None, "CCC3C33")]
    assert all("numerofrota" not in v for v in d["transito"])


@pytest.mark.parametrize("tipo, classe", [
    ("CAVALO TRUCADO 6X2 PJ", "6x2"),        # TRUCADO não é truck
    ("CAVALO MECANICO 4X2 EURO", "4x2"),
    ("3/4", "3/4"),
    ("CAMINHAO TOCO", "toco"),
    ("CAMINHAO TRUCK", "truck"),
    ("CAVALO 6X4", "6x4"),
    ("EMPILHADEIRA", None),                   # não inventa rótulo
    (None, None),
])
def test_a_classe_de_tracao_sai_do_tipo_do_cadastro(tipo, classe):
    assert queries._tracao(tipo) == classe


def test_a_posicao_leva_a_tracao_e_nao_o_tipo_cru(monkeypatch):
    d, _, _ = _torre(monkeypatch, [], [_posicao("AAA1A11", "7", "CAVALO TRUCADO 6X2 PJ")])
    p = d["posicoes"][0]
    assert p["tracao"] == "6x2" and "tipo_veiculo" not in p


def test_a_telemetria_recebe_as_placas_da_frota_normalizadas(monkeypatch):
    """O cache de performance grava "AAA1A11 - FR12"; o do ERP, "aaa-1a11 ".
    A telemetria só casa se as duas pontas passarem pela mesma régua."""
    _, _, cap = _torre(monkeypatch, [], frota=["aaa-1a11 ", "BBB2B22"])
    assert cap["frota"] == {"AAA1A11", "BBB2B22"}


# ------------------------------------------------------------ a programação

def _mot(cod_util, em_viagem):
    return {"motorista": "X", "ult_saida": datetime(2026, 9, 10).date(),
            "em_viagem": em_viagem, "venc_cnh": None, "utilizacao": cod_util}


def _programacao(monkeypatch, motoristas, agr):
    _banco(monkeypatch, {
        queries.PROG_DIESEL_SQL: {"custo": 0.0},
        queries.PROG_KM_PROPRIO_SQL: {"km": 0.0},
        queries.PROG_MOT_DISP_SQL: motoristas,
        queries.PROG_AGR_DISP_SQL: agr,
    })
    return queries.get_programacao()["kpis"]


def test_motorista_em_viagem_se_separa_por_modalidade(monkeypatch):
    k = _programacao(monkeypatch, [
        _mot("AGR", 1), _mot("AGR", 1), _mot("AGR", 0),
        _mot("TRA", 1), _mot("LOC", 0), _mot("LOC", 0), _mot("TRA", 0),
        _mot("TER", 0), _mot(None, 1),
    ], {"total": 0})
    assert k["mot_viagem"] == 4                     # o total não muda
    assert (k["mot_viagem_agregado"], k["mot_viagem_proprio"],
            k["mot_viagem_terceiro"]) == (2, 1, 0)
    # o % livre é SÓ do próprio: 3 de 4 próprios sem viagem
    assert (k["mot_proprios"], k["mot_proprios_disp"]) == (4, 3)
    assert k["pct_proprios_disp"] == 75.0


def test_sem_proprio_o_percentual_e_nulo_e_nao_zero(monkeypatch):
    """Zero diria "nenhum próprio livre" — ninguém mediu isso."""
    k = _programacao(monkeypatch, [_mot("AGR", 1)], {"total": 0})
    assert k["mot_proprios"] == 0 and k["pct_proprios_disp"] is None


def test_a_tracao_agregada_vem_ao_lado_da_frota(monkeypatch):
    k = _programacao(monkeypatch, [], {"total": 120, "em_viagem": 64,
                                       "ativos_30d": 116, "disponiveis": 52})
    assert (k["agr_total"], k["agr_viagem"], k["agr_ativos_30d"], k["agr_disp"]) \
        == (120, 64, 116, 52)


def test_a_tracao_agregada_ausente_vira_zero_sem_derrubar(monkeypatch):
    k = _programacao(monkeypatch, [], None)
    assert k["agr_disp"] == 0 and k["agr_ativos_30d"] == 0
