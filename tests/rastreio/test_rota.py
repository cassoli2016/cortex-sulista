# -*- coding: utf-8 -*-
"""A rota que o veículo deve fazer, e o progresso ao longo dela.

POR QUE A LINHA RETA SAIU. Ela subestima sempre. Medido nas mesmas cargas,
antes e depois:

    CT-e 268146   reta: faltam 56 km      rota: faltam 73 km  (617 km de rota)
    CT-e 359163   reta: 38%, faltam 22 km rota: 16%, faltam 88 km (105 km)

O segundo é uma milk-run com várias paradas: a reta dizia 22 km, a estrada tem
88. Erro de quatro vezes, num número que quem espera na doca usa para chamar a
equipe.

A FONTE ESTAVA NO BANCO, pela terceira vez no mesmo dia. Fui procurar o KML no
webservice do gerenciador de risco e a rota já estava no ERP: `coleta.trajeto`
aponta o trajeto, `trajeto.extensao` é o km rodoviário (93% das rotas ativas) e
`trajeto_percurso` traz os pontos (coordenada em 33.260 de 33.260).
"""
from __future__ import annotations

import pytest

from api.rastreio import rota


# Um corredor em L: desce em latitude e depois anda em longitude. Uma reta
# entre as pontas cortaria o canto e mediria bem menos que o caminho.
PONTOS = [
    {"lat": -23.0, "lng": -46.0, "rodovia": "BR-116"},
    {"lat": -24.0, "lng": -46.0, "rodovia": "BR-116"},
    {"lat": -24.0, "lng": -47.0, "rodovia": "SP-270"},
]
ROTA = {"codigo": 1, "extensao_km": 400.0, "pontos": PONTOS}


def test_o_progresso_anda_ao_longo_da_ROTA_e_nao_da_reta():
    """No começo do segundo trecho, metade da poligonal ficou para trás — e a
    reta entre as pontas diria outra coisa, porque ela corta o canto do L."""
    p = rota.progresso(ROTA, -24.0, -46.0)
    assert 40 <= p["progresso_pct"] <= 60


def test_o_km_que_falta_sai_da_EXTENSAO_rodoviaria():
    """A poligonal dá a forma; a `extensao` dá o tamanho. O que falta é sempre
    km de asfalto, nunca de reta."""
    p = rota.progresso(ROTA, -24.0, -46.0)
    assert p["rota_km"] == 400
    assert p["percorrido_km"] + p["falta_km"] == pytest.approx(400, abs=1)


def test_no_comeco_e_no_fim_os_extremos_batem():
    ini = rota.progresso(ROTA, -23.0, -46.0)
    fim = rota.progresso(ROTA, -24.0, -47.0)
    assert ini["progresso_pct"] == 0 and ini["falta_km"] == 400
    assert fim["progresso_pct"] == 100 and fim["falta_km"] == 0


def test_o_afastamento_da_rota_e_medido():
    """É o que distingue 'está na rota, no meio dela' de 'está em outra
    viagem' — e é melhor que comparar distâncias, porque não depende de o
    destino estar à frente."""
    perto = rota.progresso(ROTA, -23.5, -46.02)
    longe = rota.progresso(ROTA, -8.0, -35.0)
    assert perto["afastado_km"] < 5
    assert longe["afastado_km"] > 500


def test_rota_com_um_ponto_so_nao_e_rota():
    """Um ponto é um endereço. Devolver isso faria a tela desenhar uma linha de
    tamanho zero e um progresso sem denominador."""
    assert rota.progresso({"extensao_km": 100.0, "pontos": PONTOS[:1]},
                          -23.0, -46.0) is None


def test_sem_extensao_nao_inventa_km():
    """Sem o km rodoviário cadastrado, o progresso ainda existe (a forma
    basta), mas a distância NÃO é estimada a partir da poligonal — ela seria
    reta com outro nome."""
    p = rota.progresso({"codigo": 1, "extensao_km": 0, "pontos": PONTOS},
                       -24.0, -46.0)
    assert p is not None
    assert "falta_km" not in p and "rota_km" not in p


# --------------------------------------------------------------------------
# o defeito que quase passou calado
# --------------------------------------------------------------------------
def test_a_consulta_da_rota_NAO_castea_interval():
    """O guard que existe por um erro que se escondeu sozinho.

    `trajeto.quantidadehorasprevistas` é `interval` no ERP, e o
    `::float8` que eu tinha posto sobre ela derrubava a consulta INTEIRA com
    "cannot cast type interval to double precision". Como o módulo captura a
    exceção e devolve `None` — que é o certo, para o ERP com dia ruim não
    derrubar a página —, o sintoma era só a rota sumir. Nenhum erro na tela,
    nenhuma linha vermelha: o progresso simplesmente voltava a ser em linha
    reta, que é um número plausível.
    """
    # O INVARIANTE E O CAST, nao a mencao: a primeira versao deste teste
    # procurava o nome do campo e ficava vermelha por causa do proprio
    # comentario que explica por que ele nao entra. Duas vezes no mesmo dia —
    # teste afirma COMPORTAMENTO, nunca texto-fonte.
    assert "quantidadehorasprevistas::" not in rota.ROTA_SQL
    assert "AS horas" not in rota.ROTA_SQL


def test_ponto_com_coordenada_zerada_fica_de_fora():
    """(0,0) é no golfo da Guiné. Um ponto ali entortaria a poligonal inteira
    e jogaria o progresso para perto de zero em toda a frota."""
    assert "latitude <> 0" in rota.PONTOS_SQL
    assert "longitude <> 0" in rota.PONTOS_SQL


def test_a_rota_exige_extensao_util():
    """Rota sem km cadastrado não serve para medir distância — e é melhor cair
    para a reta declarada do que publicar um `falta_km` de zero."""
    assert "coalesce(t.extensao,0) > 0" in rota.ROTA_SQL
