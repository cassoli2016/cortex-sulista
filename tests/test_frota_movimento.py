# -*- coding: utf-8 -*-
"""A reserva da TomTom pela velocidade da própria frota (ERP + Gobrax).

As placas e as séries aqui são INVENTADAS: o repositório é público, e placa e
coordenada reais não entram em commit. O FORMATO é o real — o ponto da Gobrax
traz só `date`, `lat`, `lon`, `speed` (medido em 11/09/2026) e a linha do ERP é
`(placa, dt, velocidade)` de `veiculo_posicao`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from api import credenciais, frota_movimento as fm
from api.tomtom import cliente, coleta

AGORA = datetime(2026, 9, 11, 11, 0, 0)


def serie(*vels, passo_min=5, fim_ha_min=1):
    """Pontos igualmente espaçados terminando `fim_ha_min` antes de AGORA."""
    fim = AGORA - timedelta(minutes=fim_ha_min)
    n = len(vels)
    return [(fim - timedelta(minutes=passo_min * (n - 1 - i)), float(v))
            for i, v in enumerate(vels)]


# ------------------------------------------------------------- a classificação

def test_andando_e_andando():
    c = fm.classificar(serie(70, 72, 68), AGORA)
    assert c["estado"] == "livre" and c["rotulo"] == "Andando" and c["velocidade"] == 68


def test_LENTO_so_com_duas_leituras_seguidas():
    """Uma leitura lenta é pedágio ou rotatória; duas seguidas é trânsito."""
    c = fm.classificar(serie(70, 30, 22, 18), AGORA)
    assert c["estado"] == "lento" and c["minutos"] == 10
    assert c["rotulo"] == "Lento há 10 min"


def test_UMA_leitura_lenta_nao_e_verde_nem_transito():
    """Visto com o dado real de 11/09/2026: um caminhão a 10 km/h saía
    "Andando", em verde. Uma leitura só não decide — fica neutra, com a
    velocidade à mostra."""
    c = fm.classificar(serie(70, 70, 10), AGORA)
    assert c["estado"] == "nd" and c["rotulo"] == "Devagar numa leitura só (10 km/h)"


def test_PARADO_diz_o_tempo_e_NAO_a_causa():
    c = fm.classificar(serie(60, 0, 0, 0), AGORA)
    assert c["estado"] == "parado" and c["minutos"] == 10
    assert c["motivo"] == "não informado"
    assert "congest" not in c["rotulo"].lower()


def test_parado_a_JANELA_TODA_e_ha_MAIS_de():
    """A série começa no meio da parada: "há 40 min" afirmaria quando ela
    começou, e a fonte não disse."""
    c = fm.classificar(serie(0, 0, 0, 0, 0, 0, 0, 0, 0), AGORA)
    assert c["rotulo"] == "Parado há mais de 40 min"


def test_ponto_VELHO_nao_e_agora():
    c = fm.classificar(serie(70, 0, fim_ha_min=45), AGORA)
    assert c["estado"] == "nd" and "há 45 min" in c["rotulo"]


def test_sem_ponto_nenhum_e_nd_e_nao_livre():
    assert fm.classificar([], AGORA)["estado"] == "nd"


# ------------------------------------------------------------- as duas fontes

def test_o_ultimo_ponto_da_GOBRAX_vence_quando_e_mais_novo():
    """A Gobrax manda a cada 30 s: com o ERP a 5 min, é ela que diz o agora."""
    posicoes = {"posicoes": {"AAA0A00": {"fonte": "gobrax", "velocidade": 64,
                                         "quando": AGORA - timedelta(seconds=20)}}}
    ler = lambda placas, agora: {"AAA0A00": serie(0, 0, 0, fim_ha_min=4)}
    t = fm.condicao(["AAA0A00"], posicoes, AGORA, ler=ler)[0]
    assert t["estado"] == "livre" and t["fonte_velocidade"] == "gobrax"
    assert t["fonte"] == "frota" and t["atraso_s"] is None


def test_gobrax_mais_VELHA_que_o_ERP_nao_entra():
    posicoes = {"posicoes": {"AAA0A00": {"fonte": "gobrax", "velocidade": 64,
                                         "quando": AGORA - timedelta(minutes=20)}}}
    ler = lambda placas, agora: {"AAA0A00": serie(0, 0, 0)}
    t = fm.condicao(["AAA0A00"], posicoes, AGORA, ler=ler)[0]
    assert t["estado"] == "parado" and t["fonte_velocidade"] == "erp"


def test_a_consulta_do_ERP_serve_ao_indice_e_ao_9_3():
    """`(veiculo, dt)` é o índice que torna a consulta barata numa tabela de
    4,2 milhões de linhas; `make_interval` não existe no PostgreSQL 9.3."""
    sql = " ".join(fm.SERIE_SQL.split())
    assert "WHERE veiculo = ANY(%s) AND dt >= %s" in sql
    assert "make_interval" not in sql


# ------------------------------------------------------------- a reserva na Torre

VIAGENS = [{"placa": "AAA0A00"}, {"placa": "BBB1B11"}]
POSICOES = {"posicoes": {
    "AAA0A00": {"lat": -26.3, "lon": -48.8, "fonte": "erp", "idade_min": 2.0},
    "BBB1B11": {"lat": -25.4, "lon": -49.2, "fonte": "erp", "idade_min": 3.0},
}, "por_fonte": {"erp": 2}, "fontes_fora": []}


@pytest.fixture
def torre(tmp_path, monkeypatch):
    monkeypatch.setattr(credenciais, "CAMINHO", tmp_path / "cred.json")
    for n in ("TOMTOM_API_KEY", "TOMTOM_API_KEY_SERVIDOR"):
        monkeypatch.delenv(n, raising=False)
    credenciais.gravar("TOMTOM_API_KEY", "chave-de-teste-aaaaaaaa")
    monkeypatch.setattr(cliente, "_FREIO", {})
    # a reserva por FALHA da TomTom é o assunto; a por decisão tem arquivo
    # próprio (test_tomtom_trafego_desligado.py)
    monkeypatch.setattr(cliente, "TRAFEGO_DESLIGADO", None)
    monkeypatch.setattr(coleta, "_cache", None)
    monkeypatch.setattr(coleta, "registrar", lambda *a, **k: None)
    # a reserva por FALHA da varredura é o assunto; por padrão a Torre nem
    # varre (`coleta.FLUXO_NA_TORRE`), e isso tem teste próprio abaixo
    monkeypatch.setattr(coleta, "FLUXO_NA_TORRE", True)
    monkeypatch.setattr(fm, "serie", lambda placas, agora=None, janela_min=45: {
        "AAA0A00": serie(30, 20, 15, fim_ha_min=1),
        "BBB1B11": serie(0, 0, 0, fim_ha_min=1)})
    # o relógio da classificação acompanha o das séries
    real = fm.classificar
    monkeypatch.setattr(fm, "classificar", lambda pts, agora: real(pts, AGORA))


def test_com_o_FREIO_de_credito_a_torre_recebe_a_RESERVA(torre, monkeypatch):
    monkeypatch.setattr(cliente, "freio", lambda familia="traffic": {
        "familia": "traffic", "desde": "2026-09-11T10:17:04",
        "ate": "2026-09-11T11:17:04", "resta_s": 3000})
    monkeypatch.setattr(cliente, "fluxo", lambda *a, **k: pytest.fail("saiu para a TomTom"))
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["reserva"] is True and r["sem_creditos"] is True
    assert "erro" not in r, "com `erro` a Torre esconderia as linhas da reserva"
    estados = {t["placa"]: t["estado"] for t in r["trechos"]}
    assert estados == {"AAA0A00": "lento", "BBB1B11": "parado"}
    assert "sem créditos" in r["reserva_motivo"]


def test_a_SONDA_recusada_por_credito_tambem_cai_na_reserva(torre, monkeypatch):
    def sem_credito(*a, **k):
        raise cliente.TomTomSemCreditos("sem crédito", "traffic")
    monkeypatch.setattr(cliente, "fluxo", sem_credito)
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["reserva"] is True and len(r["trechos"]) == 2


def test_TomTom_recusando_TODOS_os_pontos_cai_na_reserva(torre, monkeypatch):
    def fora(*a, **k):
        raise cliente.TomTomIndisponivel("A TomTom respondeu HTTP 500.")
    monkeypatch.setattr(cliente, "fluxo", fora)
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["reserva"] is True and "não respondeu" in r["reserva_motivo"]


def test_SEM_CHAVE_a_reserva_responde(torre, monkeypatch):
    monkeypatch.setattr(cliente, "configurado", lambda: False)
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["reserva"] is True and r["configurado"] is False
    assert len(r["trechos"]) == 2


def test_por_padrao_a_torre_NAO_varre_a_TomTom(torre, monkeypatch):
    """11/09/2026: a franquia grátis de fluxo é de 20 mil por MÊS e a varredura
    gastava de 3 a 7 mil por DIA. A Torre fica com a velocidade da frota."""
    monkeypatch.setattr(coleta, "FLUXO_NA_TORRE", False)
    monkeypatch.setattr(cliente, "fluxo", lambda *a, **k: pytest.fail("varreu a TomTom"))
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["fonte_principal"] == "frota" and "20 mil" in r["reserva_motivo"]
    assert {t["placa"]: t["estado"] for t in r["trechos"]} == {
        "AAA0A00": "lento", "BBB1B11": "parado"}


def test_com_a_TomTom_respondendo_NAO_ha_reserva(torre, monkeypatch):
    """O contrapeso: a TomTom é a principal, por decisão de quem opera."""
    monkeypatch.setattr(cliente, "fluxo", lambda *a, **k: {"flowSegmentData": {
        "currentSpeed": 80, "freeFlowSpeed": 80, "confidence": 1,
        "currentTravelTime": 60, "freeFlowTravelTime": 60, "roadClosure": False}})
    monkeypatch.setattr(fm, "condicao", lambda *a, **k: pytest.fail("usou a reserva"))
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert not r.get("reserva") and {t["estado"] for t in r["trechos"]} == {"livre"}


def test_a_reserva_que_TAMBEM_falha_diz_as_duas_coisas(torre, monkeypatch):
    monkeypatch.setattr(cliente, "configurado", lambda: False)

    def erp_fora(*a, **k):
        raise RuntimeError("ERP fora")
    monkeypatch.setattr(fm, "condicao", erp_fora)
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["trechos"] == [] and "reserva" in r["erro"] and "RuntimeError" in r["erro"]


# ------------------------------------------------------------- a TV

def test_a_TV_nao_poe_selo_vermelho_no_PARADO_da_reserva():
    html = (Path(__file__).resolve().parent.parent / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    i = html.index("function tvBadgeChegada(")
    corpo = html[i:html.index("\n}\n", i)]
    j = corpo.index("tr.fonte === 'frota'")
    assert j < corpo.index("'PARADO'"), "a regra da reserva tem de vir ANTES do selo PARADO"
