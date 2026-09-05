# -*- coding: utf-8 -*-
"""Quando cada pneu chega no limite.

O QUE ESTES GUARDS PROTEGEM. Data de troca vira ordem de compra e vira agenda
de oficina. Um número errado aqui não parece errado: parece um pneu que dura
mais, ou menos, do que dura.

Três coisas já apareceram na primeira medição real:

1. **Sem piso, a taxa da frota deu ZERO.** Mais da metade dos pares tinha as
   duas medições perto demais para o sulco mudar, e dividir um arredondamento
   por um km pequeno produz qualquer número. Com os pisos, a mediana dá
   0,0967 mm/1.000 km — uma vida implícita de 134 mil km, que é a ordem de
   grandeza certa para pneu de carga.
2. **Sulco que SOBE** entre duas medições é rodízio, recapagem ou dedo trocado
   — nunca desgaste negativo, que projetaria um pneu ficando novo com o uso.
3. **Pneu já abaixo do limite não é "previsão de zero dias"**: ele já está lá.
   Misturar os dois faz a lista de urgentes virar a lista dos vencidos, e a
   previsão — o motivo do módulo existir — some embaixo deles.
"""
from __future__ import annotations

import datetime

import pytest

from api.pneus import desgaste

HOJE = datetime.date.today()


def _d(n):
    return HOJE - datetime.timedelta(days=n)


@pytest.fixture(autouse=True)
def cache_limpo():
    from api import queries
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


@pytest.fixture
def cenario(monkeypatch):
    estado = {"serie": [], "atuais": [], "km": {}}

    def _query(sql, params=None):
        return list(estado["serie"] if "pne_inspecao i" in sql
                    else estado["atuais"])

    def _no_periodo(placa, de, ate=None, dias_janela=365):
        v = estado["km"].get(placa)
        return ({"km": None, "motivo": "sem leitura"} if v is None
                else {"km": v, "metodo": "odometro", "dias_com_dado": 30})

    monkeypatch.setattr(desgaste.pglocal, "query", _query)
    monkeypatch.setattr(desgaste.kmmod, "no_periodo", _no_periodo)
    monkeypatch.setattr(desgaste.kmmod, "obter", lambda d=365: {
        "veiculos": {p: {"km": k} for p, k in estado["km"].items()}})
    return estado


def _med(pid, placa, dias_atras, sulco, marca="X", modelo="Y", medida="Z"):
    return {"pneu_id": pid, "placa": placa, "d": _d(dias_atras),
            "sulcos_mm": [sulco, sulco + 1, sulco + 1, sulco + 1],
            "modelo_id": 1, "vida_atual": 1, "placa_atual": placa,
            "posicao_atual": "1DE", "status": "rodando",
            "marca": marca, "modelo": modelo, "medida": medida}


def _atual(pid, placa, sulco, marca="X", modelo="Y", medida="Z"):
    return {"id": pid, "placa": placa, "posicao_atual": "1DE", "vida_atual": 1,
            "filial": "MTZ", "marca": marca, "modelo": modelo,
            "medida": medida, "sulcos_mm": [sulco, sulco + 1, sulco + 1],
            "medido_em": _d(1)}


# --------------------------------------------------------------------------
# o sulco que vale
# --------------------------------------------------------------------------
def test_o_sulco_que_conta_e_o_MENOR_dos_quatro():
    """É ele que a lei mede e é ele que tira o pneu de circulação. A média
    esconderia o ombro gasto de um pneu desalinhado — justamente o caso em que
    a troca é urgente."""
    assert desgaste._menor([9.0, 9.0, 9.0, 2.0]) == 2.0
    assert desgaste._menor([]) is None and desgaste._menor(None) is None


