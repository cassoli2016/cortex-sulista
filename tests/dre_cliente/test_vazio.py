"""Testes da atribuicao de km vazio ao cliente originador."""
from __future__ import annotations

from api.dre_cliente.vazio import atribuir_vazio


def _v(id, veiculo, t, tipo, cliente=None):
    return {"id": id, "veiculo": veiculo, "dtsaida": t, "tipo": tipo,
            "cliente": cliente, "km": 100.0}


def test_retorno_vazio_vai_para_carregada_anterior():
    viagens = [_v(1, "AAA", 1, tipo=1, cliente="A"), _v(2, "AAA", 2, tipo=3)]
    assert atribuir_vazio(viagens) == {2: "A"}


def test_posicionamento_vai_para_proxima_carga():
    viagens = [_v(1, "AAA", 1, tipo=3), _v(2, "AAA", 2, tipo=1, cliente="B")]
    assert atribuir_vazio(viagens) == {1: "B"}


def test_dois_vazios_consecutivos_apos_carregada():
    viagens = [_v(1, "AAA", 1, tipo=1, cliente="A"),
               _v(2, "AAA", 2, tipo=3), _v(3, "AAA", 3, tipo=3)]
    r = atribuir_vazio(viagens)
    assert r == {2: "A", 3: "A"}


def test_vazio_entre_duas_carregadas_empate_prefere_proxima():
    viagens = [_v(1, "AAA", 1, tipo=1, cliente="A"),
               _v(2, "AAA", 2, tipo=3),
               _v(3, "AAA", 3, tipo=1, cliente="B")]
    assert atribuir_vazio(viagens)[2] == "B"


def test_vazio_sem_carregada_no_veiculo_fica_none():
    viagens = [_v(1, "AAA", 1, tipo=3)]
    assert atribuir_vazio(viagens) == {1: None}


def test_nao_cruza_veiculos():
    viagens = [_v(1, "AAA", 1, tipo=1, cliente="A"), _v(2, "BBB", 2, tipo=3)]
    assert atribuir_vazio(viagens) == {2: None}
