# -*- coding: utf-8 -*-
"""A semeadura do banco próprio de pneus a partir do instantâneo local.

O GUARD QUE JUSTIFICA O ARQUIVO é o da segunda passada. A semeadura roda a
cada coleta, em cima do que já trouxe — e na primeira vez que rodei duas vezes
seguidas, `pne_modelo` foi de 8.572 para 17.144 linhas. Nenhum erro, nenhum
aviso: só o catálogo dobrando em silêncio, com o `modelo_id` de cada pneu
apontando para uma linha nova a cada passada.

A causa é a regra de NULL do SQL: num índice único, `NULL` é sempre DIFERENTE
de `NULL`. Como `medida` vem vazia nos 8.572 pneus (ela mora noutro endpoint da
Prolog e ainda não foi buscada), nenhuma linha casava com outra e o
`ON CONFLICT` nunca encontrava nada. O número já denunciava antes da causa:
não existem 8.572 modelos de pneu — existe um por pneu. São 125.
"""
from __future__ import annotations

import pytest

from api import pglocal
from api.pneus import replica


def _pneu(i: int, **kw) -> dict:
    """Um pneu no formato que `analise.pneu()` produz."""
    base = {
        "id": 1000 + i,
        "serie": "S%04d" % i,
        "dot": "3623",
        "frota": "F%04d" % i,
        "marca": "Bridgestone",
        "modelo": "R268",
        # MEDIDA VAZIA de propósito: é assim que o dado real chega, e é
        # exatamente essa ausência que quebrava a chave única.
        "medida": None,
        "desenho": None,
        "direcional": False,
        "status": "INSTALLED",
        "filial": "Matriz",
        "vida": 1,
        "placa": "ABC%04d" % i,
        "posicao": "3DE",
        "custo_compra": 1800.0,
        "sulcos": [12.0, 11.5, 11.0, 12.0],
        "pressao": 110.0,
        "pressao_rec": 120.0,
        "cpk_por_vida": [{"vida": 0, "km": 90000, "cpk": 0.02},
                         {"vida": 1, "km": 40000, "cpk": 0.015}],
    }
    base.update(kw)
    return base


@pytest.fixture
def instantaneo(monkeypatch):
    def _montar(pneus):
        monkeypatch.setattr(replica.servico, "obter", lambda *a, **k: {
            "pneus": pneus, "atualizado_em": "2026-09-04 20:30"})
    return _montar


def _contar(esquema: str) -> dict:
    fora = {}
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + esquema)
        for t in ("pne_pneu", "pne_vida", "pne_inspecao", "pne_modelo",
                  "pne_veiculo"):
            cur.execute("SELECT count(*)::int AS n FROM " + t)
            fora[t] = cur.fetchone()["n"]
    return fora


@pytest.fixture
def semear_em(esquema_pg, monkeypatch):
    """Roda a semeadura dentro do schema do teste."""
    original = pglocal.get_conn

    def _conn(esquema=None):
        return original(esquema or esquema_pg)

    monkeypatch.setattr(pglocal, "get_conn", _conn)
    monkeypatch.setattr(replica.pglocal, "get_conn", _conn)
    return esquema_pg


def test_a_semeadura_traz_carcaca_vidas_e_inspecao(instantaneo, semear_em):
    instantaneo([_pneu(i) for i in range(5)])
    r = replica.semear()
    assert r["ok"] and r["pneus"] == 5 and r["novos"] == 5
    n = _contar(semear_em)
    assert n["pne_pneu"] == 5
    assert n["pne_vida"] == 10          # duas vidas por carcaça
    assert n["pne_inspecao"] == 5
    assert n["pne_veiculo"] == 5


def test_a_SEGUNDA_passada_nao_dobra_nada(instantaneo, semear_em):
    """O guard central.

    `pne_modelo` foi de 8.572 para 17.144 na segunda passada porque a chave
    única tinha `medida` NULL e, num índice único, NULL nunca casa com NULL.
    """
    instantaneo([_pneu(i) for i in range(20)])
    replica.semear()
    antes = _contar(semear_em)
    r2 = replica.semear()
    depois = _contar(semear_em)

    assert r2["novos"] == 0, "a segunda passada inseriu carcaça de novo"
    assert r2["atualizados"] == 20
    for tabela, n in antes.items():
        assert depois[tabela] == n, (
            "%s dobrou na segunda passada: %d -> %d" % (tabela, n, depois[tabela]))


