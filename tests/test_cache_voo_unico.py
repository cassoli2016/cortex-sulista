# -*- coding: utf-8 -*-
"""O cache de respostas: TTL, VOO ÚNICO e última leitura boa.

O voo único nasceu de um incidente medido em 04/09/2026: `/api/health` em 503
por ~50 minutos com o banco SÃO o tempo todo — uma conexão nova respondia em
0,1 s enquanto a API não conseguia nenhuma em 15 s.

A conta que explica: a Visão Geral abre `ThreadPoolExecutor(len(grupos)+1)` = 5
workers e cada um segura UMA conexão do pool. Com o cache frio e duas pessoas
abrindo a tela ao mesmo tempo, eram 10 conexões pedidas de um pool de 6 — e a
terceira pessoa levava `PoolTimeout`. O painel se derrubava sozinho sempre que
o ERP ficava lento o bastante para as consultas não saírem de cima da vaga.

Com a trava, a primeira consulta corre e as outras esperam por ela.
"""
from __future__ import annotations

import threading
import time

import pytest

from api import queries


@pytest.fixture(autouse=True)
def _cache_limpo():
    queries._RESP_CACHE.clear()
    with queries._RESP_LOCKS_GUARD:
        queries._RESP_LOCKS.clear()
    yield
    queries._RESP_CACHE.clear()
    with queries._RESP_LOCKS_GUARD:
        queries._RESP_LOCKS.clear()