# --------------------------------------------------------------------------
# a taxa
# --------------------------------------------------------------------------
def test_a_taxa_e_mm_por_MIL_KM_e_nao_por_mes(cenario):
    """Dois pneus montados no mesmo dia, um num cavalo de 200 mil km/ano e
    outro numa carreta parada, chegam ao limite com meio ano de diferença."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 20000.0}
    d = desgaste.obter()
    # 2 mm em 20.000 km = 0,1 mm por 1.000 km
    assert d["taxas_pneu"][1] == pytest.approx(0.1)


def test_par_com_POUCO_KM_nao_vira_taxa(cenario):
    """Sem o piso a mediana da frota deu ZERO: dividir um arredondamento por um
    km pequeno produz qualquer número."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": desgaste.KM_MINIMO_PAR - 1}
    d = desgaste.obter()
    assert not d["taxas_pneu"]
    assert "km rodado abaixo do piso" in d["recusas"]


def test_par_com_POUCO_DESGASTE_nao_vira_taxa(cenario):
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 9.8)]
    cenario["km"] = {"AAA1A11": 50000.0}
    d = desgaste.obter()
    assert not d["taxas_pneu"]
    assert "desgaste abaixo do piso de medição" in d["recusas"]


def test_sulco_que_SOBE_sai_da_conta(cenario):
    """Rodízio, recapagem ou dedo trocado. Taxa negativa projetaria um pneu
    ficando novo com o uso."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 4.0), _med(1, "AAA1A11", 10, 12.0)]
    cenario["km"] = {"AAA1A11": 50000.0}
    d = desgaste.obter()
    assert not d["taxas_pneu"]
    assert any("subiu" in k for k in d["recusas"])


def test_a_serie_e_por_PNEU_E_PLACA(cenario):
    """Trocar de veículo troca o km e o regime de uso; emendar os dois trechos
    misturaria coisas diferentes."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "BBB2B22", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 50000.0, "BBB2B22": 50000.0}
    d = desgaste.obter()
    assert not d["taxas_pneu"], "emendou medições de veículos diferentes"


# --------------------------------------------------------------------------
# a previsão
# --------------------------------------------------------------------------
def test_a_previsao_diz_a_PROCEDENCIA_da_taxa(cenario):
    """Própria, do modelo ou da frota respondem a mesma pergunta com confianças
    muito diferentes. Apresentá-las iguais faria alguém programar a troca de um
    pneu pela média de outros sem saber."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 20000.0, "CCC3C33": 20000.0}
    cenario["atuais"] = [_atual(1, "AAA1A11", 8.0),
                         _atual(9, "CCC3C33", 8.0, marca="Outra")]
    d = desgaste.previsao()
    por_id = {i["id"]: i for i in d["itens"]}
    assert por_id[1]["taxa_origem"] == "própria"
    assert por_id[9]["taxa_origem"] == "frota"


def test_o_dia_sai_do_KM_DA_PLACA_e_nao_do_calendario(cenario):
    """Mesmo sulco, mesma taxa, km diferente: datas diferentes. É essa
    diferença que o módulo existe para mostrar."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 100000.0, "LENTA999": 5000.0}
    cenario["atuais"] = [_atual(1, "AAA1A11", 8.0), _atual(2, "LENTA999", 8.0)]
    d = desgaste.previsao()
    por_id = {i["id"]: i for i in d["itens"]}
    assert por_id[1]["km_ate_recape"] == por_id[2]["km_ate_recape"]
    assert por_id[1]["dias_ate_recape"] < por_id[2]["dias_ate_recape"]