def test_o_catalogo_tem_UM_modelo_por_modelo_e_nao_um_por_pneu(instantaneo,
                                                               semear_em):
    """Vinte pneus da mesma marca e modelo são UMA linha de catálogo. O número
    é o que denuncia antes da causa: 8.572 modelos para 8.572 pneus não é
    catálogo, é cópia."""
    instantaneo([_pneu(i) for i in range(20)])
    replica.semear()
    assert _contar(semear_em)["pne_modelo"] == 1


def test_modelos_diferentes_continuam_diferentes(instantaneo, semear_em):
    """A correção da chave não pode ter colado modelos distintos num só."""
    instantaneo([
        _pneu(1, marca="Bridgestone", modelo="R268"),
        _pneu(2, marca="Bridgestone", modelo="M840"),
        _pneu(3, marca="Michelin", modelo="XZE"),
        _pneu(4, marca="Michelin", modelo="XZE", medida="295/80R22.5"),
    ])
    replica.semear()
    assert _contar(semear_em)["pne_modelo"] == 4


def test_a_semeadura_NAO_inventa_historico(instantaneo, semear_em):
    """Do instantâneo sai o ESTADO de hoje, nunca eventos. Um `pne_evento`
    fabricado a partir da foto seria história inventada com cara de registro —
    e ninguém, daqui a um ano, saberia que aquele movimento nunca aconteceu."""
    instantaneo([_pneu(i) for i in range(5)])
    replica.semear()
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + semear_em)
        cur.execute("SELECT count(*)::int AS n FROM pne_evento")
        assert cur.fetchone()["n"] == 0


def test_o_status_da_prolog_vira_o_vocabulario_da_casa(instantaneo, semear_em):
    """Traduzir na ENTRADA: se cada tela traduzir, cada tela erra diferente, e
    no dia em que a Prolog sumir o vocabulário dela fica encravado no código."""
    instantaneo([
        _pneu(1, status="INSTALLED"), _pneu(2, status="DISPOSAL"),
        _pneu(3, status="ANALYSIS"), _pneu(4, status="INVENTORY"),
    ])
    replica.semear()
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + semear_em)
        cur.execute("SELECT status, count(*)::int AS n FROM pne_pneu "
                    "GROUP BY status ORDER BY status")
        got = {r["status"]: r["n"] for r in cur.fetchall()}
    assert got == {"rodando": 1, "sucata": 1, "analise": 1, "estoque": 1}


def test_km_zero_vira_LACUNA_e_nao_zero(instantaneo, semear_em):
    """'Rodou 0 km' e 'não sabemos quanto rodou' decidem coisas opostas: o
    primeiro entra no CPK e o afunda, o segundo tem de ficar de fora."""
    instantaneo([_pneu(1, cpk_por_vida=[{"vida": 0, "km": 0, "cpk": 0}])])
    replica.semear()
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + semear_em)
        cur.execute("SELECT km FROM pne_vida WHERE numero = 0")
        assert cur.fetchone()["km"] is None


def test_a_inspecao_guarda_as_QUATRO_medidas(instantaneo, semear_em):
    """Todos os 8.572 pneus têm exatamente quatro medidas de sulco. Guardar
    três jogaria uma fora em toda a frota — e o desgaste irregular, que é o
    diagnóstico, se lê na diferença entre os pontos."""
    instantaneo([_pneu(1, sulcos=[12.0, 11.5, 11.0, 10.5])])
    replica.semear()
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + semear_em)
        cur.execute("SELECT sulcos_mm FROM pne_inspecao")
        assert [float(x) for x in cur.fetchone()["sulcos_mm"]] == [
            12.0, 11.5, 11.0, 10.5]


def test_a_inspecao_e_carimbada_com_a_data_da_COLETA(instantaneo, semear_em):
    """Carimbar `now()` faria a série de desgaste ter degraus onde só houve
    importação: o sulco foi medido no pátio, não no momento em que o CÓRTEX
    leu o arquivo."""
    instantaneo([_pneu(1)])
    replica.semear()
    with pglocal.get_conn() as c, c.cursor() as cur:
        cur.execute("SET search_path TO " + semear_em)
        cur.execute("SELECT medido_em FROM pne_inspecao")
        medido = cur.fetchone()["medido_em"]
    assert medido.strftime("%Y-%m-%d %H:%M") == "2026-09-04 20:30"


def test_instantaneo_vazio_nao_apaga_o_que_ja_existe(instantaneo, semear_em):
    """Coleta vazia NUNCA vira retrato completo — é a regra da casa para toda
    integração, e aqui ela vale para a semeadura também."""
    instantaneo([_pneu(i) for i in range(5)])
    replica.semear()
    instantaneo([])
    r = replica.semear()
    assert not r["ok"] and r["pneus"] == 0
    assert _contar(semear_em)["pne_pneu"] == 5
