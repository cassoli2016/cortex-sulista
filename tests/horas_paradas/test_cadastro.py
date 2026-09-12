"""Perfis e ajustes: o que move dinheiro não muda sem rastro."""
from __future__ import annotations

import pytest

from api.horas_paradas import cadastro, regras

CH = "1|1|20|1|0|1|20234"


def test_config_vazia_e_o_padrao_da_casa():
    cfg = cadastro.validar_config({})
    assert cfg["inicio_carga"] == regras.MAIOR and cfg["recorte"] == "fim_descarga"
    assert cfg["regras"] == [] and cfg["colunas"]


def test_chave_AUSENTE_herda_e_as_outras_valem():
    cfg = cadastro.validar_config({"inicio_descarga": "janela"})
    assert cfg["inicio_descarga"] == "janela" and cfg["inicio_carga"] == regras.MAIOR


@pytest.mark.parametrize("cfg, trecho", [
    ({"inicio_carga": "amanha"}, "Início do relógio"),
    ({"arredondamento_min": 7}, "Arredondamento"),
    ({"recorte": "quando_quiser"}, "Recorte"),
    ({"regras": [{"nome": "nada"}]}, "não tem condição nem efeito"),
    ({"regras": [{"mercadorias": ["X"], "freetime_h": 100}]}, "fora da faixa"),
    ({"regras": [{"mercadorias": ["X"], "clausula": "a melhor"}]}, "cláusula"),
    ({"colunas": [{"campo": "senha"}]}, "Coluna desconhecida"),
    ({"colunas": []}, "Colunas"),
])
def test_configuracao_invalida_e_RECUSADA_com_o_motivo(cfg, trecho):
    with pytest.raises(cadastro.Recusa, match=trecho):
        cadastro.validar_config(cfg)


def test_freetime_VAZIO_na_regra_e_herda_nao_zero():
    cfg = cadastro.validar_config({"regras": [{"mercadorias": ["X"], "freetime_h": "",
                                               "valor_h": "97,30"}]})
    assert cfg["regras"][0]["freetime_h"] is None
    assert cfg["regras"][0]["valor_h"] == 97.30


def test_regra_so_com_CONDICAO_e_excecao_valida():
    """"Para este destino, mantém o contrato" — sem efeito próprio, mas com
    condição: é a exceção que vem antes da regra geral."""
    cfg = cadastro.validar_config({"regras": [{"mercadorias": ["X"], "destinos": ["1"]}]})
    assert cfg["regras"][0]["destinos"] == ["1"]


def test_perfil_duplicado_e_recusado(esquema_pg):
    cadastro.criar_perfil(8, "CLIENTE A", "a@x", esquema=esquema_pg)
    with pytest.raises(cadastro.Recusa, match="já tem perfil"):
        cadastro.criar_perfil(8, "CLIENTE A", "b@x", esquema=esquema_pg)


def test_salvar_VERSIONA_so_quando_muda(esquema_pg):
    p = cadastro.criar_perfil(8, "CLIENTE A", "a@x", esquema=esquema_pg)
    assert len(cadastro.versoes(p["id"], esquema=esquema_pg)) == 1
    cadastro.salvar_config(p["id"], {}, "a@x", esquema=esquema_pg)
    assert len(cadastro.versoes(p["id"], esquema=esquema_pg)) == 1
    novo = cadastro.salvar_config(p["id"], {"inicio_carga": "chegada"}, "b@x",
                                  esquema=esquema_pg)
    assert novo["config"]["inicio_carga"] == "chegada"
    assert novo["atualizado_por"] == "b@x"
    v = cadastro.versoes(p["id"], esquema=esquema_pg)
    assert len(v) == 2 and v[0]["autor"] == "b@x"


def test_ajuste_sem_MOTIVO_nao_entra(esquema_pg):
    with pytest.raises(cadastro.Recusa, match="motivo"):
        cadastro.ajustar(CH, "carga_chegada", "2026-09-09 07:40", None, "ok", "a@x",
                         esquema=esquema_pg)


def test_ajuste_normaliza_o_horario_e_guarda_a_FOTO_do_ERP(esquema_pg):
    r = cadastro.ajustar(CH, "carga_chegada", "2026-09-09 07:40", "2026-09-09T08:30:00",
                         "portaria anotou 07:40", "a@x", esquema=esquema_pg)
    assert r["valor"] == "2026-09-09T07:40" and r["valor_erp"].startswith("2026-09-09T08:30")
    aj = cadastro.ajustes_de([CH], esquema=esquema_pg)
    assert aj[CH]["carga_chegada"]["motivo"] == "portaria anotou 07:40"


def test_ajustar_de_novo_SUBSTITUI_e_desfazer_volta_ao_ERP(esquema_pg):
    cadastro.ajustar(CH, "descarga_janela", "2026-09-09 14:00", None, "janela remarcada",
                     "a@x", esquema=esquema_pg)
    cadastro.ajustar(CH, "descarga_janela", "2026-09-09 15:00", None, "remarcada de novo",
                     "b@x", esquema=esquema_pg)
    aj = cadastro.ajustes_de([CH], esquema=esquema_pg)[CH]
    assert aj["descarga_janela"]["valor"] == "2026-09-09T15:00"
    assert aj["descarga_janela"]["autor"] == "b@x"
    assert cadastro.desfazer(CH, "descarga_janela", esquema=esquema_pg)
    assert cadastro.ajustes_de([CH], esquema=esquema_pg) == {}
    assert not cadastro.desfazer(CH, "descarga_janela", esquema=esquema_pg)


@pytest.mark.parametrize("campo, valor", [
    ("carga_chegada", "ontem"), ("incluir", "talvez"), ("placa", "X"), ("referencia", "  ")])
def test_valor_de_ajuste_invalido_e_recusado(esquema_pg, campo, valor):
    with pytest.raises(cadastro.Recusa):
        cadastro.ajustar(CH, campo, valor, None, "motivo qualquer", "a@x", esquema=esquema_pg)


def test_contagem_para_a_saude(esquema_pg):
    assert cadastro.contagem(esquema=esquema_pg)["perfis"] == 0
    cadastro.criar_perfil(8, "CLIENTE A", "a@x", esquema=esquema_pg)
    cadastro.ajustar(CH, "incluir", "nao", None, "carga de teste do cliente", "a@x",
                     esquema=esquema_pg)
    c = cadastro.contagem(esquema=esquema_pg)
    assert c["perfis"] == 1 and c["ajustes"] == 1 and c["ultimo_ajuste"]
