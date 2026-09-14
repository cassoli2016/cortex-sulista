# -*- coding: utf-8 -*-
"""O banco de horas se lê como o EXTRATO DO BANCO DE HORAS do Globus.

O QUE ACONTECEU (14/09/2026)
============================
Quem opera mandou o extrato oficial (período 08/2026, 97 pessoas) para validar
a tela. Ele foi reproduzido 97/97 a partir de `globus729.frq_bancohoras`:

    Saldo anterior .... `saldoanterior` da competência
    Saldo atual ....... `credito − debito` da competência, em MINUTOS
    Total ............. `saldoanterior` da competência SEGUINTE

E a tela não batia com ele por DOIS motivos, os dois calados: lia
`saldonacompet` (um acumulador — 6.161 h credoras contra 1.158 h do extrato) e
somava a hora do Globus, que é HH.MM (`-17.36` = −17h36), como decimal.

POR QUE O DUBLÊ TEM O FORMATO QUE TEM
=====================================
Os números são LITERAIS no formato do Globus, copiados de linhas reais do
extrato — e a pessoa é inventada: o repo é público. Três deles existem porque
a conta decimal erra neles (36.00 − 1.37, 21.10 − 0.14, 5.19 − 8.54), e é por
eles que o teste pega quem voltar a somar o número cru. E o roteador RECUSA
qualquer consulta que leia `saldonacompet`: o campo não é saldo.
"""
from __future__ import annotations

import json

import pytest

from api import frequencia as F
from tests.rh.test_frequencia import _roteador as _base

_COMPS = [{"c": "2026-09"}, {"c": "2026-08"}, {"c": "2026-07"}]


def _linha(cod, comp, nome, anterior, credito, debito, situacao="A",
           salbase=3000.0, valorpago=0.0):
    return {"cod": cod, "comp": comp, "chapa": " %06d" % (100 + cod), "nome": nome,
            "filial": "MATRIZ", "funcao": "ANALISTA", "situacao": situacao,
            "salbase": salbase, "anterior": anterior, "credito": credito,
            "debito": debito, "valorpago": valorpago}


_MES = {
    "2026-08": [
        # credor que a casa PAGOU no fechamento: entra em setembro zerado
        _linha(1, "2026-08", "PESSOA A", 98.33, 36.00, 1.37, valorpago=1.0),
        # devedor sem movimento: é LEVADO para setembro como está
        _linha(2, "2026-08", "PESSOA B", -17.36, 0.0, 0.0),
        # devedor que virou credor no mês e foi pago
        _linha(3, "2026-08", "PESSOA C", -7.28, 21.10, 0.14, valorpago=1.0),
        # credor que virou devedor no mês e foi acertado (o ERP zera)
        _linha(4, "2026-08", "PESSOA D", 5.19, 0.0, 8.54),
        # DESLIGADO com saldo: fora do extrato e fora dos totais
        _linha(5, "2026-08", "PESSOA E", -58.30, 0.0, 0.0, situacao="D"),
        # tudo zerado: o extrato lista mesmo assim
        _linha(6, "2026-08", "PESSOA F", 0.0, 0.0, 0.0, valorpago=None),
    ],
    "2026-09": [
        _linha(1, "2026-09", "PESSOA A", 0.0, 2.15, 0.0),
        _linha(2, "2026-09", "PESSOA B", -17.36, 0.0, 0.0),
        _linha(3, "2026-09", "PESSOA C", 0.0, 0.0, 0.0),
        _linha(4, "2026-09", "PESSOA D", 0.0, 0.0, 0.0),
        _linha(5, "2026-09", "PESSOA E", -58.30, 0.0, 0.0, situacao="D"),
        _linha(6, "2026-09", "PESSOA F", 0.0, 0.0, 0.0),
    ],
}

#: A matéria da série: só ATIVOS, três meses (setembro em curso).
_SERIE = ([{"comp": "2026-07", "anterior": 90.00, "credito": 8.33, "debito": 0.0},
           {"comp": "2026-07", "anterior": -10.00, "credito": 0.0, "debito": 7.36}]
          + [{"comp": r["comp"], "anterior": r["anterior"], "credito": r["credito"],
              "debito": r["debito"]} for r in _MES["2026-08"] + _MES["2026-09"]
             if r["situacao"] == "A"])

_CRED_DEB_12M = [{"credito": 15.22, "debito": 12.37}, {"credito": 6.01, "debito": 3.43}]


