# -*- coding: utf-8 -*-
"""Fase 2 do GR: a gravação e a coleta do RasterIntegra.

O dublê copia o corpo REAL do fornecedor (medido ao vivo em 01/09/2026),
inclusive as manias que o manual não conta: Rota como OBJETO {CodRota,
Descricao}, contador de risco OMITIDO quando é zero, viagens abertas (L/I)
vindo junto das finalizadas mesmo com filtro de datas.
"""
from __future__ import annotations

from datetime import date

import pytest

from api.rasterintegra import armazenamento as arm
from api.rasterintegra import coleta

# corpo real (anonimizado) de uma viagem FINALIZADA do getEventoFimViagem —
# note BotaoPanico AUSENTE com ParadasAreaRisco presente, e Rota-objeto
VIAGEM_F = {
    "CodSolicitacao": 8400001, "CodFilial": 123,
    "PlacaVeiculo": "ABC-1234", "VincVeiculo": "A",
    "PlacaCarreta1": "XYZ-9876", "VincCarreta1": "A",
    "CPFMotorista1": "00000000000", "VincMotorista1": "A",
    "CNPJClienteOrig": "11111111111111", "CNPJClienteDest": "22222222222222",
    "DataHoraPrevIni": "2026-08-28T08:00:00.000-03:00",
    "DataHoraPrevFim": "2026-08-29T18:00:00.000-03:00",
    "StatusViagem": "F", "StatusEngate": "S", "StatusRota": "I",
    "DataHoraRealIni": "2026-08-28T08:12:31.230-03:00",
    "DataHoraRealFim": "2026-08-29T12:33:02.000-03:00",
    "DentroPrazo": "N", "PercentualAtraso": 12.5,
    "VelocidadeMedia": 47.3, "LocalMaiorVelocidade": "BR-116 KM 220",
    "TempoTotalViagem": 1701, "TempoParado": 412, "TempoMovimentando": 1289,
    "PercentualMovimentando": 75.8, "TempoParadoAreaRisco": 412,
    "ParadasAreaRisco": 3, "EventosVelocidade": 34,
    "RodouForaHorario": "N",
    "Rota": {"CodRota": 3848735, "Descricao": "TW CACAPAVA - ADIENT SJP"},
    "ColetasEntregas": [
        {"Tipo": "C", "DentroPrazo": "S"},
        {"Tipo": "E", "DentroPrazo": "N"},
    ],
    "LinkTimeLine": "https://exemplo/timeline/8400001",
    "CNPJProprietario": "33333333333333",
}

# viagem ABERTA (status L) — vem junto na mesma resposta e NÃO pode entrar
VIAGEM_L = {
    "CodSolicitacao": 8400002, "PlacaVeiculo": "DEF-5678",
    "VincVeiculo": "F", "StatusViagem": "L",
    "DataHoraPrevIni": "2026-08-30T10:00:00.000-03:00",
    "DentroPrazo": "N", "PercentualAtraso": 0, "VelocidadeMedia": 0,
    "UltimaTemperatura": {},
}


def _linhas(cur, esquema, tabela):
    cur.execute(f"SELECT count(*) AS n FROM {tabela}")
    return cur.fetchone()["n"]


class TestArmazenamento:
    def test_so_a_finalizada_entra_e_o_upsert_e_idempotente(self, esquema_pg):
        from api import pglocal
        n = arm.upsert_viagens([VIAGEM_F, VIAGEM_L], esquema=esquema_pg)
        assert n == 1  # a L fica de fora — não tem consolidado
        n2 = arm.upsert_viagens([VIAGEM_F, VIAGEM_L], esquema=esquema_pg)
        assert n2 == 1  # recoletar é o caso normal
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            assert _linhas(cur, esquema_pg, "gr_viagem_fim") == 1
            cur.execute("SELECT * FROM gr_viagem_fim")
            v = dict(cur.fetchone())
        assert v["placa"] == "ABC1234"            # normalizada, sem hífen
        assert v["rota"] == "TW CACAPAVA - ADIENT SJP"  # objeto → descrição
        assert v["botao_panico"] is None          # omitido fica NULL
        assert v["paradas_area_risco"] == 3
        assert v["dentro_prazo"] is False
        assert v["coletas_entregas"] == 2 and v["coletas_no_prazo"] == 1
        assert v["real_fim"] is not None

    def test_atualizacao_muda_o_campo_e_nao_duplica(self, esquema_pg):
        from api import pglocal
        arm.upsert_viagens([VIAGEM_F], esquema=esquema_pg)
        depois = dict(VIAGEM_F, EventosVelocidade=40, BotaoPanico=1)
        arm.upsert_viagens([depois], esquema=esquema_pg)
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT eventos_velocidade, botao_panico,"
                        " count(*) OVER () AS n FROM gr_viagem_fim")
            v = dict(cur.fetchone())
        assert (v["n"], v["eventos_velocidade"], v["botao_panico"]) == (1, 40, 1)

    def test_km_idempotente_e_normalizado(self, esquema_pg):
        from api import pglocal
        itens = [{"Placa": "AJS-1111", "Motorista": "FULANO", "CPF": "0",
                  "VinculoVeiculo": "Agregado", "KMComViagem": 320.5,
                  "KMSemViagem": 12.0}]
        dia = date(2026, 8, 31)
        assert arm.upsert_km(dia, itens, esquema=esquema_pg) == 1
        itens[0]["KMComViagem"] = 340.0
        assert arm.upsert_km(dia, itens, esquema=esquema_pg) == 1
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT placa, km_com_viagem,"
                        " count(*) OVER () AS n FROM gr_km_dia")
            v = dict(cur.fetchone())
        assert (v["n"], v["placa"], v["km_com_viagem"]) == (1, "AJS1111", 340.0)

    def test_sn_com_I_da_apolice_vira_none(self):
        assert arm.sn("S") is True
        assert arm.sn("N") is False
        assert arm.sn("I") is None   # ignorado pela apólice ≠ não
        assert arm.sn("") is None


