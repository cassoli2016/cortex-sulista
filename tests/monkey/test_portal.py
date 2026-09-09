# -*- coding: utf-8 -*-
"""Portal Tupy: o espelho local e a leitura da tela de validacao.

O duble copia o formato REAL medido em producao (01/09/2026): sponsor=TUPY
(sacado), buyer=banco investidor, effective_payment_date preenchida (a
real_payment_date NUNCA veio), Rota nao existe aqui, e 100% dos titulos tem
taxa/desagio/investidor — todo titulo do convenio e antecipado.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api import pglocal
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


class TestCustoEConcentracao:
    """Os indicadores de custo, mes corrente e dependencia de comprador.

    Cada teste aqui foi SABOTADO antes de entrar: trocar a data de agrupamento,
    incluir o mes corrente na propria media, usar taxa vezes 12 em vez de
    composta, ou baixar o piso de base da concentracao faz um destes ficar
    vermelho. Guard que nao acende nao conferiu nada.
    """

    def _cria(self, esquema_pg, itens):
        """itens: (ext, criado_iso, venc, valor, recebe, taxa, comprador)."""
        pares = []
        for ext, criado, venc, valor, recebe, taxa, comprador in itens:
            pares.append(("111", _receb(
                ext, venc=venc, valor=valor, recebe=recebe,
                purchasedTax=taxa, buyerName=comprador,
                createdAt=criado + "T03:00:00.000-03:00",
                updatedAt=criado + "T12:00:00.000-03:00")))
        espelho.upsert(pares, esquema=esquema_pg)

    def test_a_serie_de_antecipacao_agrupa_pela_entrada_nao_pelo_vencimento(
            self, esquema_pg):
        # o titulo ENTRA num mes e VENCE dois meses depois: as duas series
        # tem de contá-lo em meses DIFERENTES, senao uma delas esta errada
        hoje = date.today()
        entrada = (hoje.replace(day=1) - timedelta(days=1)).replace(day=10)
        venc = entrada + timedelta(days=75)
        self._cria(esquema_pg, [("E1", entrada.isoformat(), venc.isoformat(),
                                 1000.0, 975.0, 1.20, "BANCO A")])
        d = portal.montar(esquema=esquema_pg)
        ant = {m["mes"]: m for m in d["antecipado"]}
        assert ant[entrada.strftime("%Y-%m")]["titulos"] == 1, \
            "a serie de antecipacao tem de contar no mes de ENTRADA"
        assert ant.get(venc.strftime("%Y-%m"), {}).get("titulos", 0) == 0, \
            "contar no mes de vencimento seria repetir a serie que ja existia"

    def test_o_mes_corrente_e_parcial_e_fica_fora_da_propria_media(
            self, esquema_pg):
        hoje = date.today()
        ant_mes = (hoje.replace(day=1) - timedelta(days=1)).replace(day=5)
        itens = [("M1", ant_mes.isoformat(), (ant_mes + timedelta(days=60)
                                              ).isoformat(),
                  10000.0, 9700.0, 1.20, "BANCO A"),
                 ("M2", hoje.replace(day=1).isoformat(),
                  (hoje + timedelta(days=60)).isoformat(),
                  1000.0, 970.0, 1.20, "BANCO A")]
        self._cria(esquema_pg, itens)
        mc = portal.montar(esquema=esquema_pg)["mes_corrente"]
        assert mc["parcial"] is True
        assert mc["nominal"] == 1000.0
        # a media so olha meses FECHADOS: se o corrente entrasse, ela cairia
        # para 5.500 e o "% da media" saltaria de 10% para 18%
        assert mc["media_fechada"] == 10000.0, \
            "o mes em curso nao pode entrar na media que ele e' comparado"
        assert mc["meses_na_media"] == 1
        assert round(mc["pct_da_media"]) == 10

    def test_taxa_ao_ano_e_composta_nunca_vezes_doze(self):
        # 1,2488% a.m. -> 16,06% a.a. compostos. Vezes 12 daria 14,99% e
        # subestimaria o custo em mais de um ponto percentual.
        aa = portal.ao_ano(1.2488)
        assert 16.0 < aa < 16.2, aa
        assert abs(aa - 1.2488 * 12) > 1.0, "esta multiplicando em vez de compor"
        assert portal.ao_ano(None) is None

    def test_concentracao_sem_base_publica_o_numero_mas_nao_da_veredito(
            self, esquema_pg):
        # UM dia de leilao: 100% de concentracao e verdade e nao significa nada
        hoje = date.today()
        self._cria(esquema_pg, [
            ("C1", hoje.isoformat(), (hoje + timedelta(days=60)).isoformat(),
             5000.0, 4850.0, 1.20, "BANCO A")])
        c = portal.montar(esquema=esquema_pg)["concentracao"]
        assert c["lider_pct"] == 100.0, "o percentual continua sendo publicado"
        assert c["estado"] == "info", "sem base nao se acusa"
        assert "base" in (c["motivo"] or "")

    def test_concentracao_com_base_acusa_o_lider_e_precifica_a_saida(
            self, esquema_pg):
        hoje = date.today()
        itens = [(f"D{i}", (hoje - timedelta(days=i)).isoformat(),
                  (hoje + timedelta(days=60)).isoformat(),
                  10000.0, 9700.0, 1.10, "BANCO LIDER") for i in range(4)]
        itens.append(("D9", (hoje - timedelta(days=5)).isoformat(),
                      (hoje + timedelta(days=60)).isoformat(),
                      1000.0, 970.0, 1.30, "BANCO OUTRO"))
        self._cria(esquema_pg, itens)
        c = portal.montar(esquema=esquema_pg)["concentracao"]
        assert c["lider"] == "BANCO LIDER"
        assert c["estado"] == "alerta" and c["lider_pct"] > 95
        assert c["lotes"] >= portal._LOTES_MINIMOS
        # o lider e' 0,20 p.p. mais barato: sair dele CUSTA, e o cartao diz quanto
        assert c["risco_anual"] > 0, "concentracao sem consequencia nao decide"

    def test_lote_em_aberto_alarma_por_idade_e_nunca_por_contagem(
            self, esquema_pg):
        hoje = date.today()
        # 40 titulos abertos, todos de HOJE: muitos, e nada de errado
        self._cria(esquema_pg, [
            (f"A{i}", hoje.isoformat(), (hoje + timedelta(days=60)).isoformat(),
             1000.0, 1000.0, 1.20, None) for i in range(40)])
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("UPDATE mky_recebiveis SET status = 'ACTIVE'")
        lote = portal.montar(esquema=esquema_pg)["lote_aberto"]
        assert lote["titulos"] == 40 and lote["estado"] == "ok", \
            "contagem alta com lote fresco nao e' alarme"
        # o MESMO lote, parado ha tres dias, e' alarme
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("UPDATE mky_recebiveis"
                        " SET criado_fornecedor = now() - interval '72 hours'")
        lote = portal.montar(esquema=esquema_pg)["lote_aberto"]
        assert lote["estado"] == "alerta" and lote["horas"] >= 48

    def test_faixas_de_prazo_medem_da_antecipacao_ate_o_vencimento(
            self, esquema_pg):
        hoje = date.today()
        criado = hoje - timedelta(days=10)
        self._cria(esquema_pg, [
            ("F1", criado.isoformat(), (criado + timedelta(days=20)).isoformat(),
             1000.0, 990.0, 1.30, "BANCO A"),
            ("F2", criado.isoformat(), (criado + timedelta(days=90)).isoformat(),
             1000.0, 960.0, 1.10, "BANCO A")])
        faixas = {f["faixa"]: f for f in portal.montar(esquema=esquema_pg)["faixas_prazo"]}
        assert "até 29 dias" in faixas and "84 dias ou mais" in faixas, faixas
        assert faixas["até 29 dias"]["titulos"] == 1
        assert faixas["84 dias ou mais"]["titulos"] == 1

    def test_a_unidade_da_taxa_e_declarada_e_mensal(self):
        # o modulo publicava a taxa sem unidade enquanto nao havia prova;
        # com a prova, publicar cru voltaria a esconder o que se sabe
        assert portal.TAXA_UNIDADE == "% a.m."
