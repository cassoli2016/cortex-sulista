# -*- coding: utf-8 -*-
"""CPK — o número que decide a próxima compra de pneu.

O QUE ESTES GUARDS PROTEGEM. Um CPK errado não parece errado: parece um pneu
que rendeu bem ou mal. Três enganos apareceram na primeira medição real, e os
três davam números com cara de verdade:

1. Pneu de segunda vida com o preço do pneu NOVO. Erra 2,5× (R$ 1.500 × R$ 610)
   e sempre no mesmo sentido — faz o recapado parecer caro.
2. Custo de R$ 0,01 e de R$ 1.300.001,10 no mesmo campo. O primeiro vira CPK
   zero e encabeça o ranking dos melhores; o segundo vira CPK absurdo.
3. Pneu montado há três semanas liderando a lista dos PIORES. Ele não tem
   defeito nenhum — só não rodou. Ranking sem piso pune sempre o pneu que
   acabou de ser comprado.
"""
from __future__ import annotations

import pytest

from api.pneus import cpk


@pytest.fixture(autouse=True)
def cache_limpo():
    from api import queries
    queries._RESP_CACHE.clear()
    yield
    queries._RESP_CACHE.clear()


@pytest.fixture
def cenario(monkeypatch):
    """Substitui o banco local e o km. Nenhum dos dois é o assunto aqui."""
    estado = {"pneus": [], "km": {}}

    monkeypatch.setattr(cpk.pglocal, "query",
                        lambda sql, p=None: list(estado["pneus"]))

    def _no_periodo(placa, de, ate=None, dias_janela=365):
        v = estado["km"].get(placa)
        if v is None:
            return {"km": None, "dias_com_dado": 0, "motivo": "sem leitura"}
        return {"km": v, "dias_com_dado": 30, "metodo": "odometro"}

    monkeypatch.setattr(cpk.kmmod, "no_periodo", _no_periodo)
    return estado


def _pneu(id_, placa, **kw):
    base = {"id": id_, "placa": placa, "posicao_atual": "1DE", "vida_atual": 1,
            "custo_aquisicao": 1500, "filial": "MTZ", "status": "instalado",
            "marca": "Durable", "modelo": "DR766", "medida": "295/80 R22.5",
            "desenho": None, "instalado_em": None, "custo_recapagem": None}
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# o custo é o da VIDA
# --------------------------------------------------------------------------
def test_pneu_recapado_usa_o_custo_da_RECAPAGEM(cenario):
    """Usar o preço do pneu novo em toda vida erra 2,5× — e sempre contra o
    recapado, que é justamente a decisão que a operação quer avaliar."""
    cenario["pneus"] = [_pneu(1, "ABC1D23", vida_atual=3,
                              custo_aquisicao=1500, custo_recapagem=610)]
    cenario["km"] = {"ABC1D23": 50000.0}
    i = cpk.obter()["itens"][0]
    assert i["custo"] == 610.0 and i["custo_origem"] == "recapagem"
    assert i["cpk"] == round(610 / 50000, 4)


def test_recapado_SEM_custo_de_recapagem_nao_cai_no_preco_de_compra(cenario):
    """Cair no preço de compra seria pior que não responder: daria um número
    concreto e errado, e ninguém desconfia de número concreto."""
    cenario["pneus"] = [_pneu(1, "ABC1D23", vida_atual=2,
                              custo_aquisicao=1500, custo_recapagem=None)]
    cenario["km"] = {"ABC1D23": 50000.0}
    i = cpk.obter()["itens"][0]
    assert i["cpk"] is None and "recapagem" in i["motivo"]


# --------------------------------------------------------------------------
# faixa física do custo
# --------------------------------------------------------------------------
@pytest.mark.parametrize("valor", [0.01, 48.0, 1300001.10])
def test_custo_fora_da_faixa_e_LACUNA_e_nao_CPK(cenario, valor):
    """R$ 0,01 vira CPK zero e encabeça o ranking dos melhores. Zero que é
    cadastro furado não é pneu barato."""
    cenario["pneus"] = [_pneu(1, "ABC1D23", custo_aquisicao=valor)]
    cenario["km"] = {"ABC1D23": 50000.0}
    d = cpk.obter()
    i = d["itens"][0]
    assert i["cpk"] is None
    assert "faixa" in i["motivo"]
    assert d["custo_fora_da_faixa"] == 1
    # O BRUTO VAI JUNTO: quem for corrigir o cadastro precisa ver o que está lá.
    assert i["custo_bruto"] == valor