def _roteador(sql, p=None):
    s = " ".join(sql.split()).upper()
    assert "SALDONACOMPET" not in s, "saldonacompet é um ACUMULADOR, não o saldo do extrato"
    if "SELECT DISTINCT TO_CHAR(COMPETENCIA" in s:
        return _COMPS
    if "ADD_MONTHS(TO_DATE(:COMP,'YYYY-MM'),1)" in s:
        comp = (p or {})["comp"]
        return _MES.get(comp, []) + _MES.get(F._mes_seguinte(comp), [])
    if "VF.SITUACAOFUNC = 'A'" in s and "B.SALDOANTERIOR ANTERIOR" in s:
        return _SERIE
    if s.startswith("SELECT CREDITO, DEBITO FROM GLOBUS729.FRQ_BANCOHORAS"):
        return _CRED_DEB_12M
    return _base(sql, p)


@pytest.fixture(autouse=True)
def _sem_oracle(monkeypatch):
    from api import queries
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(F.db, "query", _roteador)
    yield
    queries._RESP_CACHE.clear()


def _p(d, nome):
    return {x["nome"]: x for x in d["pessoas"] + d["nao_ativos"]}[nome]


# ═════════════════════════════════════════════════════════ a hora do Globus ═══

def test_a_hora_do_globus_e_HH_MM():
    assert F.minutos(-17.36) == -(17 * 60 + 36)
    assert F.minutos(-0.13) == -13
    assert F.minutos(17.359999999) == 17 * 60 + 36, "o ponto flutuante não pode mudar o minuto"
    assert F.minutos(None) == 0
    assert F.hhmm(-13) == "-0:13" and F.hhmm(8784) == "146:24"
    assert F.hhmm(None) is None


def test_minutos_de_60_para_cima_e_formato_QUEBRADO_e_recusa():
    """Converter assim mesmo publicaria um saldo errado com cara de certo."""
    with pytest.raises(ValueError, match="HH.MM"):
        F.minutos(1.75)


def test_a_conta_e_em_MINUTOS_e_nao_no_numero_cru():
    """15:22 − 12:37 = 2:45. Subtraindo o número cru daria 2,85 — que não é
    hora nenhuma. É o erro que a tela carregou até a v1.80.0."""
    assert F.minutos(15.22) - F.minutos(12.37) == 2 * 60 + 45


def test_o_mes_seguinte_atravessa_o_ano():
    assert F._mes_seguinte("2026-08") == "2026-09"
    assert F._mes_seguinte("2026-12") == "2027-01"


# ═══════════════════════════════════════════════════ as colunas do extrato ═══

def test_as_TRES_colunas_do_extrato_saem_do_saldoanterior_e_do_movimento():
    d = F.get_banco_horas()
    a = _p(d, "PESSOA A")
    assert (a["anterior"], a["movimento"], a["levado"]) == ("98:33", "34:23", "0:00")
    assert a["fim"] == "132:56"
    c = _p(d, "PESSOA C")
    assert (c["anterior"], c["movimento"], c["fim"], c["levado"]) == \
        ("-7:28", "20:56", "13:28", "0:00")
    b = _p(d, "PESSOA B")
    assert b["levado"] == "-17:36", "devedor sem acerto é levado como está"


def test_o_movimento_NAO_e_a_subtracao_decimal():
    a = _p(F.get_banco_horas(), "PESSOA A")
    assert a["movimento_min"] == 34 * 60 + 23
    assert a["movimento_min"] != round((36.00 - 1.37) * 60), "voltou a somar HH.MM como decimal"


def test_o_levado_vem_do_ERP_e_nao_de_conta_nossa():
    """A PESSOA D terminou agosto devendo 3:35 e entrou em setembro zerada — o
    ERP acertou. Calcular "levado = fim" diria −3:35."""
    dd = _p(F.get_banco_horas(), "PESSOA D")
    assert dd["fim"] == "-3:35" and dd["levado"] == "0:00"


def test_so_ATIVOS_entram_e_quem_nao_esta_ativo_nao_some():
    d = F.get_banco_horas()
    assert [x["nome"] for x in d["pessoas"]] == \
        ["PESSOA A", "PESSOA B", "PESSOA C", "PESSOA D", "PESSOA F"], \
        "ativos, na ordem do extrato (nome), inclusive quem está zerado"
    assert [x["nome"] for x in d["nao_ativos"]] == ["PESSOA E"]
    assert d["kpis"]["pessoas"] == 5 and d["kpis"]["nao_ativos"] == 1


# ══════════════════════════════════════════════════════════════════ KPIs ═════

