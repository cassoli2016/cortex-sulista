# -*- coding: utf-8 -*-
"""O KM RODADO por veículo — o denominador do CPK.

O QUE ESTES GUARDS PROTEGEM. Um km inflado não parece errado. Ele parece um
caminhão que rodou muito, e o CPK que sai dele parece um pneu que rendeu bem —
e é sobre esse número que alguém decide comprar a próxima carga de pneus.

Dois erros já apareceram aqui, e os dois davam resultados PLAUSÍVEIS:

1. Somar por manifesto contava o mesmo dia três vezes. Mediana de 65.681 km/ano
   que virou 36.812 ao deduplicar — 78% de inflação com cara de normal.
2. Um dia de cavalo virava dois dias inteiros de carreta no bitrem, e a frota
   de carretas somava mais km do que os cavalos rodaram.

Por isso o módulo tem `conferir()`: um SEGUNDO caminho para o mesmo número.
Carreta só anda puxada, então o km delas TEM de ser menor que o dos cavalos —
e é essa impossibilidade que denuncia a contagem dobrada.
"""
from __future__ import annotations

import datetime

import pytest

from api.pneus import km

HOJE = datetime.date.today()


def _d(n: int) -> datetime.date:
    """n dias atrás."""
    return HOJE - datetime.timedelta(days=n)


@pytest.fixture(autouse=True)
def cache_limpo():
    """O cache é de módulo e atravessaria os testes."""
    from api import queries
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


@pytest.fixture
def banco(monkeypatch):
    """Dublê do AVA que responde por SQL, não por ordem de chamada."""
    estado = {"trechos": [], "engates": []}

    def _query(sql, params=None):
        if "ctaplus_abastecimentos" in sql:
            return list(estado["trechos"])
        if "manifesto" in sql:
            return list(estado["engates"])
        raise AssertionError("consulta inesperada: %s" % sql[:60])

    monkeypatch.setattr(km.db, "query", _query)
    return estado


def _trecho(placa, dias_atras, km_rodado, dias=1):
    return {"placa": placa, "de": _d(dias_atras + dias),
            "ate": _d(dias_atras), "km": km_rodado, "dias": dias}


def _engate(cavalo, carreta, dias_atras, dias=0):
    return {"cavalo": cavalo, "carreta": carreta,
            "de": _d(dias_atras + dias), "ate": _d(dias_atras)}


# --------------------------------------------------------------------------
# tração: o odômetro
# --------------------------------------------------------------------------
def test_km_da_tracao_sai_do_odometro(banco):
    banco["trechos"] = [_trecho("ABC1D23", 10, 700, dias=7)]
    d = km.obter(365)
    assert d["veiculos"]["ABC1D23"]["km"] == 700.0
    assert d["veiculos"]["ABC1D23"]["metodo"] == "odometro"
    # O trecho vale 7 dias: o km se espalha por eles, e é isso que permite
    # fatiar depois "desde a instalação do pneu".
    assert d["veiculos"]["ABC1D23"]["dias_com_dado"] == 7


# --------------------------------------------------------------------------
# implemento: o engate
# --------------------------------------------------------------------------
def test_o_MESMO_DIA_em_varios_manifestos_conta_UMA_VEZ(banco):
    """O guard da inflação de 78%.

    O mesmo cavalo puxa a mesma carreta em três manifestos no mesmo dia. Somar
    por manifesto triplicaria o dia — e 3× um número plausível continua
    plausível, que é o que torna este erro perigoso.
    """
    banco["trechos"] = [_trecho("CAV1A11", 5, 600, dias=1)]
    banco["engates"] = [_engate("CAV1A11", "CAR2B22", 5)] * 3

    d = km.obter(365)
    assert d["veiculos"]["CAR2B22"]["km"] == 600.0, "contou o dia mais de uma vez"


def test_um_dia_de_cavalo_se_REPARTE_entre_as_carretas(banco):
    """Bitrem, ou troca de carreta no meio do dia. O cavalo rodou 600 km, não
    1.200 — e sem esta repartição a frota de carretas somaria mais que a de
    cavalos, que é fisicamente impossível."""
    banco["trechos"] = [_trecho("CAV1A11", 5, 600, dias=1)]
    banco["engates"] = [_engate("CAV1A11", "CAR2B22", 5),
                        _engate("CAV1A11", "CAR3C33", 5)]

    d = km.obter(365)
    assert d["veiculos"]["CAR2B22"]["km"] == 300.0
    assert d["veiculos"]["CAR3C33"]["km"] == 300.0
    assert d["km_carreta_total"] == 600.0


