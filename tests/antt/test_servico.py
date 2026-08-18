"""Conferência e KPIs — puros, sem banco."""
from __future__ import annotations

from api.antt.servico import conferir_viagens, resumir, serie_mensal


def _linha(**kw):
    base = {"numero": 1, "dtemissao": "2026-08-01", "codigo": "T1",
            "transportador": "TRANSP UM", "placa": "AAA1A11",
            "origem": "SBC/SP", "destino": "RIO/RJ", "km": 500.0,
            "pago": 1000.0, "vazio": False, "veic_tipo": "CAVALO MECANICO",
            "veic_carroceria": "CARGA SECA", "veic_bitrem": False,
            "veic_tipocarga": "CARGA GERAL"}
    base.update(kw)
    return base


def test_viagem_completa_e_conferida_e_marcada_abaixo():
    r = conferir_viagens([_linha()])[0]
    assert r["estado"] == "calculado"
    assert r["eixos"] == 5
    assert r["tipo_carga"] == "carga_geral"
    assert r["abaixo"] is True          # 1000 < 500*6,6718 + 657,56
    assert r["gap"] < 0


def test_viagem_bem_paga_nao_e_abaixo():
    r = conferir_viagens([_linha(pago=9000.0)])[0]
    assert r["abaixo"] is False
    assert r["gap"] > 0


def test_veiculo_sem_tipo_conhecido_vira_pendencia_nao_irregular():
    r = conferir_viagens([_linha(veic_tipo="NAVE ESPACIAL")])[0]
    assert r["estado"] == "sem_eixos"
    assert r["abaixo"] is False
    assert r["piso"] is None


def test_vazio_sem_obrigacao_fica_isento():
    r = conferir_viagens([_linha(vazio=True)])[0]
    assert r["estado"] == "isento"
    assert r["abaixo"] is False


def test_vazio_de_conteiner_e_conferido_a_92_por_cento():
    r = conferir_viagens([_linha(vazio=True, veic_tipocarga="CONTEINER")])[0]
    assert r["estado"] == "calculado"
    assert r["cc"] is None


def test_resumo_declara_cobertura_e_nao_conta_isento_no_denominador():
    conferidas = conferir_viagens([
        _linha(numero=1),
        _linha(numero=2, veic_tipo="NAVE ESPACIAL"),
        _linha(numero=3, vazio=True),
    ])
    k = resumir(conferidas)
    assert k["viagens"] == 3
    assert k["conferidas"] == 1        # só a completa
    assert k["nao_conferidas"] == 1    # a sem eixos
    assert k["isentas"] == 1
    assert k["abaixo"] == 1
    assert k["exposicao"] < 0


def test_resumo_de_lista_vazia_nao_divide_por_zero():
    k = resumir([])
    assert k["viagens"] == 0
    assert k["aderencia"] is None


def test_serie_mensal_agrupa_por_competencia_e_ordena():
    conferidas = conferir_viagens([
        _linha(numero=1, dtemissao="2026-08-01"),
        _linha(numero=2, dtemissao="2026-07-15", pago=9000.0),
        _linha(numero=3, dtemissao="2026-08-20"),
    ])
    serie = serie_mensal(conferidas)
    assert [r["mes"] for r in serie] == ["2026-07", "2026-08"]
    assert serie[0]["abaixo"] == 0 and serie[0]["aderencia"] == 1.0
    assert serie[1]["abaixo"] == 2 and serie[1]["aderencia"] == 0.0


def test_serie_mensal_ignora_isento_e_nao_conferido():
    conferidas = conferir_viagens([
        _linha(numero=1, dtemissao="2026-08-01", vazio=True),
        _linha(numero=2, dtemissao="2026-08-02", veic_tipo="NAVE ESPACIAL"),
    ])
    assert serie_mensal(conferidas) == []


def test_pendencias_agrupam_o_que_falta_cadastrar():
    conferidas = conferir_viagens([
        _linha(numero=1, veic_tipo="NAVE ESPACIAL", placa="BBB2B22"),
        _linha(numero=2, veic_tipo="NAVE ESPACIAL", placa="BBB2B22"),
    ])
    k = resumir(conferidas)
    assert k["placas_pendentes"] == 1   # a mesma placa não conta duas vezes


def test_viagem_de_julho_e_de_agosto_usam_resolucoes_diferentes():
    """A virada de vigência é 17/07/2026. Duas viagens iguais, meses
    diferentes, têm pisos diferentes — e é isso que impede o reajuste de
    reescrever período já fechado."""
    jun, ago = conferir_viagens([_linha(numero=1, dtemissao="2026-06-10"),
                                 _linha(numero=2, dtemissao="2026-08-10")])
    assert jun["resolucao"] == "6.076/2026"
    assert ago["resolucao"] == "6.084/2026"
    assert ago["piso"] > jun["piso"]
