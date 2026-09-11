# -*- coding: utf-8 -*-
"""O que a página inicial lê, o cartão da Saúde e o resumo do Copiloto."""
from __future__ import annotations

import json
from datetime import date

import psycopg
import pytest

from api import pglocal
from api.radar import coleta, painel


@pytest.fixture
def carregado(esquema_pg, rede, tomtom, relogio):
    coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom)
    return esquema_pg


# ------------------------------------------------------------------ diesel

def test_o_diesel_compara_com_a_semana_que_fechou_SETE_DIAS_ANTES(carregado):
    d = painel.painel(carregado)["diesel"]["diesel_s10"]
    assert d["ultimo"]["semana_fim"] == "2026-09-05" and d["ultimo"]["revenda"] == 6.88
    assert d["anterior"]["semana_fim"] == "2026-08-29"
    assert d["ref_4s"]["dia"] == "2026-08-08"


def test_sem_pesquisa_na_semana_anterior_NAO_HA_comparacao(carregado):
    """A posição anterior da lista seria uma semana de duas semanas atrás
    apresentada como "a semana passada"."""
    pglocal.executar("DELETE FROM rad_combustivel WHERE semana_fim = '2026-08-29'",
                     esquema=carregado)
    assert painel.painel(carregado)["diesel"]["diesel_s10"]["anterior"] is None


# ------------------------------------------------------------------ mercado

def test_o_brent_de_agora_e_o_fechamento_do_pregao_anterior(carregado):
    b = painel.painel(carregado)["brent"]
    assert b["agora"]["valor"] == 103.68 and b["agora"]["dia"] == "2026-09-11"
    assert b["fechamento_anterior"]["dia"] == "2026-09-10"
    assert b["ref_30d"]["dia"] <= "2026-08-12"
    assert b["serie"][-1]["dia"] == "2026-09-11"


def test_o_dolar_nao_leva_serie_so_as_referencias(carregado):
    d = painel.painel(carregado)["dolar"]
    assert d["agora"]["valor"] == 5.0949
    assert d["serie"] == [] and d["fechamento_anterior"] is not None


def test_o_payload_inteiro_e_JSON(carregado):
    json.dumps(painel.painel(carregado))


# ------------------------------------------------------------------ notícias

def test_a_mesma_manchete_em_dois_veiculos_aparece_UMA_vez(carregado):
    n = painel.painel(carregado)["noticias"]["diesel"]
    um = n["itens"][0]
    pglocal.executar(
        "INSERT INTO rad_noticia (tema, guid, titulo, fonte, link, publicada_em) "
        "VALUES ('diesel', 'copia', %s, 'Outro Veículo', 'https://x.test/b', %s)",
        (um["titulo"].upper(), um["publicada_em"]), esquema=carregado)
    assert painel.painel(carregado)["noticias"]["diesel"]["total"] == n["total"]


def test_link_que_nao_e_https_NAO_SAI_na_tela(carregado):
    pglocal.executar(
        "INSERT INTO rad_noticia (tema, guid, titulo, link, publicada_em) "
        "VALUES ('trc', 'js', 'Manchete maliciosa', 'javascript:alert(1)', "
        "'2026-09-11T10:00:00Z')", esquema=carregado)
    titulos = [i["titulo"] for i in painel.painel(carregado)["noticias"]["trc"]["itens"]]
    assert "Manchete maliciosa" not in titulos


def test_a_janela_das_rodovias_e_de_tres_dias(carregado, relogio):
    relogio.andar(days=3)
    n = painel.painel(carregado)["noticias"]
    assert n["rodovias"]["total"] < n["diesel"]["total"]


# ------------------------------------------------------------------ rodovias

def test_a_rodovia_fechada_vem_antes_da_lenta(carregado):
    r = painel.painel(carregado)["rodovias"]
    assert r["itens"][0]["bloqueia"] is True
    assert r["bloqueios"] == 4
    lenta = next(i for i in r["itens"] if not i["bloqueia"])
    assert lenta["atraso_min"] == 5, "300 s viram 5 minutos"
    assert {c["itens"] for c in r["corredores"]} == {2}


# ------------------------------------------------------------------- ANTT

def test_a_tabela_da_ANTT_vigente_e_a_anterior():
    a = painel._antt(date(2026, 9, 11))
    assert a["resolucao"] == "6.084/2026" and a["anterior"]["resolucao"] == "6.076/2026"
    assert [l["eixos"] for l in a["carga_geral"]] == [5, 6, 7, 9]
    seis = next(l for l in a["carga_geral"] if l["eixos"] == 6)
    assert seis["ccd_anterior"] == 6.7774
    assert a["revisao_vencida"] is False


def test_passada_a_revisao_esperada_a_tela_pede_CONFERENCIA():
    """O cadastro é à mão: no dia em que a ANTT publicar a tabela nova, esta
    tela continua mostrando a velha até alguém atualizar o arquivo."""
    assert painel._antt(date(2027, 2, 1))["revisao_vencida"] is True


# ------------------------------------------------------------------ Saúde

def test_a_saude_sem_coleta_nenhuma_e_info_e_diz_por_que(esquema_pg, relogio):
    c = painel.cartao_saude(esquema_pg)
    assert c["status"] == "info" and "primeira coleta" in c["detalhe"]


def test_a_saude_fresca_e_ok_e_envelhecida_acende(carregado, relogio):
    assert painel.cartao_saude(carregado)["status"] == "ok"
    relogio.andar(minutes=90)
    assert painel.cartao_saude(carregado)["status"] == "alerta", "Brent de 1h30 atrás"
    relogio.andar(hours=4)
    assert painel.cartao_saude(carregado)["status"] == "erro"


def test_a_saude_diz_QUAL_fonte_falhou_e_por_que(esquema_pg, rede, tomtom, relogio):
    rede.falhar.add("gov.br/anp")
    coleta.coletar(esquema=esquema_pg, baixar=rede, consultar_tomtom=tomtom)
    c = painel.cartao_saude(esquema_pg)
    assert c["status"] == "erro"
    assert "Diesel (ANP): HTTPError 503" in c["detalhe"]


def test_sem_as_tabelas_a_tela_e_a_saude_dizem_e_nao_quebram(monkeypatch):
    def _sem(*a, **k):
        raise psycopg.errors.UndefinedTable("relation rad_coleta does not exist")
    monkeypatch.setattr(coleta, "estado", _sem)
    assert painel.painel()["pronto"] is False
    assert painel.cartao_saude()["status"] == "info"


# ---------------------------------------------------------------- Copiloto

def test_o_resumo_do_copiloto_e_SO_ESCALAR(carregado):
    r = painel.resumo_copiloto(carregado)
    assert all(not isinstance(v, (list, dict, tuple, set)) for v in r.values()), r
    assert r["brent_agora"] == 103.68 and r["diesel_s10_bomba_rs_litro"] == 6.88
    assert r["antt_tabela_vigente"].startswith("Res. ")
    assert r["rodovias_bloqueios_agora"] in (4, None)
