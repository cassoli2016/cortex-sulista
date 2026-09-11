# -*- coding: utf-8 -*-
"""O TRÂNSITO DA TOMTOM DESLIGADO POR DECISÃO — e não por falha.

O QUE ACONTECEU EM 11/09/2026: o produto de trânsito ficou sem crédito
(InsufficientFunds) e quem opera decidiu NÃO recarregar. O freio de uma hora
(`test_tomtom_creditos.py`) serve à falta que vai ser consertada; para a que
não vai, ele deixava a Saúde e o Radar vermelhos para sempre e a TV pedindo ao
navegador a camada de um produto sem crédito. Desligado: nada de trânsito sai
daqui, a Torre usa a velocidade da própria frota, e os cartões dizem a decisão
— em azul, porque não há o que consertar.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from api import credenciais
from api.tomtom import cliente

DECISAO = {"desde": "2026-09-11",
           "motivo": "sem crédito no produto de trânsito, e a decisão foi não recarregar"}


@pytest.fixture
def cofre(tmp_path, monkeypatch):
    monkeypatch.setattr(credenciais, "CAMINHO", tmp_path / "cred.json")
    for n in ("TOMTOM_API_KEY", "TOMTOM_API_KEY_SERVIDOR"):
        monkeypatch.delenv(n, raising=False)
    credenciais.gravar("TOMTOM_API_KEY", "chave-do-mapa-aaaaaaaa")
    credenciais.gravar("TOMTOM_API_KEY_SERVIDOR", "chave-do-servidor-bbbbbbbb")
    monkeypatch.setattr(cliente, "_FREIO", {})
    return tmp_path


@pytest.fixture
def desligado(cofre, monkeypatch):
    monkeypatch.setattr(cliente, "TRAFEGO_DESLIGADO", dict(DECISAO))


@pytest.fixture
def ligado(cofre, monkeypatch):
    monkeypatch.setattr(cliente, "TRAFEGO_DESLIGADO", None)


class _Resposta:
    def __init__(self, corpo: dict):
        self._b = json.dumps(corpo).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Rede:
    """`urlopen` de mentira que responde a busca e ANOTA tudo que saiu."""

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, req, timeout=None, context=None):
        self.urls.append(req.full_url)
        return _Resposta({"results": [{"position": {"lat": -25.43, "lon": -49.27},
                                       "address": {"municipality": "Curitiba"}}]})


@pytest.fixture
def rede(monkeypatch) -> Rede:
    r = Rede()
    monkeypatch.setattr(cliente.urllib.request, "urlopen", r)
    return r


# ------------------------------------------------------------- a decisão

def test_a_decisao_escrita_tem_DATA_e_MOTIVO():
    """Desligar sem dizer desde quando e por quê produz um cartão azul que
    ninguém sabe explicar. Religar é `None` — e isso também passa aqui."""
    d = cliente.TRAFEGO_DESLIGADO
    if d is not None:
        date.fromisoformat(d["desde"])
        assert str(d["motivo"]).strip()


def test_desligado_o_TRANSITO_nao_sai_para_a_rede_e_a_BUSCA_sai(desligado, rede):
    with pytest.raises(cliente.TomTomDesligado) as e:
        cliente.fluxo(-26.3, -48.8)
    with pytest.raises(cliente.TomTomDesligado):
        cliente.incidentes(sul=-26.1, oeste=-49.9, norte=-24.8, leste=-48.4)
    assert not any("/traffic/" in u for u in rede.urls), "trânsito saiu para a rede desligado"
    assert "11/09/2026" in str(e.value)
    assert "chave-do-servidor" not in str(e.value)
    assert cliente.geocodificar("Curitiba", "PR") is not None
    assert any("/search/" in u for u in rede.urls), "a busca é outro produto e segue"
    assert cliente.freio("traffic") is None, "decisão não é falha: o freio não liga"


def test_o_radar_diz_a_DECISAO_e_nao_sem_credito():
    from api.radar import fontes
    exc = cliente.TomTomDesligado("O trânsito da TomTom está desligado...", "traffic")
    assert fontes.descrever_falha(exc) == "trânsito da TomTom desligado por decisão"


# ------------------------------------------------------------- a Torre e a TV

VIAGENS = [{"placa": f"AAA{i}A1{i}"} for i in range(6)]
POSICOES = {"posicoes": {f"AAA{i}A1{i}": {"lat": -26.3, "lon": -48.8, "fonte": "erp",
                                          "idade_min": 3.0} for i in range(6)},
            "por_fonte": {"erp": 6}, "fontes_fora": []}


def test_a_torre_vai_direto_para_a_RESERVA_sem_sonda_e_sem_contar(desligado, monkeypatch):
    from api import frota_movimento
    from api.tomtom import coleta
    monkeypatch.setattr(coleta, "_cache", None)
    registros = []
    monkeypatch.setattr(coleta, "registrar", lambda *a, **k: registros.append((a, k)))
    monkeypatch.setattr(frota_movimento, "serie", lambda *a, **k: {})
    monkeypatch.setattr(cliente, "fluxo", lambda *a, **k: pytest.fail("sondou a TomTom desligada"))
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES, origem="tv")
    assert r["reserva"] is True and r["desligado"]["desde"] == "2026-09-11"
    assert "desligado por decisão desde 11/09/2026" in r["reserva_motivo"]
    assert "erro" not in r and not r.get("sem_creditos")
    assert registros == [], "nada foi tentado: não há varredura barrada para contar"


def test_a_TV_nao_recebe_a_chave_nem_pede_a_camada(desligado):
    from api import main
    corpo = json.loads(main.tv_estradas().body)
    assert corpo["configurado"] is False and corpo["key"] == ""
    assert corpo["desligado"]["desde"] == "2026-09-11"


def test_LIGADO_a_TV_recebe_a_chave_do_MAPA(ligado):
    from api import main
    corpo = json.loads(main.tv_estradas().body)
    assert corpo["configurado"] is True and corpo["key"] == "chave-do-mapa-aaaaaaaa"
    assert corpo["desligado"] is None


# ------------------------------------------------------------- o Radar

def test_o_radar_nem_PLANEJA_a_coleta_de_rodovias(desligado):
    from api.radar import coleta as rcoleta
    from api.radar import rodovias
    assert rodovias.ativo() is False
    assert rodovias.desligado()["desde_br"] == "11/09/2026"
    assert "rodovias" not in [f for f, _ in rcoleta._plano(baixar=None, esquema=None)]


# ------------------------------------------------------------- a Saúde

def _saude(monkeypatch):
    from api import servidor
    from api.tomtom import coleta
    monkeypatch.setattr(coleta, "consumo", lambda *a, **k: {"hoje": 27, "erros_hoje": 27})
    monkeypatch.setattr(coleta, "consumo_por_origem", lambda *a, **k: [])
    monkeypatch.setattr(cliente, "freio", lambda familia="traffic": {
        "familia": "traffic", "desde": "2026-09-11T10:17:04",
        "ate": "2026-09-11T11:17:04", "resta_s": 3000})
    return servidor._servico_tomtom()


def test_o_cartao_da_TomTom_diz_a_DECISAO_em_azul_mesmo_com_erros_de_hoje(desligado,
                                                                          monkeypatch):
    c = _saude(monkeypatch)
    assert c["nome"] == "TomTom (trânsito)"
    assert c["status"] == "info", c
    assert "DESLIGADO por decisão desde 11/09/2026" in c["detalhe"]
    assert "SEM CRÉDITOS" not in c["detalhe"]
    assert "27 chamada(s) hoje" in c["detalhe"], "o consumo continua à vista"


def test_LIGADO_e_sem_credito_o_cartao_segue_VERMELHO(ligado, monkeypatch):
    """O contrapeso: a decisão não pode ter engolido o alarme da falta que
    vai ser consertada."""
    c = _saude(monkeypatch)
    assert c["status"] == "erro" and c["detalhe"].startswith("SEM CRÉDITOS")
