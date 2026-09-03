# -*- coding: utf-8 -*-
"""Painel de TV — Comunicação Veículos × Rastreadora.

Os guards aqui são das DUAS decisões que separam este painel do relatório do
ERP (terceiro parado fora, com motor × sem motor separados) e da distinção que
impede o painel de virar acusação: "sem posição" não é "leitura velha".
"""
from __future__ import annotations

import datetime as dt

from api import queries


def _stub(monkeypatch, linhas):
    class _Cur:
        def execute(self, sql, params=None):
            self._sql = sql

        def fetchall(self):
            return linhas

        def fetchone(self):
            return {"ts": dt.datetime(2026, 9, 3, 8, 0)}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(queries.db, "get_conn", lambda: _Conn())
    queries._RESP_CACHE.clear()


def _v(placa, com_motor=True, rastr="RASTER", dias=0, frota=None):
    """Um veículo. `dias=None` = nenhuma posição registrada, nunca."""
    hoje = dt.date.today()
    return {
        "placa": placa, "numerofrota": frota, "tipofrota": 1,
        "com_motor": com_motor, "rastreadora": rastr,
        "ultima": None if dias is None
        else dt.datetime.combine(hoje - dt.timedelta(days=dias), dt.time(7, 0)),
        "ignicao": "D", "posicao": "",
    }


def test_com_motor_e_sem_motor_sao_populacoes_separadas(monkeypatch):
    """A média das duas não decide nada: no dado real os tratores comunicam em
    82% e os implementos em 23%, e um único percentual (50,8%) esconde as duas
    verdades. Por isso o corte é de primeira classe, não rodapé."""
    _stub(monkeypatch, [
        _v("AAA1111", com_motor=True, dias=0),
        _v("BBB2222", com_motor=True, dias=0),
        _v("CCC3333", com_motor=False, dias=None),
        _v("DDD4444", com_motor=False, dias=None),
    ])
    d = queries.get_tv_comunicacao()
    por = {m["chave"]: m for m in d["motor"]}
    assert por["com_motor"]["total"] == 2 and por["com_motor"]["hoje"] == 2
    assert por["sem_motor"]["total"] == 2 and por["sem_motor"]["hoje"] == 0
    assert por["sem_motor"]["sem_posicao"] == 2
    # e o total da frota continua batendo com a soma dos dois lados
    assert d["total"] == por["com_motor"]["total"] + por["sem_motor"]["total"]


def test_sem_posicao_nao_se_mistura_com_leitura_velha(monkeypatch):
    """São coisas diferentes e o painel não pode fundi-las: ausência de leitura
    pode ser integração que não traz, enquanto leitura de 40 dias é o veículo
    que parou de reportar. Chamar as duas de "rastreador com defeito" seria
    acusar equipamento sem prova."""
    _stub(monkeypatch, [
        _v("AAA1111", dias=None),   # nunca teve posição
        _v("BBB2222", dias=40),     # tem, mas velha
    ])
    d = queries.get_tv_comunicacao()
    assert d["kpis"]["sem_posicao"] == 1
    assert d["kpis"]["mais15"] == 1
    faixas = {f["chave"]: f["veiculos"] for f in d["faixas"]}
    assert faixas["sem_posicao"] == 1 and faixas["mais15"] == 1
    # as faixas particionam a frota: ninguém contado duas vezes, ninguém fora
    assert sum(faixas.values()) == d["total"]


def test_as_faixas_particionam_a_frota(monkeypatch):
    """Faixa que se sobrepõe faz o painel somar mais que a frota — o tipo de
    erro que só aparece quando alguém confere na mão."""
    _stub(monkeypatch, [_v("A1", dias=0), _v("A2", dias=1), _v("A3", dias=2),
                        _v("A4", dias=3), _v("A5", dias=15), _v("A6", dias=16),
                        _v("A7", dias=None)])
    d = queries.get_tv_comunicacao()
    faixas = {f["chave"]: f["veiculos"] for f in d["faixas"]}
    assert faixas == {"hoje": 1, "ate2": 2, "ate15": 2,
                      "mais15": 1, "sem_posicao": 1}
    assert sum(faixas.values()) == d["total"] == 7


def test_a_lista_de_mudos_e_limitada_mas_diz_o_total(monkeypatch):
    """Top-N sem contador vira total falso: quem lê 14 linhas conclui que são
    14 veículos mudos, e no dado real são 200."""
    _stub(monkeypatch, [_v("M%03d" % i, dias=None) for i in range(40)])
    d = queries.get_tv_comunicacao()
    assert len(d["mudos"]) == 14
    assert d["mudos_total"] == 40


def test_sem_posicao_vem_antes_do_mudo_antigo_na_lista(monkeypatch):
    """Quem nunca reportou é o pior estado e encabeça a lista; entre os que
    reportaram, o mais antigo primeiro."""
    _stub(monkeypatch, [_v("VELHO", dias=90), _v("NUNCA", dias=None),
                        _v("MENOS", dias=20)])
    d = queries.get_tv_comunicacao()
    assert [m["placa"] for m in d["mudos"]] == ["NUNCA", "VELHO", "MENOS"]


def test_veiculo_sem_rastreadora_e_contado_e_nomeado(monkeypatch):
    """19 dos 205 tratores não têm rastreadora cadastrada. Isso é um buraco de
    CADASTRO, não de comunicação, e some se virar só mais um 'sem posição'."""
    _stub(monkeypatch, [_v("AAA1111", rastr=""), _v("BBB2222", rastr="RASTER")])
    d = queries.get_tv_comunicacao()
    assert d["kpis"]["sem_rastreadora"] == 1
    nomes = [r["rastreadora"] for r in d["rastreadoras"]]
    assert queries.SEM_RASTREADORA in nomes


def test_o_rotulo_do_veiculo_usa_a_regra_da_casa(monkeypatch):
    """A chave é a PLACA; `numerofrota` tem cobertura real de 46%. O rótulo sai
    de frota_identidade.rotulo(frota, placa) — e a ORDEM dos argumentos importa:
    invertida, ela devolve rótulo errado sem erro nenhum."""
    _stub(monkeypatch, [_v("JOK3003", dias=None, frota="582"),
                        _v("XYZ9999", dias=None, frota=None)])
    d = queries.get_tv_comunicacao()
    rot = {m["placa"]: m["frota"] for m in d["mudos"]}
    assert rot["JOK3003"] == "582 · JOK3003"
    assert rot["XYZ9999"] == "XYZ9999"


def test_o_terceiro_parado_fica_fora_e_o_proprio_nao(monkeypatch):
    """A regra vive no SQL (o dublê não a executa), então o guard é sobre o
    texto da consulta: ela precisa excluir tipofrota=2 sem viagem, e o filtro
    NÃO pode alcançar próprio nem agregado — foram 227 carretas próprias que
    quase saíram junto do painel."""
    sql = " ".join(queries.TVCOM_SQL.split())
    assert "v.tipofrota = 2" in sql
    assert "coalesce(vg.em_viagem, 0) = 0" in sql
    assert "NOT (v.tipofrota = 2" in sql, "o filtro tem de ser SÓ do terceiro"
    assert "v.ativoinativo = 1" in sql


def test_a_rota_esta_amarrada_na_tela(monkeypatch):
    """Middleware fail-closed: rota /api/* não mapeada é 403 para não-admin."""
    from api import auth
    rotas = dict(auth.ROTA_TELAS)
    assert "tvcom" in auth.TELAS
    assert rotas["/api/frota/comunicacao-tv"] == frozenset({"tvcom"})
