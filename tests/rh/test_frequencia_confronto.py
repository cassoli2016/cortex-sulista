# -*- coding: utf-8 -*-
"""O saldo do banco de horas NÃO é o passivo — e a tela é obrigada a dizer.

O DEFEITO QUE ISTO CONSERTA, E QUEM O ACHOU
===========================================
Em 09/09/2026 a tela de Frequência subiu publicando o saldo de `FRQ_BANCOHORAS`
como "Passivo de banco de horas", com valor em reais. Quem opera leu a tela e
perguntou: "o banco não zera a cada 6 meses?".

A pergunta desfez o número. Medido no ERP:

    pago em hora extra em 24 meses .... 27.516,3 h   R$ 573.133,74
    baixado do banco pela folha .......    156,4 h   (0,6%)
    saldo registrado ..... 2.617,6 h -> 6.160,9 h    SUBIU 3.543 h

E nos três meses de fechamento semestral (ago/25, fev/26, ago/26), em que a
casa pagou 2.233 h, 1.003 h e 1.352 h de `H.E 50%`, o saldo do banco subiu 42 h,
caiu 144 h e subiu 245 h. O evento que daria a baixa (`DEBITO BANCO DE HORAS`)
movimentou 86,4 h para 7 pessoas no maior mês de pagamento do ano.

São DUAS CONTABILIDADES que rodam em paralelo e não se encontram. O saldo é um
ACUMULADOR que ninguém zera — chamá-lo de dívida transformou horas já pagas em
passivo, com valor em reais, numa tela de decisão.

A lição de método: eu validei o número contra si mesmo (a série batia, o cálculo
batia) e não contra a REALIDADE que ele afirma descrever. Número coerente não é
número verdadeiro.
"""
from __future__ import annotations

import pytest

from api import frequencia as F


# Os dublês vêm do teste irmão: um só arranjo, e o roteador dele já conhece
# as consultas do confronto.
from tests.rh.test_frequencia import _roteador  # noqa: E402


@pytest.fixture(autouse=True)
def _sem_oracle(monkeypatch):
    from api import queries
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(F.db, "query", _roteador)
    yield
    queries._RESP_CACHE.clear()


def test_o_saldo_NUNCA_viaja_sozinho():
    """Quem recebe o saldo recebe, na MESMA resposta, o que foi pago.

    Não é conferência de texto: é o payload. Se o confronto sumir, a tela
    volta a ter só o número que se lê como dívida.
    """
    d = F.get_banco_horas()
    assert "confronto" in d, "o saldo não pode ser entregue sem o outro lado"
    c = d["confronto"]
    assert c["pago_h"] > 0, "o confronto veio vazio — a tela mostraria só o saldo"
    assert "baixa_pela_folha_h" in c


def test_o_custo_em_reais_vem_com_a_ressalva():
    """Valor em reais sem ressalva vira passivo na cabeça de quem lê — foi
    exatamente isso que aconteceu na versão que subiu."""
    d = F.get_banco_horas()
    assert d["kpis"]["passivo_custo"] > 0
    ressalva = d.get("ressalva_custo") or ""
    assert ressalva, "custo em reais sem ressalva"
    assert "não baixam" in ressalva or "nao baixam" in ressalva


def test_o_confronto_mostra_o_mes_em_que_pagou_e_o_saldo_SUBIU():
    """O fato que desfaz a leitura de dívida, no payload: o mês de maior
    pagamento é um mês em que o saldo cresceu."""
    c = F.get_banco_horas()["confronto"]
    ago = [x for x in c["serie"] if x["comp"] == "2026-08"][0]
    assert ago["pago_h"] > 1000
    assert ago["variacao"] > 0, (
        "o mês de maior pagamento tinha saldo SUBINDO — é este o fato")
    assert ago["baixa_pela_folha"] < ago["pago_h"] / 10


def test_nenhum_mes_e_rotulado_como_FECHAMENTO():
    """A tentativa fica registrada porque quase virou etiqueta: um corte por
    múltiplo da mediana separava os três fechamentos e levava out/2025 junto,
    que não é fechamento. Régua que não separa não vira rótulo."""
    c = F.get_banco_horas()["confronto"]
    for x in c["serie"]:
        assert "fechamento" not in x, "voltou a rotular mês como fechamento"


def test_confronto_poe_as_duas_contabilidades_na_mesma_linha(monkeypatch):
    """Cada mês traz o que se pagou E o que o saldo fez. Sem os dois lados,
    quem lê a série vê um número subindo e conclui dívida crescente."""
    pagos = [{"comp": "2026-07", "pessoas": 34, "horas": 650.2, "reais": 13278.34},
             {"comp": "2026-08", "pessoas": 60, "horas": 1506.7, "reais": 27945.42}]
    saldos = [{"comp": "2026-07", "saldo": 5915.2, "debito": 277.5},
              {"comp": "2026-08", "saldo": 6160.9, "debito": 358.9}]
    baixas = [{"comp": "2026-08", "horas": 86.4}]

    def falso(sql, p=None):
        s = " ".join(sql.split()).upper()
        if "FLP_FICHAEVENTOS" in s and "CODEVENTO = 1016" in s:
            return baixas
        if "FLP_FICHAEVENTOS" in s:
            return pagos
        return saldos

    monkeypatch.setattr(F, "_q", falso)
    from api import queries
    queries._RESP_CACHE.clear()
    d = F.confronto()
    queries._RESP_CACHE.clear()

    ago = [x for x in d["serie"] if x["comp"] == "2026-08"][0]
    assert ago["pago_h"] == 1506.7
    assert ago["saldo"] == 6160.9
    # o mês em que mais se pagou é o mês em que o saldo SUBIU: é o fato inteiro
    assert ago["variacao"] == pytest.approx(245.7, abs=0.1)
    assert ago["baixa_pela_folha"] == 86.4
    assert d["pago_h"] == pytest.approx(2156.9, abs=0.1)
    assert d["baixa_pela_folha_h"] == 86.4


def test_confronto_sobrevive_a_mes_sem_um_dos_lados(monkeypatch):
    """Mês com pagamento e sem saldo (ou o contrário) não pode derrubar a
    série: o `GROUP BY` de cada lado devolve conjuntos diferentes."""
    monkeypatch.setattr(F, "_q", lambda sql, p=None: (
        [{"comp": "2026-08", "pessoas": 1, "horas": 10.0, "reais": 100.0}]
        if "FLP_FICHAEVENTOS" in " ".join(sql.split()).upper()
           and "CODEVENTO = 1016" not in " ".join(sql.split()).upper()
        else []))
    from api import queries
    queries._RESP_CACHE.clear()
    d = F.confronto()
    queries._RESP_CACHE.clear()
    assert len(d["serie"]) == 1
    assert d["serie"][0]["saldo"] is None
    assert d["serie"][0]["variacao"] is None