def test_a_faixa_deixa_passar_o_pneu_de_verdade(cenario):
    """Mediana medida no cadastro: R$ 1.500. p99: R$ 2.405. A faixa existe para
    cortar digitação, não para discutir preço de pneu premium."""
    for v in (400.0, 1500.0, 2405.0, 4900.0):
        cenario["pneus"] = [_pneu(1, "ABC1D23", custo_aquisicao=v)]
        cenario["km"] = {"ABC1D23": 50000.0}
        from api import queries
        queries._RESP_CACHE.clear()
        assert cpk.obter()["itens"][0]["cpk"] is not None, v


# --------------------------------------------------------------------------
# piso de materialidade
# --------------------------------------------------------------------------
def test_pneu_novo_fica_EM_FORMACAO_e_nao_entre_os_piores(cenario):
    """Um pneu com 1.242 km sai com CPK de R$ 1,20/km e lidera os piores sem
    ter nada de errado."""
    cenario["pneus"] = [_pneu(1, "ABC1D23"), _pneu(2, "XYZ9Z99")]
    cenario["km"] = {"ABC1D23": 1242.0, "XYZ9Z99": 50000.0}
    d = cpk.obter()
    novo = [i for i in d["itens"] if i["id"] == 1][0]
    assert novo["cpk"] is None
    assert "piso" in novo["motivo"]
    assert d["em_formacao"] == 1 and d["avaliados"] == 1


def test_o_piso_se_DECLARA_no_payload(cenario):
    """Filtro escondido vira verdade do sistema. Quem lê a tela tem de saber
    que 176 pneus ficaram de fora e por quê."""
    cenario["pneus"] = [_pneu(1, "ABC1D23")]
    cenario["km"] = {"ABC1D23": 50000.0}
    d = cpk.obter()
    assert d["piso_km"] == cpk.KM_MINIMO
    assert d["faixa_custo"] == [cpk.CUSTO_MIN, cpk.CUSTO_MAX]


def test_sem_km_NAO_vira_CPK_infinito(cenario):
    cenario["pneus"] = [_pneu(1, "ABC1D23")]
    cenario["km"] = {}
    d = cpk.obter()
    assert d["itens"][0]["cpk"] is None and d["sem_km"] == 1


# --------------------------------------------------------------------------
# a lista sai ordenada de verdade
# --------------------------------------------------------------------------
def test_a_lista_sai_ORDENADA_e_os_sem_CPK_vao_para_o_fim(cenario):
    """Ordenar só uma cópia interna deixa a ordenação virar código morto — e
    quem ler `itens` acha que está ordenado. Aconteceu na primeira versão."""
    cenario["pneus"] = [_pneu(1, "AAA1A11"), _pneu(2, "BBB2B22"),
                        _pneu(3, "CCC3C33")]
    cenario["km"] = {"AAA1A11": 50000.0, "BBB2B22": 100000.0}
    itens = cpk.obter()["itens"]
    cpks = [i["cpk"] for i in itens]
    assert cpks[0] is not None and cpks[0] <= cpks[1]
    assert cpks[-1] is None, "pneu sem CPK ficou no meio da lista"


# --------------------------------------------------------------------------
# por modelo
# --------------------------------------------------------------------------
def test_por_modelo_usa_MEDIANA_e_nao_media(cenario):
    """Um pneu com CPK de 70× move a média o bastante para se inocentar, e a
    régua passa a caber em cima do próprio outlier."""
    cenario["pneus"] = [_pneu(i, "P%03d" % i) for i in range(1, 6)]
    cenario["km"] = {"P%03d" % i: 50000.0 for i in range(1, 5)}
    cenario["km"]["P005"] = 20000.0     # o caro da turma
    m = cpk.por_modelo()["modelos"][0]
    assert m["cpk_mediano"] == round(1500 / 50000, 4)


def test_modelo_com_POUCOS_pneus_se_declara_sem_base(cenario):
    """Chamar de "melhor" o que se mediu em três pneus é o jeito de comprar
    errado com confiança."""
    cenario["pneus"] = [_pneu(1, "AAA1A11"), _pneu(2, "BBB2B22")]
    cenario["km"] = {"AAA1A11": 50000.0, "BBB2B22": 50000.0}
    r = cpk.por_modelo()
    assert r["modelos"][0]["suficiente"] is False
    assert r["com_base"] == 0 and r["total"] == 1


def test_a_MATURIDADE_viaja_junto_do_CPK(cenario):
    """Este CPK é acumulado até hoje, não da vida inteira: um pneu com 40 mil
    dos 120 mil km que vai dar mostra um CPK três vezes maior que o final.
    Comparar modelos de maturidades diferentes é o erro que isso previne."""
    cenario["pneus"] = [_pneu(i, "P%03d" % i) for i in range(1, 4)]
    cenario["km"] = {"P%03d" % i: 40000.0 for i in range(1, 4)}
    r = cpk.por_modelo()
    assert r["acumulado"] is True and r["ressalva"]
    assert r["modelos"][0]["km_mediano"] == 40000.0
