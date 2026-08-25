"""Detecção de chegada/saída por cerca geográfica.

Cada teste aqui corresponde a um jeito real de errar o horário — e é por isso
que a automação existe: hoje 46% das chegadas são digitadas com segundo `:00`
e há 1.462 viagens em 30 dias entre cidades diferentes com duração menor que
15 minutos.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api.milkrun import deteccao as d

# MWM São Paulo (do cadastro do ERP)
LAT, LNG = -23.674342, -46.701986


def _p(minuto, lat, lng, base=datetime(2026, 8, 25, 6, 0)):
    return {"dt": base + timedelta(minutes=minuto), "lat": lat, "lng": lng}


def _perto(m):
    """Ponto a ~m metros ao norte do alvo (1 grau de lat ~ 111.320 m)."""
    return LAT + m / 111_320.0, LNG


def test_distancia_bate_com_a_realidade():
    """Haversine, não diferença de graus: um grau de longitude vale ~102 km no
    equador e ~92 km no Sul, e com raio de 300 m isso erraria a cerca."""
    lat2, lng2 = _perto(1000)
    assert 995 <= d.distancia_m(LAT, LNG, lat2, lng2) <= 1005


def test_permanencia_vira_visita_com_chegada_e_saida():
    lat_in, lng_in = _perto(100)
    lat_out, lng_out = _perto(5000)
    pos = [_p(0, lat_out, lng_out)] + [_p(i, lat_in, lng_in) for i in (6, 12, 18, 24, 30)] \
        + [_p(36, lat_out, lng_out)]
    v = d.detectar(pos, LAT, LNG)
    assert len(v) == 1
    assert v[0].chegada == datetime(2026, 8, 25, 6, 6)
    # saida fica no MEIO entre a ultima dentro (30) e a primeira fora (36)
    assert v[0].saida == datetime(2026, 8, 25, 6, 33)
    assert not v[0].em_andamento


def test_passagem_rapida_nao_conta_como_visita():
    """Caminhão que passa em frente a caminho de outro lugar entra e sai do
    raio em um ou dois pings — contar isso como coleta seria inventar."""
    lat_in, lng_in = _perto(100)
    lat_out, lng_out = _perto(5000)
    pos = [_p(0, lat_out, lng_out), _p(6, lat_in, lng_in), _p(12, lat_out, lng_out)]
    assert d.detectar(pos, LAT, LNG) == []


def test_lacuna_no_rastro_nao_encerra_a_visita():
    """O rastreador dorme e o caminhão entra em galpão coberto. Fechar no
    primeiro ping ausente marcaria saída no meio do carregamento."""
    lat_in, lng_in = _perto(80)
    lat_out, lng_out = _perto(5000)
    pos = [_p(0, lat_in, lng_in), _p(90, lat_in, lng_in),   # 90 min sem ping
           _p(96, lat_out, lng_out)]
    v = d.detectar(pos, LAT, LNG)
    assert len(v) == 1
    assert v[0].minutos > 90


def test_ainda_no_local_nao_ganha_horario_de_saida():
    """Marcar saída = última posição diria 'já saiu' sobre um caminhão que
    está carregando agora."""
    lat_in, lng_in = _perto(80)
    pos = [_p(i, lat_in, lng_in) for i in (0, 6, 12, 18)]
    v = d.detectar(pos, LAT, LNG)
    assert len(v) == 1 and v[0].em_andamento and v[0].saida is None


def test_posicao_zero_zero_e_descartada():
    """lat/lng zerados são rastreador sem fix, não o Golfo da Guiné."""
    lat_in, lng_in = _perto(80)
    pos = [{"dt": datetime(2026, 8, 25, 6, 0), "lat": 0, "lng": 0},
           _p(6, lat_in, lng_in), _p(12, lat_in, lng_in), _p(30, lat_in, lng_in)]
    v = d.detectar(pos, LAT, LNG)
    assert len(v) == 1 and v[0].chegada == datetime(2026, 8, 25, 6, 6)


def test_rastro_fora_de_ordem_nao_parte_a_visita():
    """Rastro que chega em lotes vem desordenado; sem ordenar, uma visita
    viraria duas."""
    lat_in, lng_in = _perto(80)
    pos = [_p(30, lat_in, lng_in), _p(6, lat_in, lng_in), _p(18, lat_in, lng_in)]
    assert len(d.detectar(pos, LAT, LNG)) == 1


def test_duas_passagens_no_dia_escolhe_a_do_agendamento():
    """Coleta de manhã e retorno à tarde: pegar a primeira marcaria a
    passagem errada."""
    lat_in, lng_in = _perto(80)
    lat_out, lng_out = _perto(5000)
    pos = ([_p(i, lat_in, lng_in) for i in (0, 6, 12, 18)]
           + [_p(30, lat_out, lng_out)]
           + [_p(i, lat_in, lng_in) for i in (480, 486, 492, 498)]
           + [_p(510, lat_out, lng_out)])
    vs = d.detectar(pos, LAT, LNG)
    assert len(vs) == 2
    tarde = d.visita_da_janela(vs, datetime(2026, 8, 25, 14, 0))
    assert tarde.chegada.hour == 14


def test_visita_fora_da_tolerancia_nao_e_atribuida():
    """Melhor dizer 'não chegou' que casar a visita errada."""
    lat_in, lng_in = _perto(80)
    lat_out, lng_out = _perto(5000)
    pos = [_p(i, lat_in, lng_in) for i in (0, 6, 12, 18)] + [_p(30, lat_out, lng_out)]
    vs = d.detectar(pos, LAT, LNG)
    assert d.visita_da_janela(vs, datetime(2026, 8, 25, 23, 0)) is None


@pytest.mark.parametrize("atraso,esperado", [
    (-90, "adiantado"), (-10, "no prazo"), (0, "no prazo"),
    (20, "no prazo"), (75, "atrasado"),
])
def test_semaforo_de_pontualidade(atraso, esperado):
    prev = datetime(2026, 8, 25, 8, 0)
    v = d.Visita(chegada=prev + timedelta(minutes=atraso),
                 saida=prev + timedelta(minutes=atraso + 40),
                 posicoes=5, minutos=40, distancia_min_m=50)
    assert d.classificar(v, prev)["pontualidade"] == esperado


def test_sem_janela_nao_inventa_atraso():
    """Julgar pontualidade contra referência inexistente é alarme falso."""
    v = d.Visita(chegada=datetime(2026, 8, 25, 8, 0), saida=None,
                 posicoes=3, minutos=20, distancia_min_m=50)
    r = d.classificar(v, None)
    assert r["pontualidade"] == "sem janela" and r["atraso_min"] is None


def test_ponto_nao_visitado_fica_aguardando():
    r = d.classificar(None, datetime(2026, 8, 25, 8, 0))
    assert r["estado"] == "aguardando"


# ---------------------------------------------------------------------------
# Velocidade separa PARAR de PASSAR. Caso real: viagem 175882 (São Bernardo),
# veículo a 209 m do ponto — dentro do raio — e a visita sumia porque só houve
# um ping lá dentro antes de o rastreador calar.
# ---------------------------------------------------------------------------

def _pv(minuto, lat, lng, vel, base=datetime(2026, 8, 25, 6, 0)):
    return {"dt": base + timedelta(minutes=minuto), "lat": lat, "lng": lng,
            "velocidade": vel}


def test_parada_curta_com_veiculo_parado_conta_como_visita():
    lat_in, lng_in = _perto(100)
    lat_out, lng_out = _perto(5000)
    pos = [_pv(0, lat_out, lng_out, 70),
           _pv(6, lat_in, lng_in, 0),      # parado dentro do raio
           _pv(12, lat_out, lng_out, 65)]
    v = d.detectar(pos, LAT, LNG)
    assert len(v) == 1 and v[0].parou


def test_passagem_em_movimento_continua_descartada():
    """Velocidade sozinha não basta: caminhão a 60 km/h cruzando o raio não
    parou ali."""
    lat_in, lng_in = _perto(100)
    lat_out, lng_out = _perto(5000)
    pos = [_pv(0, lat_out, lng_out, 70),
           _pv(6, lat_in, lng_in, 62),
           _pv(12, lat_out, lng_out, 68)]
    assert d.detectar(pos, LAT, LNG) == []


def test_velocidade_ausente_nao_vira_parada():
    """Rastreador sem o campo não pode virar coleta que nunca houve."""
    lat_in, lng_in = _perto(100)
    lat_out, lng_out = _perto(5000)
    pos = [{"dt": datetime(2026, 8, 25, 6, 0), "lat": lat_out, "lng": lng_out},
           {"dt": datetime(2026, 8, 25, 6, 6), "lat": lat_in, "lng": lng_in},
           {"dt": datetime(2026, 8, 25, 6, 12), "lat": lat_out, "lng": lng_out}]
    assert d.detectar(pos, LAT, LNG) == []


def test_permanencia_longa_ainda_vale_sem_velocidade():
    """A regra antiga continua valendo — as duas somam, não se substituem."""
    lat_in, lng_in = _perto(100)
    lat_out, lng_out = _perto(5000)
    pos = [_p(0, lat_out, lng_out)] + [_p(i, lat_in, lng_in) for i in (6, 20, 40)] \
        + [_p(50, lat_out, lng_out)]
    v = d.detectar(pos, LAT, LNG)
    assert len(v) == 1 and not v[0].parou