def test_pneu_JA_ABAIXO_do_limite_nao_e_previsao(cenario):
    """Ele não "vai chegar lá em zero dias": já está lá, e precisa de oficina
    hoje. Misturar faz a lista de urgentes virar a lista dos vencidos."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 20000.0}
    cenario["atuais"] = [_atual(1, "AAA1A11", 2.0)]     # abaixo dos 3 mm
    d = desgaste.previsao()
    assert d["vencidos_n"] == 1 and d["com_previsao"] == 0
    assert d["vencidos"][0]["vencido"] is True
    assert not any(i["id"] == 1 for i in d["itens"]), "vencido entrou na previsão"


def test_o_ILEGAL_se_separa_do_vencido(cenario):
    """3 mm é quando o pneu tem de SAIR para recapar; 1,6 mm é quando ele fica
    ilegal. Quem programa oficina olha o primeiro; quem responde por autuação
    olha o segundo."""
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 20000.0}
    cenario["atuais"] = [_atual(1, "AAA1A11", 2.5), _atual(2, "AAA1A11", 1.0)]
    d = desgaste.previsao()
    assert d["vencidos_n"] == 2 and d["ilegais_n"] == 1


def test_sem_taxa_NENHUMA_a_previsao_e_LACUNA_e_nao_data(cenario):
    """Inventar uma data aqui é pior que não responder: data de troca vira
    ordem de compra."""
    cenario["serie"] = []            # nada mensurável em lugar nenhum
    cenario["km"] = {"AAA1A11": 50000.0}
    cenario["atuais"] = [_atual(1, "AAA1A11", 8.0)]
    d = desgaste.previsao()
    i = d["itens"][0]
    assert i["dias_ate_recape"] is None and i["data_recape"] is None
    assert i["motivo"] and d["sem_taxa"] == 1


def test_modelo_com_POUCOS_pneus_nao_vira_referencia(cenario):
    """Chamar de taxa do modelo o que se mediu em dois pneus é o jeito de
    programar a frota inteira por um acaso."""
    cenario["serie"] = []
    for pid in (1, 2):
        cenario["serie"] += [_med(pid, "P%d" % pid, 200, 10.0),
                             _med(pid, "P%d" % pid, 10, 8.0)]
    cenario["km"] = {"P1": 20000.0, "P2": 20000.0}
    d = desgaste.obter()
    assert d["pneus_com_taxa"] == 2
    assert d["modelos_com_taxa"] == 0, "2 pneus viraram referência de modelo"
    assert desgaste.MODELO_MINIMO >= 5


def test_a_ressalva_viaja_com_o_numero(cenario):
    cenario["serie"] = [_med(1, "AAA1A11", 200, 10.0), _med(1, "AAA1A11", 10, 8.0)]
    cenario["km"] = {"AAA1A11": 20000.0}
    cenario["atuais"] = [_atual(1, "AAA1A11", 8.0)]
    d = desgaste.previsao()
    assert "crescendo" in d["ressalva"]
    assert d["limite_recape_mm"] == 3.0 and d["limite_legal_mm"] == 1.6


# --------------------------------------------------------------------------
# o hodômetro da inspeção manda sobre a derivação
# --------------------------------------------------------------------------
def test_o_HODOMETRO_da_inspecao_vence_o_km_derivado(cenario):
    """Ele é uma subtração entre duas leituras do MESMO painel: não depende de
    a placa casar com o cadastro do ERP, nem do engate do manifesto, nem da
    janela de 365 dias. Medição direta ganha de atribuição."""
    cenario["serie"] = [dict(_med(1, "AAA1A11", 200, 10.0), km_veiculo=300000),
                        dict(_med(1, "AAA1A11", 10, 8.0), km_veiculo=320000)]
    cenario["km"] = {"AAA1A11": 999999.0}     # a derivação diria outra coisa
    d = desgaste.obter()
    # 2 mm em 20.000 km de hodômetro = 0,1 — e não o que a derivação daria
    assert d["taxas_pneu"][1] == pytest.approx(0.1)
    assert d["km_origens"].get("hodômetro") == 1


def test_sem_hodometro_nas_DUAS_pontas_cai_na_derivacao(cenario):
    """Carreta não tem hodômetro nenhum, e é ela que a derivação atende."""
    cenario["serie"] = [dict(_med(1, "AAA1A11", 200, 10.0), km_veiculo=300000),
                        dict(_med(1, "AAA1A11", 10, 8.0), km_veiculo=None)]
    cenario["km"] = {"AAA1A11": 20000.0}
    d = desgaste.obter()
    assert d["taxas_pneu"][1] == pytest.approx(0.1)
    assert d["km_origens"].get("derivado") == 1


def test_hodometro_que_ANDA_PARA_TRAS_cai_na_derivacao(cenario):
    """Troca de painel, não km negativo. Aceitar isso daria uma taxa negativa,
    que projetaria um pneu ficando novo com o uso."""
    cenario["serie"] = [dict(_med(1, "AAA1A11", 200, 10.0), km_veiculo=500000),
                        dict(_med(1, "AAA1A11", 10, 8.0), km_veiculo=20000)]
    cenario["km"] = {"AAA1A11": 20000.0}
    d = desgaste.obter()
    assert d["taxas_pneu"][1] == pytest.approx(0.1)
    assert d["km_origens"].get("derivado") == 1


def test_a_PROCEDENCIA_do_km_e_contada(cenario):
    """Ver quanto da taxa da frota se apoia em medição direta e quanto no plano
    B é o que separa "a curva está boa" de "a curva está inteira no plano B"."""
    cenario["serie"] = [
        dict(_med(1, "P1", 200, 10.0), km_veiculo=300000),
        dict(_med(1, "P1", 10, 8.0), km_veiculo=320000),
        dict(_med(2, "P2", 200, 10.0), km_veiculo=None),
        dict(_med(2, "P2", 10, 8.0), km_veiculo=None)]
    cenario["km"] = {"P1": 20000.0, "P2": 20000.0}
    d = desgaste.obter()
    assert d["km_origens"] == {"hodômetro": 1, "derivado": 1}


def test_o_par_com_hodometro_e_TENTADO_PRIMEIRO_e_as_pontas_ficam_de_reserva(cenario):
    """O guard de uma escolha que custou duas medições erradas seguidas.

    A ponta mais antiga da série costuma ser uma FOTO do instantâneo, sem
    hodômetro. Pegar as pontas cegamente jogava para a derivação 968 pneus que
    já tinham o par completo medido no painel. Mas trocar um pelo outro também
    não servia: o par com hodômetro tem janela mais curta e cai nos pisos —
    medido, ganhava 26 medições diretas e perdia 43 pneus por completo.

    Os dois saem, nesta ordem, e quem consome cai no segundo quando o primeiro
    não qualifica.
    """
    obs = [(_d(300), 12.0, None),        # foto antiga, sem hodômetro
           (_d(60), 10.0, 300000),
           (_d(10), 8.0, 320000)]
    pares = list(desgaste._pares(obs))
    assert len(pares) == 2
    assert pares[0] == (obs[1], obs[2]), "o par com hodômetro não veio primeiro"
    assert pares[1] == (obs[0], obs[2]), "as pontas não ficaram de reserva"


def test_serie_toda_com_hodometro_nao_gera_par_repetido():
    obs = [(_d(60), 10.0, 300000), (_d(10), 8.0, 320000)]
    assert list(desgaste._pares(obs)) == [(obs[0], obs[-1])]


def test_quando_o_par_direto_NAO_qualifica_a_taxa_ainda_sai(cenario):
    """É este o caso que a ordem existe para atender: janela curta demais no
    hodômetro, janela larga o bastante nas pontas."""
    cenario["serie"] = [
        dict(_med(1, "AAA1A11", 300, 12.0), km_veiculo=None),
        dict(_med(1, "AAA1A11", 12, 10.1), km_veiculo=300000),
        dict(_med(1, "AAA1A11", 10, 10.0), km_veiculo=300100)]
    cenario["km"] = {"AAA1A11": 40000.0}
    d = desgaste.obter()
    assert d["taxas_pneu"], "perdeu o pneu por causa do par curto"
    assert d["km_origens"].get("derivado") == 1