def test_dez_chamadas_simultaneas_consultam_UMA_vez():
    """O guard central. Sem a trava isto dá 10 e o pool de conexões estoura."""
    chamadas = []
    barreira = threading.Barrier(10)

    @queries.cached(ttl=60)
    def consulta_cara():
        chamadas.append(1)
        time.sleep(0.25)          # a janela em que todas colidiriam
        return {"valor": 42}

    def bate():
        barreira.wait()           # todas partem juntas, como na tela real
        return consulta_cara()

    threads = [threading.Thread(target=bate) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(chamadas) == 1, (
        "%d idas ao ERP para a mesma pergunta — é o defeito que derrubou o "
        "painel" % len(chamadas))


def test_quem_espera_recebe_a_MESMA_resposta():
    """Esperar não pode virar 'recebeu nada': a fila tem de sair com o valor."""
    barreira = threading.Barrier(6)
    saidas = []
    trava_saida = threading.Lock()

    @queries.cached(ttl=60)
    def consulta():
        time.sleep(0.2)
        return {"valor": 7}

    def bate():
        barreira.wait()
        r = consulta()
        with trava_saida:
            saidas.append(r)

    threads = [threading.Thread(target=bate) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(saidas) == 6
    assert all(s == {"valor": 7} for s in saidas)


def test_chaves_diferentes_nao_esperam_uma_pela_outra():
    """A trava é POR CHAVE. Uma trava global transformaria o cache num
    gargalo: a DRE de 40 s seguraria a tela de outra pessoa."""
    ordem = []

    @queries.cached(ttl=60)
    def consulta(qual):
        if qual == "lenta":
            time.sleep(0.4)
        ordem.append(qual)
        return {"qual": qual}

    t1 = threading.Thread(target=lambda: consulta("lenta"))
    t1.start()
    time.sleep(0.05)
    t2 = threading.Thread(target=lambda: consulta("rapida"))
    t2.start()
    t1.join()
    t2.join()

    assert ordem == ["rapida", "lenta"], (
        "a consulta rápida esperou a lenta: a trava não é por chave")


def test_o_ttl_continua_valendo():
    chamadas = []

    @queries.cached(ttl=0.15)
    def consulta():
        chamadas.append(1)
        return {"n": len(chamadas)}

    assert consulta() == {"n": 1}
    assert consulta() == {"n": 1}          # dentro do TTL: veio do cache
    time.sleep(0.25)
    assert consulta() == {"n": 2}          # expirou: consultou de novo


def test_a_ultima_leitura_boa_ainda_e_servida_e_carimbada():
    """A trava não pode ter comido o `velha_ate` — é ele que segura o painel
    de pé no dia ruim do ERP."""
    estado = {"falhar": False}

    @queries.cached(ttl=0.05, velha_ate=3600)
    def consulta():
        if estado["falhar"]:
            raise RuntimeError("ERP fora")
        return {"valor": 1}

    assert consulta() == {"valor": 1}
    time.sleep(0.1)
    estado["falhar"] = True
    r = consulta()
    assert r["valor"] == 1
    assert r["leitura_velha"] is True
    assert "leitura_em" in r and "leitura_idade_seg" in r
    # e o carimbo NÃO ficou grudado no que está guardado
    estado["falhar"] = False
    time.sleep(0.1)
    assert "leitura_velha" not in consulta()


def test_sem_leitura_boa_a_falha_sobe():
    @queries.cached(ttl=60, velha_ate=3600)
    def consulta():
        raise RuntimeError("ERP fora")

    with pytest.raises(RuntimeError):
        consulta()


def test_a_falha_nao_deixa_a_trava_presa():
    """Exceção dentro da trava tem de liberá-la — senão o primeiro erro
    congela aquela chave para sempre, e o remédio vira a doença."""
    estado = {"falhar": True}

    @queries.cached(ttl=60)
    def consulta():
        if estado["falhar"]:
            raise RuntimeError("ERP fora")
        return {"ok": True}

    with pytest.raises(RuntimeError):
        consulta()
    estado["falhar"] = False
    assert consulta() == {"ok": True}      # travaria aqui se não liberasse


def test_o_pool_cabe_o_maior_leque_da_casa():
    """`max_size` tem de ser maior que o maior leque de threads da casa.

    A Visão Geral abre `len(grupos) + 1` = 5 conexões de uma vez. Com o pool
    em 6, sobrava UMA vaga para o sistema inteiro.
    """
    import inspect

    from api import db

    fonte = inspect.getsource(db._get_pool)
    assert "max_size=16" in fonte, "o pool encolheu de novo"
    assert "min_size=2" in fonte


# --------------------------------------------------------------------------
# a chave: nome não basta
# --------------------------------------------------------------------------
def test_funcoes_HOMONIMAS_de_modulos_diferentes_NAO_dividem_a_entrada():
    """O guard de um defeito real, 05/09/2026.

    A chave era `(nome, args, kwargs)`. `api/pneus/km._calcular` e
    `api/pneus/cpk._calcular` — mesmo nome, mesmo argumento — passaram a
    dividir a MESMA entrada, e a segunda recebia o resultado da primeira.

    O que salvou foi a sorte: os dois payloads eram diferentes o bastante para
    estourar um `KeyError` longe daqui. Se tivessem campos parecidos — dois
    módulos calculando "km" ou "total", que é o normal nesta casa — teria
    virado número errado em tela, calado, sem exceção nenhuma para investigar.

    `_calcular`, `_dados`, `_montar` são nomes que se repetem naturalmente
    entre módulos; o guard existe para o próximo par não custar a mesma tarde.
    """
    import types

    from api import queries

    def _faz(modulo: str, valor: str):
        fn = lambda n: {"quem": valor, "n": n}   # noqa: E731
        fn.__name__ = "_calcular"
        fn.__module__ = modulo
        return queries.cached(600)(fn)

    queries._RESP_CACHE.clear()
    try:
        a = _faz("api.um.alfa", "alfa")
        b = _faz("api.dois.beta", "beta")
        assert a(365)["quem"] == "alfa"
        assert b(365)["quem"] == "beta", "a segunda recebeu o cache da primeira"
        # e cada uma continua sendo cacheada de verdade
        assert a(365)["quem"] == "alfa"
        assert len(queries._RESP_CACHE) == 2
    finally:
        queries._RESP_CACHE.clear()
