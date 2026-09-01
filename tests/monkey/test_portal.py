# -*- coding: utf-8 -*-
"""Portal Tupy: o espelho local e a leitura da tela de validacao.

O duble copia o formato REAL medido em producao (01/09/2026): sponsor=TUPY
(sacado), buyer=banco investidor, effective_payment_date preenchida (a
real_payment_date NUNCA veio), Rota nao existe aqui, e 100% dos titulos tem
taxa/desagio/investidor — todo titulo do convenio e antecipado.
"""
from __future__ import annotations

import pytest

from api.monkey import espelho
from api.monkey import portal


def _receb(ext, status="SOLD", venc="2026-10-15", valor=1000.0, recebe=975.0,
           **extra):
    r = {
        "externalId": ext, "invoiceNumber": "NF" + ext, "installment": 1,
        "totalInstallment": 1, "assetType": "DUPLICATA_MERCANTIL",
        "status": status, "purchasedTax": 1.15,
        "invoiceDate": "2026-08-01T00:00:00.000-03:00",
        "paymentDate": venc + "T00:00:00.000-03:00",
        "effectivePaymentDate": venc + "T00:00:00.000-03:00",
        "paymentValue": valor, "receiptValue": recebe,
        "sponsorName": "TUPY S/A", "sponsorGovernmentId": "84683374000149",
        "buyerName": "BANCO SOFISA S.A.", "buyerGovernmentId": "60889128000180",
        "_seller_cnpj": "76101234000101", "_seller_nome": "SULISTA",
        "_links": {"self": {"href": f"https://x/v2/sellers/1/receivables/{ext}"}},
    }
    r.update(extra)
    return r


class TestEspelho:
    def test_upsert_idempotente_pela_chave_natural(self, esquema_pg):
        from api import pglocal
        pares = [("111", _receb("A1")), ("111", _receb("A2", status="PAID"))]
        g, sem = espelho.upsert(pares, esquema=esquema_pg)
        assert (g, sem) == (2, 0)
        # recoleta com status novo: atualiza, nao duplica
        g2, _ = espelho.upsert([("111", _receb("A1", status="PAID"))],
                               esquema=esquema_pg)
        assert g2 == 1
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM mky_recebiveis")
            assert cur.fetchone()["n"] == 2, "upsert nao duplica"
            cur.execute("SELECT status, id_monkey FROM mky_recebiveis"
                        " WHERE external_id = 'A1'")
            v = dict(cur.fetchone())
        assert v["status"] == "PAID"
        assert v["id_monkey"] == "A1"   # extraido do _links.self

    def test_sem_externalId_conta_como_sem_chave(self, esquema_pg):
        r = _receb("X"); r.pop("externalId")
        g, sem = espelho.upsert([("111", r)], esquema=esquema_pg)
        assert (g, sem) == (0, 1), "campo ausente e ACHADO, nao silencio"

    def test_data_corta_no_T_sem_andar_um_dia(self):
        ln = espelho.linha(_receb("D1", venc="2026-10-15",
                                  paymentDate="2026-10-15T23:30:00.000-03:00"),
                           "111")
        assert ln["payment_date"] == "2026-10-15"


class TestPortal:
    def _semear(self, esquema):
        pares = [
            ("111", _receb("S1", "SOLD", "2026-10-10", 1000.0, 975.0)),
            ("111", _receb("S2", "SOLD", "2026-11-05", 2000.0, 1950.0)),
            ("111", _receb("P1", "PAID", "2026-08-10", 3000.0, 2940.0)),
            ("222", _receb("P2", "PAID", "2026-07-15", 4000.0, 3920.0,
                           _seller_cnpj="76101234000202")),
            ("222", _receb("AB", "ACTIVE", "2026-12-01", 500.0, None)),
        ]
        espelho.upsert(pares, esquema=esquema)

    def test_kpis_e_a_semantica_medida(self, esquema_pg):
        self._semear(esquema_pg)
        d = portal.montar(esquema=esquema_pg)
        assert d["disponivel"] is True
        k = d["kpis"]
        assert k["titulos"] == 5 and k["valor_total"] == 10500.0
        # o antecipado historico e o TOTAL — 100% do convenio passa pelo
        # leilao (medido); o desagio tambem e sobre o total
        assert k["desagio_total"] == pytest.approx(25 + 50 + 60 + 80)
        assert k["desagio_pct"] == pytest.approx(100 * 215 / 10500.0)
        assert k["vendidos"] == 2 and k["valor_vendido"] == 3000.0
        assert k["abertos"] == 1 and k["valor_aberto"] == 500.0

    def test_mensal_gera_meses_e_ancora_no_ultimo_vencimento(self, esquema_pg):
        self._semear(esquema_pg)
        d = portal.montar(esquema=esquema_pg)
        meses = [m["mes"] for m in d["mensal"]]
        assert len(meses) == 13 and meses[-1] == "2026-12"
        vazio = next(m for m in d["mensal"] if m["mes"] == "2026-09")
        assert vazio["titulos"] == 0, "mes sem titulo aparece VAZIO, gerado"

    def test_sellers_agrupados_pelo_id_nunca_pelo_nome(self, esquema_pg):
        # as filiais tem a MESMA razao social no portal — agrupar por nome
        # colapsaria tudo numa linha (defeito visto na primeira leitura real)
        self._semear(esquema_pg)
        d = portal.montar(esquema=esquema_pg)
        assert len(d["sellers"]) == 2
        assert {x["seller_id"] for x in d["sellers"]} == {"111", "222"}

    def test_busca_filtra_por_documento_e_id_externo(self, esquema_pg):
        self._semear(esquema_pg)
        d = portal.montar(q="NFS1", esquema=esquema_pg)
        assert [t["external_id"] for t in d["titulos"]] == ["S1"]
        d2 = portal.montar(q="P2", esquema=esquema_pg)
        assert [t["external_id"] for t in d2["titulos"]] == ["P2"]

    def test_espelho_vazio_diz_o_motivo_em_vez_de_zero_verde(self, esquema_pg):
        d = portal.montar(esquema=esquema_pg)
        assert d["disponivel"] is False and "coleta" in d["motivo"]

    def test_a_conferencia_traz_os_dois_caminhos(self, esquema_pg, monkeypatch):
        self._semear(esquema_pg)
        from api.antecipacoes import registro
        monkeypatch.setattr(registro, "ESQUEMA", esquema_pg)
        d = portal.montar(esquema=esquema_pg)
        conf = d["conferencia"]
        assert conf["espelho_abertos"] == 1
        assert "painel" in conf
