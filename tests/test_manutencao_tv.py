# -*- coding: utf-8 -*-
"""O quadrante de manutenção da TV de operação (15/09/2026).

Quem opera trocou a telemetria do quadrante superior direito por manutenção:
revisões vencidas e a vencer, parados em manutenção — cavalo e semirreboque
sempre separados. As consultas rodam contra um cursor falso: o que se testa
aqui é a montagem do payload. As SQL foram executadas contra o ERP real
antes da entrega.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from api import queries


class _Hoje(date):
    """31 de MARÇO: o mês anterior (fevereiro) é mais curto, e a janela
    equivalente tem de parar no último dia dele."""

    @classmethod
    def today(cls):
        return cls(2026, 3, 31)


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    queries._RESP_CACHE.clear()
    monkeypatch.setattr(queries, "date", _Hoje)
    monkeypatch.setattr(queries, "get_manutencao_preventiva", lambda *a, **k: PREV)
    yield
    queries._RESP_CACHE.clear()


PREV = {"kpis": {"tracoes_vencidas": 1, "tracoes_proximas": 3, "tracoes_avaliadas": 66,
                 "carretas_vencidas": 2, "carretas_proximas": 12, "carretas_avaliadas": 175},
        "horizonte": 30,
        # a FORMA do payload real de `get_manutencao_preventiva`, campos
        # "inúteis" inclusive: é deles que a lista do modal se monta
        "tracoes": [{"frota": "C901", "veiculo": "AAA1A11", "status": "vencida",
                     "km_faltante": -557, "intervalo": 50000, "odometro": 512340},
                    {"frota": "C902", "veiculo": "BBB2B22", "status": "proxima",
                     "km_faltante": 2149, "intervalo": 50000, "odometro": 447851}],
        "carretas": [{"frota": None, "veiculo": "SSS9S99", "status": "vencida", "dias": -15,
                      "ultima": "2026-03-01", "limite": 180, "bau": False},
                     {"frota": "S903", "veiculo": "TTT9T99", "status": "proxima", "dias": 11,
                      "ultima": "2026-03-20", "limite": 240, "bau": True}]}


def _v(placa, motor, em_viagem=0, os_abertas=0, desde=None, frota=None):
    """`frota=None` é o cadastro SEM número; `frota=placa` é a placa copiada
    no campo — os dois casos reais, e em nenhum deles a lista pode inventar um
    número de frota (regra de `frota_identidade`)."""
    return {"placa": placa, "numerofrota": frota, "utilizacao": "FROTA",
            "com_motor": motor, "ult_saida": None,
            "em_viagem": em_viagem, "os_abertas": os_abertas, "os_desde": desde}


# hoje = 31/03/2026
VEIC = [
    _v("CAV0001", True, os_abertas=1, desde=date(2026, 3, 20), frota="B9001"),  # 11 dias: longa
    # a PLACA copiada no campo de frota: não é número, e a lista mostra a placa
    _v("CAV0002", True, os_abertas=2, desde=date(2026, 3, 24), frota="CAV0002"),
    _v("CAV0003", True, em_viagem=1, os_abertas=1, desde=date(2026, 1, 5)),  # rodando
    _v("CAV0004", True),
    _v("SEM0001", False, os_abertas=1, desde=date(2026, 3, 30)),
    _v("SEM0002", False, os_abertas=1, desde=date(2026, 2, 1)),   # 58 dias: longa
    _v("SEM0003", False),
]
# AS OS DO MÊS, UMA A UMA: as contagens do cartão saem DESTA lista, que é a
# mesma que o modal mostra. O mês anterior entra só como comparação, e aí sim
# por contagem (não há lista para mostrar).
OS_MES = ([{"numero": 900 + i, "filial": 1, "placa": f"CAV{i:04d}", "objetivo": 14,
            "emissao": "2026-03-10 08:00", "fechamento": "2026-03-11",
            "com_motor": True, "utilizacao": "FROTA"} for i in range(2)]
          + [{"numero": 910 + i, "filial": 1, "placa": f"SEM{i:04d}", "objetivo": 15,
              "emissao": "2026-03-12 08:00", "fechamento": None,
              "com_motor": False, "utilizacao": "FROTA"} for i in range(3)]
          + [{"numero": 920, "filial": 2, "placa": "CAV0001", "objetivo": 16,
              "emissao": "2026-03-20 22:10", "fechamento": None,
              "com_motor": True, "utilizacao": "LOCACAO"}])
ANT = {"preventivas": 30, "corretivas": 70, "socorro": 12}


def _banco(monkeypatch, respostas=None):
    respostas = dict(respostas or {})
    respostas.setdefault(queries.PROG_VEIC_DISP_SQL, VEIC)
    vistos: list = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            self.sql, self.p = sql, params
            vistos.append((sql, params))

        def _valor(self):
            if self.sql == queries.MANUT_TV_OS_SQL:
                return OS_MES
            if self.sql == queries.MANUT_TV_MES_SQL:
                return ANT
            if "current_timestamp AS ts" in self.sql:
                return {"ts": datetime(2026, 3, 31, 10, 0)}
            return respostas.get(self.sql)

        def fetchall(self):
            v = self._valor()
            return [dict(x) for x in v] if isinstance(v, list) else []

        def fetchone(self):
            v = self._valor()
            return dict(v) if isinstance(v, dict) else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return Cur()

    monkeypatch.setattr(queries.db, "get_conn", lambda: Conn())
    return vistos


def test_parado_e_oficina_longa_por_cavalo_e_semirreboque(monkeypatch):
    _banco(monkeypatch)
    of = queries.get_manutencao_tv()["oficina"]
    # com viagem aberta o veículo está rodando, mesmo com OS aberta
    assert {k: v for k, v in of["cavalos"].items() if k != "lista"} == {
        "frota": 4, "parados": 2, "longa": 1}
    assert {k: v for k, v in of["semirreboques"].items() if k != "lista"} == {
        "frota": 3, "parados": 2, "longa": 1}
    assert of["longa_dias"] == queries.OFICINA_LONGA_DIAS == 7


def test_a_lista_da_oficina_e_a_MESMA_dos_numeros(monkeypatch):
    """A lista é o que o modal do cartão mostra (16/09/2026). Lista e número
    calculados em lugares diferentes discordam no primeiro ajuste — aqui um
    sai do outro, e o mais tempo parado abre a lista."""
    _banco(monkeypatch)
    of = queries.get_manutencao_tv()["oficina"]
    cav = of["cavalos"]["lista"]
    assert [x["placa"] for x in cav] == ["CAV0001", "CAV0002"], cav
    assert [x["dias"] for x in cav] == [11, 7]
    assert [x["longa"] for x in cav] == [True, False], "7 dias não é 'mais de 7'"
    assert len(cav) == of["cavalos"]["parados"]
    assert sum(1 for x in cav if x["longa"]) == of["cavalos"]["longa"]
    assert of["semirreboques"]["lista"][0]["placa"] == "SEM0002"   # 58 dias, o mais velho
    # o NÚMERO DE FROTA vai junto, pela régua da casa: número de verdade vira
    # `frota`; a placa copiada no campo, não (16/09/2026, os modais chamam o
    # veículo pelo número)
    assert [x["frota"] for x in cav] == ["B9001", None], cav
    assert cav[1]["rotulo"] == "CAV0002", cav[1]


def test_as_contagens_do_mes_saem_da_PROPRIA_lista(monkeypatch):
    """Duas consultas — uma que conta e outra que lista — é como o cartão e o
    detalhe passam a discordar sem ninguém ver."""
    _banco(monkeypatch)
    mes = queries.get_manutencao_tv()["mes"]
    # a MESMA lista, linha a linha — comparada pelo que identifica a OS, e não
    # pelo dicionário inteiro: as linhas ganham `frota`/`rotulo` no caminho
    assert [(l["numero"], l["placa"], l["objetivo"]) for l in mes["lista"]] == [
        (o["numero"], o["placa"], o["objetivo"]) for o in OS_MES]
    assert all("rotulo" in l and "numerofrota" not in l for l in mes["lista"])
    assert (mes["preventivas"], mes["corretivas"], mes["socorro"]) == (2, 3, 1)
    for chave, objetivo in (("preventivas", 14), ("corretivas", 15), ("socorro", 16)):
        assert mes[chave] == sum(1 for o in mes["lista"] if o["objetivo"] == objetivo)


def test_as_revisoes_publicam_a_lista_de_cada_lado(monkeypatch):
    _banco(monkeypatch)
    rev = queries.get_manutencao_tv()["revisoes"]
    cav = rev["cavalos"]["lista"]
    assert [(x["frota"], x["status"], x["km_faltante"]) for x in cav] == [
        ("C901", "vencida", -557), ("C902", "proxima", 2149)]
    # sem número de frota no ERP, a placa: a lista não pode ter linha sem nome
    assert rev["semirreboques"]["lista"][0]["frota"] == "SSS9S99"
    for lado, venc, prox in (("cavalos", 1, 3), ("semirreboques", 2, 12)):
        lista = rev[lado]["lista"]
        assert sum(1 for x in lista if x["status"] == "vencida") <= venc
        assert rev[lado]["vencidas"] == venc and rev[lado]["a_vencer"] == prox


def test_o_mes_anterior_e_recortado_ate_o_mesmo_dia(monkeypatch):
    """31/03 contra fevereiro, que só tem 28: a janela para no dia 28. Mês
    inteiro de um lado e mês em curso do outro fariam todo começo de mês
    parecer melhora."""
    vistos = _banco(monkeypatch)
    d = queries.get_manutencao_tv()
    janelas = [(p["de"], p["ate"]) for sql, p in vistos
               if sql in (queries.MANUT_TV_OS_SQL, queries.MANUT_TV_MES_SQL)]
    assert janelas == [(date(2026, 3, 1), date(2026, 4, 1)),
                       (date(2026, 2, 1), date(2026, 3, 1))]
    objetivos = {(p["prev"], p["corr"], p["socorro"]) for sql, p in vistos
                 if sql in (queries.MANUT_TV_OS_SQL, queries.MANUT_TV_MES_SQL)}
    assert objetivos == {(14, 15, 16)}
    assert {k: v for k, v in d["mes"].items() if k != "lista"} == {
        "preventivas": 2, "corretivas": 3, "socorro": 1,
        "socorro_ant": 12, "dia": 31, "mes_ant": "2026-02"}


def test_no_meio_do_mes_o_anterior_para_no_mesmo_dia(monkeypatch):
    """O caso de 31/03 sozinho não prova a janela: lá o fevereiro recortado
    termina em 01/03, o mesmo lugar do mês INTEIRO, e trocar a regra pelo mês
    cheio passava verde (sabotado em 15/09/2026). No dia 15, o agosto
    comparável vai do dia 1 ao 15, e não até 31."""
    class _Dia15(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 15)
    monkeypatch.setattr(queries, "date", _Dia15)
    vistos = _banco(monkeypatch)
    d = queries.get_manutencao_tv()
    janelas = [(p["de"], p["ate"]) for sql, p in vistos
               if sql in (queries.MANUT_TV_OS_SQL, queries.MANUT_TV_MES_SQL)]
    assert janelas == [(date(2026, 9, 1), date(2026, 9, 16)),
                       (date(2026, 8, 1), date(2026, 8, 16))]
    assert (d["mes"]["dia"], d["mes"]["mes_ant"], d["mes"]["socorro_ant"]) == (15, "2026-08", 12)


def test_as_revisoes_vem_da_preventiva_com_as_vencidas_por_nome(monkeypatch):
    _banco(monkeypatch)
    r = queries.get_manutencao_tv()["revisoes"]
    sem_lista = lambda d: {k: v for k, v in d.items() if k != "lista"}  # noqa: E731
    assert sem_lista(r["cavalos"]) == {"vencidas": 1, "a_vencer": 3, "avaliados": 66}
    assert sem_lista(r["semirreboques"]) == {"vencidas": 2, "a_vencer": 12, "avaliados": 175}
    # o quanto JÁ PASSOU, positivo; sem número de frota, a placa
    assert r["vencidas"] == [{"frota": "C901", "km": 557}, {"frota": "SSS9S99", "dias": 15}]


def test_parado_em_manutencao_e_a_MESMA_conta_da_tracao_em_os(monkeypatch):
    """O cartão de tração (k1) e o de manutenção (k2) ficam na mesma parede:
    se as duas contas divergissem, a TV se contradiria sozinha."""
    _banco(monkeypatch, {
        queries.PROG_DIESEL_SQL: {"custo": 0.0},
        queries.PROG_KM_PROPRIO_SQL: {"km": 0.0},
        queries.PROG_MOT_DISP_SQL: [],
        queries.PROG_AGR_DISP_SQL: {"total": 0},
    })
    prog = queries.get_programacao()
    of = queries.get_manutencao_tv()["oficina"]
    assert of["cavalos"]["parados"] == prog["kpis"]["tracao_os"]
    assert of["cavalos"]["parados"] + of["semirreboques"]["parados"] == prog["kpis"]["frota_os"]
    # e a data da OS não vaza para o payload da programação
    assert "os_desde" not in json.dumps(prog, default=str)
