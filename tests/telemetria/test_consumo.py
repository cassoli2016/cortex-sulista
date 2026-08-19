"""Telemetria × abastecimento: duas medidas independentes do mesmo consumo."""
from __future__ import annotations

from api.gobrax import consumo


def _tel(placa="AAA1A11", km=1000.0, litros=250.0, km_l=4.0):
    return {"placa": placa, "km": km, "litros": litros, "km_l": km_l,
            "vel_media": 60.0, "odometro": 100000.0, "freadas": 5,
            "freadas_alta": 1}


def _ava(placa="AAA1A11", litros=250.0, km=1000.0):
    return {"placa": placa, "litros_ava": litros, "km_ava": km,
            "abastecimentos": 3}


def test_placas_que_batem_ganham_as_duas_medidas():
    l = consumo.cruzar([_tel()], [_ava()])[0]
    assert l["km_l"] == 4.0
    assert l["km_l_ava"] == 4.0
    assert l["delta_pct"] == 0


def test_divergencia_e_calculada_em_percentual():
    """Telemetria 4,0 e abastecimento 3,2: a telemetria está 25% acima."""
    l = consumo.cruzar([_tel(km_l=4.0)], [_ava(litros=312.5)])[0]
    assert round(l["km_l_ava"], 2) == 3.2
    assert round(l["delta_pct"], 1) == 25.0


def test_veiculo_so_na_telemetria_nao_inventa_delta():
    l = consumo.cruzar([_tel()], [])[0]
    assert l["km_l_ava"] is None
    assert l["delta_pct"] is None


def test_veiculo_so_no_ava_aparece_como_sem_telemetria():
    linhas = consumo.cruzar([], [_ava(placa="BBB2B22")])
    assert linhas[0]["placa"] == "BBB2B22"
    assert linhas[0]["km_l"] is None


def test_placa_com_e_sem_hifen_casa():
    """A Gobrax devolve ABC-1234 e o AVA guarda ABC1234."""
    l = consumo.cruzar([_tel(placa="ABC-1234")], [_ava(placa="ABC1234")])[0]
    assert l["km_l_ava"] is not None


def test_abastecimento_sem_litros_nao_vira_divisao_por_zero():
    l = consumo.cruzar([_tel()], [_ava(litros=0)])[0]
    assert l["km_l_ava"] is None
    assert l["delta_pct"] is None


def test_km_l_implausivel_e_marcado_e_fica_fora_da_media():
    """Medido em julho/2026: a frota real trouxe 0,1 e 17,88 km/l, os dois
    impossíveis para caminhão. Entram na lista marcados, não na média."""
    linhas = consumo.cruzar([_tel(placa="OK", km_l=4.0),
                             _tel(placa="ABSURDO", km_l=17.88, km=100.0, litros=5.6)],
                            [])
    absurdo = [l for l in linhas if l["placa"] == "ABSURDO"][0]
    assert absurdo["suspeito"] is True
    k = consumo.resumir(linhas)
    assert k["suspeitos"] == 1
    assert k["km_l_frota"] == 4.0      # só a leitura plausível entrou


def test_resumo_declara_a_cobertura_do_cruzamento():
    linhas = consumo.cruzar([_tel(), _tel(placa="BBB2B22")], [_ava()])
    k = consumo.resumir(linhas)
    assert k["veiculos"] == 2
    assert k["com_as_duas_medidas"] == 1
    assert k["km_l_frota"] is not None


def test_resumo_de_lista_vazia_nao_divide_por_zero():
    k = consumo.resumir([])
    assert k["veiculos"] == 0 and k["km_l_frota"] is None


def test_divergentes_sao_os_que_passam_do_limite():
    linhas = consumo.cruzar(
        [_tel(placa="OK", km_l=4.0), _tel(placa="RUIM", km_l=4.0)],
        [_ava(placa="OK", litros=250.0), _ava(placa="RUIM", litros=400.0)])
    k = consumo.resumir(linhas, limite_pct=15.0)
    assert k["divergentes"] == 1


def test_cada_lado_usa_o_proprio_km():
    """O erro que isto trava: misturar o km da telemetria com os litros do
    abastecimento produziu km/l de 0,01 e delta de +50.000% em julho/2026."""
    l = consumo.cruzar([_tel(km=1400.0, litros=350.0, km_l=4.0)],
                       [_ava(litros=500.0, km=1500.0)])[0]
    assert l["km_l_ava"] == 3.0          # 1500 / 500, e não 1400 / 500
    assert round(l["delta_pct"], 1) == 33.3


def test_telemetria_que_cobre_pouco_do_periodo_nao_vira_divergencia():
    """BBF5G20 em julho/2026: odômetro de 995 mil km, telemetria reportou 32,95
    km no mês e o AVA registra 6.644 km. Isso é rastreador mudo, não consumo."""
    l = consumo.cruzar([_tel(km=32.95, litros=6.56, km_l=5.03)],
                       [_ava(litros=3310.0, km=6644.0)])[0]
    assert l["telemetria_incompleta"] is True
    assert l["delta_pct"] is None
    k = consumo.resumir([l])
    assert k["telemetria_incompleta"] == 1
    assert k["divergentes"] == 0


def test_cobertura_e_declarada_como_fracao():
    l = consumo.cruzar([_tel(km=800.0, litros=200.0, km_l=4.0)],
                       [_ava(litros=250.0, km=1000.0)])[0]
    assert round(l["cobertura_tel"], 2) == 0.80
    assert l["telemetria_incompleta"] is False


def test_leitura_implausivel_tambem_fica_fora_da_comparacao():
    l = consumo.cruzar([_tel(km=1000.0, litros=50.0, km_l=20.0)],
                       [_ava(litros=250.0, km=1000.0)])[0]
    assert l["suspeito"] is True
    assert l["delta_pct"] is None


def test_km_l_implausivel_do_ava_tambem_barra_a_comparacao():
    """OHT7F16 em julho/2026: 0,14 km/l pelo abastecimento gerava delta de
    +1.765%. Isso é distância mal lançada no abastecimento, não consumo."""
    l = consumo.cruzar([_tel(km=1000.0, litros=380.0, km_l=2.65)],
                       [_ava(litros=7000.0, km=980.0)])[0]
    assert l["ava_implausivel"] is True
    assert l["delta_pct"] is None
    assert consumo.resumir([l])["divergentes"] == 0
