"""A última leitura boa, servida quando o ERP não responde.

O ERP é réplica de produção de TERCEIRO e tem dia ruim. Em 03/09/2026 ele
degradou das 05h às 05h40: `SELECT 1` respondia na hora e as consultas pesadas
estouravam o `statement_timeout`. A Visão Geral morria inteira e a manhã
começou sem painel.

Medido depois, com o ERP são: a consulta que não voltava em 120 s roda em
0,13 s. Não havia nada para otimizar — havia uma dependência externa fora do
nosso controle. O que dá para consertar do nosso lado é a tela não morrer.

A regra que estes testes guardam: um número de vinte minutos atrás, DITO na
tela, é honesto e serve para trabalhar; tela em branco não é nenhum dos dois.
O que não se faz é servir o número velho CALADO — quem serve carimba, e a tela
é obrigada a mostrar.
"""
from __future__ import annotations

import time

import pytest

from api import queries


@pytest.fixture(autouse=True)
def cache_limpo():
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


def _fonte(estado):
    """Uma função cacheável que obedece a `estado` — quebra quando mandado."""
    @queries.cached(ttl=0, velha_ate=3600)
    def consulta():
        if estado["quebrar"]:
            raise RuntimeError("canceling statement due to statement timeout")
        estado["chamadas"] += 1
        return {"saldo": estado["valor"]}
    return consulta


def test_a_leitura_boa_volta_quando_o_erp_cai(cache_limpo):
    estado = {"quebrar": False, "valor": 100.0, "chamadas": 0}
    consulta = _fonte(estado)
    assert consulta() == {"saldo": 100.0}

    estado["quebrar"] = True
    d = consulta()
    assert d["saldo"] == 100.0, "perdeu o número que já tinha"
    assert d["leitura_velha"] is True
    assert "leitura_em" in d and "leitura_idade_seg" in d


def test_a_leitura_velha_NUNCA_vai_calada(cache_limpo):
    """Número velho sem carimbo é pior que tela vazia: ninguém desconfia dele."""
    estado = {"quebrar": False, "valor": 7.0, "chamadas": 0}
    consulta = _fonte(estado)
    consulta()
    estado["quebrar"] = True
    assert consulta().get("leitura_velha") is True


def test_a_leitura_velha_e_uma_COPIA_do_que_esta_guardado(cache_limpo):
    """Devolve-se uma cópia, nunca o objeto do cache.

    ESTE TESTE NASCEU ERRADO e vale contar: a primeira versão afirmava que "o
    carimbo não gruda na próxima leitura boa" e passava mesmo com a cópia
    removida — porque a leitura boa seguinte SUBSTITUI a entrada do cache, e o
    objeto carimbado é descartado de qualquer jeito. Era verde que nunca
    ficaria vermelho.

    O que a cópia protege de verdade é o cache ser corrompido por quem RECEBE
    o dicionário: rota que acrescenta uma chave (a de auditoria faz isso) ou
    tela que ordena uma lista mexeriam no que está guardado. Então o que se
    afirma aqui é o que se pode provar: o objeto devolvido não é o do cache."""
    estado = {"quebrar": False, "valor": 1.0, "chamadas": 0}
    consulta = _fonte(estado)
    consulta()
    estado["quebrar"] = True
    d = consulta()
    guardado = next(iter(queries._RESP_CACHE.values()))[1]
    assert d is not guardado, "devolveu o proprio objeto do cache"
    assert "leitura_velha" not in guardado, "carimbou o que esta guardado"

    # e quem recebe pode mexer sem estragar o cache
    d["saldo"] = 999.0
    assert guardado["saldo"] == 1.0


def test_leitura_velha_DEMAIS_vira_erro(cache_limpo):
    """Número de meio período atrás não serve nem carimbado."""
    @queries.cached(ttl=0, velha_ate=60)
    def consulta():
        if getattr(consulta, "quebrar", False):
            raise RuntimeError("timeout")
        return {"x": 1}
    consulta()
    # envelhece a entrada do cache à mão
    chave = next(iter(queries._RESP_CACHE))
    velho, valor = queries._RESP_CACHE[chave]
    queries._RESP_CACHE[chave] = (velho - 3600, valor)
    consulta.quebrar = True
    with pytest.raises(RuntimeError):
        consulta()


def test_sem_leitura_anterior_o_erro_sobe(cache_limpo):
    """Primeira consulta do dia com o ERP fora: não há o que servir, e inventar
    zero seria pior."""
    @queries.cached(ttl=0, velha_ate=3600)
    def consulta():
        raise RuntimeError("timeout")
    with pytest.raises(RuntimeError):
        consulta()


def test_quem_nao_pediu_a_leitura_velha_continua_quebrando(cache_limpo):
    """`velha_ate` é opt-in: o comportamento antigo é o padrão, e uma consulta
    que não declarou nada não passa a servir número velho por tabela."""
    estado = {"quebrar": False}

    @queries.cached(ttl=0)
    def consulta():
        if estado["quebrar"]:
            raise RuntimeError("timeout")
        return {"x": 1}

    consulta()
    estado["quebrar"] = True
    with pytest.raises(RuntimeError):
        consulta()


def test_o_ttl_normal_continua_valendo(cache_limpo):
    """Com o ERP são, nada muda: dentro do TTL não se consulta de novo."""
    estado = {"quebrar": False, "valor": 5.0, "chamadas": 0}

    @queries.cached(ttl=300, velha_ate=3600)
    def consulta():
        estado["chamadas"] += 1
        return {"saldo": estado["valor"]}

    consulta(); consulta(); consulta()
    assert estado["chamadas"] == 1


def test_a_visao_geral_declara_a_janela_de_duas_horas():
    """A tela que quebrou é a que mais custa ficar sem — e a janela é escolha
    registrada, não acidente."""
    import inspect
    fonte = inspect.getsource(queries)
    assert "@cached(ttl=60, velha_ate=2 * 3600)\ndef get_visao_geral" in fonte