def test_engate_sem_fim_NAO_espalha_km_pelo_ano(banco):
    """Manifesto que ninguém encerrou não é uma viagem de 400 dias. Espalhar o
    km por ele atribuiria à carreta um período de pátio."""
    banco["trechos"] = [_trecho("CAV1A11", 5, 600, dias=1)]
    banco["engates"] = [_engate("CAV1A11", "CAR2B22", 5,
                                dias=km.ENGATE_DIAS_MAX + 5)]
    d = km.obter(365)
    assert "CAR2B22" not in d["veiculos"]


# --------------------------------------------------------------------------
# a conferência — o segundo caminho
# --------------------------------------------------------------------------
def test_carreta_NUNCA_roda_mais_que_cavalo(banco):
    """O guard que pegaria qualquer contagem dobrada futura, inclusive uma que
    ainda não foi inventada."""
    banco["trechos"] = [_trecho("CAV1A11", 5, 600, dias=1),
                        _trecho("CAV4D44", 5, 400, dias=1)]
    banco["engates"] = [_engate("CAV1A11", "CAR2B22", 5),
                        _engate("CAV1A11", "CAR3C33", 5),
                        _engate("CAV4D44", "CAR2B22", 5)]
    c = km.conferir(365)
    assert c["ok"], c
    assert c["razao_pct"] <= 100.0


def test_a_conferencia_ACENDE_quando_a_soma_e_impossivel(monkeypatch, banco):
    """Verde que nunca ficaria vermelho não conferiu nada."""
    banco["trechos"] = [_trecho("CAV1A11", 5, 600, dias=1)]
    banco["engates"] = [_engate("CAV1A11", "CAR2B22", 5)]
    real = km._km_das_carretas

    def _dobrado(km_cavalo, de, ate):
        k, por_dia = real(km_cavalo, de, ate)
        return ({p: v * 3 for p, v in k.items()},
                {p: {d: x * 3 for d, x in v.items()} for p, v in por_dia.items()})

    monkeypatch.setattr(km, "_km_das_carretas", _dobrado)
    from api import queries
    queries._RESP_CACHE.clear()
    assert not km.conferir(365)["ok"], "a contagem triplicada passou batido"


# --------------------------------------------------------------------------
# faixa física
# --------------------------------------------------------------------------
def test_a_faixa_fisica_e_APLICADA_NO_BANCO():
    """Odômetro que regride e salto absurdo saem na consulta, não em Python:
    trazer 1,6% de lixo do ERP para filtrar aqui seria pagar rede por dado que
    já se sabe descartar. O guard lê a consulta porque é lá que a regra mora."""
    assert "odo > odo_ant" in km.TRECHOS_SQL
    assert "%(teto)s * (d - d_ant)" in km.TRECHOS_SQL
    assert 500 <= km.KM_DIA_MAX <= 2000


# --------------------------------------------------------------------------
# o odômetro manda sobre o engate
# --------------------------------------------------------------------------
def test_placa_que_abastece_usa_o_ODOMETRO_e_nao_o_engate(banco):
    """Medição direta ganha de atribuição. Um cavalo que aparece como 'carreta'
    num manifesto mal preenchido não pode ter o km reescrito por isso."""
    banco["trechos"] = [_trecho("CAV1A11", 5, 600, dias=1),
                        _trecho("CAV4D44", 5, 900, dias=1)]
    banco["engates"] = [_engate("CAV1A11", "CAV4D44", 5)]
    d = km.obter(365)
    assert d["veiculos"]["CAV4D44"]["metodo"] == "odometro"
    assert d["veiculos"]["CAV4D44"]["km"] == 900.0


# --------------------------------------------------------------------------
# a fatia por período — o recorte que o pneu precisa
# --------------------------------------------------------------------------
def test_o_km_do_PNEU_e_o_do_periodo_dele_e_nao_o_do_ano(banco):
    """Um pneu montado há três semanas num cavalo que roda 200 mil km/ano não
    rodou 200 mil km."""
    banco["trechos"] = [_trecho("ABC1D23", 300, 5000, dias=10),
                        _trecho("ABC1D23", 10, 700, dias=7)]
    total = km.obter(365)["veiculos"]["ABC1D23"]["km"]
    assert total == 5700.0

    recente = km.no_periodo("ABC1D23", _d(20))
    assert recente["km"] == 700.0, "somou o que rodou antes da instalação"
    assert recente["dias_com_dado"] == 7


def test_periodo_ANTERIOR_a_janela_se_DECLARA_parcial(banco):
    """Truncar calado daria um km baixo demais em pneu antigo — que é
    justamente o pneu sobre o qual se decide troca."""
    banco["trechos"] = [_trecho("ABC1D23", 10, 700, dias=7)]
    r = km.no_periodo("ABC1D23", "2020-01-01")
    assert r["truncado_em"]
    assert "PARCIAL" in r["motivo"]


