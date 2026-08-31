# -*- coding: utf-8 -*-
"""Auditoria das travessias: o que contestar e o que cobrar da operação.

Os casos aqui são montados à mão no banco, e não pelo parser: o que se testa é
a REGRA, e passar pelo PDF só acrescentaria ruído entre a regra e a asserção.

O teste que mais importa é `test_par_com_categorias_diferentes_...`: a primeira
versão desta análise somou 283 pares como "cobrança duplicada" e estava mal
enquadrada — 273 deles cobram categorias que se contradizem, que é outro
argumento e mais forte. Um teste que só contasse pares teria ficado verde com o
enquadramento errado.
"""
from __future__ import annotations

import datetime as dt

import pytest

from api import pglocal
from api.pedagio import auditoria as au


@pytest.fixture()
def base(esquema_pg):
    """Uma fatura com travessias postas a dedo."""
    pglocal.executar(
        "INSERT INTO ped_faturas (id, administradora, numero_fatura, competencia) "
        "VALUES (1, 'SEM PARAR', '1', '2026-08')", esquema=esquema_pg)

    def por(linhas):
        for placa, ts, praca, eixos, valor in linhas:
            pglocal.executar(
                "INSERT INTO ped_travessias (fatura_id, tipo, placa, ts, praca, "
                " rodovia, km, eixos, categoria, valor, dc) "
                "VALUES (1, 'tag', %s, %s, %s, 'SP021', 25.36, %s, %s, %s, 'D')",
                (placa, ts, praca, eixos, str(eixos), valor), esquema=esquema_pg)
    return por


T0 = dt.datetime(2026, 8, 10, 8, 0, 0)
PRACA = "SP021, KM25+360, SUL, SÃO PAULO"


def test_par_no_mesmo_segundo_com_valores_iguais_e_IDENTICA(base, esquema_pg):
    base([("AAA1B23", T0, PRACA, 5, 17.50),
          ("AAA1B23", T0, PRACA, 5, 17.50)])
    d = au.duplicadas(esquema=esquema_pg)
    assert len(d) == 1
    assert d[0]["tipo"] == "identica"
    assert d[0]["mesmo_instante"] is True


def test_par_com_categorias_diferentes_e_DIVERGENTE_nao_identica(base, esquema_pg):
    """O caso dominante, e o que a primeira leitura desta análise errou.

    O veículo passou UMA vez e foi cobrado por 5 e por 4 eixos no mesmo
    segundo — nove eixos numa passagem. Chamar isso de "duplicata" perde o
    argumento: o equipamento leu o mesmo caminhão de duas formas.
    """
    base([("AAA1B23", T0, PRACA, 5, 17.50),
          ("AAA1B23", T0, PRACA, 4, 14.00)])
    d = au.duplicadas(esquema=esquema_pg)
    assert len(d) == 1
    assert d[0]["tipo"] == "divergente"
    assert {d[0]["eixos"], d[0]["eixos_par"]} == {4, 5}


def test_travessia_legitima_horas_depois_nao_e_apontada(base, esquema_pg):
    """Ida e volta pela mesma praça leva horas, e não é achado nenhum."""
    base([("AAA1B23", T0, PRACA, 5, 17.50),
          ("AAA1B23", T0 + dt.timedelta(hours=6), PRACA, 5, 17.50)])
    assert au.duplicadas(esquema=esquema_pg) == []


def test_a_concentracao_por_janela_e_o_que_sustenta_a_leitura(base, esquema_pg):
    """Se o número crescer muito ao abrir a janela, a tese cai — e a tela tem
    de mostrar isso em vez de esconder atrás do número que interessa."""
    base([("AAA1B23", T0, PRACA, 5, 17.50),
          ("AAA1B23", T0, PRACA, 4, 14.00),
          ("BBB4C56", T0, PRACA, 5, 17.50),
          ("BBB4C56", T0 + dt.timedelta(minutes=40), PRACA, 5, 17.50)])
    c = {x["janela_min"]: x["travessias"] for x in
         au.concentracao_duplicadas(esquema=esquema_pg)}
    assert c[5] == 1        # só o par no mesmo segundo
    assert c[60] == 2       # o de 40 minutos entra só na janela larga


def test_mesma_placa_em_duas_pracas_no_mesmo_segundo(base, esquema_pg):
    base([("AAA1B23", T0, PRACA, 5, 17.50),
          ("AAA1B23", T0, "SP021, KM15+610, NORTE, OSASCO", 5, 17.50)])
    imp = au.impossiveis(esquema=esquema_pg)
    assert len(imp) == 1
    assert imp[0]["placa"] == "AAA1B23"


# ── modalidade por extenso ──────────────────────────────────────────────────

def test_a_modalidade_sai_por_extenso_e_o_codigo_fica_ao_lado():
    """Sigla obriga a perguntar; num card que decide dinheiro isso é atrito.

    O código do ERP continua disponível, porque é por ele que alguém procura
    no AVA — o que muda é o que a tela MOSTRA.
    """
    from api import frota_identidade as fi
    assert fi.modalidade("TRA") == "Frota própria"
    assert fi.modalidade("AGR") == "Agregado"
    assert fi.modalidade("TER") == "Terceiro"
    assert fi.modalidade("LOC") == "Locação"


def test_codigo_desconhecido_NAO_ganha_rotulo_inventado():
    """`PREV` existe em 3 veículos e não há tabela de domínio na réplica.

    Traduzir por palpite é pior que mostrar o código: é a mesma regra da coluna
    "Tipo (cód.)" da Manutenção. E é assim que o código aparece no dia em que
    virar trinta.
    """
    from api import frota_identidade as fi
    assert fi.modalidade("PREV") == "PREV"
    assert fi.modalidade("XPTO") == "XPTO"
    # vazio é "sem cadastro", não travessão: a diferença entre "não cadastrado"
    # e "não se aplica" é a que faz alguém ir arrumar o cadastro
    assert fi.modalidade(None) == "sem cadastro"
    assert fi.modalidade("") == "sem cadastro"


def test_a_locacao_nao_pode_cair_dentro_de_frota_propria():
    """`tipofrota` tem três valores e dobra o alugado dentro de "própria".

    Medido na fatura de ago/2026: por `tipofrota` a tela dizia R$ 101.929 de
    frota própria; por `utilizacaoveiculo` são R$ 30.836 de própria e
    R$ 71.093 de LOCAÇÃO. Chamar caminhão alugado de nosso infla o custo da
    frota própria em 3,3x.
    """
    from api.pedagio import fatura_tag as ft
    import inspect
    fonte = inspect.getsource(ft.resumo) + inspect.getsource(ft)
    assert "utilizacaoveiculo" in fonte
    assert "tipofrota" not in inspect.getsource(ft.resumo), (
        "resumo() voltou a quebrar por tipofrota, que esconde a locação")
