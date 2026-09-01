# -*- coding: utf-8 -*-
"""A tela de Faturamento Detalhado (`fat`, v0.199.0).

O que se afirma aqui é COMPORTAMENTO da montagem do payload — janelas
equivalentes, eixo gerado, cliente sem meta virando n/d, o resíduo sem
vínculo à mostra — nunca o texto das queries. O dublê tem a ordem de
grandeza REAL (meta ~12,5 mi, realizado ~11,9 mi): dublê de brinquedo
esconde erro de unidade.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import faturamento as fat


# ---------------------------------------------------------------------------
# Janelas — a aritmética que sustenta o MoM/YoY honesto
# ---------------------------------------------------------------------------

def test_mes_fechado_compara_mes_cheio_com_mes_cheio():
    j = fat._janelas("2026-07", date(2026, 9, 1))
    assert not j["corrente"]
    assert j["corte"] == date(2026, 7, 31)
    # mês anterior: junho INTEIRO (30 dias)
    assert (j["de1"], j["ate1"]) == (date(2026, 6, 1), date(2026, 7, 1))
    # ano anterior: julho/25 INTEIRO
    assert (j["dea"], j["atea"]) == (date(2025, 7, 1), date(2025, 8, 1))


def test_mes_corrente_corta_as_tres_janelas_no_mesmo_dia():
    """Comparar agosto inteiro com setembro-até-dia-5 é a mentira clássica
    do MoM — os três períodos terminam no MESMO dia do mês."""
    j = fat._janelas("2026-09", date(2026, 9, 5))
    assert j["corrente"] and j["corte"].day == 5
    assert j["ate1"] == date(2026, 8, 6)      # agosto 01-05 (exclusivo dia 6)
    assert j["atea"] == date(2025, 9, 6)      # set/25 01-05


def test_janela_equivalente_respeita_mes_mais_curto():
    """Dia 31 de um mês de 31 dias: o mês anterior de 30 dias compara com os
    30 que ele tem — nunca inventa dia 31."""
    j = fat._janelas("2026-07", date(2026, 7, 31))
    assert j["ate1"] == date(2026, 7, 1)      # junho tem 30 dias


def test_mes_invalido_e_recusado():
    with pytest.raises(ValueError):
        fat._mes_valido("2026-13")
    with pytest.raises(ValueError):
        fat._mes_valido("agosto")
    assert fat._mes_valido("2026-08") == "2026-08"
    assert fat._mes_valido(None) is None


def test_o_eixo_de_meses_e_GERADO_e_nao_colhido():
    """GROUP BY não devolve o mês sem linha — abril emendaria em agosto."""
    eixo = fat._meses_eixo(date(2025, 8, 1), date(2026, 8, 1))
    assert len(eixo) == 13
    assert eixo[0] == "2025-08" and eixo[-1] == "2026-08"
    assert "2025-12" in eixo and "2026-01" in eixo   # a virada não engole mês


# ---------------------------------------------------------------------------
# A SQL derivada — o diário deslocável nunca diverge da oficial
# ---------------------------------------------------------------------------

def test_fat_diario_sql_e_derivada_e_parametrizada():
    from api.queries import VG_DIARIO_SQL
    assert fat.FAT_DIARIO_SQL != VG_DIARIO_SQL
    assert "current_date" not in fat.FAT_DIARIO_SQL
    assert fat.FAT_DIARIO_SQL.count("%(de)s") == 4     # 3 fontes + meta
    assert fat.FAT_DIARIO_SQL.count("%(ate)s") == 4


def test_filtros_fiscais_sao_os_canonicos():
    """Os WHERE das 3 fontes têm de ser os MESMOS da régua da meta — um
    filtro a menos e a tela mostra um faturamento que a Visão Geral nega."""
    assert "situacaocte = 3" in fat._CTE_W and "tipo IN (1, 4)" in fat._CTE_W
    assert "dtcancelamento IS NULL" in fat._CTE_W
    assert "situacaonfse = 3" in fat._NFS_W
    # cancelados: MESMOS filtros MENOS o cancelamento e a situação
    assert "dtcancelamento IS NOT NULL" in fat.FAT_CANCEL_SQL
    assert "situacaocte" not in fat.FAT_CANCEL_SQL


# ---------------------------------------------------------------------------
# Montagem do payload com dublê (ordem de grandeza real)
# ---------------------------------------------------------------------------

def _payload_stub(monkeypatch, hoje, rows):
    """Injeta um cursor dublê que responde às queries na ORDEM em que
    get_detalhado as executa."""
    class _Cur:
        def __init__(self, filas):
            self.filas = list(filas)

        def execute(self, sql, params=None):
            self._atual = self.filas.pop(0) if self.filas else []

        def fetchall(self):
            return self._atual

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def __init__(self, filas):
            self.filas = filas

        def cursor(self):
            return _Cur(self.filas)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fat.db, "get_conn", lambda: _Conn(rows))
    # o decorator @cached guarda por (nome, args) num dict GLOBAL — sem a
    # limpeza, o primeiro teste responderia por todos os seguintes
    from api import queries as _q
    _q._RESP_CACHE.clear()

    class _Hoje(date):
        @classmethod
        def today(cls):
            return hoje
    monkeypatch.setattr(fat, "date", _Hoje)


def _rows_dubie(dias_fechados=20):
    """As respostas na ordem: fontes×3, diário, sazonal(se corrente), modal,
    mensal, modal_mensal, meta_cli, real_cli, real_cli_a1, dias, cancel14,
    cancel_mes, filiais, emissores."""
    fontes = [{"fonte": "CT-e", "docs": 5511, "valor": 11194962.0},
              {"fonte": "KMM", "docs": 0, "valor": 0.0},
              {"fonte": "NFS-e", "docs": 113, "valor": 715057.0}]
    diario = [{"dia": i, "realizado": 560000.0 if i <= dias_fechados else 0.0,
               "meta": 600000.0} for i in range(1, 29)]
    modal = [{"modalidade": "AGREGADOS", "docs": 4000, "valor": 8540000.0,
              "valor_m1": 8000000.0, "valor_a1": 9000000.0},
             {"modalidade": "LOCACAO", "docs": 700, "valor": 1450000.0,
              "valor_m1": 1500000.0, "valor_a1": 3600000.0},
             {"modalidade": "RARIDADE", "docs": 1, "valor": 900.0,
              "valor_m1": 0.0, "valor_a1": 0.0}]
    mensal = [{"mes": "2026-08", "realizado": 11910019.0,
               "meta": 12483890.0, "docs": 5624}]
    meta_cli = [{"codigo": "AG1", "cliente": "TUPY", "meta_mtd": 2000000.0,
                 "meta_mes": 2180000.0},
                {"codigo": "AG2", "cliente": "FORVIA", "meta_mtd": 900000.0,
                 "meta_mes": 1000000.0}]
    real_cli = [{"codigo": "AG1", "realizado": 2410000.0},
                {"codigo": "AG9", "realizado": 122000.0}]   # AG9 SEM meta
    return [fontes, fontes, fontes, diario, [],   # sazonal vazio -> fonte erp
            modal, mensal, [], meta_cli, real_cli, [],
            [], [], [], [], []]


def test_cliente_sem_meta_vira_n_d_e_nunca_zero_por_cento(monkeypatch):
    _payload_stub(monkeypatch, date(2026, 8, 21), _rows_dubie())
    d = fat.get_detalhado("2026-08")
    por_cod = {c["codigo"]: c for c in d["clientes"]}
    assert por_cod["AG9"]["ating"] is None          # sem meta: n/d, não 0%
    assert por_cod["AG1"]["ating"] == pytest.approx(2410000.0 / 2000000.0)
    # quem tem meta e não realizou aparece com realizado 0 (não some)
    assert por_cod["AG2"]["realizado"] == 0.0


def test_o_residuo_sem_vinculo_fecha_a_conta(monkeypatch):
    """A soma dos clientes + (sem vínculo) TEM de bater com o total do mês —
    é o sensor de vínculo furado e de dupla contagem."""
    _payload_stub(monkeypatch, date(2026, 8, 21), _rows_dubie())
    d = fat.get_detalhado("2026-08")
    soma_cli = sum(c["realizado"] for c in d["clientes"])
    assert d["clientes_cobertura"]["sem_vinculo"] == \
        pytest.approx(d["kpis"]["realizado"] - soma_cli)


def test_modalidade_microscopica_vira_outros_com_contagem(monkeypatch):
    _payload_stub(monkeypatch, date(2026, 8, 21), _rows_dubie())
    d = fat.get_detalhado("2026-08")
    nomes = [m["modalidade"] for m in d["modalidades"]]
    assert "RARIDADE" not in nomes                   # 900 de 11,9 mi < 0,1%
    outros = next(m for m in d["modalidades"] if m["modalidade"] == "outros")
    assert outros["n_agrupadas"] == 1
    assert "NFS-e (serviço)" in nomes                # NFS-e nunca é "outros"


def test_kmm_zerado_nas_tres_janelas_some_da_lista(monkeypatch):
    _payload_stub(monkeypatch, date(2026, 8, 21), _rows_dubie())
    d = fat.get_detalhado("2026-08")
    assert all(f["fonte"] != "KMM" for f in d["fontes"])
    assert d["kmm_encerrado"] == "2023-05-31"        # a tela diz, não esconde


def test_atingimento_usa_meta_ate_o_corte_e_nao_a_do_mes_inteiro(monkeypatch):
    """No dia 21, a meta acumulada é a de 21 dias — dividir pela meta do mês
    inteiro faria todo dia parecer 30% abaixo."""
    _payload_stub(monkeypatch, date(2026, 8, 21), _rows_dubie())
    d = fat.get_detalhado("2026-08")
    assert d["kpis"]["meta_mtd"] == pytest.approx(21 * 600000.0)
    assert d["kpis"]["meta_mes"] == pytest.approx(28 * 600000.0)
    assert d["kpis"]["atingimento"] == \
        pytest.approx(d["kpis"]["realizado"] / (21 * 600000.0))


def test_atingimento_fechado_ignora_o_dia_em_curso(monkeypatch):
    """O chip da tela julga só dias FECHADOS — no dia 21 de manhã, o dia 21
    não conta (meta cheia contra realizado de horas)."""
    _payload_stub(monkeypatch, date(2026, 8, 21), _rows_dubie())
    d = fat.get_detalhado("2026-08")
    k = d["kpis"]
    assert k["atingimento_fechado"] == \
        pytest.approx((20 * 560000.0) / (20 * 600000.0))
