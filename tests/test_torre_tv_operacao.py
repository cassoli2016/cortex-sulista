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

from datetime import date, datetime, timedelta

import pytest

from api import queries, queries_folha

# a função de verdade, guardada ANTES de o fixture abaixo trocá-la
_CNH_GLOBUS_REAL = queries._cnh_globus

HOJE = date.today()
VENCIDA = HOJE - timedelta(days=100)
VALIDA = HOJE + timedelta(days=1500)


@pytest.fixture(autouse=True)
def sem_globus(monkeypatch):
    """A suíte nunca lê a folha de produção: por padrão, "Globus fora". Quem
    precisa do Globus põe um dublê no teste."""
    monkeypatch.setattr(queries, "_cnh_globus", lambda: None)


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

def _viagem(placa, numerofrota, critica, atrasada=False, chegada=None):
    """A linha como o SQL a devolve: `atrasada` aqui é a PREVISÃO VENCIDA —
    quem decide o atraso é get_torre(), olhando a chegada no cliente."""
    return {"numero": 1, "filial": 1, "placa": placa, "utilizacao": "AGREGADOS",
            "motorista": "M", "cliente": "C", "origem": "A/PR", "destino": "B/SP",
            "saida": "2026-09-13 08:00", "previsao_chegada": "2026-09-14 10:00",
            "previsao_vencida": atrasada, "chegada_cliente": chegada,
            "vazio": False, "km": 100.0, "valorfrete": 1.0,
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
    # a chegada no cliente, idem
    assert params[0]["ocorrencia_chegada"] == 396
    assert queries.OCORRENCIA_CHEGADA_DESCARGA == 396


def test_a_viagem_que_chegou_na_ultima_entrega_esta_FINALIZADA(monkeypatch):
    """15/09/2026: um agregado chegou no cliente 7 min ANTES da previsão, com
    a chegada para descarga (SAC 396) apontada, e ficou ATRASADA na TV a
    tarde toda — a viagem só saía do trânsito com a baixa da programação, e a
    previsão venceu antes dela. Decisão de quem opera no mesmo dia: chegou na
    última entrega, está finalizada — sai da lista e das contagens, e a
    posição do caminhão deixa de ser "em viagem"."""
    d, _, _ = _torre(monkeypatch, [
        _viagem("AAA1A11", "101", False, atrasada=True),
        _viagem("BBB2B22", "102", True, atrasada=True, chegada="2026-09-15 12:53"),
        _viagem("CCC3C33", "103", False, chegada="2026-09-15 08:00"),
        _viagem("DDD4D44", "104", False),
    ], posicoes=[_posicao("BBB2B22", "102", None), _posicao("AAA1A11", "101", None)])
    assert [x["placa"] for x in d["transito"]] == ["AAA1A11", "DDD4D44"]
    k = d["kpis"]
    assert (k["em_transito"], k["atrasadas"], k["no_cliente"]) == (2, 1, 2)
    # a crítica que já chegou também sai da contagem de críticas em trânsito
    assert k["criticas"] == 0
    pos = {p["placa"]: p["em_viagem"] for p in d["posicoes"]}
    assert pos == {"BBB2B22": False, "AAA1A11": True}
    assert all("previsao_vencida" not in x for x in d["transito"])


def test_as_atrasadas_abrem_a_lista_e_o_resto_fica_na_ordem_da_previsao(monkeypatch):
    """O SQL já não ordena por atraso (ele não sabe quem chegou): a ordem das
    atrasadas primeiro é do Python, e é ESTÁVEL — dentro de cada grupo fica a
    ordem da previsão que veio do banco."""
    d, _, _ = _torre(monkeypatch, [
        _viagem("AAA1A11", "101", False),
        _viagem("BBB2B22", "102", False, atrasada=True),
        _viagem("CCC3C33", "103", False),
        _viagem("DDD4D44", "104", False, atrasada=True),
    ])
    assert [x["placa"] for x in d["transito"]] == [
        "BBB2B22", "DDD4D44", "AAA1A11", "CCC3C33"]


def test_a_ficha_do_veiculo_usa_a_MESMA_chegada_da_torre():
    """As duas telas leem a mesma viagem; duas cópias da regra discordariam no
    primeiro ajuste (uma dizendo ATRASADA, a outra "no cliente")."""
    for sql in (queries.TORRE_TRANSITO_SQL, queries.VEICF_VIAGEM_SQL):
        assert queries._CHEGADA_CLIENTE_SQL in sql
        assert "previsao_vencida" in sql and " AS atrasada" not in sql
    # a ÚLTIMA entrega: o N-ésimo 396, contado contra os destinatários da
    # coleta — o "primeiro 396" (min) encerraria a viagem na primeira parada
    frag = queries._CHEGADA_CLIENTE_SQL.lower()
    assert "coleta_cliente" in frag and "row_number()" in frag
    assert "min(o.dtocorrencia)" not in frag


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

def _mot(cod_util, em_viagem, venc=None, codigo="00000000000"):
    return {"motorista": "X", "codigo": codigo,
            "ult_saida": datetime(2026, 9, 10).date(),
            "em_viagem": em_viagem, "venc_cnh": venc, "utilizacao": cod_util}


def _prog_completo(monkeypatch, motoristas, agr):
    _banco(monkeypatch, {
        queries.PROG_DIESEL_SQL: {"custo": 0.0},
        queries.PROG_KM_PROPRIO_SQL: {"km": 0.0},
        queries.PROG_MOT_DISP_SQL: motoristas,
        queries.PROG_AGR_DISP_SQL: agr,
    })
    return queries.get_programacao()


def _programacao(monkeypatch, motoristas, agr):
    return _prog_completo(monkeypatch, motoristas, agr)["kpis"]


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


# ------------------------------------------------------- a CNH pelo Globus

def _motoristas_cnh():
    return [
        # próprio rodando, vencido no cadastro e RENOVADO no Globus: o caso real
        _mot("TRA", 1, VENCIDA, "11111111111"),
        # agregado rodando, vencido no cadastro; o CPF está no Globus como
        # EX-FUNCIONÁRIO com validade futura -- e mesmo assim não vale
        _mot("AGR", 1, VENCIDA, "22222222222"),
        # próprio parado, vencido no cadastro e sem linha no Globus
        _mot("LOC", 0, VENCIDA, "33333333333"),
        # próprio sem data no cadastro, com data no Globus
        _mot("TRA", 0, None, "44444444444"),
    ]


def test_a_cnh_do_proprio_sai_do_globus_e_a_do_agregado_do_cadastro(monkeypatch):
    monkeypatch.setattr(queries, "_cnh_globus", lambda: {
        "11111111111": VALIDA, "22222222222": VALIDA, "44444444444": VALIDA})
    d = _prog_completo(monkeypatch, _motoristas_cnh(), {"total": 0})
    k = d["kpis"]
    # vencidas: o agregado (Globus não vale para ele) e o próprio sem Globus
    assert (k["cnh_vencida"], k["cnh_vencida_rodando"]) == (2, 1)
    assert k["cnh_vencida_rodando_por_classe"]["agregado"] == 1
    assert k["cnh_vencida_rodando_por_classe"]["proprio"] == 0
    assert k["cnh_globus_ok"] is True
    assert k["cnh_renovada_no_globus"] == 1      # só o que ERA vencido
    assert {a["fonte_cnh"] for a in d["cnh_alertas"]} == {"cadastro"}


def test_sem_globus_vale_o_cadastro_e_o_payload_diz(monkeypatch):
    k = _programacao(monkeypatch, _motoristas_cnh(), {"total": 0})
    assert (k["cnh_vencida"], k["cnh_vencida_rodando"]) == (3, 2)
    assert k["cnh_globus_ok"] is False and k["cnh_renovada_no_globus"] == 0


def test_cadastro_mais_novo_que_o_globus_continua_valendo(monkeypatch):
    """A mais recente das duas. Nunca aconteceu na medição (o AVA nunca foi o
    mais novo), mas renovar no ERP antes do RH não pode virar vencida."""
    monkeypatch.setattr(queries, "_cnh_globus", lambda: {"11111111111": VENCIDA})
    k = _programacao(monkeypatch, [_mot("TRA", 1, VALIDA, "11111111111")], {"total": 0})
    assert k["cnh_vencida"] == 0


def test_o_cpf_nao_sai_do_servidor(monkeypatch):
    monkeypatch.setattr(queries, "_cnh_globus", lambda: {"11111111111": VALIDA})
    d = _prog_completo(monkeypatch, _motoristas_cnh(), {"total": 0})
    for lista in ("cnh_alertas", "motoristas_parados"):
        for linha in d[lista]:
            assert "codigo" not in linha and "33333333333" not in str(linha), linha


def test_a_suite_nunca_le_a_folha_de_producao():
    """Sob pytest a função de verdade devolve None sem abrir o Oracle."""
    assert _CNH_GLOBUS_REAL() is None


def test_oracle_fora_pausa_as_tentativas(monkeypatch):
    """Cada tentativa contra um Oracle fora pode segurar a resposta até 60 s;
    depois de uma falha, 10 min sem tentar -- e cai no cadastro."""
    import api.sob_teste as st
    monkeypatch.setattr(st, "sob_teste", lambda: False)
    chamadas = []

    def falha():
        chamadas.append(1)
        raise RuntimeError("oracle fora")
    monkeypatch.setattr(queries, "_cnh_globus_cache", falha)
    monkeypatch.setattr(queries, "_cnh_globus_falhou_em", 0.0)
    assert _CNH_GLOBUS_REAL() is None and len(chamadas) == 1
    assert _CNH_GLOBUS_REAL() is None and len(chamadas) == 1, "tentou de novo na pausa"


def test_a_folha_devolve_a_validade_mais_longa_por_cpf(monkeypatch):
    vistos = {}

    def q(sql, params=None):
        vistos["sql"], vistos["params"] = sql, params
        return [{"cpf": "111.111.111-11", "venc": datetime(2027, 1, 1)},
                {"cpf": "11111111111", "venc": datetime(2030, 1, 1)},
                {"cpf": "123", "venc": datetime(2030, 1, 1)},          # CPF torto
                {"cpf": "22222222222", "venc": None}]
    monkeypatch.setattr(queries_folha, "_q", q)
    assert queries_folha.venc_cnh_por_cpf() == {"11111111111": date(2030, 1, 1)}
    assert "vencimento_cnh" in vistos["sql"] and vistos["params"] == {"emp": queries_folha.EMPRESA}
