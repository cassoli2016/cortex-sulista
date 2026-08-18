"""Tradução do cadastro do AVA para (eixos, tipo de carga) da tabela ANTT."""
from __future__ import annotations

from api.antt.eixos import normalizar, resolver_carga, resolver_eixos


def test_normalizar_tira_acento_e_caixa():
    assert normalizar(" Semi-Reboque Frigorífico ") == "SEMI-REBOQUE FRIGORIFICO"
    assert normalizar(None) == ""


def test_cavalo_com_semirreboque_comum_da_5_eixos():
    assert resolver_eixos("CAVALO MECANICO", "CARGA SECA", bitrem=False) == 5


def test_bitrem_da_7_eixos():
    assert resolver_eixos("CAVALO MECANICO", "CARGA SECA", bitrem=True) == 7


def test_truck_da_3_eixos():
    assert resolver_eixos("TRUCK", "CARGA SECA", bitrem=False) == 3


def test_toco_da_2_eixos():
    assert resolver_eixos("TOCO", "CARGA SECA", bitrem=False) == 2


def test_tipo_desconhecido_devolve_none():
    assert resolver_eixos("NAVE ESPACIAL", "CARGA SECA", bitrem=False) is None


def test_acento_no_cadastro_nao_atrapalha():
    # o AVA grava "CAVALO MECÂNICO" com acento em parte dos registros
    assert resolver_eixos("Cavalo Mecânico", "CARGA SECA", bitrem=False) == 5


def test_carroceria_frigorifica_vira_carga_frigorificada():
    assert resolver_carga(None, "FRIGORIFICO") == "frigorificada"


def test_tipo_de_carga_do_veiculo_tem_precedencia_sobre_a_carroceria():
    assert resolver_carga("GRANEL SOLIDO", "CARGA SECA") == "granel_solido"


def test_carga_seca_cai_no_default_carga_geral():
    assert resolver_carga(None, "CARGA SECA") == "carga_geral"


def test_sem_nenhuma_informacao_devolve_none():
    assert resolver_carga(None, None) is None


def test_todo_valor_do_mapa_e_um_tipo_valido_da_antt():
    """Guarda contra erro de digitação no YAML: um valor fora das 12 classes
    faria toda viagem daquele tipo cair em 'sem_tabela' silenciosamente."""
    from api.antt.coeficientes import TIPOS_CARGA
    from api.antt.eixos import _mapa

    carga = _mapa()["carga"]
    for grupo in ("por_tipo_carga", "por_carroceria"):
        for chave, valor in carga[grupo].items():
            assert valor in TIPOS_CARGA, f"{grupo}/{chave} aponta para {valor}"