def test_placa_sem_leitura_volta_NULO_e_nao_ZERO(banco):
    """Zero que é ausência de leitura não é veículo parado. Confundir os dois
    daria CPK infinito num pneu que roda normalmente."""
    banco["trechos"] = [_trecho("ABC1D23", 10, 700, dias=7)]
    r = km.no_periodo("XYZ9Z99", _d(30))
    assert r["km"] is None and r["motivo"]

    d = km.de_placas(["ABC1D23", "XYZ9Z99"])
    assert d["pedidas"] == 2 and d["com_km"] == 1
    assert d["veiculos"]["XYZ9Z99"]["km"] is None


def test_a_cobertura_e_DITA_em_vez_de_suposta(banco):
    banco["trechos"] = [_trecho("ABC1D23", 10, 700, dias=7)]
    d = km.de_placas(["ABC1D23", "XYZ9Z99", "QQQ0Q00"])
    assert (d["pedidas"], d["com_km"]) == (3, 1)


# --------------------------------------------------------------------------
# o segundo caminho — o hodômetro da Prolog
# --------------------------------------------------------------------------
def test_o_confronto_compara_os_DOIS_CAMINHOS(banco, monkeypatch):
    """Vale mais que qualquer teste deste arquivo.

    Um caminho sai do odômetro do abastecimento no ERP; o outro é o número que
    um borracheiro digitou na Prolog no dia da montagem. Eles não têm uma linha
    de código em comum — concordar por acaso é implausível. Medido em produção
    (05/09/2026): razão mediana 0,98 em 61 pares.
    """
    from api import pglocal

    banco["trechos"] = [_trecho("ABC1D23", 5, 10000, dias=30)]

    def _erp(sql, p=None):
        if "current_date - 60" in sql:   # só a ODO_HOJE_SQL tem
            return [{"placa": "ABC1D23", "odo": 110000}]
        return list(banco["trechos"])
    monkeypatch.setattr(km.db, "query", _erp)
    monkeypatch.setattr(pglocal, "query", lambda sql, p=None: [
        {"id": 1, "placa": "ABC1D23", "km_inst": 100000,
         "inst_em": _d(40), "placa_evento": "ABC1D23"}])

    r = km.confrontar(365)
    # direto = 110.000 - 100.000 = 10.000; derivado = 10.000 -> razão 1,0
    assert r["pares"] == 1 and r["razao_mediana"] == 1.0 and r["ok"]


def test_pneu_que_MUDOU_DE_VEICULO_sai_do_confronto(banco, monkeypatch):
    """O par compararia hodômetros de caminhões diferentes — e a diferença
    seria lida como erro do nosso cálculo."""
    from api import pglocal
    banco["trechos"] = [_trecho("ABC1D23", 5, 10000, dias=30)]

    def _erp(sql, p=None):
        if "current_date - 60" in sql:   # só a ODO_HOJE_SQL tem
            return [{"placa": "ABC1D23", "odo": 110000}]
        return list(banco["trechos"])
    monkeypatch.setattr(km.db, "query", _erp)
    monkeypatch.setattr(pglocal, "query", lambda sql, p=None: [
        {"id": 1, "placa": "ABC1D23", "km_inst": 100000,
         "inst_em": _d(40), "placa_evento": "OUTRA99"}])

    r = km.confrontar(365)
    assert r["pares"] == 0
    assert r["motivo"], "sem par comparável tem de DIZER, não devolver ok"


def test_a_RESSALVA_do_confronto_viaja_junto(banco, monkeypatch):
    """Só há hodômetro em veículo que tem hodômetro: o confronto cobre a
    tração e NÃO cobre o engate, que atende 83% dos pneus da frota. Vender
    esta conferência como se cobrisse tudo seria pior que não tê-la."""
    from api import pglocal
    banco["trechos"] = [_trecho("ABC1D23", 5, 10000, dias=30)]

    def _erp(sql, p=None):
        if "current_date - 60" in sql:   # só a ODO_HOJE_SQL tem
            return [{"placa": "ABC1D23", "odo": 110000}]
        return list(banco["trechos"])
    monkeypatch.setattr(km.db, "query", _erp)
    monkeypatch.setattr(pglocal, "query", lambda sql, p=None: [
        {"id": 1, "placa": "ABC1D23", "km_inst": 100000,
         "inst_em": _d(40), "placa_evento": "ABC1D23"}])
    r = km.confrontar(365)
    assert r["so_tracao"] is True and "engate" in r["ressalva"]