class TestColeta:
    def test_coleta_grava_e_registra_a_trilha(self, esquema_pg, monkeypatch):
        from api import pglocal
        respostas = {"ABC1234": {"Viagens": [VIAGEM_F, VIAGEM_L]},
                     "DEF5678": {"Viagens": []}}
        chamadas = []

        def falso_chamar(metodo, corpo):
            chamadas.append((metodo, dict(corpo)))
            return respostas[corpo["Placa"]]

        monkeypatch.setattr(coleta.cliente, "chamar", falso_chamar)
        r = coleta.coletar_viagens(placas=["ABC1234", "DEF5678"], pausa=0,
                                   esquema=esquema_pg)
        assert r["placas"] == 2 and r["gravadas"] == 1
        # toda chamada leva a janela de datas — é o filtro que o servidor honra
        assert all("DataInicial" in c and "DataFinal" in c
                   for _, c in chamadas)
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT tipo, consultas, gravadas, erro FROM gr_carga")
            carga = dict(cur.fetchone())
        assert carga == {"tipo": "viagens", "consultas": 2,
                         "gravadas": 1, "erro": None}

    def test_falha_no_meio_fica_escrita_na_trilha(self, esquema_pg, monkeypatch):
        from api import pglocal
        from api.rasterintegra import cliente as cli

        def explode(metodo, corpo):
            raise cli.RasterIntegraIndisponivel("HTTP 500 em getEventoFimViagem")

        monkeypatch.setattr(coleta.cliente, "chamar", explode)
        with pytest.raises(cli.RasterIntegraIndisponivel):
            coleta.coletar_viagens(placas=["ABC1234"], pausa=0,
                                   esquema=esquema_pg)
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT gravadas, erro FROM gr_carga")
            carga = dict(cur.fetchone())
        assert carga["gravadas"] == 0
        assert "RasterIntegraIndisponivel" in carga["erro"]

    def test_placa_instavel_e_pulada_e_a_varredura_continua(
            self, esquema_pg, monkeypatch):
        """O 503 da Raster no meio da varredura matou a primeira carga
        completa (01/09/2026). Instabilidade transitória custa UMA placa,
        nunca a noite: pula, conta e segue — a janela de 8 dias da noite
        seguinte cobre o buraco."""
        from api import pglocal
        from api.rasterintegra import cliente as cli

        def instavel(metodo, corpo):
            if corpo["Placa"] == "RUIM0001":
                raise cli.RasterIntegraIndisponivel("HTTP 503 em getEventoFimViagem")
            return {"Viagens": [VIAGEM_F]}

        monkeypatch.setattr(coleta.cliente, "chamar", instavel)
        monkeypatch.setattr(coleta.time, "sleep", lambda s: None)
        r = coleta.coletar_viagens(
            placas=["ABC1234", "RUIM0001", "DEF5678"], pausa=0,
            esquema=esquema_pg)
        assert r["placas"] == 2 and r["puladas"] == 1
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT janela, erro FROM gr_carga")
            carga = dict(cur.fetchone())
        assert carga["erro"] is None, "varredura que TERMINOU é carga limpa"
        assert "1 puladas" in carga["janela"]

    def test_servico_fora_do_ar_interrompe_e_fica_dito(
            self, esquema_pg, monkeypatch):
        """Mais de um quinto pulado não é instabilidade, é o serviço FORA —
        parar e escrever o erro vale mais que varrer o vazio até o fim."""
        from api import pglocal
        from api.rasterintegra import cliente as cli

        def morto(metodo, corpo):
            raise cli.RasterIntegraIndisponivel("HTTP 503 em getEventoFimViagem")

        monkeypatch.setattr(coleta.cliente, "chamar", morto)
        monkeypatch.setattr(coleta.time, "sleep", lambda s: None)
        with pytest.raises(cli.RasterIntegraIndisponivel):
            coleta.coletar_viagens(placas=[f"P{i:07d}" for i in range(9)],
                                   pausa=0, esquema=esquema_pg)
        with pglocal.get_conn(esquema_pg) as conn, conn.cursor() as cur:
            cur.execute("SELECT erro FROM gr_carga")
            assert "RasterIntegraIndisponivel" in cur.fetchone()["erro"]

    def test_rate_limit_espera_e_repete_uma_vez(self, monkeypatch):
        from api.rasterintegra import cliente as cli
        tentativas = []

        def quase(metodo, corpo):
            tentativas.append(1)
            if len(tentativas) == 1:
                raise cli.RasterIntegraIndisponivel(
                    "getEventoFimViagem: CodErro 102 — consumo indevido")
            return {"Viagens": []}

        monkeypatch.setattr(coleta.cliente, "chamar", quase)
        monkeypatch.setattr(coleta.time, "sleep", lambda s: None)
        d = coleta._chamar_com_paciencia("getEventoFimViagem", {})
        assert d == {"Viagens": []} and len(tentativas) == 2