def test_os_totais_sao_somados_em_MINUTOS():
    k = F.get_banco_horas()["kpis"]
    assert k["credor_hhmm"] == "146:24" and k["credores"] == 2       # A + C
    assert k["devedor_hhmm"] == "-21:11" and k["devedores"] == 2     # B + D
    assert k["liquido_hhmm"] == "125:13"
    assert k["maior_hhmm"] == "132:56"


def test_o_fechamento_ZERA_os_credores_pagos():
    """O contrário do que a tela afirmou até a v1.80.0 ("o pagamento não baixa
    o saldo"): pagou, entrou no mês seguinte zerado."""
    k = F.get_banco_horas()["kpis"]
    assert k["pagos_no_mes"] == 2 and k["credores_zerados"] == 2
    assert k["levado_hhmm"] == "-17:36", "só o devedor sem acerto foi levado"


def test_sem_o_mes_seguinte_gerado_o_levado_e_NAO_SEI():
    """Setembro está em curso e outubro não existe: "levado" não é zero."""
    d = F.get_banco_horas("2026-09")
    assert d["competencia_seguinte"] is None
    assert d["kpis"]["levado_h"] is None and d["kpis"]["credores_zerados"] is None
    assert all(x["levado"] is None for x in d["pessoas"])


def test_o_custo_e_so_do_credor_e_a_premissa_vai_junto():
    d = F.get_banco_horas()
    a = _p(d, "PESSOA A")
    assert a["custo"] == pytest.approx(round((98 * 60 + 33 + 34 * 60 + 23) / 60, 2)
                                       * (3000.0 / 220) * 1.5, abs=0.05)
    assert _p(d, "PESSOA B")["custo"] == 0.0
    assert "220" in d["premissa_custo"]


# ═══════════════════════════════════════════════════════ série e confronto ═══

def test_a_serie_usa_o_saldo_do_EXTRATO_e_marca_o_mes_em_curso():
    s = {x["comp"]: x for x in F.get_banco_horas()["serie"]}
    assert s["2026-07"]["credor"] == pytest.approx((98 * 60 + 33) / 60, abs=0.01)
    assert s["2026-08"]["credor"] == pytest.approx(8784 / 60, abs=0.01)
    assert s["2026-09"]["parcial"] is True and s["2026-08"]["parcial"] is False


def test_o_confronto_e_o_cartao_dizem_o_MESMO_saldo():
    """Dois caminhos para o mesmo número: se um voltar a ler outro campo, eles
    discordam — foi assim que o acumulador passou meses por saldo."""
    d = F.get_banco_horas()
    ago = [x for x in d["confronto"]["serie"] if x["comp"] == "2026-08"][0]
    assert ago["saldo"] == d["kpis"]["credor_h"]


def test_o_destino_da_he_converte_o_banco_e_nao_a_folha():
    """O banco é HH.MM; a folha (hora paga) é decimal."""
    d = F.get_banco_horas()["destino_he"]
    esperado = round(((15 * 60 + 22) + (6 * 60 + 1)) / 60, 1)
    assert d["creditado_horas"] == esperado
    assert d["compensado_horas"] == round(((12 * 60 + 37) + (3 * 60 + 43)) / 60, 1)


# ═══════════════════════════════════════════════════════════════ contrato ════

def test_o_payload_nao_carrega_mais_o_fechamento_escrito_a_mao():
    d = F.get_banco_horas()
    for chave in ("desde_fechamento", "ressalva_custo", "cadastro"):
        assert chave not in d, chave
    assert not hasattr(F, "FECHAMENTO_CONHECIDO")


def test_o_snapshot_do_copiloto_e_so_ESCALAR():
    r = F.resumo_escalares()
    assert r["banco_horas_credor_h"] == pytest.approx(8784 / 60, abs=0.01)
    assert r["banco_horas_levado_mes_seguinte_h"] == pytest.approx(-(17 * 60 + 36) / 60, abs=0.01)
    assert r["he_pct_paga_em_dinheiro"] is not None, "a fração que vira dinheiro saiu do snapshot"
    bruto = json.dumps(r, ensure_ascii=False).upper()
    # os NOMES do dublê — "PESSOAS_COM_PONTO" é chave legítima e contém "PESSOA"
    for proibido in ("PESSOA A", "PESSOA E", "000101", "MATRIZ"):
        assert proibido not in bruto, f"{proibido} vazou para o snapshot"
    assert all(not isinstance(v, (list, dict)) for v in r.values())
