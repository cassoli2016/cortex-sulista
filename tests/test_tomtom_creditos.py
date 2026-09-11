# -*- coding: utf-8 -*-
"""A TomTom SEM CRÉDITO: dizer isso, não insistir, e saber quem gasta.

O QUE ACONTECEU EM 11/09/2026: o produto de trânsito da TomTom respondia HTTP
403 com o corpo abaixo — literal, copiado da resposta real — e o CÓRTEX lia
isso como "a chave do mapa está restrita por domínio", mandando conferir uma
chave que estava certa. Enquanto isso a Torre seguia varrendo a frota inteira a
cada ciclo, ~70 chamadas por varredura, todas recusadas: 7.440 de 7.440 até as
10h. E a busca de endereço, no mesmo minuto, respondia normal — o crédito é POR
PRODUTO, e o freio também tem de ser.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from api import credenciais
from api.tomtom import cliente

#: O corpo REAL do 403 de 11/09/2026, 10:20.
CORPO_SEM_CREDITO = (b'{"detailedError":{"code":"InsufficientFunds",'
                     b'"message":"You do not have enough credits to perform this action"}}')


@pytest.fixture
def cofre(tmp_path, monkeypatch):
    monkeypatch.setattr(credenciais, "CAMINHO", tmp_path / "cred.json")
    for n in ("TOMTOM_API_KEY", "TOMTOM_API_KEY_SERVIDOR"):
        monkeypatch.delenv(n, raising=False)
    credenciais.gravar("TOMTOM_API_KEY", "chave-do-mapa-aaaaaaaa")
    monkeypatch.setattr(cliente, "_FREIO", {})
    # o assunto aqui é o FREIO; a decisão de desligar tem arquivo próprio
    # (test_tomtom_trafego_desligado.py)
    monkeypatch.setattr(cliente, "TRAFEGO_DESLIGADO", None)
    return tmp_path


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
    """`urlopen` de mentira: trânsito sem crédito, busca respondendo."""

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, req, timeout=None, context=None):
        url = req.full_url
        self.urls.append(url)
        if "/traffic/" in url:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {},
                                         io.BytesIO(CORPO_SEM_CREDITO))
        return _Resposta({"results": [{"position": {"lat": -25.43, "lon": -49.27},
                                       "address": {"municipality": "Curitiba"}}]})


@pytest.fixture
def rede(cofre, monkeypatch) -> Rede:
    r = Rede()
    monkeypatch.setattr(cliente.urllib.request, "urlopen", r)
    return r


# ------------------------------------------------------------- dizer o motivo

def test_InsufficientFunds_e_FALTA_DE_CREDITO_e_nao_chave_restrita(rede):
    with pytest.raises(cliente.TomTomSemCreditos) as e:
        cliente.fluxo(-26.3, -48.8)
    msg = str(e.value)
    assert "CRÉDITOS" in msg and "InsufficientFunds" in msg
    assert "restrita por domínio" not in msg, "a pista da chave manda olhar o lugar errado"
    assert "chave-do-mapa-aaaaaaaa" not in msg
    assert e.value.rotulo_curto == "TomTom sem créditos no produto de trânsito"


def test_o_403_SEM_o_corpo_de_credito_continua_explicando_a_chave(cofre, monkeypatch):
    """O caso antigo não pode sumir: 403 de chave restrita não traz
    InsufficientFunds, e a explicação da chave do mapa segue valendo."""
    def explode(*a, **k):
        raise urllib.error.HTTPError("https://api.tomtom.com/x", 403, "Forbidden", {}, None)
    monkeypatch.setattr(cliente.urllib.request, "urlopen", explode)
    with pytest.raises(cliente.TomTomIndisponivel) as e:
        cliente.fluxo(-26.3, -48.8)
    assert not isinstance(e.value, cliente.TomTomSemCreditos)
    assert "restrita por domínio" in str(e.value)


# ------------------------------------------------------------- não insistir

def test_com_o_freio_ligado_o_TRANSITO_nao_sai_para_a_rede(rede):
    with pytest.raises(cliente.TomTomSemCreditos):
        cliente.fluxo(-26.3, -48.8)
    saidas = len(rede.urls)
    for _ in range(5):
        with pytest.raises(cliente.TomTomFreado):
            cliente.fluxo(-26.3, -48.8)
    with pytest.raises(cliente.TomTomFreado):
        cliente.incidentes(sul=-26.1, oeste=-49.9, norte=-24.8, leste=-48.4)
    assert len(rede.urls) == saidas, "chamada saiu para a rede com o freio ligado"
    assert cliente.freio("traffic")["resta_s"] > 3000


def test_o_freio_e_POR_PRODUTO_e_a_busca_continua(rede):
    """Medido: com o trânsito em InsufficientFunds, o geocode respondia."""
    with pytest.raises(cliente.TomTomSemCreditos):
        cliente.fluxo(-26.3, -48.8)
    assert cliente.geocodificar("Curitiba", "PR") is not None
    assert any("/search/" in u for u in rede.urls)
    assert cliente.freio("search") is None


def test_passado_o_freio_o_transito_TENTA_de_novo(rede, monkeypatch):
    with pytest.raises(cliente.TomTomSemCreditos):
        cliente.fluxo(-26.3, -48.8)
    agora = cliente.time.monotonic()
    monkeypatch.setattr(cliente.time, "monotonic", lambda: agora + cliente.FREIO_S + 1)
    saidas = len(rede.urls)
    with pytest.raises(cliente.TomTomSemCreditos):
        cliente.fluxo(-26.3, -48.8)
    assert len(rede.urls) == saidas + 1, "passado o freio, UMA chamada tem de sair"


# ------------------------------------------------------------- a varredura

VIAGENS = [{"placa": f"AAA{i}A1{i}"} for i in range(6)]
POSICOES = {"posicoes": {f"AAA{i}A1{i}": {"lat": -26.3, "lon": -48.8, "fonte": "erp",
                                          "idade_min": 3.0} for i in range(6)},
            "por_fonte": {"erp": 6}, "fontes_fora": []}


@pytest.fixture
def varredura(cofre, monkeypatch):
    from api import frota_movimento
    from api.tomtom import coleta
    monkeypatch.setattr(coleta, "_cache", None)
    registros = []
    monkeypatch.setattr(coleta, "registrar", lambda *a, **k: registros.append((a, k)))
    # Sem crédito a Torre cai na RESERVA pela velocidade da frota, que lê o
    # ERP — e nenhum teste consulta o ERP de verdade.
    monkeypatch.setattr(frota_movimento, "serie", lambda *a, **k: {})
    return coleta, registros


def test_sem_credito_a_varredura_manda_UMA_SONDA_e_nao_as_seis(varredura, monkeypatch):
    coleta, registros = varredura
    chamadas = []

    def sem_credito(lat, lon, zoom=cliente.ZOOM):
        chamadas.append(1)
        raise cliente.TomTomSemCreditos("sem crédito", "traffic")
    monkeypatch.setattr(cliente, "fluxo", sem_credito)
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES, origem="tv")
    assert len(chamadas) == 1, "a sonda falhou por crédito e as outras cinco saíram mesmo assim"
    assert r["sem_creditos"] is True and r["reserva"] is True
    assert "créditos" in r["reserva_motivo"]
    (recurso,), k = registros[-1]
    assert recurso == "fluxo" and k["n"] == 1 and k["origem"] == "tv"
    assert k["apos_reinicio"] is True, "cache vazio = primeira varredura do processo"


def test_com_o_freio_ligado_a_varredura_NEM_COMECA(varredura, monkeypatch):
    coleta, registros = varredura
    monkeypatch.setattr(cliente, "freio", lambda familia="traffic": {
        "familia": "traffic", "desde": "2026-09-11T10:17:04", "ate": "2026-09-11T11:17:04",
        "resta_s": 3000})
    monkeypatch.setattr(cliente, "fluxo", lambda *a, **k: pytest.fail("saiu para a rede"))
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert r["sem_creditos"] is True and r["reserva"] is True
    assert all(t["fonte"] == "frota" for t in r["trechos"]), "o que aparece é a RESERVA"
    (recurso,), k = registros[-1]
    assert k["n"] == 0 and k["barradas"] == 1 and k["origem"] == "torre"


def test_com_credito_a_varredura_segue_inteira(varredura, monkeypatch):
    """O contrapeso: sem isto a sonda poderia estar cortando a varredura SEMPRE."""
    coleta, registros = varredura
    chamadas = []

    def ok(lat, lon, zoom=cliente.ZOOM):
        chamadas.append(1)
        return {"flowSegmentData": {"currentSpeed": 80, "freeFlowSpeed": 80, "confidence": 1,
                                    "currentTravelTime": 60, "freeFlowTravelTime": 60,
                                    "roadClosure": False}}
    monkeypatch.setattr(cliente, "fluxo", ok)
    r = coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES)
    assert len(chamadas) == 6 and not r.get("sem_creditos")
    assert registros[-1][1]["n"] == 6
    coleta.condicao_da_frota(viagens=VIAGENS, posicoes_atuais=POSICOES, forcar=True)
    assert registros[-1][1]["apos_reinicio"] is False, "segunda varredura não é reinício"


# ------------------------------------------------------------- quem gasta

def test_quem_chama_fica_REGISTRADO_por_origem(esquema_pg):
    from api import pglocal
    from api.tomtom import coleta
    coleta.registrar("fluxo", n=70, erros=70, esquema=esquema_pg, origem="tv",
                     apos_reinicio=True)
    coleta.registrar("fluxo", n=0, esquema=esquema_pg, origem="tv", barradas=1)
    coleta.registrar("fluxo", n=65, esquema=esquema_pg, origem="torre")
    linhas = {l["origem"]: l for l in pglocal.query(
        "SELECT * FROM tt_chamadas_origem ORDER BY origem", esquema=esquema_pg)}
    tv = linhas["tv"]
    assert (tv["varreduras"], tv["chamadas"], tv["erros"], tv["barradas"],
            tv["apos_reinicio"]) == (2, 70, 70, 1, 1)
    assert linhas["torre"]["chamadas"] == 65
    total = pglocal.um("SELECT chamadas FROM tt_chamadas WHERE recurso = 'fluxo'",
                       esquema=esquema_pg)
    assert total["chamadas"] == 135, "o total por recurso continua o mesmo de sempre"
    por = coleta.consumo_por_origem(dias=1, esquema=esquema_pg)
    assert {p["origem"] for p in por} == {"tv", "torre"}


def test_a_rota_so_aceita_ORIGEM_da_lista(monkeypatch):
    from api import main
    from api.tomtom import coleta
    visto = {}
    monkeypatch.setattr(coleta, "condicao_da_frota", lambda **k: visto.update(k) or {})
    main.torre_estradas(tolerancia=1800, origem="tv")
    assert visto["origem"] == "tv" and visto["idade_maxima_s"] == 1800
    main.torre_estradas(origem="'; drop table x; --")
    assert visto["origem"] == "torre"


def test_o_painel_de_TV_pede_30_min_e_SE_IDENTIFICA():
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "api" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert "/api/operacao/torre/estradas?tolerancia=1800&origem=tv" in html
    assert "estradas?tolerancia=1200" not in html


def test_o_radar_diz_SEM_CREDITO_e_nao_o_nome_da_excecao():
    from api.radar import fontes
    exc = cliente.TomTomSemCreditos("A TomTom respondeu HTTP 403 ...", "traffic")
    assert fontes.descrever_falha(exc) == "TomTom sem créditos no produto de trânsito"
